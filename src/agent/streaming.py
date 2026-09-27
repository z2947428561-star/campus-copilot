"""统一的流式消费与 HITL 中断处理(消灭 5 份重复实现)。

课程对应:
    第07章 §8.2(p68-76) stream_mode 取值与多模式组合
        —— 多模式产出是 (mode, payload),**mode 在前**(课件 P75-76 原文:
        `for stream_mode, chunk in agent.stream(..., stream_mode=["tasks","updates"])`)
    第07章 §9.3(p80-81) 把 agent + 历史 + 交互封成一个类,而不是四处复制
    第07章 §5(p26-28)   给 Agent 设 name 做流式归因
    第08章 §2.2(p12-19) HumanInTheLoopMiddleware:中断 / 决策 / Command(resume=...)
        —— 课件 P18:"决策的顺序必须和返回的中断请求顺序一致"

为什么必须抽出来:
    旧版在 5 个文件里各写了一份同样的逻辑,合计约 180 行:
      chat_agent_cli.py / chat_agent_mw_cli.py / chat_memory_cli.py /
      server.py / scripts/eval_m6.py(外加 scripts/test_m3.py)
    其中"节点过滤"片段重复 5 处,stream+HITL 循环重复 4 处。
    更实际的风险是:旧版 server.py 固定只发 1 个 decision
    (`Command(resume={"decisions": [decision]})`),而 CLI 侧发的是
    `[decision] * len(actions)` —— 一旦 HITL 覆盖第二个工具且模型同一次
    并发调用两个受保护工具,Web 端就会因决策数量不匹配而出错。

本模块只负责"协议",不负责"交互方式":
    CLI 传一个 input() 回调,Web 传一个发 SSE 事件的回调,评估脚本传自动放行。
"""
import logging
from typing import Callable, Iterator

from langgraph.types import Command

logger = logging.getLogger("campus")

# 模型节点的名字。第07章 §8.3(p75)对比表里写明 messages 模式的元数据会带
# "来自哪个节点(model/tool)"。这里收敛成一处常量,不再散落 5 个文件。
MODEL_NODE = "model"

__all__ = [
    "MODEL_NODE",
    "model_text",
    "extract_text",
    "InterruptInfo",
    "stream_turn",
]


def extract_text(message) -> str:
    """从消息/分片里取出纯文本。

    第04章 §1.7.1(p20-21):content 是弱类型的,可能直接是 str,
    也可能是内容块列表(list[dict],多模态或 reasoning 时)。
    """
    text = getattr(message, "content", message)
    if isinstance(text, list):
        return "".join(
            block.get("text", "")
            for block in text
            if isinstance(block, dict) and block.get("type") in (None, "text")
        )
    return text or ""


def model_text(chunk, metadata) -> str:
    """只取模型节点的文本增量(过滤掉工具节点产生的内容)。

    第07章 §8.2.3(p70):messages 模式会输出 token 及其元数据(如来自哪个节点)。
    """
    if metadata.get("langgraph_node") != MODEL_NODE:
        return ""
    return extract_text(chunk)


class InterruptInfo:
    """一次 HITL 中断的待确认动作。

    结构取自课件第08章 §2.2(p15-17):
        interrupts[0].value["action_requests"] = [{name, args, description}, ...]
        interrupts[0].value["review_configs"]  = [{action_name, allowed_decisions}, ...]
    """

    def __init__(self, action_requests: list[dict], review_configs: list[dict]):
        self.action_requests = action_requests
        self.review_configs = review_configs

    @classmethod
    def from_interrupt(cls, interrupt) -> "InterruptInfo":
        value = interrupt.value if isinstance(interrupt.value, dict) else {}
        return cls(
            action_requests=value.get("action_requests", []) or [],
            review_configs=value.get("review_configs", []) or [],
        )

    def __len__(self) -> int:
        return len(self.action_requests)

    def allowed_decisions(self, index: int) -> list[str]:
        """第08章 §2.2(p16-17):每个动作的 review_configs 给出允许的决策集合。"""
        if 0 <= index < len(self.review_configs):
            allowed = self.review_configs[index].get("allowed_decisions")
            if allowed:
                return list(allowed)
        # 没给配置时的兜底:课件 P12 说取值可为 True(全部决策可用)
        return ["approve", "edit", "reject"]

    def describe(self) -> str:
        lines = []
        for a in self.action_requests:
            lines.append(
                f"{a.get('name', '未知工具')}({a.get('args', {})})"
                f" —— {a.get('description', '该工具属于敏感操作')}"
            )
        return "\n".join(lines)


def stream_turn(
    agent,
    inputs,
    cfg,
    on_decide: Callable[[InterruptInfo], list[dict] | None],
    *,
    on_token: Callable[[str], None] | None = None,
    context=None,
    max_interrupt_rounds: int = 3,
) -> str:
    """跑完一轮对话,直到没有待处理中断。

    参数:
        inputs:        {"messages": [...]} 或 Command(resume=...)
        cfg:           运行配置(thread_id / recursion_limit 等,见 agent.runtime)
        on_decide:     收到中断时回调,返回 decisions 列表;
                       返回 None 表示"不处理"(调用方自己负责收尾),此时函数提前返回
        on_token:      每收到一段模型文本增量时回调(CLI 打印 / SSE 推送)
        context:       第09章 §4(p60-80)的运行级静态上下文(承载 user_id)
        max_interrupt_rounds: 防止中断-恢复无限循环

    返回:本轮模型输出的完整文本。

    ⚠️ 第08章 §2.2(p13)的关键约束:中断恢复依赖 checkpointer 保存现场,
       且恢复时必须传**同一个 thread_id**(即同一个 cfg)。
    """
    full_reply = ""
    current_inputs = inputs

    for _ in range(max_interrupt_rounds):
        pending = None
        # 第07章 §8.2(p75-76):多模式产出的元组是 (mode, payload),mode 在前
        stream_kwargs = {"stream_mode": ["messages", "updates"]}
        if context is not None:
            stream_kwargs["context"] = context
        for mode, data in agent.stream(current_inputs, cfg, **stream_kwargs):
            if mode == "messages":
                chunk, metadata = data
                text = model_text(chunk, metadata)
                if text:
                    full_reply += text
                    if on_token:
                        on_token(text)
            elif mode == "updates" and data.get("__interrupt__"):
                pending = data["__interrupt__"][0]

        if pending is None:
            return full_reply

        info = InterruptInfo.from_interrupt(pending)
        decisions = on_decide(info)
        if decisions is None:
            # 调用方表示"到此为止"(例如 Web 端发完 interrupt 事件就断流)
            return full_reply

        # 第08章 §2.2(p18):决策顺序与动作顺序一致,数量也要对齐
        if len(decisions) != len(info):
            logger.warning(
                "[HITL] 决策数量(%d)与待确认动作数量(%d)不一致,已按动作数补齐",
                len(decisions),
                len(info),
            )
            decisions = (decisions + [{"type": "reject"} for _ in range(len(info))])[: len(info)]

        current_inputs = Command(resume={"decisions": decisions})

    logger.warning("[HITL] 中断轮次超过上限 %d,提前结束", max_interrupt_rounds)
    return full_reply

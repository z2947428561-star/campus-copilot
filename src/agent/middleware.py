"""中间件层:Agent 的"生产级保险丝"。

课程对应:第08章《中间件》(115 页,全课程最大的一章)

课件 §1(p1-8)把中间件定义为 Agent 执行过程中的**钩子函数**,并在 §1.3-1.4
给出分类。本项目用到的内置中间件与课件页码对照:

    §2.1 SummarizationMiddleware      (p7-11)  长对话压缩
    §2.2 HumanInTheLoopMiddleware     (p12-19) 高危工具执行前确认
    §2.3 PIIMiddleware                (p20-24) PII 脱敏
    §3.1 ModelCallLimitMiddleware     (p34)    模型调用次数上限  ← 本次新增
    §3.2 ToolCallLimitMiddleware      (p44)    工具调用次数上限  ← 本次新增
    §3.3 ModelFallbackMiddleware      (p53)    模型降级
    §3.8 ContextEditingMiddleware     (p73)    清理旧工具输出    ← 本次新增
    §5.3-5.4 Node/Wrap-style hooks    (p85-111) 钩子函数,本项目用 wrap-style
    §5.6 执行顺序                      (p112-115) 中间件组合与顺序

顺序设计(洋葱圈;课件 §5.6 p112-115):
    进入:[MW1 before] → [MW2 before] → [MW3 before] → 模型调用
    返回:[MW3 after]  → [MW2 after]  → [MW1 after]
本项目顺序:PII → 摘要 → 模型审计 → 调用限额 → 降级 → 工具审计 → HITL
    - PII 最外层:任何组件(包括摘要模型)都不该看到原始手机号/学号
    - 摘要第二:压缩历史前先脱敏
    - 审计 Hook 包住降级:一次调用若发生降级,总耗时能反映出来
    - 限额紧贴模型/工具:先刹车再谈降级
    - HITL 最内层:只在工具真正执行前拦一道

一处与旧版不同的重要改动(工厂化):
    旧版把 pii_guard / summarization / hitl 做成**模块级单例**,却在
    get_fallback_middleware() 里特意每次新建实例并注释"模型对象是有状态的,
    避免共享" —— 同一个文件对"中间件是否有状态"给了相反处理。
    现在全部改成工厂函数,每次组装 agent 都拿新实例。
"""
import logging
import re
import time

from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
    ToolCallLimitMiddleware,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.agents.middleware.pii import PIIMatch

import config
from model import (
    get_cheap_model,
    get_chat_model,
    get_fallback_model,
    get_ollama_model,  # noqa: F401 —— 旧脚本(scripts/test_m3.py)从本模块 import 它
)

logger = logging.getLogger("campus")


def _require_gpa_tool(request, handler):
    """个人绩点请求在首轮模型调用时明确指定 GPA 工具。

    仅看最后一条消息，工具返回后不再强制，避免重复调用。政策类的
    「对考试成绩不满意」不属于个人 GPA 查询。
    """
    last = request.messages[-1] if request.messages else None
    content = getattr(last, "content", "")
    if (getattr(last, "type", None) == "human" and isinstance(content, str)
            and re.search(r"\bGPA\b|绩点|拉分|我的成绩", content, re.I)
            and any(getattr(tool, "name", None) == "calculate_gpa" for tool in request.tools)):
        request = request.override(tool_choice="calculate_gpa")
    return handler(request)


def get_gpa_routing_middleware():
    return wrap_model_call(_require_gpa_tool, name="GpaToolChoiceHook")


# ---------------------------------------------------------------- 1. 审计 Hook
def _model_timing_hook(request, handler):
    """wrap_model_call:记录每次模型调用耗时 + token 用量(课件 §5.4 p99-103)。

    request / handler 由框架传入;handler(request) 才是真正调模型,
    前后包夹计时,顺带从响应里掏 usage_metadata。
    """
    t0 = time.perf_counter()
    response = handler(request)
    dt = time.perf_counter() - t0
    model_desc = getattr(request.model, "model_name", request.model)
    if not isinstance(model_desc, str):
        model_desc = type(request.model).__name__
    usage = getattr(response, "usage_metadata", None) or {}
    if usage:
        logger.info(
            "[模型] %-18s 耗时 %5.2fs | tokens 输入=%s 输出=%s",
            model_desc,
            dt,
            usage.get("input_tokens", "?"),
            usage.get("output_tokens", "?"),
        )
    else:
        logger.info("[模型] %-18s 耗时 %5.2fs", model_desc, dt)
    return response


def _tool_timing_hook(request, handler):
    """wrap_tool_call:记录每次工具调用的名称 + 耗时(课件 §5.4 p104-111)。"""
    name = request.tool_call["name"]
    t0 = time.perf_counter()
    result = handler(request)
    logger.info("[工具] %-24s 耗时 %6.3fs", name, time.perf_counter() - t0)
    return result


def get_audit_middlewares() -> list:
    return [
        wrap_model_call(_model_timing_hook, name="ModelAuditHook"),
        wrap_tool_call(_tool_timing_hook, name="ToolAuditHook"),
    ]


# ---------------------------------------------------------------- 2. PII 脱敏
# 注意用 (?<!\d)/(?!\d) 数字环视而不是 \b:中文字符也算"词字符",
# 「手机13812345678」这种中文紧贴数字的写法 \b 匹配不到
# (这是评估集 m03 抓出的真 bug,已修复)
_PHONE_CN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 马来西亚手机号:+60 12-345 6789 / 012-345 6789 等形态
_PHONE_MY = re.compile(r"(?<!\d)(?:\+?60|0)\s?1[0-9][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
# 学号:独立的 8 位数字(XMUM 学号形态;纯日期如 2026-09-02 带连字符不会误伤)
_STUDENT_ID = re.compile(r"(?<!\d)[1-9]\d{7}(?!\d)")


def _detect_pii(text: str) -> list[PIIMatch]:
    """自定义 PII 检测器。

    框架内置只认 email / 信用卡 / IP / MAC / URL,
    学号和手机号得自己写正则(课件 §2.3 p20-24 的自定义 detector 用法)。
    """
    matches: list[PIIMatch] = []
    for pattern, ptype in (
        (_PHONE_CN, "phone"),
        (_PHONE_MY, "phone"),
        (_STUDENT_ID, "student_id"),
    ):
        for m in pattern.finditer(text):
            matches.append(
                PIIMatch(type=ptype, value=m.group(), start=m.start(), end=m.end())
            )
    return matches


def get_pii_middleware() -> PIIMiddleware:
    """PII 脱敏(课件 §2.3 p20-24)。

    strategy="redact":命中处替换为占位符。
    课件 §2.3 p20-23 演示了 redact / mask / hash / block 四种策略,
    以及 apply_to_input / apply_to_output 的方向控制。
    """
    return PIIMiddleware(
        pii_type="custom",
        strategy="redact",
        detector=_detect_pii,
        apply_to_input=True,
        apply_to_output=False,   # 模型输出一般不含 PII,省 token
    )


# ---------------------------------------------------------------- 3. 长对话压缩
def get_summarization() -> SummarizationMiddleware:
    """摘要压缩(课件 §2.1 p7-11 + 第09章 §2.4.3 p30-34)。

    三处按课件调整:
    1) trigger 从"只看消息条数"改成**条数 + token 双阈值**。
       第09章 §2.4.3(p34)强调要"留一些余量给工具调用和系统提示" ——
       本项目工具返回很重(RAG 片段、课表、成绩报告),10 条长消息就可能
       爆窗口,而条数阈值对此完全不敏感。
    2) 摘要模型改用 get_cheap_model():课件 p34 指出摘要可以让便宜模型干,
       并提醒"摘要会让成本翻倍"(每轮多一次模型调用)。
    3) keep 仍保留最近 10 条原文。
    """
    return SummarizationMiddleware(
        model=get_cheap_model(),
        trigger=[
            ("messages", config.SUMMARY_TRIGGER_MESSAGES),
            ("tokens", config.SUMMARY_TRIGGER_TOKENS),
        ],
        keep=("messages", config.SUMMARY_KEEP_MESSAGES),
    )


# ---------------------------------------------------------------- 4. 调用限额
def get_call_limit_middlewares() -> list:
    """模型/工具调用次数上限(课件 §3.1 p34、§3.2 p44)。

    课件 §3.2(p44)给出三种退出行为:error(抛异常)/ end(结束会话)/
    continue(继续,默认,可能死循环)。这里选 end —— 对本项目更友好:
    与其抛异常让 Web 端报 500,不如优雅结束本轮。

    为什么需要:第07章 §4.4 问题5/6(p26)指出"默认没有工具调用次数限制,
    可能会超时",而本项目有 9 个工具、且评估集暴露过"模型反复调工具"的行为。

    ⚠️⚠️ 实测踩坑(重要,别重犯):
        `thread_limit` 是**按会话累计**的上限,不是"每轮"。计数存在
        state["thread_model_call_count"] / state["thread_tool_call_count"] 里,
        由 checkpointer 持久化 —— 所以一个 thread 上的多轮对话会一直累加。
        一旦触顶,且 exit_behavior="end",该会话后续每一轮都会被**立即结束**:
        模型不再输出任何内容,回答变成空字符串,**而且不报错**。

        实测证据:评估集 31 题最初共用一个 thread(旧 eval_m6 把没标 thread 的题
        都归到 "eval-{run_id}"),累计到 thread_limit=30 之后余下题目全部返回空,
        综合通过率从 81% 掉到 58%,失败原因显示为"关键词未命中"。
        把上限压到 3 复现时,第 3 题就开始返回空。

        因此:
          1) 评估/批量场景必须**一题一个 thread**(见 scripts/eval_m6.py 的说明);
          2) 本项目有持久化多用户会话,长对话很常见(一轮问答约 2-3 次模型调用),
             所以上限放宽到 config 里的 200 作为成本兜底;
          3) 单轮的失控保护交给 recursion_limit 与 §3.2 的工具级限额,
             两者分工不同:recursion_limit 管"一次运行跑多久",
             thread_limit 管"一个会话总共花多少"。
    """
    return [
        ToolCallLimitMiddleware(
            thread_limit=config.TOOL_CALL_THREAD_LIMIT,
            exit_behavior="end",
        ),
        ModelCallLimitMiddleware(
            thread_limit=config.MODEL_CALL_THREAD_LIMIT,
            exit_behavior="end",
        ),
    ]


# ---------------------------------------------------------------- 5. 上下文编辑
def get_context_editing() -> ContextEditingMiddleware:
    """清理旧的工具输出(课件 §3.8 p73)。

    课件说明:该中间件"通过更改发送给模型的消息列表来控制成本",
    且**不会修改真实的消息列表** —— 只能通过 token 用量推测是否做了裁剪。

    ⚠️⚠️ 实测踩坑(重要,别重犯):
        初版写成 `ClearToolUsesEdit(trigger=50, keep=0)`,结果**功能被它弄坏**:
        实测"问「我是什么年级」"时,read_profile 工具确实被调用且返回了正确画像
        ({"ok": true, "profile": {"major": "软件工程", "grade": "大二"}}),
        但模型回答"抱歉,画像是空的" —— 因为工具结果在模型作答**之前**就被清掉了,
        模型拿到的是一份没有工具输出的上下文。
        消融测试证据(scripts 外的临时脚本 ablation):
            全开(含 trigger=50/keep=0) → 无视画像
            关掉 ContextEditing          → 正确读出"大二/软件工程"

        参数语义(实测签名,课件未讲):
            ClearToolUsesEdit(trigger=100000, clear_at_least=0, keep=3, ...)
            - `trigger` 是 **token 数**上限(默认 10 万),不是消息条数;
              设成 50 等于"任何稍有内容的对话都立刻触发"。
            - `keep` 是**保留最近几条工具结果**(默认 3);设 0 = 全部清除。
        所以 trigger 调得过低 + keep=0 的组合,等价于"禁止模型使用任何工具结果"。

    结论:本中间件对"工具输出极长、需要主动抽脂"的场景才有价值,
    默认**不启用**(见 get_middlewares 的 with_context_editing 默认值)。
    确实要用时,请让 trigger 与真实 token 预算匹配(如 20000+),
    keep 保持 >=1,并先跑一遍带工具的用例确认结果没被清掉。
    """
    return ContextEditingMiddleware(
        edits=[
            ClearToolUsesEdit(
                trigger=config.CONTEXT_EDIT_TRIGGER_TOKENS,
                keep=config.CONTEXT_EDIT_KEEP_TOOL_RESULTS,
            )
        ],
    )


# ---------------------------------------------------------------- 6. 模型降级
def _ollama_reachable(timeout: float = 1.5) -> bool:
    """探测本机 Ollama 是否可用(用于决定降级备胎要不要挂)。"""
    import urllib.request

    try:
        with urllib.request.urlopen(
            config.OLLAMA_BASE_URL.rstrip("/") + "/api/tags", timeout=timeout
        ):
            return True
    except Exception:  # noqa: BLE001
        return False


def get_fallback_middleware(local_ollama: bool = False):
    """模型降级(课件 §3.3 p53)。返回 None 表示"没有可用的备胎"。

    ⚠️⚠️ 实测踩坑:备胎必须与主模型**不同源**。
        我最初把备胎写成"同厂商的便宜模型"(再取一次 LLM_MODEL),理由是
        "云上不该回连开发机"。实测证明**那等于没有降级** —— 主备共用同一个
        DEEPSEEK_API_KEY,而降级要应对的恰恰是"key 失效 / 余额不足 / 厂商故障",
        同一个 key 一坏,主备一起挂:
            主=deepseek-chat(坏key) + 备=deepseek-chat(同一坏key) → 401 崩掉
            主=deepseek-chat(坏key) + 备=Ollama qwen3:0.6b        → 兜住
        现在默认指向本机 Ollama(独立于云端);云部署要跨厂商降级时设
        LLM_FALLBACK_PROVIDER=cloud + LLM_FALLBACK_API_KEY(另一家的 key)。

    返回 None 时调用方**不要挂**这个中间件。"没有降级"比"挂一个同源备胎
    假装有降级"诚实:后者在真出故障时会给出同一个 401,却让人以为有兜底。

    local_ollama: 兼容旧签名;True 时强制用本机 Ollama 当备胎
    """
    provider = config.LLM_FALLBACK_PROVIDER

    if provider == "none":
        logger.warning("[降级] LLM_FALLBACK_PROVIDER=none,未挂载降级备胎")
        return None

    if provider == "cloud" or config.LLM_FALLBACK_API_KEY:
        if not config.LLM_FALLBACK_API_KEY:
            logger.warning(
                "[降级] 配了 cloud 备胎但缺少 LLM_FALLBACK_API_KEY;"
                "为避免同源无效降级,本次不挂载备胎"
            )
            return None
        logger.info(
            "[降级] 备胎 = 云端 %s @ %s(跨厂商)",
            config.LLM_FALLBACK_MODEL or config.LLM_MODEL,
            config.LLM_FALLBACK_BASE_URL,
        )
        return ModelFallbackMiddleware(get_chat_model(), get_fallback_model())

    # 默认/显式:本机 Ollama(独立于云端)
    if not _ollama_reachable():
        logger.warning(
            "[降级] 本机 Ollama 不可达(%s),为避免同源无效降级,本次不挂载备胎。"
            "启用降级二选一:① 启动 Ollama ② 配 LLM_FALLBACK_PROVIDER=cloud + "
            "LLM_FALLBACK_API_KEY(另一家厂商的 key)",
            config.OLLAMA_BASE_URL,
        )
        return None

    logger.info("[降级] 备胎 = 本机 Ollama %s", config.OLLAMA_MODEL)
    return ModelFallbackMiddleware(get_chat_model(), get_ollama_model())


# ---------------------------------------------------------------- 7. 高危动作确认
def get_hitl() -> HumanInTheLoopMiddleware:
    """高危动作确认(课件 §2.2 p12-19)。

    课件 p12-13 的可选决策是 approve / edit / reject 三种,
    p18 讲 edit 用 edited_action 改参数。旧版只开放了 approve/reject,
    这里把 edit 一起开出来(前端与 CLI 可以按 allowed_decisions 渲染)。

    ⚠️ p13 的关键约束:中断恢复需要 checkpointer 保存现场,
    并且恢复时必须传同一个 thread_id。
    ⚠️ p18:决策的顺序与数量必须和返回的中断请求一致。
    """
    return HumanInTheLoopMiddleware(
        interrupt_on={
            # calculate_gpa 要处理成绩单 —— 个人敏感数据,执行前问一句
            "calculate_gpa": {
                "allowed_decisions": ["approve", "edit", "reject"],
                "description": "即将分析你的成绩数据(GPA 计算涉及个人敏感信息)",
            },
        },
    )


# ---------------------------------------------------------------- 组装
def get_middlewares(
    with_fallback: bool = True,
    *,
    local_ollama: bool = False,
    with_limits: bool = True,
    with_context_editing: bool = False,
) -> list:
    """返回中间件栈。顺序即洋葱圈层次,见模块 docstring。

    local_ollama: 降级备胎是否指向本机 Ollama(仅本地验证用)
    with_context_editing:
        默认 **False** —— 见 get_context_editing() 里的实测踩坑说明:
        ContextEditingMiddleware 若参数配得激进(trigger 过小 / keep=0),
        会在模型作答前把工具结果清掉,导致模型"看不见"工具输出、
        进而回答"查不到"。它对超长工具输出的场景才有价值,属可选优化。
    """
    stack = [get_pii_middleware(), get_summarization(), get_gpa_routing_middleware()]

    if with_context_editing:
        stack.append(get_context_editing())

    stack.extend(get_audit_middlewares())

    if with_limits:
        stack.extend(get_call_limit_middlewares())

    if with_fallback:
        fb = get_fallback_middleware(local_ollama=local_ollama)
        # 没有可用备胎时不挂(见 get_fallback_middleware 的说明:
        # 宁可不挂,也不要挂一个与主模型同源的假备胎)
        if fb is not None:
            stack.append(fb)

    stack.append(get_hitl())
    return stack


# ---------------------------------------------------------------- 兼容别名
# 旧版这里是模块级单例(既用于组装中间件栈,也被脚本直接 import)。
# 现在**只保留真正被外部引用的那一个**,并且只保留"构造时不依赖 API key"的那个。
#
# 为什么删掉 summarization / hitl / model_audit / tool_audit 这四个别名:
#   它们在模块导入时就会构造模型(get_summarization → get_cheap_model),
#   于是一旦环境里没有 DEEPSEEK_API_KEY,"import agent.middleware" 直接抛
#   RuntimeError —— 连只想知道 PII 正则的测试都跑不起来(实测踩到)。
#   新代码请一律用上面的 get_*() 工厂函数。
#
# pii_guard 保留:scripts/test_m3.py 需要它,且它只构造正则检测器、不碰模型,
# 导入无副作用。
pii_guard = get_pii_middleware()

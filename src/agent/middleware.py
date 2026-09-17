"""M3:中间件层 —— 给 Agent 加"生产级保险丝"。

课程对应:中间件三件套(Summarization / HumanInTheLoop / PII / ModelFallback)
+ wrap_model_call / wrap_tool_call 两个 Hook。

设计思路(为什么是这个顺序):
    middleware 列表靠前的包住靠后的,像洋葱圈。本项目的顺序:
    PII → Summarization → 审计 Hook → Fallback → HITL
    - PII 最外层:任何组件(包括总结模型)都不该看到原始手机号/学号
    - Summarization 第二:压缩历史前先脱敏
    - 审计 Hook 包住 Fallback:一次模型调用若发生降级,总耗时能反映出来
    - HITL 在最内层:只在工具真正执行前拦一道
"""
import logging
import re
import time

from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelFallbackMiddleware,
    PIIMiddleware,
    SummarizationMiddleware,
    wrap_model_call,
    wrap_tool_call,
)
from langchain.agents.middleware.pii import PIIMatch
from langchain_openai import ChatOpenAI

from model import get_chat_model

logger = logging.getLogger("campus")


# ---------------------------------------------------------------- Ollama 本地模型
def get_ollama_model(model_name: str = "qwen3:0.6b") -> ChatOpenAI:
    """本地 Ollama 模型(OpenAI 兼容协议接入)。

    用途:DeepSeek 挂了时的降级备胎 —— 免费、离线、但能力弱(0.6B)。
    为什么不用 deepseek-r1:1.5b:r1 系列没有 tools 模板,
    Agent 场景(请求里必带工具 schema)会被 Ollama 直接 400 拒绝;
    qwen3:0.6b 支持工具调用,才能作为 Agent 的完整降级。
    Ollama 的 /v1 接口不校验 key,但 langchain-openai 要求非空,填占位符即可。
    """
    return ChatOpenAI(
        api_key="ollama",
        base_url="http://localhost:11434/v1",
        model=model_name,
    )


# ---------------------------------------------------------------- 1. 审计 Hook
def _model_timing_hook(request, handler):
    """wrap_model_call:记录每次模型调用耗时 + token 用量。

    request / handler 由框架传入;handler(request) 才是真正调模型,
    前后包夹计时,顺带从响应里掏 usage_metadata。
    """
    t0 = time.perf_counter()
    response = handler(request)
    dt = time.perf_counter() - t0
    # request.model 可能是 str 也可能是模型实例(取 .model_name)
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
    """wrap_tool_call:记录每次工具调用的名称 + 耗时。

    M3 DoD 里的"工具耗时在日志可见"就是它。
    """
    name = request.tool_call["name"]
    t0 = time.perf_counter()
    result = handler(request)
    logger.info("[工具] %-24s 耗时 %6.3fs", name, time.perf_counter() - t0)
    return result


# wrap_model_call(func) 直接把函数转成中间件实例(不用 @ 装饰器形式,便于集中管理)
model_audit = wrap_model_call(_model_timing_hook, name="ModelAuditHook")
tool_audit = wrap_tool_call(_tool_timing_hook, name="ToolAuditHook")


# ---------------------------------------------------------------- 2. PII 脱敏
# 中国手机号:1 开头 11 位;马来西亚手机号:01x 开头 7-8 位(可带 +60/横线/空格)
# 注意用 (?<!\d)/(?!\d) 数字环视而不是 \b:中文字符也算"词字符",
# 「手机13812345678」这种中文紧贴数字的写法 \b 匹配不到(评估集 m03 抓出的真 bug)
_PHONE_CN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_PHONE_MY = re.compile(r"(?<!\d)(?:\+?60|0)1[0-9][- ]?\d{3,4}[- ]?\d{3,4}(?!\d)")
# 学号:独立的 8 位数字(XMUM 学号形态;纯日期如 2026-09-02 带连字符不会误伤)
_STUDENT_ID = re.compile(r"(?<!\d)[1-9]\d{7}(?!\d)")


def _detect_pii(text: str) -> list[PIIMatch]:
    """自定义 PII 检测器:框架内置只认 email/信用卡/IP/MAC/URL,
    学号和手机号得自己写正则。返回命中列表(PIIMatch 是 TypedDict)。
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


pii_guard = PIIMiddleware(
    pii_type="custom",  # 用自定义 detector,不用内置类型
    strategy="redact",  # 命中处替换为 [REDACTED_phone] 之类占位符
    detector=_detect_pii,
    apply_to_input=True,   # 用户输入里出现 → 脱敏后模型才看得到
    apply_to_output=False,  # 模型输出一般不含 PII,暂不处理(省 token)
)


# ---------------------------------------------------------------- 3. 长对话压缩
summarization = SummarizationMiddleware(
    model=get_chat_model(),          # 压缩这件事本身也要调模型,用便宜的主模型干
    trigger=("messages", 30),        # 历史超过 30 条消息 → 触发压缩
    keep=("messages", 10),           # 压缩后保留最近 10 条原文,更早的揉进摘要
)


# ---------------------------------------------------------------- 4. 模型降级
def get_fallback_middleware() -> ModelFallbackMiddleware:
    """DeepSeek(云端,主力)→ Ollama(本地,备胎)自动切换。

    注意每次新建实例:fallback 里包着的模型对象是有状态的,复用旧 agent
    场景下避免共享(参考框架文档的中间件生命周期说明)。
    """
    return ModelFallbackMiddleware(get_chat_model(), get_ollama_model())


# ---------------------------------------------------------------- 5. 高危动作确认
hitl = HumanInTheLoopMiddleware(
    interrupt_on={
        # calculate_gpa 要处理成绩单 —— 个人敏感数据,执行前问一句
        "calculate_gpa": {
            "allowed_decisions": ["approve", "reject"],
            "description": "即将分析你的成绩数据(GPA 计算涉及个人敏感信息)",
        },
    },
)


# ---------------------------------------------------------------- 组装
def get_middlewares(with_fallback: bool = True) -> list:
    """返回 M3 中间件栈。顺序即洋葱圈层次,见模块 docstring。"""
    stack = [pii_guard, summarization, model_audit]
    if with_fallback:
        stack.append(get_fallback_middleware())
    stack.append(tool_audit)
    stack.append(hitl)
    return stack

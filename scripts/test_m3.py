"""M3 DoD 自动验证:中间件四件套 + 审计 Hook 逐项过堂。

DoD 对照(docs/milestones.md):
1. 配错 API key 不崩,自动降级到本地 Ollama     → test_fallback()
2. 20 轮对话不超限(历史自动压缩)               → test_summarization()
3. 工具耗时在日志可见                            → test_hitl_and_tool_log()
4. PII:学号/手机号进模型前被脱敏                 → test_pii()
5. 多中间件执行顺序                              → test_pii() 里顺带验证
   (PII 在最外层先处理消息,压缩在后 —— 通过日志时序观察)

运行(项目根目录):.venv\\Scripts\\python scripts\\test_m3.py
会真实调用 DeepSeek / Ollama,产生少量 API 费用(分币级)。
"""
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))  # 让 agent/ tools/ model 可导入

from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import (  # noqa: E402
    ModelFallbackMiddleware,
    SummarizationMiddleware,
)
from langgraph.types import Command  # noqa: E402

from agent.middleware import (  # noqa: E402
    _detect_pii,
    get_ollama_model,
    pii_guard,
)
from model import get_chat_model  # noqa: E402
from tools import ALL_TOOLS  # noqa: E402
from agent.assistant import SYSTEM_PROMPT  # noqa: E402

# 收集 campu 审计日志,供断言"耗时可见"
LOG_RECORDS: list[str] = []


class _Capture(logging.Handler):
    def emit(self, record):
        LOG_RECORDS.append(record.getMessage())


campus_log = logging.getLogger("campus")
campus_log.setLevel(logging.INFO)
campus_log.addHandler(_Capture())


PASS = "  [通过] "
FAIL = "  [失败] "
failures = 0


def check(name: str, ok: bool, detail: str = ""):
    global failures
    print(f"{PASS if ok else FAIL}{name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures += 1


# ---------------------------------------------------------------- 4. PII 脱敏(单元级,不花钱)
def test_pii():
    print("\n[1/4] PII 脱敏(自定义检测器,_process_content 单测)")

    text = "我的手机号 13812345678,备用 012-345 6789,学号 23123456,周三有课吗"
    processed, matches = pii_guard._process_content(text)
    print(f"        命中 {len(matches)} 处: {[m['type'] for m in matches]}")
    print(f"        脱敏后: {processed}")

    check("中国手机号命中", any(m["type"] == "phone" for m in matches))
    check("马来西亚手机号命中", len([m for m in matches if m["type"] == "phone"]) == 2)
    check("学号命中", any(m["type"] == "student_id" for m in matches))
    check("原文中不再含手机号/学号", "13812345678" not in processed and "23123456" not in processed)
    check("正常内容不受影响", "周三有课吗" in processed)

    # 执行顺序验证:PII 是列表第一个(最外层),先于其他中间件处理消息
    from agent.middleware import get_middlewares

    order = [type(m).__name__ for m in get_middlewares()]
    print(f"        中间件栈(外→内): {order}")
    check("PII 位于最外层(第 1 个)", order[0] == "PIIMiddleware")
    check("栈共 6 层:PII→压缩→模型审计→降级→工具审计→HITL", len(order) == 6)


# ---------------------------------------------------------------- 1. 模型降级(云→本地)
def test_fallback():
    print("\n[2/4] 模型降级:DeepSeek 错误 key → Ollama qwen3:0.6b 兜底")

    os.environ["DEEPSEEK_API_KEY"] = "sk-this-key-is-wrong-on-purpose"  # 模拟配错
    try:
        from importlib import reload

        import model as model_mod

        reload(model_mod)  # 重载让 get_chat_model 拿到坏 key

        agent = create_agent(
            model=model_mod.get_chat_model(),
            tools=ALL_TOOLS,
            system_prompt=SYSTEM_PROMPT,
            middleware=[ModelFallbackMiddleware(
                model_mod.get_chat_model(),
                get_ollama_model(),
            )],
        )
        result = agent.invoke(
            {"messages": [{"role": "user", "content": "只回复两个字:在线"}]}
        )
        final = result["messages"][-1].content
        if isinstance(final, list):
            final = "".join(b.get("text", "") for b in final if isinstance(b, dict))
        print(f"        最终回答(前 80 字): {str(final)[:80]}")
        check("配错 key 不崩溃且拿到回答", bool(str(final).strip()))
    finally:
        # 还原真实 key(从 .env 重新加载)
        from dotenv import load_dotenv

        for k in ("DEEPSEEK_API_KEY",):
            os.environ.pop(k, None)
        load_dotenv(ROOT / ".env", override=True)


# ---------------------------------------------------------------- 3. HITL + 工具耗时日志(真实 Agent)
def test_hitl_and_tool_log():
    print("\n[3/4] HITL 高危确认 + 工具耗时日志(calculate_gpa)")

    from agent.assistant import get_agent

    agent = get_agent(with_middleware=True)
    # HITL 恢复依赖 checkpointer,按 thread_id 定位会话现场
    cfg = {"configurable": {"thread_id": "hitl-test"}}
    interrupted = None
    resumed_reply = ""

    # 注意:多 stream_mode 时产出 (mode, payload) —— mode 在前!
    for mode, data in agent.stream(
        {"messages": [{"role": "user", "content": "用 calculate_gpa 工具帮我算这学期的 GPA"}]},
        cfg,
        stream_mode=["messages", "updates"],
    ):
        if mode == "updates" and data.get("__interrupt__"):
            interrupted = data["__interrupt__"][0]
        elif mode == "messages":
            pass  # 中断前的思考 token 不重要

    check("calculate_gpa 执行前被拦截", interrupted is not None)
    if interrupted:
        info = interrupted.value if isinstance(interrupted.value, dict) else {}
        actions = info.get("action_requests", [])
        print(f"        中断动作: {[a.get('name') for a in actions]}")

        # 放行后应出现工具结果并给出最终回答
        result = agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}] * max(len(actions), 1)}),
            config=cfg,
        )
        msgs = result["messages"]
        tool_calls = [
            m for m in msgs
            if m.__class__.__name__ == "ToolMessage" and m.name == "calculate_gpa"
        ]
        final = msgs[-1].content
        if isinstance(final, list):
            final = "".join(b.get("text", "") for b in final if isinstance(b, dict))
        print(f"        放行后回答(前 80 字): {str(final)[:80]}")
        check("放行后工具真实执行", len(tool_calls) >= 1)
        check("拿到最终回答", bool(str(final).strip()))

    timing_logs = [r for r in LOG_RECORDS if r.startswith("[工具]")]
    model_logs = [r for r in LOG_RECORDS if r.startswith("[模型]")]
    print(f"        工具耗时日志示例: {timing_logs[0] if timing_logs else '无'}")
    check("工具耗时日志可见", len(timing_logs) >= 1)
    check("模型调用耗时日志可见", len(model_logs) >= 1)


# ---------------------------------------------------------------- 2. 长对话压缩
def test_summarization():
    print("\n[4/4] 长对话压缩(小阈值模拟 20 轮以上对话)")

    # 独立小 Agent:阈值调低到 8 条消息,只验证压缩机制本身
    agent = create_agent(
        model=get_chat_model(),
        tools=[],
        system_prompt="你是测试助手,用中文极简回答。",
        middleware=[SummarizationMiddleware(
            model=get_chat_model(),
            trigger=("messages", 8),
            keep=("messages", 2),
        )],
    )
    history = []
    for i in range(1, 11):  # 10 轮,足以触发多次压缩
        result = agent.invoke(
            {"messages": history + [{"role": "user", "content": f"第{i}轮:记住暗号是{i}号。回复'好'即可"}]}
        )
        msgs = result["messages"]
        history = [
            {"role": "user", "content": m.content} if m.__class__.__name__ == "HumanMessage"
            else {"role": "assistant", "content": m.content}
            for m in msgs
            if m.__class__.__name__ in ("HumanMessage", "AIMessage")
        ]

    n_human = sum(1 for m in history if m["role"] == "user")
    print(f"        喂了 10 轮对话,压缩后 state 里仅剩 {len(history)} 条消息(其中用户 {n_human} 条)")
    check("历史被压缩(远小于 20 条原始消息)", len(history) < 20)
    check("压缩后仍保留最近消息(≥2 条)", len(history) >= 2)

    # 压缩后记忆仍在:问暗号,能从摘要里答出最后一轮
    result = agent.invoke({"messages": history + [{"role": "user", "content": "暗号是多少号?(只答数字)"}]})
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = "".join(b.get("text", "") for b in final if isinstance(b, dict))
    print(f"        压缩后问答: {str(final)[:60]}")
    check("摘要保留了关键信息(含'10')", "10" in str(final))


if __name__ == "__main__":
    print("=" * 60)
    print("M3 DoD 自动验证")
    print("=" * 60)
    test_pii()
    test_fallback()
    test_hitl_and_tool_log()
    test_summarization()
    print("\n" + "=" * 60)
    if failures:
        print(f"结果:{failures} 项失败,看上面 [失败] 行")
        sys.exit(1)
    print("结果:全部通过 ✓")

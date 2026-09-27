"""M3:中间件版 Agent CLI —— 带脱敏 / 压缩 / 降级 / 高危确认 / 审计日志。

课程对应:
    第08章 §2.1-2.3(p7-24)   Summarization / HITL / PII 三个中间件
    第08章 §3.1-3.3(p34-53)  调用限额与模型降级
    第08章 §5.3-5.4(p85-111) 钩子函数(本项目用 wrap-style)
    第08章 §2.2(p13-19)      HITL 中断→恢复:需要 checkpointer 存现场,
                             恢复时必须传同一个 thread_id

与旧版的差异:
    旧版在本文件里自己写了一套 stream + 中断处理循环(约 50 行)。
    现在改用 agent.streaming.stream_turn,本文件只保留"怎么问用户"这一段交互。
    (第07章 §9.3 p80-81 建议把这类逻辑封装,而不是每个入口抄一份。)

历史管理:M3 起不再手工维护 history,交给 checkpointer 按 thread_id 托管
(第09章 §2.1.2 p7-8);本文件用 InMemorySaver,进程退出即失 —— 要持久化请用
chat_memory_cli.py。

运行(项目根目录):
    run_mw.cmd  或  .venv\\python src\\chat_agent_mw_cli.py
"""
import bootstrap  # noqa: F401 —— 先执行(设置 sys.path / 编码)

bootstrap.setup_logging()
bootstrap.setup_langsmith()

from agent.assistant import get_agent  # noqa: E402
from agent.runtime import default_thread_id, make_config  # noqa: E402
from agent.streaming import stream_turn  # noqa: E402
from context import UserContext  # noqa: E402

EXIT_WORDS = {"exit", "quit", "退出"}
USER_ID = "cli"


def on_decide(info) -> list:
    """HITL 交互:把待确认动作打印给用户,收集决策(第08章 §2.2 p15-18)。"""
    print("\n⚠️  以下操作需要你确认:")
    for i, action in enumerate(info.action_requests, 1):
        print(f"   [{i}] {action.get('name', '未知工具')}({action.get('args', {})})")
        print(f"       {action.get('description', '该工具属于敏感操作')}")
        print(f"       可选决策:{', '.join(info.allowed_decisions(i - 1))}")
    answer = input("   放行吗?(y=放行 / 其他=拒绝): ").strip().lower()
    decision = (
        {"type": "approve"}
        if answer == "y"
        else {"type": "reject", "message": "用户在终端选择了拒绝执行"}
    )
    # 第08章 §2.2 p18:决策数量与顺序必须和 action_requests 一致
    return [decision] * max(len(info), 1)


def main():
    # local_ollama=True:本文件就是"验证降级"的地方,备胎指向本机 Ollama
    # (第08章 §3.3 p53)。云上请用默认值 False,走云端备胎。
    agent = get_agent(with_middleware=True, local_ollama=True)
    cfg = make_config(thread_id=default_thread_id(USER_ID), user_id=USER_ID)

    print("=== Campus Copilot · M3 中间件版 ===")
    print("已启用:PII 脱敏 / 摘要压缩 / 上下文清理 / 调用限额 / DeepSeek→Ollama 降级 / GPA 确认")
    print("试试:「我手机 13812345678,现在第几教学周」「算下我的GPA」")
    print("输入「退出」「exit」「quit」结束(审计日志见 stderr)\n")

    while True:
        user_input = input("你> ").strip()
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            print("已退出,下次见!")
            break

        print("助手> ", end="", flush=True)
        stream_turn(
            agent,
            {"messages": [{"role": "user", "content": user_input}]},
            cfg,
            on_decide=on_decide,
            on_token=lambda t: print(t, end="", flush=True),
            context=UserContext(user_id=USER_ID),
        )
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

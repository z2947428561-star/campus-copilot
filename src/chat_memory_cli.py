"""M4:记忆版 CLI —— 持久化会话 + 用户画像,重启不丢。

课程对应:
    第09章 §2.1.3(p11)    同 thread_id 共享记忆、异 thread_id 完全隔离
    第09章 §2.2(p14-18)   外部存储持久化(checkpointer)
    第09章 §3.1.3(p39-41) store → namespace → key → value
    第09章 §4.2(p74-80)   用户身份由 context 显式传入
    第08章 §2.2(p13-19)   HITL 中断→恢复

与 M3 的差异:
- checkpointer:InMemorySaver → 持久化实现(默认 SQLite,可切 PostgreSQL)
- 新增 store:长期画像按用户隔离,namespace = ("profiles", user_id)
- 启动时问用户名:user_id 定画像命名空间,thread_id 定短期会话
- 同一用户再次启动 → 自动接上上次的话题续聊

体验要点:
- 换个用户名 → 完全另一段会话、另一份画像(多用户隔离)
- 关掉窗口重开、输入同一用户名 → 上次聊到哪继续(重启可恢复)

本次修订:
    用户身份不再只塞在 configurable 里,而是通过 context=UserContext(...)
    显式传入(第09章 §4.2 p74-80)—— 工具的 ToolRuntime 从 runtime.context 读。

运行(项目根目录):
    run_mem.cmd  或  .venv\\python src\\chat_memory_cli.py
"""
import bootstrap  # noqa: F401 —— 先执行(设置 sys.path / 编码)

bootstrap.setup_logging()
bootstrap.setup_langsmith()

from agent.assistant import get_agent  # noqa: E402
from agent.runtime import default_thread_id, make_config  # noqa: E402
from agent.streaming import stream_turn  # noqa: E402
from context import UserContext  # noqa: E402

EXIT_WORDS = {"exit", "quit", "退出"}


def on_decide(info) -> list:
    """HITL 交互(同 M3)。"""
    print("\n⚠️  以下操作需要你确认:")
    for i, action in enumerate(info.action_requests, 1):
        print(f"   [{i}] {action.get('name', '未知工具')}({action.get('args', {})})")
        print(f"       {action.get('description', '该工具属于敏感操作')}")
    answer = input("   放行吗?(y=放行 / 其他=拒绝): ").strip().lower()
    decision = (
        {"type": "approve"}
        if answer == "y"
        else {"type": "reject", "message": "用户在终端选择了拒绝执行"}
    )
    return [decision] * max(len(info), 1)


def main():
    agent = get_agent(with_middleware=True, with_memory=True)

    # --- 多用户入口:user_id 定画像 namespace,thread_id 定短期会话 ---
    user = input("你是谁?(输入用户名,直接回车为 default): ").strip() or "default"
    thread_id = default_thread_id(user)
    cfg = make_config(thread_id=thread_id, user_id=user, run_name=f"campus-cli:{user}")
    user_context = UserContext(user_id=user)

    # 探测该会话是否已有历史(重启续聊的提示)——
    # 第09章 §2.1.2(p8-10)的 agent.get_state(config)
    state = agent.get_state(cfg)
    n_history = len(state.values.get("messages", [])) if state.values else 0

    print(f"\n=== Campus Copilot · M4 记忆版(用户:{user})===")
    if n_history:
        print(f"已恢复你的历史会话({n_history} 条消息),继续聊上次的吧")
        print("试试:「我们刚才聊到哪了」「我是大几的」「我常问什么」")
    else:
        print("新会话。聊聊你自己吧:「我是大一新生,计算机专业」")
        print("长期画像会自动记录,重启也记得")
    print("输入「退出」「exit」「quit」结束\n")

    while True:
        user_input = input("你> ").strip()
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            print("已退出,下次见!(会话已存盘)")
            break

        print("助手> ", end="", flush=True)
        stream_turn(
            agent,
            {"messages": [{"role": "user", "content": user_input}]},
            cfg,
            on_decide=on_decide,
            on_token=lambda t: print(t, end="", flush=True),
            context=user_context,      # 第09章 §4.2 p74-80
        )
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

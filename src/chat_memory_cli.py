"""M4:记忆版 CLI —— 持久化会话 + 用户画像,重启不丢。

与 M3 chat_agent_mw_cli.py 的差异:
- InMemorySaver → SqliteSaver(data/memory.db):进程退出会话不丢
- 新增 store:长期画像按用户隔离("profiles", user_id)
- 启动时问用户名:user_id 定画像命名空间,thread_id 定短期会话
- 同一用户再次启动 → 自动接上上次的话题续聊

体验要点(对应 M4 DoD):
- 换个用户名登录 → 完全另一段会话、另一份画像(多用户隔离)
- 关掉窗口重开、输入同一用户名 → 上次聊到哪继续(重启可恢复)

运行(项目根目录,CMD):
    cd /d "E:\\Campus Copilot"
    .venv\\python src\\chat_memory_cli.py
"""
import logging
import sys

from langgraph.types import Command

from agent.assistant import get_agent

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

EXIT_WORDS = {"exit", "quit", "退出"}


def _print_model_chunk(chunk, metadata) -> str:
    """只打印模型节点的文本 token(工具节点不进聊天界面)。"""
    if metadata.get("langgraph_node") != "model":
        return ""
    text = chunk.content
    if isinstance(text, list):
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    if text:
        print(text, end="", flush=True)
    return text or ""


def run_turn(agent, inputs, cfg) -> str:
    """流式输出一轮;遇 HITL 中断则确认后继续(同 M3)。"""
    full_reply = ""
    pending = None

    while True:
        for mode, data in agent.stream(inputs, cfg, stream_mode=["messages", "updates"]):
            if mode == "messages":
                chunk, metadata = data
                full_reply += _print_model_chunk(chunk, metadata)
            elif mode == "updates" and data.get("__interrupt__"):
                pending = data["__interrupt__"][0]

        if pending is None:
            return full_reply

        req = pending.value if isinstance(pending.value, dict) else {}
        actions = req.get("action_requests", [])
        for a in actions:
            print(f"\n⚠️  {a.get('description', '该工具属于敏感操作')}")
            print(f"   即将执行: {a.get('name', '未知工具')}({a.get('args', {})})")
        answer = input("   放行吗?(y=放行 / 其他=拒绝): ").strip().lower()
        decision = (
            {"type": "approve"}
            if answer == "y"
            else {"type": "reject", "message": "用户在终端选择了拒绝执行"}
        )
        inputs = Command(resume={"decisions": [decision] * max(len(actions), 1)})
        pending = None


def main():
    agent = get_agent(with_middleware=True, with_memory=True)

    # --- 多用户入口:user_id 定画像,thread_id 定会话 ---
    user = input("你是谁?(输入用户名,直接回车为 default): ").strip() or "default"
    thread_id = f"{user}-main"
    cfg = {"configurable": {"thread_id": thread_id, "user_id": user}}

    # 探测该会话是否已有历史(重启续聊的提示)
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
        run_turn(agent, {"messages": [{"role": "user", "content": user_input}]}, cfg)
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

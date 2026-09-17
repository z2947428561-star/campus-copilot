"""M3:中间件版 Agent CLI —— 带脱敏/压缩/降级/高危确认/审计日志。

与 M2 chat_agent_cli.py 的差异:
- get_agent(with_middleware=True):挂 M3 中间件栈 + InMemorySaver
- 历史管理升级:M2 手动维护 history 列表,M3 起交给 checkpointer
  (每轮只发新消息,会话状态按 thread_id 托管;M4 换持久化后端即可)
- stream_mode 从 "messages" 升级为 ["messages", "updates"]:
  messages 流 token 给用户看,updates 流用来捕获 HITL 中断事件
- calculate_gpa 被执行前会弹确认,输入 y 才放行(Command(resume=decisions))
- 审计日志走 stderr,和聊天正文(stdout)不混流

运行(项目根目录,CMD):
    cd /d "E:\\Campus Copilot"
    .venv\\Scripts\\python src\\chat_agent_mw_cli.py
"""
import logging
import sys

from langgraph.types import Command

from agent.assistant import get_agent

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

# 日志配置:耗时/审计信息打到 stderr,聊天正文在 stdout,互不干扰
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # 压掉底层请求噪音
logging.getLogger("openai").setLevel(logging.WARNING)

EXIT_WORDS = {"exit", "quit", "退出"}
THREAD_ID = "cli-session"  # checkpointer 按 thread_id 定位会话现场


def _print_model_chunk(chunk, metadata) -> str:
    """只打印模型节点的文本 token,返回拼接结果(工具节点不进聊天界面)。"""
    if metadata.get("langgraph_node") != "model":
        return ""
    text = chunk.content
    if isinstance(text, list):  # 内容块列表形态兼容
        text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
    if text:
        print(text, end="", flush=True)
    return text or ""


def run_turn(agent, inputs, cfg) -> str:
    """跑完整一轮:流式输出 →(若遇 HITL 中断)确认 → 继续流式,直到出最终回答。"""
    full_reply = ""
    pending = None  # 挂起的 HumanInTheLoop 中断

    while True:
        # 双通道流:messages 出 token,updates 捕获 __interrupt__
        # 注意:多 stream_mode 时产出 (mode, payload) —— mode 在前
        for mode, data in agent.stream(inputs, cfg, stream_mode=["messages", "updates"]):
            if mode == "messages":
                chunk, metadata = data
                full_reply += _print_model_chunk(chunk, metadata)
            elif mode == "updates" and data.get("__interrupt__"):
                pending = data["__interrupt__"][0]

        if pending is None:
            return full_reply  # 本轮跑完

        # --- 处理高危工具确认 ---
        # 中断对象 .value 是 HITLRequest,里面 action_requests 是待确认动作列表
        req = pending.value if isinstance(pending.value, dict) else {}
        actions = req.get("action_requests", [])
        for a in actions:
            print(f"\n⚠️  {a.get('description', '该工具属于敏感操作')}")
            print(f"   即将执行: {a.get('name', '未知工具')}({a.get('args', {})})")
        answer = input("   放行吗?(y=放行 / 其他=拒绝): ").strip().lower()

        # 恢复格式:每个被拦截的动作对应一个 decision
        decision = (
            {"type": "approve"}
            if answer == "y"
            else {"type": "reject", "message": "用户在终端选择了拒绝执行"}
        )
        inputs = Command(resume={"decisions": [decision] * max(len(actions), 1)})
        pending = None


def main():
    agent = get_agent(with_middleware=True)
    cfg = {"configurable": {"thread_id": THREAD_ID}}

    print("=== Campus Copilot · M3 中间件版 ===")
    print("已启用:PII 脱敏 / 30 条消息自动压缩 / DeepSeek→Ollama 降级 / GPA 工具执行前确认")
    print("试试:「我手机 13812345678,现在第几教学周」「算下我的GPA」")
    print("输入「退出」「exit」「quit」结束(审计日志见下方时间戳行)\n")

    while True:
        user_input = input("你> ").strip()
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            print("已退出,下次见!")
            break

        print("助手> ", end="", flush=True)
        # 历史由 checkpointer 托管:这里只发本条新消息,不再手动拼 history
        full_reply = run_turn(
            agent, {"messages": [{"role": "user", "content": user_input}]}, cfg
        )
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

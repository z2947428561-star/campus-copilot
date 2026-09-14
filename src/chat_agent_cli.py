"""M2:Agent 版多轮对话 CLI —— 会调用工具的校园助手。

与 M1 的差异:
- M1:(prompt | llm).stream —— 模板填充后模型直接回答
- M2:agent.stream —— 模型先"思考",需要时调用工具,拿到结果再回答

历史管理说明(务实的取舍):
- 本版只把「用户输入 + 最终回答」两条放进 history,工具调用的中间消息不存
- 代价:模型下轮不记得上次调过什么工具(会重新调用,多一次 API 开销)
- M4 会用 LangGraph checkpointer 托管完整 state,那才是正规做法

运行(项目根目录):.venv\\Scripts\\python src\\chat_agent_cli.py
"""
import sys

from agent.assistant import get_agent

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

EXIT_WORDS = {"exit", "quit", "退出"}


def main():
    agent = get_agent()
    history: list[dict] = []  # [{"role": "user"/"assistant", "content": ...}]

    print("=== Campus Copilot · Agent 版(M2 验证)===")
    print("试试:「现在第几教学周」「周三10点哪有空教室」「我GPA多少」「CS301要先修什么」")
    print("输入「退出」「exit」「quit」结束\n")

    while True:
        user_input = input("你> ").strip()
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            print("已退出,下次见!")
            break

        print("助手> ", end="", flush=True)
        full_reply = ""

        # stream_mode="messages":token 级流式,输出 (chunk, metadata) 元组
        # 用 metadata 里的 langgraph_node 过滤,只打印模型节点的文本
        # (工具调用步骤产生的是 ToolMessage,不应该打进聊天界面)
        for chunk, metadata in agent.stream(
            {"messages": history + [{"role": "user", "content": user_input}]},
            stream_mode="messages",
        ):
            if metadata.get("langgraph_node") != "model":
                continue
            text = chunk.content
            # content 可能是 str,也可能是内容块列表(多模态/结构化时),做兼容
            if isinstance(text, list):
                text = "".join(
                    block.get("text", "") for block in text if isinstance(block, dict)
                )
            if text:
                print(text, end="", flush=True)
                full_reply += text
        print()

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": full_reply})


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

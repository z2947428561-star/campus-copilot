
import sys
from langchain_core.messages import AIMessage, HumanMessage
from model import get_chat_model
from prompt import prompt


sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

EXIT_WORDS = { "quit", "退出"}


def main():
    llm = get_chat_model()
    history: list = []

    print("=== Campus Copilot · 多轮对话===")
    print("聊天;输入「退出」[quit] 结束\n")

    while True:
        user_input = input("你> ").strip()
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            print("已退出")
            break

        print("助手> ", end="", flush=True)
        full_reply = ""


        for chunk in (prompt | llm).stream({"history": history, "input": user_input}):
            print(chunk.content, end="", flush=True)
            full_reply += chunk.content
        print()


        history.append(HumanMessage(user_input))
        history.append(AIMessage(full_reply))

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

#cd /d "E:\Campus Copilot"
#run_chat.cmd
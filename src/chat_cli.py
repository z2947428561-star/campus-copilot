"""M1:多轮对话 CLI —— 带内存历史的终端聊天程序。

核心原理(课程 P25-27):
- 模型 API 本身是无状态的,它不记得任何对话
- "记忆"的本质 = 每轮把完整历史(messages 列表)重发给模型
- 每轮对话 = 往列表追加 HumanMessage(你)+ AIMessage(模型)

运行(项目根目录):.venv\\Scripts\\python src\\chat_cli.py
课程对应:P27-28(对话历史管理、多轮对话聊天机器人案例)
"""
import sys

from langchain_core.messages import AIMessage, HumanMessage

from model import get_chat_model
from prompt import prompt

# Windows 终端编码统一为 UTF-8,避免中文输入输出乱码
sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

EXIT_WORDS = {"exit", "quit", "退出"}


def main():
    llm = get_chat_model()
    # 多轮对话的核心数据结构:消息列表(纯内存版——程序退出即丢失)
    # M4 会用 PostgreSQL 把它持久化,现在先理解最朴素的原理
    history: list = []

    print("=== Campus Copilot · 多轮对话(M1 验证版)===")
    print("随便聊;输入「退出」「exit」「quit」结束\n")

    while True:
        user_input = input("你> ").strip()
        if not user_input:
            continue
        if user_input.lower() in EXIT_WORDS:
            print("已退出,下次见!")
            break

        print("助手> ", end="", flush=True)
        full_reply = ""

        # prompt | llm:LCEL 链式组合——模板填充后的消息交给模型
        # stream 传入字典,模板里的 {input} 和 history 占位符在此被填充
        for chunk in (prompt | llm).stream({"history": history, "input": user_input}):
            print(chunk.content, end="", flush=True)
            full_reply += chunk.content  # 边打印边拼接,历史里要存完整回答
        print()  # 回答结束后换行

        # 关键一步:本轮问答追加进历史,下一轮模型才能"记得"
        history.append(HumanMessage(user_input))
        history.append(AIMessage(full_reply))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n(已通过 Ctrl+C 退出)")

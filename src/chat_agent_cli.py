"""M2:Agent 版多轮对话 CLI —— 会调用工具的校园助手。

课程对应:
    第07章 §3(p6-9)       agent.invoke / stream 的调用方式
    第07章 §8.2.3(p70)    stream_mode="messages" 输出 token 与元数据
    第04章 §1.6.1(p16-17) 关键规则:每次调用必须传递完整的对话历史
    第04章 §1.6.2(p17-18) 历史变长后要裁剪(只保留最近 N 轮)
    第04章 §1.6.3(p18-19) 课件给的 MAX_PAIRS_HISTORY = 10 写法

历史管理说明(与旧版的差异):
    旧版只把「用户输入 + 最终回答」两条放进 history,工具中间消息不存,
    代价是模型下轮不记得上次调过什么工具(会重新调用)。这违反第04章
    §1.6.1(p16)的"必须传递完整的对话历史"。

    课件给的"标准答案"是 checkpointer 托管完整 state(第09章 §2《短期记忆》),
    但那是 M3/M4 的事。本文件作为 M2 的教学对照保留**手工历史**写法,
    并补上旧版缺失的历史裁剪(第04章 §1.6.2/1.6.3)。

    日常使用请用 chat_memory_cli.py(历史由 checkpointer 托管)。

运行(项目根目录):
    .venv\\python src\\chat_agent_cli.py
"""
import bootstrap  # noqa: F401 —— 必须先执行(设置 sys.path / 编码 / LangSmith)

bootstrap.setup_langsmith()

from agent.assistant import get_agent  # noqa: E402
from agent.streaming import MODEL_NODE, extract_text  # noqa: E402
from context import UserContext  # noqa: E402

EXIT_WORDS = {"exit", "quit", "退出"}

# 第04章 §1.6.3(p18-19):每轮 = 用户 + 助手两条,保留最近 10 轮
MAX_PAIRS_HISTORY = 10


def keep_recent(history: list, max_pairs: int = MAX_PAIRS_HISTORY) -> list:
    """只保留最近 N 轮对话(第04章 §1.6.2 p17-18)。

    课件的方法还会"总是保留第一条 system 消息";本项目 M2 走的
    create_agent(system_prompt=...) 路线,系统提示词不由 history 承载,
    所以这里只做"保留最近 N 轮"这半边。
    """
    return history[-(max_pairs * 2):]


def main():
    agent = get_agent()

    history: list = []
    print("=== Campus Copilot · Agent 版(M2)===")
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

        # stream_mode="messages":token 级流式,产出 (chunk, metadata) 元组;
        # 用 metadata 里的节点名过滤,只打印模型节点的文本
        # (工具调用步骤产生的是 ToolMessage,不该打进聊天界面)—— 第07章 §8.2.3 p70
        for chunk, metadata in agent.stream(
            {"messages": keep_recent(history) + [{"role": "user", "content": user_input}]},
            stream_mode="messages",
            context=UserContext(user_id="cli"),
        ):
            if metadata.get("langgraph_node") != MODEL_NODE:
                continue
            text = extract_text(chunk)
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

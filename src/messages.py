"""消息构造统一入口。

课程对应:
    第04章 §1.3(p3)     消息有两种格式:JSON 字典 / 对象
    第04章 §1.5.3(p10-12) AIMessage 的 tool_calls 字段
    第04章 §1.5.4(p13-15) ToolMessage 必须紧邻匹配的 AIMessage,且 tool_call_id 一致
    第04章 §1.6.1(p16-17) 关键规则:每次调用必须传递完整的对话历史

为什么统一:
    旧版在 4 个文件里各手写一份 `{"messages": [{"role": "user", "content": ...}]}`
    (chat_agent_cli.py / chat_agent_mw_cli.py / chat_memory_cli.py / server.py),
    外加 scripts/test_m3.py 里一份。写法本身合法(课件 §1.3 p3 两种格式都给了),
    但课件 §1.5.4(p13-15)演示 ToolMessage 时特意把 dict 版注释掉、改用对象版,
    原因是 tool_call_id 必须精确匹配 —— 字段越多的消息越不该手写 dict。

    历史由 checkpointer 托管后(第09章 §2),入口只需要构造"本轮的新消息",
    所以这里只保留一个极薄的构造函数。
"""
from langchain_core.messages import HumanMessage

__all__ = ["user_turn", "assistant_turn"]


def user_turn(text: str) -> dict:
    """构造一轮用户输入(Agent 的输入形态)。

    用 HumanMessage 对象而不是 dict:与课件 §1.5.4(p15)的对象格式一致,
    且后续若要加 name / metadata 等字段不必改调用方。
    """
    return {"messages": [HumanMessage(text)]}


def assistant_turn(text: str) -> dict:
    """构造一轮助手回复(仅在手工维护历史的场景用,如 M1 的 CLI)。"""
    from langchain_core.messages import AIMessage

    return {"messages": [AIMessage(text)]}

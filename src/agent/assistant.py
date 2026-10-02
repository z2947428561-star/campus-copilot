"""Agent 组装:模型 + 工具集 + 系统提示词 + 中间件 + 记忆。

课程对应:
    第07章 §1.4(p2-4)   create_agent 是 v1.0 的统一入口(替代 v0.x 的
                        create_react_agent / create_tool_calling_agent 等碎片化 API)
    第07章 §2(p3-5)     模型的传入方式(字符串 / 模型实例)
    第07章 §4(p10-26)   绑定工具,并提醒"一般 2-5 个工具最佳"(p21)
    第07章 §5(p26-28)   name 参数 —— 流式输出归因 / trace 可读性
    第07章 §6(p28-34)   system_prompt(可以是 str 或 SystemMessage)
    第07章 §7(p35-67)   结构化输出 response_format(本次留出参数,未默认启用)
    第09章 §4(p60-80)   context_schema / Runtime 注入运行级静态上下文
    第08章 §2-§5        中间件与 Hook

与旧版的差异(为什么改):
1) 系统提示词不再是一个大字符串常量,改为按阶段组装
   (prompts.build_system_prompt),修掉"M2 裸 Agent 被要求调 save_profile
   而那个工具必然失败"的矛盾。
2) 加上 name 参数(第07章 §5 p26-28)。
3) 加上 context_schema=UserContext(第09章 §4.2 p74-80):用户身份改由
   context 显式传入,工具通过 ToolRuntime 读取。
4) 中间件改为工厂函数(见 middleware.py)。
"""
import logging

from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.memory import get_checkpointer, get_store
from agent.middleware import get_middlewares
from context import UserContext
from model import get_chat_model
from prompts import build_system_prompt
from tools import ALL_TOOLS

logger = logging.getLogger("campus")

# 第07章 §5(p26-28):给 Agent 一个名字,用于流式输出归因与 trace 可读性
AGENT_NAME = "campus_copilot"

# 兼容别名:旧版这里是一个 SYSTEM_PROMPT 常量,已有脚本(scripts/test_m3.py)
# 从本模块 import 它。现在提示词按阶段组装(见 prompts/),这个常量给出
# "全量阶段"的字符串,仅供对照与旧脚本使用;**新代码请调 prompts.build_system_prompt**
# 或直接 get_agent(),不要再用这个常量 —— 它是写死的一份,无法按阶段裁剪。
SYSTEM_PROMPT = build_system_prompt(with_memory=True, with_rag=True)


def get_agent(
    with_middleware: bool = False,
    with_memory: bool = False,
    *,
    tools: list | None = None,
    response_format=None,
    local_ollama: bool = False,
):
    """创建并返回组装好的 Agent 实例。

    create_agent 返回一个基于 LangGraph 的 runnable,
    输入 {"messages": [...]},输出含完整消息链(含工具调用)的 state。

    with_middleware:
        False —— 裸 Agent(兼容旧 CLI / 简单测试)
        True  —— 挂中间件栈(PII / 摘要 / 审计 / 限额 / 降级 / HITL)。
                 HITL 中断→恢复必须有 checkpointer 存现场(第08章 §2.2 p13)
    with_memory:
        False —— checkpointer 用 InMemorySaver(进程内,重启即失)
        True  —— 换持久化实现 + 挂 store 供画像工具读写长期记忆
    tools:
        None → 用全部工具(ALL_TOOLS)
        其它  → 显式传入工具子集(第07章 §4.1 p21 建议按场景裁剪)
    response_format:
        None              → 不启用 Agent 级结构化输出
        ToolStrategy(...) → 第07章 §7.2(p36-39)推荐的做法

        ⚠️ 不要给通用 Agent 默认启用:第07章 §7.1(p35)的对比表说明,
           Agent 结构化输出只在"Agent 决定任务结束时"解析,一旦设置,
           空教室/政策问答等所有最终答案都会被强制套进同一结构。
           只有做"专用报表 Agent"时才该用。
    local_ollama:
        是否显式使用本机 Ollama 验证降级；False 时读取配置的备用模型。
    """
    if with_memory:
        checkpointer = get_checkpointer()
        store = get_store()
    elif with_middleware:
        checkpointer = InMemorySaver()
        store = None
    else:
        checkpointer = None
        store = None

    # 第04章 §1.2(p2) 的"工作说明书":按阶段组装,不再用一份写死的大常量
    system_prompt = build_system_prompt(
        with_memory=store is not None,
        # 知识库是否可用由检索层自己决定并诚实回报;这里默认注入引用纪律,
        # 若知识库未接入,search_policy 会返回"未接入"提示,
        # 而提示词里的诚实底线要求模型如实转述。
        with_rag=True,
    )

    # 注意:create_agent 的 middleware=None 会直接崩(内部会迭代),
    # 不挂时必须整个省略参数
    kwargs = dict(
        model=get_chat_model(),
        tools=tools if tools is not None else ALL_TOOLS,
        system_prompt=system_prompt,
        name=AGENT_NAME,                       # 第07章 §5(p26-28)
        checkpointer=checkpointer,
        store=store,
        context_schema=UserContext,            # 第09章 §4.2(p74-80)
    )
    if with_middleware:
        kwargs["middleware"] = get_middlewares(local_ollama=local_ollama)
    if response_format is not None:
        kwargs["response_format"] = response_format   # 第07章 §7(p35-39)

    return create_agent(**kwargs)

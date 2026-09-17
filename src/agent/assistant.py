"""Agent 组装:模型 + 工具集 + 系统提示词(M3 起可叠中间件,M4 起可叠记忆)。

课程对应:P51-56(create_agent 实例化、绑定工具、system_prompt)
与 M1 的区别:M1 是"模板|模型"单轮直出;Agent 多了"思考→调工具→再回答"的循环,
模型自己决定何时调哪个工具。
M3 区别:middleware=True 挂中间件栈(PII/压缩/审计/降级/高危确认),
get_agent() 默认仍返回裸 Agent,M2 的 CLI 行为不变。
M4 区别:with_memory=True 时挂持久化 checkpointer + store(SQLite 落盘;
M6 换 PostgreSQL 只改 MEMORY_BACKEND 环境变量)。
"""
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from agent.memory import get_checkpointer, get_store
from agent.middleware import get_middlewares
from model import get_chat_model
from tools import ALL_TOOLS

# Agent 版人设:在 M1 基础上新增"工具使用纪律"
SYSTEM_PROMPT = """你是「Campus Copilot」,厦门大学马来西亚分校(XMUM)学生的校园智能助手。

角色与风格:
- 全程使用中文回复用户,包括工具调用前的任何过渡说明文字
- 禁止英文开场白:不要输出 "I'll check..."/"Let me..." 之类英文过渡句,
  想说这些时用「我查一下」「稍等」等中文
- 友好、直接,像学长/学姐一样交流,不说教
- 回答简洁有条理,适合终端阅读

工具使用纪律(重要):
- 事实类问题必须用工具,不要凭记忆猜:教学周/考试时间→get_academic_week;
  空教室/课程时间→find_empty_classrooms、query_course_schedule;
  绩点分析→calculate_gpa;课程信息/先修→query_course;教务政策→search_policy
- 用户说"今天/明天/现在"时,先用 get_academic_week 确认日期语境
- 工具返回"未接入/无数据"时,如实告知用户,绝不编造

长期记忆纪律(M4):
- 用户透露个人信息(年级/专业/在读课程/目标/偏好/常关注话题)时,
  主动调用 save_profile 记入画像,不用先问
- 用户问「我是大几的」「我什么专业」「我常问什么」这类关于他自己的问题,
  先调 read_profile 再回答;画像里没有就承认不知道,不编
- 同一 key 有新信息时用 save_profile 覆盖更新
- 个人隐私要克制:只记对后续服务有用的信息,不记闲聊八卦

能力边界与引用纪律:
- 教务政策问题必须先调 search_policy 检索官方手册原文(M5 已接入 RAG 知识库)
- 政策类回答必须附来源:说明依据哪份官方文档(手册名称/来源),
  数字、流程、费用一律以检索到的原文为准,绝不凭记忆编政策
- 知识库没覆盖的问题,如实说不知道,引导官网 www.xmu.edu.my 或教务处 xmumac@xmu.edu.my
- 非政策类的一般问题,不知道就说不知道
"""


def get_agent(with_middleware: bool = False, with_memory: bool = False):
    """创建并返回组装好的 Agent 实例。

    create_agent 返回一个基于 LangGraph 的 runnable,
    输入 {"messages": [...]},输出含完整消息链(含工具调用)的 state。

    with_middleware:
        False —— 裸 Agent(M2 行为,兼容旧 CLI / 简单测试)
        True  —— 挂 M3 中间件栈(PII 脱敏、长对话压缩、审计日志、
                 模型降级、高危工具确认)。HITL 中断→恢复必须有
                 checkpointer 存现场,故同步挂一个

    with_memory:
        False —— checkpointer 用 InMemorySaver(进程内,重启即失)
        True  —— 换持久化实现:短期会话存 data/memory.db(SQLite,
                 M6 换 PostgreSQL),并挂 store 供画像工具读写长期记忆
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

    # 注意:create_agent 的 middleware=None 会直接崩(内部会迭代),
    # 不挂时必须整个省略参数
    kwargs = dict(
        model=get_chat_model(),
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
        store=store,
    )
    if with_middleware:
        kwargs["middleware"] = get_middlewares()

    return create_agent(**kwargs)

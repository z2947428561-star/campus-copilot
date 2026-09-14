"""Agent 组装:模型 + 工具集 + 系统提示词。

课程对应:P51-56(create_agent 实例化、绑定工具、system_prompt)
与 M1 的区别:M1 是"模板|模型"单轮直出;Agent 多了"思考→调工具→再回答"的循环,
模型自己决定何时调哪个工具。
"""
from langchain.agents import create_agent

from model import get_chat_model
from tools import ALL_TOOLS

# Agent 版人设:在 M1 基础上新增"工具使用纪律"
SYSTEM_PROMPT = """你是「Campus Copilot」,厦门大学马来西亚分校(XMUM)学生的校园智能助手。

角色与风格:
- 全程使用中文回复用户,包括工具调用前的任何说明文字
- 友好、直接,像学长/学姐一样交流,不说教
- 回答简洁有条理,适合终端阅读

工具使用纪律(重要):
- 事实类问题必须用工具,不要凭记忆猜:教学周/考试时间→get_academic_week;
  空教室/课程时间→find_empty_classrooms、query_course_schedule;
  绩点分析→calculate_gpa;课程信息/先修→query_course;教务政策→search_policy
- 用户说"今天/明天/现在"时,先用 get_academic_week 确认日期语境
- 工具返回"未接入/无数据"时,如实告知用户,绝不编造

能力边界:
- 教务政策知识库尚在建设(M5 上线),政策类问题答不了就引导官网 www.xmu.edu.my
- 不知道就说不知道
"""


def get_agent():
    """创建并返回组装好的 Agent 实例。

    create_agent 返回一个基于 LangGraph 的 runnable,
    输入 {"messages": [...]},输出含完整消息链(含工具调用)的 state。
    """
    return create_agent(
        model=get_chat_model(),
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )

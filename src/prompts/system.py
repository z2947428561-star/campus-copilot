"""按运行阶段组装 system_prompt。

课程对应:
    第04章 §2.4.1(p37-38) partial():预填充固定变量,为不同场景创建模板变体
    第04章 §2.4.3(p40-41) 模板库
    第04章 §2.4.4(p41-42) 模板组合
    第04章 §2.3.2(p30-31) invoke / format / format_messages 的区别
    第07章 §6(p28-34)     system_prompt(str 或 SystemMessage)

⚠️ 一个课件点名过的坑(第04章 §2.3.2 p31):
    `ChatPromptTemplate.format()` 返回的是**拼接后的字符串**,里面会带上
    「System: 」「Human: 」这样的角色前缀。如果把它直接喂给
    create_agent(system_prompt=...),这些前缀会被写进人设里。
    所以取系统提示词要用 format_messages()[0].content,而不是 format()。
"""
from langchain_core.prompts import ChatPromptTemplate

from prompts.common import CLOSING, HONESTY, PERSONA, STYLE
from prompts.discipline import (
    CITATION_DISCIPLINE,
    MEMORY_DISCIPLINE,
    TOOL_DISCIPLINE,
)

# 固定值集中一处:第04章 §2.4.1(p37-38)的"部分变量预填充"
FIXED_VARS = {
    "school": "厦门大学马来西亚分校(XMUM)",
    "tool_routing": (
        "教学周 / 考试时间→get_academic_week;"
        "空教室→find_empty_classrooms;课程上课时间→query_course_schedule;"
        "用户自己的课表→query_my_schedule;"
        "绩点分析→calculate_gpa;课程信息与先修→query_course;"
        "选课经验/教师讨论→search_course_recommendations;某门课的原始评价→get_course_reviews;"
        "教务政策→search_policy"
    ),
    # 与 src/tools/policy.py 返回的引导语保持一致
    "official_site": "www.xmu.edu.my",
    "contact_email": "xmumac@xmu.edu.my",
}


def build_prompt(
    *,
    with_memory: bool = False,
    with_rag: bool = True,
) -> ChatPromptTemplate:
    """按阶段拼出提示词模板(变量已用 partial 预填充)。

    with_memory: 是否挂了 store —— 决定要不要注入长期记忆纪律
    with_rag:    知识库是否可用 —— 决定要不要注入引用纪律
    """
    parts = [PERSONA, STYLE]

    # 工具纪律只在真的有工具时才有意义(裸 Agent 场景不注入)
    parts.append(TOOL_DISCIPLINE)
    if with_memory:
        parts.append(MEMORY_DISCIPLINE)
    if with_rag:
        parts.append(CITATION_DISCIPLINE)
    parts.append(HONESTY)
    parts.append(CLOSING)   # 第07章 §7.3.1(p43):收口放末尾

    template = ChatPromptTemplate.from_messages([("system", "\n\n".join(parts))])
    return template.partial(**FIXED_VARS)


def build_system_prompt(*, with_memory: bool = False, with_rag: bool = True) -> str:
    """组装 create_agent 需要的 system_prompt 字符串。

    注意用 format_messages() 取 content,而不是 format()(见模块 docstring)。
    """
    messages = build_prompt(with_memory=with_memory, with_rag=with_rag).format_messages()
    return messages[0].content

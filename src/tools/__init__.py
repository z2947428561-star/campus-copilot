"""工具包:统一导出所有 Agent 可用工具。

课程对应:第05章 §6.2(p41-42)功能单一
    课件对工具数量的建议在 **第07章 §4.1(p21)**:"一般 2-5 个工具最佳",
    "工具太多会混淆"。本项目目前有 11 个,因此这里按**场景分组**导出,
    让调用方可以只挂需要的子集(参见 TOOL_GROUPS),而不是无脑全挂。

    同时第07章 §4.4(p26)提醒:默认没有工具调用次数限制。若某天工具继续
    增加,应改用第08章 §3.4(p55)的 LLMToolSelectorMiddleware 动态筛工具。
"""
from .academic import get_academic_week
from .courses import query_course
from .gpa import calculate_gpa
from .policy import search_policy
from .profile import read_profile, save_profile
from .recommendations import get_course_reviews, search_course_recommendations
from .timetable import find_empty_classrooms, query_course_schedule, query_my_schedule

# 按场景分组(第07章 §4.1 p21:只给 Agent 需要的工具)
TOOL_GROUPS = {
    # 课表 / 校历 / 教室 —— 结构化查询,精确性优先
    "schedule": [get_academic_week, find_empty_classrooms, query_course_schedule, query_my_schedule],
    # 课程与先修关系
    "curriculum": [query_course],
    "recommendations": [search_course_recommendations, get_course_reviews],
    # 教务政策 —— RAG 检索
    "policy": [search_policy],
    # 成绩分析
    "grade": [calculate_gpa],
    # 长期画像读写
    "profile": [save_profile, read_profile],
}

ALL_TOOLS = [
    get_academic_week,
    find_empty_classrooms,
    query_course_schedule,
    query_my_schedule,
    calculate_gpa,
    query_course,
    search_course_recommendations,
    get_course_reviews,
    search_policy,
    save_profile,
    read_profile,
]


def tools_for(*groups: str) -> list:
    """按场景取工具子集,例如 tools_for("schedule", "policy")。"""
    picked: list = []
    for g in groups:
        if g not in TOOL_GROUPS:
            raise KeyError(f"未知工具组:{g}(可选:{sorted(TOOL_GROUPS)})")
        picked.extend(TOOL_GROUPS[g])
    return picked


__all__ = [
    "ALL_TOOLS",
    "TOOL_GROUPS",
    "tools_for",
    "get_academic_week",
    "find_empty_classrooms",
    "query_course_schedule",
    "query_my_schedule",
    "calculate_gpa",
    "query_course",
    "search_course_recommendations",
    "get_course_reviews",
    "search_policy",
    "save_profile",
    "read_profile",
]

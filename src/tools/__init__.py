"""工具包:统一导出所有 Agent 可用工具。"""
from .academic import get_academic_week
from .courses import query_course
from .gpa import calculate_gpa
from .policy import search_policy
from .profile import read_profile, save_profile
from .timetable import find_empty_classrooms, query_course_schedule

ALL_TOOLS = [
    get_academic_week,
    find_empty_classrooms,
    query_course_schedule,
    calculate_gpa,
    query_course,
    search_policy,
    save_profile,
    read_profile,
]

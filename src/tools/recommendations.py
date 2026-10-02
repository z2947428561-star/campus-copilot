"""Search source-attributed community feedback without inventing recommendation scores."""
import json
import sqlite3

from langchain_core.tools import tool

import course_recommendations as repository
from .schemas import CourseReviewsInput, RecommendationSearchInput


@tool(args_schema=RecommendationSearchInput, description=(
    "搜索本机学生共编的选课经验、具名教师讨论和选课问答，不是官方课程目录。"
    "query 使用课程英文名片段、教师名或原文关键词（如 Python、pre、没考试），"
    "多个空格分隔词需全部命中；不要直接传整句问题。可按 Art/Business/Science 和分区筛选。"
    "留空关键词可浏览目录；结果按相关名称匹配及原表顺序排列，不是推荐分数排名。"
))
def search_course_recommendations(query: str = "", category: str = "all",
                                  section: str = "courses", limit: int = 5, offset: int = 0) -> str:
    try:
        source, records = repository.load_records()
    except (sqlite3.Error, OSError):
        return json.dumps(repository.unavailable(), ensure_ascii=False)
    words = repository.normalize(query).split()
    matches = []
    for record in records:
        if section != "all" and record["section"] != section:
            continue
        if category != "all" and record["category"] != category:
            continue
        text = repository.normalize(" ".join(c["text"] for c in record["cells"]))
        if all(word in text for word in words):
            matches.append(record)
    if words:
        matches.sort(key=lambda r: not all(w in repository.normalize(r["title"]) for w in words))
    return json.dumps(repository.response(source, matches, limit=limit, offset=offset), ensure_ascii=False)


@tool(args_schema=CourseReviewsInput, description=(
    "按完整课程名称读取学生选课经验的原始行，合并展示同名重复行但保留每条出处和矛盾意见。"
    "不接受课程代码；名称不确定时先用 search_course_recommendations 查目录。"
    "没有标题的评论不会自动归到上一门课；未找到不代表课程不开设。"
))
def get_course_reviews(course_name: str, limit: int = 5, offset: int = 0) -> str:
    try:
        source, records = repository.load_records()
    except (sqlite3.Error, OSError):
        return json.dumps(repository.unavailable(), ensure_ascii=False)
    name = repository.normalize(course_name)
    matches = [r for r in records if r["section"] == "courses" and r["title"]
               and repository.normalize(r["title"]) == name]
    result = repository.response(source, matches, limit=limit, offset=offset)
    if not matches:
        result["note"] = "没有该完整课程名称的记录；可先按关键词搜索，不推断课程是否开设。"
    return json.dumps(result, ensure_ascii=False)

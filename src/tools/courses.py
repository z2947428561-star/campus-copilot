"""课程信息查询工具(含完整先修链)。

先修链是树状依赖:CS301 ← DS201 ← CS101,用递归展开到无先修为止。
对应验收场景:"大二能修 CS301 吗""Machine Learning 需要先修什么"

课程对应:
    第05章 §3.1(p16-18) parse_docstring
    第05章 §3.3(p20-24) args_schema
    第05章 §6.4(p43)    工具返回字符串
"""
import json
import sqlite3

from langchain_core.tools import tool

from .schemas import CourseQueryInput

DB_PATH = "data/campus.db"

SEM_CN = {"Sep": "九月学期", "Apr": "四月学期"}


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _prereq_chain(conn: sqlite3.Connection, course_id: str, seen: set) -> list[str]:
    """递归展开先修链,返回从当前课程到根的路径列表。"""
    if course_id in seen:
        return []  # 防循环依赖
    seen.add(course_id)
    row = conn.execute(
        "SELECT prerequisites FROM courses WHERE course_id = ?", (course_id,)
    ).fetchone()
    if not row:
        return []
    prereqs = json.loads(row[0])
    if not prereqs:
        return []
    chain = []
    for p in prereqs:
        chain.append(p)
        chain.extend(_prereq_chain(conn, p, seen))
    return chain


@tool(
    parse_docstring=True,
    args_schema=CourseQueryInput,
    description=(
        "查询课程信息:课程名、学分、开课学院、开设学期、建议学年,以及完整先修链。"
        "适用于「CS301 需要先修什么」「machine learning 这门课怎么样」「大二能修 XX 吗」。"
    ),
)
def query_course(query: str) -> str:
    """查询课程信息与先修关系。

    Args:
        query: 课程代码(如 CS301)或课程名关键词(中英文均可)。

    Returns:
        课程信息的 JSON 字符串(含 course_id/name/credits/dept/semester_cn/
        year/prerequisite_chain/dependents);未找到时含 error,命中多门时
        含 candidates 列表提示改用课程代码精确查询。
    """
    q = query.strip()
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT course_id, name, credits, dept, sem, year FROM courses "
            "WHERE course_id = ?",
            (q.upper(),),
        ).fetchone()

        if not row:
            matches = conn.execute(
                "SELECT course_id, name, credits, dept, sem, year FROM courses "
                "WHERE LOWER(name) LIKE ? ORDER BY year, course_id LIMIT 3",
                (f"%{q.lower()}%",),
            ).fetchall()
            if not matches:
                return _dump(
                    {"query": query, "error": f"课程库中未找到与「{query}」匹配的课程"}
                )
            if len(matches) > 1:
                return _dump(
                    {
                        "query": query,
                        "candidates": [
                            {"course_id": m[0], "name": m[1]} for m in matches
                        ],
                        "note": "命中多门课程,请用课程代码精确查询",
                    }
                )
            row = matches[0]

        cid, name, credits, dept, sem, year = row
        chain = _prereq_chain(conn, cid, set())

        # 反向查:哪些课以本课为先修(帮助回答"修了它有什么用")
        dependents = conn.execute(
            "SELECT course_id FROM courses WHERE prerequisites LIKE ?", (f'%"{cid}"%',)
        ).fetchall()
    finally:
        conn.close()

    payload = {
        "course_id": cid,
        "name": name,
        "credits": credits,
        "dept": dept,
        "semester": sem,
        "semester_cn": SEM_CN.get(sem, sem),
        "year": year,
        # 去重但保持依赖顺序(最后是无先修的根课程)
        "prerequisite_chain": list(dict.fromkeys(chain)),
        "dependents": [d[0] for d in dependents],
    }
    if not chain:
        payload["prerequisite_note"] = "无先修课程,可直接修读"
    return _dump(payload)

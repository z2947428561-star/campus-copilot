"""课程信息查询工具(含完整先修链)。

先修链是树状依赖:CS301 ← DS201 ← CS101,用递归展开到无先修为止。
对应验收场景:"大二能修 CS301 吗""Machine Learning 需要先修什么"
"""
import json
import sqlite3

from langchain_core.tools import tool

DB_PATH = "data/campus.db"


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


@tool
def query_course(query: str) -> str:
    """查询课程信息:课程名、学分、开课学院、开设学期、建议学年,以及完整先修链。

    适用于:"CS301 需要先修什么""machine learning 这门课怎么样""大二能修 XX 吗"。

    Args:
        query: 课程代码(如 CS301)或课程名关键词(如 "machine learning"、中英文均可)
    """
    q = query.strip()
    conn = sqlite3.connect(DB_PATH)

    row = conn.execute(
        "SELECT course_id, name, credits, dept, sem, year FROM courses WHERE course_id = ?",
        (q.upper(),),
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT course_id, name, credits, dept, sem, year FROM courses "
            "WHERE LOWER(name) LIKE ? ORDER BY year, course_id LIMIT 3",
            (f"%{q.lower()}%",),
        ).fetchall()
        if not row:
            conn.close()
            return f"课程库中未找到与「{query}」匹配的课程。"
        if len(row) > 1:
            conn.close()
            cands = ", ".join(f"{r[0]}({r[1]})" for r in row)
            return f"找到多门匹配课程:{cands}。请用课程代码精确查询。"
        row = row[0]

    cid, name, credits, dept, sem, year = row
    chain = _prereq_chain(conn, cid, set())

    # 反向查:哪些课以本课为先修(帮助回答"修了它有什么用")
    dependents = conn.execute(
        "SELECT course_id FROM courses WHERE prerequisites LIKE ?", (f'%"{cid}"%',)
    ).fetchall()
    conn.close()

    sem_cn = {"Sep": "九月学期", "Apr": "四月学期"}.get(sem, sem)
    result = (
        f"{cid} {name}\n"
        f"  学分:{credits} | 学院:{dept} | 开设:{sem_cn} | 建议 Year {year}"
    )
    if chain:
        # 链中课程按依赖顺序展示(最后是无先修的根课程)
        result += f"\n  先修链:{cid} ← " + " ← ".join(dict.fromkeys(chain))
    else:
        result += "\n  先修链:无(可直接修读)"
    if dependents:
        result += f"\n  本课是以下课程的先修:{', '.join(d[0] for d in dependents)}"
    return result

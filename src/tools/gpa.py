"""GPA 计算与分析工具(Pydantic 结构化输出)。

结构化输出的价值:返回值有固定 schema,GPA 报告可以直接用于展示或下游处理,
而不是一段需要再解析的自然语言。课程对应:P41-50(Pydantic 模式)
"""
import sqlite3

from langchain_core.tools import tool
from pydantic import BaseModel

DB_PATH = "data/campus.db"


class CourseGrade(BaseModel):
    course_id: str
    name: str
    credits: float
    grade_point: float
    letter: str


class GpaReport(BaseModel):
    total_credits: float
    weighted_gpa: float
    strongest: CourseGrade
    weakest: CourseGrade
    level: str
    advice: str


@tool
def calculate_gpa() -> dict:
    """计算本学期加权 GPA 并生成分析报告:总学分、最强/最弱课程、等级与建议。

    适用于:"我这学期 GPA 多少""哪门课最拉分""绩点怎么样"。
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        """
        SELECT g.course_id, c.name, c.credits, g.grade_point, g.letter
        FROM grades g JOIN courses c ON g.course_id = c.course_id
        """
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "grades 表无成绩记录"}

    grades = [
        CourseGrade(course_id=r[0], name=r[1], credits=r[2], grade_point=r[3], letter=r[4])
        for r in rows
    ]
    total = sum(g.credits for g in grades)
    gpa = round(sum(g.grade_point * g.credits for g in grades) / total, 2)
    weakest = min(grades, key=lambda g: g.grade_point)
    strongest = max(grades, key=lambda g: g.grade_point)

    if gpa >= 3.7:
        level, advice = "优秀", "保持节奏,可考虑挑战更高阶课程或参与科研/竞赛。"
    elif gpa >= 3.0:
        level, advice = (
            "良好",
            f"整体稳健。重点补 {weakest.course_id}({weakest.name},{weakest.letter}),"
            f"它是当前绩点的主要拖累项。",
        )
    else:
        level, advice = (
            "预警",
            f"绩点偏低,{weakest.course_id} 需要优先补救,建议预约任课老师 office hour 并调整时间分配。",
        )

    report = GpaReport(
        total_credits=total,
        weighted_gpa=gpa,
        strongest=strongest,
        weakest=weakest,
        level=level,
        advice=advice,
    ).model_dump()

    # M4:把本次 GPA 结果顺手写进长期画像(工具内写记忆的示范)。
    # store 未挂载(裸 CLI/测试)时静默跳过,不影响主流程。
    try:
        from langgraph.config import get_config, get_store

        user = (get_config() or {}).get("configurable", {}).get("user_id")
        if user:
            store = get_store()
            store.put(
                ("profiles", user),
                "latest_gpa",
                {"value": f"{gpa}({level}),最弱 {weakest.course_id} {weakest.letter}"},
            )
    except Exception:
        pass  # 记忆系统不在场,不拦正事

    return report

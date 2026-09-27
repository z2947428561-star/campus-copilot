"""登录用户的课程与成绩数据；公共课程目录仍在 campus.db。"""
import sqlite3
from pathlib import Path

from auth import _conn, _ph

CATALOG_DB = Path(__file__).resolve().parents[1] / "data" / "campus.db"
SEMESTER = "September Semester 2026"


def init_student_data() -> None:
    with _conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS student_grades (
            user_id TEXT NOT NULL, semester TEXT NOT NULL, course_id TEXT NOT NULL,
            grade_point DOUBLE PRECISION NOT NULL, letter TEXT NOT NULL,
            PRIMARY KEY (user_id, semester, course_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS student_courses (
            user_id TEXT NOT NULL, semester TEXT NOT NULL, course_id TEXT NOT NULL,
            PRIMARY KEY (user_id, semester, course_id))""")
        conn.commit()


def course_details(course_id: str) -> dict | None:
    with sqlite3.connect(CATALOG_DB) as conn:
        row = conn.execute(
            "SELECT course_id, name, credits FROM courses WHERE course_id = ?",
            (course_id.strip().upper(),),
        ).fetchone()
    return dict(zip(("course_id", "name", "credits"), row)) if row else None


def set_grade(user_id: str, course_id: str, grade_point: float, letter: str,
              semester: str = SEMESTER) -> dict:
    course = course_details(course_id)
    if course is None:
        raise ValueError("课程库中不存在该课程")
    if not 0 <= grade_point <= 4 or not letter.strip():
        raise ValueError("绩点需在 0–4 之间，等级不能为空")
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_grades WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, semester, course["course_id"]),
        )
        conn.execute(
            f"INSERT INTO student_grades (user_id,semester,course_id,grade_point,letter) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph})",
            (user_id, semester, course["course_id"], grade_point, letter.strip().upper()),
        )
        conn.commit()
    return {**course, "grade_point": grade_point, "letter": letter.strip().upper(), "semester": semester}


def delete_grade(user_id: str, course_id: str, semester: str = SEMESTER) -> None:
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_grades WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, semester, course_id.strip().upper()),
        )
        conn.commit()


def list_grades(user_id: str, semester: str = SEMESTER) -> list[dict]:
    ph = _ph()
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT course_id,grade_point,letter FROM student_grades "
            f"WHERE user_id={ph} AND semester={ph} ORDER BY course_id",
            (user_id, semester),
        ).fetchall()
    return [{**(course_details(cid) or {"course_id": cid, "name": cid, "credits": 0}),
             "grade_point": point, "letter": letter} for cid, point, letter in rows]


def set_course(user_id: str, course_id: str, semester: str = SEMESTER) -> dict:
    course = course_details(course_id)
    if course is None:
        raise ValueError("课程库中不存在该课程")
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_courses WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, semester, course["course_id"]),
        )
        conn.execute(
            f"INSERT INTO student_courses (user_id,semester,course_id) VALUES ({ph},{ph},{ph})",
            (user_id, semester, course["course_id"]),
        )
        conn.commit()
    return course


def delete_course(user_id: str, course_id: str, semester: str = SEMESTER) -> None:
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_courses WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, semester, course_id.strip().upper()),
        )
        conn.commit()


def list_courses(user_id: str, semester: str = SEMESTER) -> list[dict]:
    ph = _ph()
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT course_id FROM student_courses WHERE user_id={ph} AND semester={ph} ORDER BY course_id",
            (user_id, semester),
        ).fetchall()
    with sqlite3.connect(CATALOG_DB) as conn:
        out = []
        for (cid,) in rows:
            course = course_details(cid)
            sessions = conn.execute(
                "SELECT weekday,period,room,weeks FROM timetable WHERE course_id=? ORDER BY weekday,period",
                (cid,),
            ).fetchall()
            out.append({**(course or {"course_id": cid, "name": cid}),
                        "sessions": [dict(zip(("weekday", "period", "room", "weeks"), s)) for s in sessions]})
    return out

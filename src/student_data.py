"""登录用户的课程与成绩数据；公共课程目录仍在 campus.db。"""
from pathlib import Path

from auth import _conn, _ph, _use_pg
from semesters import catalog_connection, resolve_semester, term_rows

CATALOG_DB = Path(__file__).resolve().parents[1] / "data" / "campus.db"


def init_student_data() -> None:
    with _conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS student_grades (
            user_id TEXT NOT NULL, semester TEXT NOT NULL, course_id TEXT NOT NULL,
            grade_point DOUBLE PRECISION NOT NULL, letter TEXT NOT NULL,
            PRIMARY KEY (user_id, semester, course_id))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS student_courses (
            user_id TEXT NOT NULL, semester TEXT NOT NULL, course_id TEXT NOT NULL,
            PRIMARY KEY (user_id, semester, course_id))""")
        for name, kind in (("credits_snapshot", "DOUBLE PRECISION"), ("name_snapshot", "TEXT")):
            if _use_pg():
                conn.execute(f"ALTER TABLE student_grades ADD COLUMN IF NOT EXISTS {name} {kind}")
            elif name not in {row[1] for row in conn.execute("PRAGMA table_info(student_grades)")}:
                conn.execute(f"ALTER TABLE student_grades ADD COLUMN {name} {kind}")
        conn.commit()


def course_details(course_id: str) -> dict | None:
    with catalog_connection() as conn:
        row = conn.execute(
            "SELECT course_id, name, credits FROM courses WHERE course_id = ?",
            (course_id.strip().upper(),),
        ).fetchone()
    return dict(zip(("course_id", "name", "credits"), row)) if row else None


def set_grade(user_id: str, course_id: str, grade_point: float, letter: str,
              semester: str | None = None) -> dict:
    term = resolve_semester(semester)
    course = course_details(course_id)
    if course is None:
        raise ValueError("课程库中不存在该课程")
    if not 0 <= grade_point <= 4 or not letter.strip():
        raise ValueError("绩点需在 0–4 之间，等级不能为空")
    ph = _ph()
    with _conn() as conn:
        old = conn.execute(
            f"SELECT credits_snapshot,name_snapshot FROM student_grades WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, term["storage_key"], course["course_id"])).fetchone()
        credits = old[0] if old and old[0] is not None else course["credits"]
        name = old[1] if old and old[1] is not None else course["name"]
        conn.execute(
            f"DELETE FROM student_grades WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, term["storage_key"], course["course_id"]),
        )
        conn.execute(
            f"INSERT INTO student_grades (user_id,semester,course_id,grade_point,letter,credits_snapshot,name_snapshot) "
            f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
            (user_id, term["storage_key"], course["course_id"], grade_point, letter.strip().upper(), credits, name),
        )
        conn.commit()
    return {**course, "credits": credits, "name": name, "grade_point": grade_point, "letter": letter.strip().upper(),
            "semester": term["label"], "semester_id": term["semester_id"]}


def delete_grade(user_id: str, course_id: str, semester: str | None = None) -> None:
    term = resolve_semester(semester)
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_grades WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, term["storage_key"], course_id.strip().upper()),
        )
        conn.commit()


def list_grades(user_id: str, semester: str | None = None) -> list[dict]:
    term = resolve_semester(semester)
    ph = _ph()
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT course_id,grade_point,letter,credits_snapshot,name_snapshot FROM student_grades "
            f"WHERE user_id={ph} AND semester={ph} ORDER BY course_id",
            (user_id, term["storage_key"]),
        ).fetchall()
    out = []
    for cid, point, letter, credits, name in rows:
        course = course_details(cid) or {"course_id": cid, "name": cid, "credits": 0}
        out.append({**course, "name": name if name is not None else course["name"],
                    "credits": credits if credits is not None else course["credits"],
                    "credits_source": "grade_snapshot" if credits is not None else "current_catalog",
                    "grade_point": point, "letter": letter,
                    "semester_id": term["semester_id"], "semester": term["label"]})
    return out


def set_course(user_id: str, course_id: str, semester: str | None = None) -> dict:
    term = resolve_semester(semester)
    course = course_details(course_id)
    if course is None:
        raise ValueError("课程库中不存在该课程")
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_courses WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, term["storage_key"], course["course_id"]),
        )
        conn.execute(
            f"INSERT INTO student_courses (user_id,semester,course_id) VALUES ({ph},{ph},{ph})",
            (user_id, term["storage_key"], course["course_id"]),
        )
        conn.commit()
    return {**course, "semester_id": term["semester_id"], "semester": term["label"]}


def delete_course(user_id: str, course_id: str, semester: str | None = None) -> None:
    term = resolve_semester(semester)
    ph = _ph()
    with _conn() as conn:
        conn.execute(
            f"DELETE FROM student_courses WHERE user_id={ph} AND semester={ph} AND course_id={ph}",
            (user_id, term["storage_key"], course_id.strip().upper()),
        )
        conn.commit()


def list_courses(user_id: str, semester: str | None = None) -> list[dict]:
    term = resolve_semester(semester)
    ph = _ph()
    with _conn() as conn:
        rows = conn.execute(
            f"SELECT course_id FROM student_courses WHERE user_id={ph} AND semester={ph} ORDER BY course_id",
            (user_id, term["storage_key"]),
        ).fetchall()
    with catalog_connection() as conn:
        timetable = term_rows(conn, "timetable", term)
        out = []
        for (cid,) in rows:
            course = course_details(cid)
            sessions = sorted([s for s in timetable if s["course_id"] == cid], key=lambda s: (s["weekday"], s["period"]))
            out.append({**(course or {"course_id": cid, "name": cid}),
                        "semester_id": term["semester_id"], "semester": term["label"],
                        "schedule_status": term["schedule_status"],
                        "sessions": [{k: s[k] for k in ("weekday", "period", "room", "weeks")} for s in sessions]})
    return out

"""建库脚本:读取 data/structured/seed_*.json,重建 data/campus.db(SQLite)。

设计要点:
- 可重复执行:每次先 DROP 再 CREATE,种子数据改完重跑即可
- prerequisites 以 JSON 数组字符串存储(SQLite 无数组类型)
- 布尔用 0/1(SQLite 无布尔类型)
- 数据库文件 data/campus.db 已被 .gitignore 忽略,不入库

运行(项目根目录):.venv\\Scripts\\python scripts\\init_db.py
"""
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 项目根目录(脚本在 scripts/ 下)
DB_PATH = ROOT / "data" / "campus.db"
SEED_DIR = ROOT / "data" / "structured"


def load_seed(filename: str) -> dict:
    with open(SEED_DIR / filename, encoding="utf-8") as f:
        return json.load(f)


def create_tables(cur: sqlite3.Cursor) -> None:
    cur.executescript(
        """
        DROP TABLE IF EXISTS courses;
        DROP TABLE IF EXISTS classrooms;
        DROP TABLE IF EXISTS timetable;
        DROP TABLE IF EXISTS calendar_weeks;
        DROP TABLE IF EXISTS semester_events;
        DROP TABLE IF EXISTS grades;

        CREATE TABLE courses(
            course_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            credits REAL NOT NULL,
            dept TEXT,
            prerequisites TEXT NOT NULL DEFAULT '[]',
            sem TEXT,
            year INTEGER
        );

        CREATE TABLE classrooms(
            room_id TEXT PRIMARY KEY,
            building TEXT,
            type TEXT,
            capacity INTEGER,
            has_projector INTEGER,
            has_ac INTEGER
        );

        CREATE TABLE timetable(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room TEXT NOT NULL,
            weekday INTEGER NOT NULL,
            period TEXT NOT NULL,
            course_id TEXT,
            weeks TEXT NOT NULL,
            FOREIGN KEY (room) REFERENCES classrooms(room_id),
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );

        CREATE TABLE calendar_weeks(
            week_no INTEGER PRIMARY KEY,
            semester TEXT NOT NULL,
            academic_year TEXT,
            start TEXT NOT NULL,
            end TEXT NOT NULL,
            type TEXT NOT NULL
        );

        CREATE TABLE semester_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT
        );

        CREATE TABLE grades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id TEXT NOT NULL,
            score REAL,
            letter TEXT,
            grade_point REAL,
            semester TEXT,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        );
        """
    )


def seed_courses(cur: sqlite3.Cursor, data: dict) -> None:
    for c in data["courses"]:
        cur.execute(
            "INSERT INTO courses VALUES (?,?,?,?,?,?,?)",
            (
                c["course_id"],
                c["name"],
                c["credits"],
                c["dept"],
                json.dumps(c["prerequisites"], ensure_ascii=False),
                c["sem"],
                c["year"],
            ),
        )


def seed_classrooms(cur: sqlite3.Cursor, data: dict) -> None:
    for r in data["rooms"]:
        cur.execute(
            "INSERT INTO classrooms VALUES (?,?,?,?,?,?)",
            (
                r["room_id"],
                data["building"],
                r["type"],
                r["capacity"],
                int(r["has_projector"]),
                int(r["has_ac"]),
            ),
        )


def seed_timetable(cur: sqlite3.Cursor, data: dict) -> None:
    for e in data["entries"]:
        cur.execute(
            "INSERT INTO timetable(room, weekday, period, course_id, weeks) VALUES (?,?,?,?,?)",
            (e["room"], e["weekday"], e["period"], e["course_id"], e["weeks"]),
        )


def seed_academic_cal(cur: sqlite3.Cursor, data: dict) -> None:
    sem, ay = data["semester"], data["academic_year"]
    for w in data["weeks"]:
        cur.execute(
            "INSERT INTO calendar_weeks VALUES (?,?,?,?,?,?)",
            (w["week_no"], sem, ay, w["start"], w["end"], w["type"]),
        )

    def add_event(name: str, etype: str, start: str, end: str | None = None) -> None:
        cur.execute(
            "INSERT INTO semester_events(name, event_type, start_date, end_date) VALUES (?,?,?,?)",
            (name, etype, start, end),
        )

    for d in data["registration_days"]:
        add_event("Registration Day", "registration", d)
    add_event("Orientation Day", "orientation", data["orientation_day"])

    rw = data["revision_week"]
    add_event("Revision Week", "revision", rw["start"], rw["end"])
    ew = data["exam_week"]
    add_event("Examination Week", "exam", ew["start"], ew["end"])
    sb = data["semester_break"]
    add_event("Semester Break", "break", sb["start"], sb["end"])

    for h in data["holidays_in_semester"]:
        add_event(h["name"], "holiday", h["date"])


def seed_grades(cur: sqlite3.Cursor, data: dict) -> None:
    sem = data["student_profile"]["semester"]
    for r in data["records"]:
        cur.execute(
            "INSERT INTO grades(course_id, score, letter, grade_point, semester) VALUES (?,?,?,?,?)",
            (r["course_id"], r["score"], r["letter"], r["grade_point"], sem),
        )


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    create_tables(cur)
    seed_courses(cur, load_seed("seed_courses.json"))
    seed_classrooms(cur, load_seed("seed_classrooms.json"))
    seed_timetable(cur, load_seed("seed_timetable.json"))
    seed_academic_cal(cur, load_seed("seed_academic_cal.json"))
    seed_grades(cur, load_seed("seed_grades.json"))
    conn.commit()

    print(f"数据库已重建:{DB_PATH}\n")
    for table in ["courses", "classrooms", "timetable", "calendar_weeks", "semester_events", "grades"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {n} 行")
    conn.close()


if __name__ == "__main__":
    main()

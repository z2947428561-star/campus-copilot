"""Build a temporary public catalog for browser tests, never copy daily databases."""
from contextlib import closing
import sqlite3

from init_db import (create_tables, load_seed, seed_academic_cal, seed_classrooms,
                     seed_courses, seed_timetable)


def create_catalog(path):
    with closing(sqlite3.connect(path)) as conn, conn:
        cur = conn.cursor()
        create_tables(cur)
        seed_courses(cur, load_seed("seed_courses.json"))
        seed_classrooms(cur, load_seed("seed_classrooms.json"))
        seed_timetable(cur, load_seed("seed_timetable.json"))
        seed_academic_cal(cur, load_seed("seed_academic_cal.json"))


def add_test_semester(path):
    """A clearly labelled synthetic term, present only in the browser-test app."""
    from semesters import import_semester
    import_semester({"semester_id": "2027-04", "label": "测试学期 2027-04", "academic_year": "2026/2027",
        "start_date": "2027-04-01", "end_date": "2027-05-01", "source": "synthetic-browser-fixture",
        "is_demo": True, "weeks": [{"week_no": 1, "start": "2027-04-05", "end": "2027-04-11"}],
        "events": [], "timetable": None}, path)

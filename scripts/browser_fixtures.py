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

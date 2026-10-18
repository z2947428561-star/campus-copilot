"""Semester-scoped student APIs and tools with temporary public/private fixtures."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from browser_fixtures import create_catalog
from test_semesters import second_term


class SemesterFixture:
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="semester-data-")
        cls.path = Path(cls.tmp.name) / "catalog.db"
        cls.env = patch.dict(os.environ, {"CAMPUS_SKIP_DOTENV": "1", "MEMORY_BACKEND": "sqlite",
            "MEMORY_DB_PATH": str(Path(cls.tmp.name) / "personal.db"), "LANGSMITH_TRACING": "false"})
        cls.env.start()
        from fastapi.testclient import TestClient
        import student_data
        import semesters
        import server
        cls.semesters = semesters
        cls.student = student_data
        cls.catalog_patch = patch.object(student_data, "CATALOG_DB", cls.path)
        cls.catalog_patch.start()
        cls.client = TestClient(server.app)
        cls.client.__enter__()
        cls.alice = cls.register("AAA2509001")
        cls.bob = cls.register("BBB2509002")

    @classmethod
    def register(cls, user):
        response = cls.client.post("/api/register", json={"username": user, "password": "Testpass123"})
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["token"]}

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.catalog_patch.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def setUp(self):
        create_catalog(self.path)
        self.semesters.import_semester(second_term(), self.path)
        from auth import _conn
        with _conn() as conn:
            conn.execute("DELETE FROM student_grades")
            conn.execute("DELETE FROM student_courses")
            conn.commit()

    def save_grade(self, semester, point=3.7, course="CS101"):
        response = self.client.put("/api/me/grades", headers=self.alice,
            json={"course_id": course, "grade_point": point, "letter": "A-", "semester_id": semester})
        self.assertEqual(response.status_code, 200, response.text)


class SemesterDataTest(SemesterFixture, unittest.TestCase):
    def test_same_course_across_semesters_and_users_is_independent(self):
        self.save_grade("2026-09", 3.7)
        self.save_grade("2027-04", 1.)
        for term, point in [("2026-09", 3.7), ("2027-04", 1.)]:
            response = self.client.get("/api/me/grades", headers=self.alice, params={"semester_id": term})
            self.assertEqual(response.json()["grades"][0]["grade_point"], point)
            self.assertEqual(response.json()["semester_id"], term)
            self.assertEqual(self.client.get("/api/me/grades", headers=self.bob,
                params={"semester_id": term}).json()["grades"], [])
        self.client.delete("/api/me/grades/CS101", headers=self.alice, params={"semester_id": "2027-04"})
        self.assertEqual(len(self.student.list_grades("AAA2509001", "2026-09")), 1)
        self.assertEqual(self.student.list_grades("AAA2509001", "2027-04"), [])

    def test_selected_courses_use_only_the_selected_semester_schedule(self):
        for term in ("2026-09", "2027-04"):
            response = self.client.put("/api/me/courses", headers=self.alice,
                json={"course_id": "CS101", "semester_id": term})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.student.list_courses("AAA2509001", "2026-09")[0]["sessions"]), 4)
        self.assertEqual(len(self.student.list_courses("AAA2509001", "2027-04")[0]["sessions"]), 1)

    def test_unknown_semester_is_rejected_and_legacy_name_is_accepted(self):
        result = self.client.put("/api/me/grades", headers=self.alice,
            json={"course_id": "CS101", "grade_point": 3., "letter": "B", "semester_id": "unknown"})
        self.assertEqual(result.status_code, 400)
        self.student.set_grade("AAA2509001", "CS101", 3., "B", semester="September Semester 2026")
        self.assertEqual(self.student.list_grades("AAA2509001", "2026-09")[0]["grade_point"], 3.)

    def test_new_gpa_uses_grade_credit_snapshots_after_catalog_changes(self):
        from tools.gpa import calculate_gpa
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE courses SET credits=4 WHERE course_id='CS101'")
            conn.execute("UPDATE courses SET credits=2 WHERE course_id='CS102'")
        self.save_grade("2026-09", 3., "CS101")
        self.save_grade("2026-09", 4., "CS102")
        self.save_grade("2027-04", 1.)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("UPDATE courses SET credits=1 WHERE course_id='CS101'")
        runtime = SimpleNamespace(context=SimpleNamespace(user_id="AAA2509001", semester_id="2026-09"), store=None)
        result = json.loads(calculate_gpa.func(runtime=runtime))
        self.assertEqual(result["weighted_gpa"], 3.33)
        self.assertEqual(result["total_credits"], 6.)
        self.assertEqual(result["semester_id"], "2026-09")
        result = json.loads(calculate_gpa.func(runtime=runtime, semester_id="2027-04"))
        self.assertEqual(result["weighted_gpa"], 1.)

    def test_legacy_grades_keep_data_and_explain_credit_fallback(self):
        from auth import _conn
        from tools.gpa import calculate_gpa
        with _conn() as conn:
            conn.execute("INSERT INTO student_grades(user_id,semester,course_id,grade_point,letter) VALUES (?,?,?,?,?)",
                         ("AAA2509001", "September Semester 2026", "CS101", 3.7, "A-"))
            conn.commit()
        runtime = SimpleNamespace(context=SimpleNamespace(user_id="AAA2509001", semester_id="2026-09"), store=None)
        report = json.loads(calculate_gpa.func(runtime=runtime))
        self.assertTrue(report["ok"])
        self.assertTrue(report["warnings"])

    def test_calendar_handles_two_week_semester_missing_events_and_outside_dates(self):
        from tools.academic import get_academic_week
        output = get_academic_week.func("2027-04-06")
        self.assertIn("第 1 教学周", output)
        self.assertIn("2 周", output)
        self.assertIn("测试四月学期", output)
        self.assertIn("未", get_academic_week.func("2030-01-01"))
        self.assertNotIn("九月学期", get_academic_week.func("2030-01-01"))

    def test_missing_timetable_is_not_reported_as_every_room_free(self):
        from tools.timetable import find_empty_classrooms
        term = second_term()
        term["timetable"] = None
        self.semesters.import_semester(term, self.path, expected_version=1)
        result = json.loads(find_empty_classrooms.func(1, "08:30-10:00", 1, semester_id="2027-04"))
        self.assertFalse(result["ok"])
        self.assertNotIn("rooms", result)

    def test_schedule_and_room_tools_use_context_and_validate_actual_week_range(self):
        from tools.timetable import find_empty_classrooms, query_course_schedule
        runtime = SimpleNamespace(context=SimpleNamespace(user_id="AAA2509001", semester_id="2027-04"))
        schedule = json.loads(query_course_schedule.func("CS101", runtime=runtime))
        self.assertEqual(schedule["semester_id"], "2027-04")
        self.assertEqual(len(schedule["sessions"]), 1)
        result = json.loads(find_empty_classrooms.func(1, "08:30-10:00", 3, runtime=runtime))
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()

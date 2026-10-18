"""Storage transactions and concurrent student updates against temporary SQLite."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from test_semester_data import SemesterFixture


class StorageTest(SemesterFixture, unittest.TestCase):
    def test_transaction_rollback_and_read_only(self):
        import storage
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with storage.personal_connection() as conn:
                conn.execute("INSERT INTO student_courses VALUES (?,?,?)", ("rollback", "term", "CS101"))
                raise RuntimeError("rollback")
        with storage.personal_connection(read_only=True) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM student_courses WHERE user_id='rollback'").fetchone()[0], 0)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM student_courses")

    def test_concurrent_grade_updates_preserve_snapshot(self):
        self.student.set_grade("AAA2509001", "CS101", 3., "B", "2026-09")
        from semesters import catalog_connection
        with catalog_connection(write=True) as conn:
            conn.execute("UPDATE courses SET credits=9, name='changed' WHERE course_id='CS101'")
            conn.commit()
        with ThreadPoolExecutor(max_workers=8) as executor:
            result = list(executor.map(lambda i: self.student.set_grade(
                "AAA2509001", "CS101", (i % 5), "B", "2026-09"), range(24)))
        self.assertEqual(len(result), 24)
        rows = self.student.list_grades("AAA2509001", "2026-09")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["credits"], 4)
        self.assertNotEqual(rows[0]["name"], "changed")

    def test_concurrent_course_selection_is_idempotent(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _: self.student.set_course("AAA2509001", "CS101", "2026-09"), range(24)))
        self.assertEqual(len(self.student.list_courses("AAA2509001", "2026-09")), 1)

    def test_missing_personal_read_does_not_create_database(self):
        import storage
        missing = Path(self.tmp.name) / "absent" / "personal.db"
        with patch.object(storage.config, "MEMORY_DB_PATH", str(missing)):
            with self.assertRaises(sqlite3.OperationalError):
                with storage.personal_connection(read_only=True):
                    self.fail("missing database opened")
        self.assertFalse(missing.parent.exists())

    def test_missing_course_lookup_does_not_create_database(self):
        import tools.courses as courses
        missing = Path(self.tmp.name) / "missing-catalog.db"
        with patch.object(courses, "DB_PATH", str(missing)):
            with self.assertRaises(sqlite3.OperationalError):
                courses.query_course.invoke({"query": "CS101"})
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()

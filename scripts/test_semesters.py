"""Semester catalog, legacy migration and versioned import on temporary public data."""
from contextlib import closing
from copy import deepcopy
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["CAMPUS_SKIP_DOTENV"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from browser_fixtures import create_catalog


def second_term():
    return {"semester_id": "2027-04", "label": "测试四月学期 2027", "academic_year": "2026/2027",
            "start_date": "2027-04-01", "end_date": "2027-05-01", "is_demo": True,
            "source": "synthetic-test-fixture", "weeks": [
                {"week_no": 1, "start": "2027-04-05", "end": "2027-04-11", "type": "teaching"},
                {"week_no": 2, "start": "2027-04-12", "end": "2027-04-18", "type": "teaching"}],
            "events": [], "timetable": [{"course_id": "CS101", "room": "A101", "weekday": 1,
                                          "period": "08:30-10:00", "weeks": "1-2"}]}


class SemesterCatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="semester-catalog-")
        self.path = Path(self.tmp.name) / "catalog.db"
        create_catalog(self.path)
        import semesters
        self.semesters = semesters

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_reads_are_non_mutating_and_preserve_the_original_name(self):
        before = self.path.read_bytes()
        terms = self.semesters.list_semesters(self.path)
        self.assertEqual(terms[0]["semester_id"], "2026-09")
        self.assertEqual(terms[0]["storage_key"], "September Semester 2026")
        self.assertEqual(terms[0]["end_date"], "2027-02-11")
        self.assertEqual(self.path.read_bytes(), before)

    def test_migration_preserves_old_ids_records_and_is_idempotent(self):
        with closing(sqlite3.connect(self.path)) as conn:
            original = conn.execute("SELECT * FROM timetable ORDER BY id").fetchall()
        self.semesters.migrate_catalog(self.path)
        self.semesters.migrate_catalog(self.path)
        with closing(sqlite3.connect(self.path)) as conn:
            rows = conn.execute("SELECT id,room,weekday,period,course_id,weeks FROM timetable ORDER BY id").fetchall()
            self.assertEqual(rows, original)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM calendar_weeks WHERE semester_id='2026-09'").fetchone()[0], 14)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM semesters").fetchone()[0], 1)

    def test_two_semesters_can_each_have_week_one_and_keep_schedules_separate(self):
        self.semesters.import_semester(second_term(), self.path)
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM calendar_weeks WHERE week_no=1").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM timetable WHERE semester_id='2026-09'").fetchone()[0], 33)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM timetable WHERE semester_id='2027-04'").fetchone()[0], 1)
        term = self.semesters.resolve_date("2027-04-06", path=self.path)
        self.assertEqual(term["semester_id"], "2027-04")

    def test_invalid_import_rolls_back_migration_and_every_row(self):
        invalid = second_term()
        invalid["timetable"][0]["course_id"] = "NO_SUCH_COURSE"
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.semesters.import_semester(invalid, self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_version_checks_prevent_lost_updates_and_equal_content_is_idempotent(self):
        term = second_term()
        first = self.semesters.import_semester(term, self.path)
        again = self.semesters.import_semester(term, self.path)
        self.assertEqual(first["version"], 1)
        self.assertEqual(again["version"], 1)
        changed = deepcopy(term)
        changed["timetable"][0]["room"] = "A102"
        for expected in (None, 0):
            with self.assertRaises(ValueError):
                self.semesters.import_semester(changed, self.path, expected_version=expected)
        updated = self.semesters.import_semester(changed, self.path, expected_version=1)
        self.assertEqual(updated["version"], 2)

    def test_missing_timetable_is_explicit_and_does_not_claim_no_occupancy(self):
        term = second_term()
        del term["timetable"]
        self.semesters.import_semester(term, self.path)
        resolved = self.semesters.resolve_semester("2027-04", path=self.path)
        self.assertEqual(resolved["schedule_status"], "unavailable")

    def test_outside_dates_and_overlapping_semesters_require_clarification(self):
        with self.assertRaises(ValueError):
            self.semesters.resolve_date("2030-01-01", path=self.path)
        term = second_term()
        term.update(semester_id="2026-10", start_date="2026-10-01", end_date="2027-05-01")
        self.semesters.import_semester(term, self.path)
        with self.assertRaises(ValueError):
            self.semesters.resolve_date("2026-10-18", path=self.path)

    def test_unknown_term_and_missing_database_never_create_files(self):
        with self.assertRaises(ValueError):
            self.semesters.resolve_semester("unknown", path=self.path)
        missing = self.path.parent / "missing.db"
        self.assertEqual(self.semesters.list_semesters(missing), [])
        self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()

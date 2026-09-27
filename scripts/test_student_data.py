"""离线验证个人课程/成绩 API 的用户隔离和 GPA 数据来源。"""
import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class StudentDataTest(unittest.TestCase):
    def test_personal_data_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = {
                "CAMPUS_SKIP_DOTENV": "1", "MEMORY_BACKEND": "sqlite",
                "MEMORY_DB_PATH": str(Path(tmp) / "memory.db"), "LANGSMITH_TRACING": "false",
            }
            with patch.dict(os.environ, settings):
                from fastapi.testclient import TestClient
                from server import app
                from tools.gpa import _load_grades
                from tools.gpa import calculate_gpa
                from tools.timetable import query_my_schedule
                from context import UserContext

                with TestClient(app) as client:
                    def register(name):
                        response = client.post("/api/register", json={"username": name, "password": "Testpass123"})
                        self.assertEqual(response.status_code, 200, response.text)
                        return {"Authorization": "Bearer " + response.json()["token"]}

                    alice = register("AAA2509001")
                    bob = register("BBB2509002")
                    self.assertEqual(client.get("/api/me/grades").status_code, 401)
                    self.assertEqual(client.put("/api/me/grades", headers=alice,
                        json={"course_id": "CS101", "grade_point": 3.7, "letter": "A-"}).status_code, 200)
                    self.assertEqual(client.put("/api/me/courses", headers=alice,
                        json={"course_id": "CS101"}).status_code, 200)
                    self.assertEqual(len(client.get("/api/me/grades", headers=alice).json()["grades"]), 1)
                    self.assertEqual(client.get("/api/me/grades", headers=bob).json()["grades"], [])
                    self.assertEqual(client.get("/api/me/courses", headers=bob).json()["courses"], [])
                    self.assertEqual(client.put("/api/me/grades", headers=bob,
                        json={"course_id": "CS101", "grade_point": 4.5, "letter": "A"}).status_code, 422)
                    self.assertEqual(client.delete("/api/me/grades/CS101", headers=bob).status_code, 200)
                    self.assertEqual(len(client.get("/api/me/grades", headers=alice).json()["grades"]), 1)
                    self.assertEqual(_load_grades("BBB2509002"), [])
                    self.assertEqual(_load_grades("AAA2509001")[0].grade_point, 3.7)
                    alice_runtime = SimpleNamespace(context=UserContext(user_id="AAA2509001"), store=None)
                    bob_runtime = SimpleNamespace(context=UserContext(user_id="BBB2509002"), store=None)
                    self.assertEqual(json.loads(calculate_gpa.func(runtime=alice_runtime))["weighted_gpa"], 3.7)
                    self.assertFalse(json.loads(calculate_gpa.func(runtime=bob_runtime))["ok"])
                    self.assertEqual(json.loads(query_my_schedule.func(runtime=alice_runtime))["courses"][0]["course_id"], "CS101")
                    self.assertEqual(json.loads(query_my_schedule.func(runtime=bob_runtime))["courses"], [])


if __name__ == "__main__":
    unittest.main()

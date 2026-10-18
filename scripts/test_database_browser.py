"""Database-browser API contracts, using temporary stores and public synthetic rows."""
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class DatabaseBrowserTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="browser-api-")
        cls.path = Path(cls.tmp.name)
        cls.env = patch.dict(os.environ, {"CAMPUS_SKIP_DOTENV": "1", "MEMORY_BACKEND": "sqlite",
            "MEMORY_DB_PATH": str(cls.path / "memory.db"), "LANGSMITH_TRACING": "false"})
        cls.env.start()
        from fastapi.testclient import TestClient
        import database_browser
        import student_data
        import server
        from init_db import create_tables
        cls.browser = database_browser
        cls.app = server.app
        cls.catalog_path = cls.path / "campus.db"
        with closing(sqlite3.connect(cls.catalog_path)) as conn, conn:
            create_tables(conn.cursor())
            conn.executemany("INSERT INTO courses VALUES (?,?,?,?,?,?,?)", [
                ("CS101", "Programming 100%_", 3., "CS", "[]", "Sep", 1),
                ("CS102", "Data Structures", 4., "CS", '["CS101"]', "Sep", 1),
                ("CS103", "编程 <img src=x onerror=alert(1)>", 3., "CS", "[]", "Sep", 1),
            ])
        cls.catalog_patch = patch.object(student_data, "CATALOG_DB", cls.catalog_path)
        cls.catalog_patch.start()
        cls.docs = cls.path / "docs"
        cls.docs.mkdir()
        (cls.docs / "attendance.md").write_text("---\ntitle: 考勤测试\nsource_type: manual_summary\n---\n# Attendance\n80%.", encoding="utf-8")
        cls.docs_patch = patch.object(database_browser, "DOCS_DIR", cls.docs)
        cls.docs_patch.start()
        cls.client = TestClient(cls.app)
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
        cls.docs_patch.stop()
        cls.catalog_patch.stop()
        cls.env.stop()
        cls.tmp.cleanup()

    def get(self, source="campus", table="courses", **params):
        return self.client.get(f"/api/database/{source}/{table}", headers=self.alice, params=params)

    def test_authentication_and_page_cache(self):
        for path in ("/api/database", "/api/database/campus/courses", "/api/database/index/chunks"):
            self.assertEqual(self.client.get(path).status_code, 401)
        for path in ("/database", "/assets/css/database.css", "/assets/js/database.js"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_catalog_never_connects_to_index_and_has_only_allowed_tables(self):
        with patch.object(self.browser, "index_page", side_effect=AssertionError("no index calls")):
            response = self.client.get("/api/database", headers=self.alice)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["read_only"])
        names = {t["id"] for s in response.json()["sources"] for t in s["tables"]}
        self.assertNotIn("web_users", names)
        self.assertNotIn("web_tokens", names)
        self.assertNotIn("grades", names)  # The public demo grades are not anybody's grades.
        self.assertIn("snapshots", names)
        self.assertIn("chunks", names)

    def test_pagination_sort_and_schema(self):
        result = self.get(page_size=1, page=2, sort="course_id", direction="desc").json()
        self.assertEqual(result["rows"][0]["course_id"], "CS102")
        self.assertEqual(result["total"], 3)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["columns"][0]["name"], "course_id")
        self.assertTrue(result["columns"][0]["primary"])

    def test_search_treats_wildcards_and_quotes_as_literal_data(self):
        for query, expected in [("100%_", 1), ("_", 1), ("%", 1), ("' OR 1=1 --", 0), ("编程", 1)]:
            with self.subTest(query=query):
                result = self.get(q=query)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["total"], expected)

    def test_identifiers_and_pagination_cannot_escape_whitelist(self):
        for source, table in [("campus", "web_users"), ("personal", "web_tokens"),
                              ("campus", 'courses"; DROP TABLE courses;--'), ("unknown", "courses")]:
            self.assertEqual(self.get(source, table).status_code, 404)
        for params in ({"sort": "password_hash"}, {"sort": 'name"; DELETE FROM courses;--'},
                       {"page": 101, "page_size": 100}):
            self.assertEqual(self.get(**params).status_code, 400)
        for params in ({"page": 0}, {"page_size": 101}, {"q": "x" * 121}, {"direction": "invalid"}):
            self.assertEqual(self.get(**params).status_code, 422)
        self.assertEqual(self.get().json()["total"], 3)

    def test_personal_rows_and_counts_are_scoped_to_the_authenticated_user(self):
        from auth import _conn
        with _conn() as conn:
            for table in ("student_grades", "student_courses", "web_conversations"):
                conn.execute(f'DELETE FROM "{table}"')
            conn.executemany("INSERT INTO student_grades(user_id,semester,course_id,grade_point,letter) VALUES (?,?,?,?,?)", [
                ("AAA2509001", "2026", "CS101", 3.7, "A-"), ("BBB2509002", "2026", "CS102", 4., "A")])
            conn.executemany("INSERT INTO student_courses VALUES (?,?,?)", [
                ("AAA2509001", "2026", "CS101"), ("BBB2509002", "2026", "CS102")])
            conn.executemany("INSERT INTO web_conversations VALUES (?,?,?,?)", [
                ("AAA2509001", "own", "Alice private title", 1.), ("BBB2509002", "other", "Bob private title", 2.)])
            conn.commit()
        for table in ("student_grades", "student_courses", "web_conversations"):
            result = self.get("personal", table).json()
            self.assertEqual(result["total"], 1)
            self.assertNotIn("BBB2509002", str(result))
            self.assertNotIn("CS102", str(result))
            self.assertNotIn("Bob private", str(result))
            self.assertNotIn("user_id", result["rows"][0])
            bob = self.client.get(f"/api/database/personal/{table}", headers=self.bob).json()
            self.assertEqual(bob["total"], 1)
        catalog = self.client.get("/api/database", headers=self.alice).json()
        own = next(s for s in catalog["sources"] if s["id"] == "personal")
        self.assertEqual([t["count"] for t in own["tables"]], [1, 1, 1])

    def test_missing_sqlite_file_is_not_created_and_errors_are_sanitized(self):
        import student_data
        missing = self.path / "secret-production-path.db"
        with patch.object(student_data, "CATALOG_DB", missing):
            response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertFalse(missing.exists())
        self.assertNotIn("secret-production-path", response.text)

    def test_sql_connections_cannot_write(self):
        with self.browser.sql_connection("campus") as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM courses")
        self.assertEqual(self.get().json()["total"], 3)

    def test_postgres_projection_uses_read_only_transaction_and_owned_parameters(self):
        from unittest.mock import MagicMock
        conn = MagicMock()
        conn.execute.return_value.fetchone.return_value = (0,)
        conn.execute.return_value.fetchall.return_value = []
        import psycopg
        with patch.object(self.browser.storage, "uses_postgres", return_value=True), \
             patch.object(self.browser.auth, "authenticate", return_value="AAA2509001"), \
             patch.object(psycopg, "connect") as factory:
            factory.return_value.__enter__.return_value = conn
            result = self.get("personal", "student_grades", q="CS101")
        self.assertEqual(result.status_code, 200)
        calls = conn.execute.call_args_list
        self.assertEqual(calls[0].args[0], "SET TRANSACTION READ ONLY")
        self.assertIn('"user_id"=%s', calls[1].args[0])
        self.assertEqual(calls[1].args[1][0], "AAA2509001")
        self.assertEqual(calls[2].args[1][0], "AAA2509001")

    def test_documents_are_distinct_from_stored_index(self):
        result = self.get("documents", "snapshots", q="考勤").json()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["effective_date"], "unknown")
        self.assertEqual(result["rows"][0]["text"], "# Attendance\n80%.")
        self.assertEqual(result["rows"][0]["filename"], "attendance.md")

    def test_index_projection_excludes_vectors_and_unknown_metadata(self):
        rows = [{"id": 3, "text": "Evidence", "source_type": "manual_summary", "vector": [1., 2.], "token_hash": "private"}]
        with patch.object(self.browser, "index_page", return_value=(rows, 1, False, {"backend": "Fake"})):
            result = self.get("index", "chunks").json()
        self.assertEqual(result["total"], 1)
        self.assertFalse(result["sortable"])
        self.assertNotIn("vector", str(result["rows"]))
        self.assertNotIn("private", str(result))

    def test_milvus_adapter_only_queries_and_closes_connection(self):
        with patch.object(self.browser.config, "KB_BACKEND", "milvus"), patch("pymilvus.MilvusClient") as factory:
            client = factory.return_value
            client.describe_collection.return_value = {"fields": [{"name": "id"}, {"name": "text"},
                {"name": "vector", "params": {"dim": 1024}}], "enable_dynamic_field": True}
            client.query.side_effect = [[{"count(*)": 1}], [{"id": 8, "text": "Indexed evidence"}]]
            response = self.get("index", "chunks", q='a" || true')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["info"]["dimension"], 1024)
            client.close.assert_called_once()
            client.create_collection.assert_not_called()
            client.insert.assert_not_called()
            client.drop_collection.assert_not_called()
            self.assertNotIn("vector", client.query.call_args.kwargs["output_fields"])

    def test_unavailable_milvus_is_reported_without_connection_details(self):
        with patch.object(self.browser.config, "KB_BACKEND", "milvus"), \
             patch("pymilvus.MilvusClient", side_effect=RuntimeError("password=private")):
            response = self.get("index", "chunks")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("password", response.text)

    def test_chroma_missing_path_does_not_create_a_store(self):
        missing = self.path / "missing-index"
        with patch.object(self.browser.config, "KB_BACKEND", "chroma"), \
             patch.object(self.browser.config, "CHROMA_DIR", str(missing)):
            response = self.get("index", "chunks")
        self.assertEqual(response.status_code, 503)
        self.assertFalse(missing.exists())

    def test_real_chroma_browsing_needs_no_embeddings(self):
        import chromadb
        import gc
        path = self.path / "test-chroma"
        client = chromadb.PersistentClient(path=str(path))
        collection = client.create_collection("browser_test", embedding_function=None)
        collection.add(ids=["a", "b"], documents=["Attendance evidence", "Fees evidence"],
                       embeddings=[[1., 0.], [0., 1.]], metadatas=[{"title": "Attendance"}, {"title": "Fees"}])
        try:
            with patch.object(self.browser.config, "KB_BACKEND", "chroma"), \
                 patch.object(self.browser.config, "CHROMA_DIR", str(path)), \
                 patch.object(self.browser.config, "MILVUS_COLLECTION", "browser_test"):
                result = self.get("index", "chunks", page_size=1).json()
                self.assertEqual(result["total"], 2)
                self.assertTrue(result["has_more"])
                result = self.get("index", "chunks", q="Attendance").json()
                self.assertIsNone(result["total"])
                self.assertEqual(result["rows"][0]["text"], "Attendance evidence")
        finally:
            del collection, client
            from chromadb.api.client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
            gc.collect()


if __name__ == "__main__":
    unittest.main()

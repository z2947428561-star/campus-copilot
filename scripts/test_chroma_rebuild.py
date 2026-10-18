"""Real temporary Chroma: failed builds keep the published version usable."""
from contextlib import ExitStack, closing
import gc
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["CAMPUS_SKIP_DOTENV"] = "1"
os.environ["ANONYMIZED_TELEMETRY"] = "False"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from langchain_core.documents import Document
import kb


class Vectors:
    def embed_documents(self, texts):
        if "FAIL" in texts:
            raise RuntimeError("synthetic embedding failure")
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [1., 0., 0.] if "old" in text else [0., 1., 0.]


def docs(*texts):
    return [Document(page_content=text, metadata={"title": text, "source_type": "manual_summary"}) for text in texts]


class ChromaPublicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        for key, value in {"KB_BACKEND": "chroma", "CHROMA_DIR": self.tmp.name + "/vectors",
            "KB_REGISTRY_PATH": self.tmp.name + "/releases.db", "MILVUS_COLLECTION": "publication_test",
            "EMBED_DIM": 3}.items():
            self.stack.enter_context(patch.object(kb.config, key, value, create=True))
        self.stack.enter_context(patch.object(kb, "get_embeddings", return_value=Vectors()))
        kb.reset_cache()

    def tearDown(self):
        kb.reset_cache()
        from chromadb.api.client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
        gc.collect()
        self.stack.close()
        self.tmp.cleanup()

    def current_text(self):
        return kb.get_vectorstore().similarity_search_with_score("old", k=1)[0][0].page_content

    def test_failed_build_keeps_published_text(self):
        first = kb.build_index(docs("old handbook"))
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            kb.build_index(docs("new handbook", "FAIL"), batch_size=1)
        self.assertEqual(self.current_text(), "old handbook")
        self.assertEqual(kb.index_status()["active"]["generation"], first["generation"])

    def test_staged_publish_and_rollback_refresh_existing_reader(self):
        first = kb.build_index(docs("old handbook"))
        reader = kb.get_vectorstore()
        candidate = kb.build_index(docs("new handbook"), publish=False)
        self.assertEqual(self.current_text(), "old handbook")
        kb.publish_index(candidate["generation"], expected_revision=1)
        self.assertEqual(self.current_text(), "new handbook")
        self.assertEqual(reader.similarity_search_with_score("old", k=1)[0][0].page_content, "old handbook")
        rolled = kb.rollback_index(expected_revision=2)
        self.assertEqual(rolled["revision"], 3)
        self.assertEqual(rolled["active"]["generation"], first["generation"])
        self.assertEqual(self.current_text(), "old handbook")

    def test_concurrent_candidates_cannot_overwrite_newer_publication(self):
        kb.build_index(docs("old handbook"))
        a = kb.build_index(docs("new A"), publish=False)
        b = kb.build_index(docs("new B"), publish=False)
        kb.publish_index(a["generation"], expected_revision=1)
        with self.assertRaises(kb.releases.PublicationConflict):
            kb.publish_index(b["generation"], expected_revision=1)
        self.assertEqual(self.current_text(), "new A")

    def test_missing_index_read_and_status_do_not_create_storage(self):
        self.assertEqual(kb.index_status()["revision"], 0)
        self.assertIsNone(kb.get_vectorstore())
        self.assertFalse(Path(kb.config.CHROMA_DIR).exists())
        self.assertFalse(Path(kb.config.KB_REGISTRY_PATH).exists())
        with self.assertRaises(ValueError):
            kb.get_vectorstore(fresh=True)

    def test_changed_embedding_refuses_cached_index(self):
        kb.build_index(docs("old handbook"))
        self.assertIsNotNone(kb.get_vectorstore())
        with patch.object(kb.config, "EMBED_MODEL", "a different model"):
            self.assertIsNone(kb.get_vectorstore())
        self.assertEqual(self.current_text(), "old handbook")

    def test_invalid_vector_and_tampered_candidate_never_publish(self):
        kb.build_index(docs("old handbook"))
        with patch.object(Vectors, "embed_documents", return_value=[[float("nan"), 0., 1.]]):
            with self.assertRaises(ValueError):
                kb.build_index(docs("new invalid"))
        candidate = kb.build_index(docs("new candidate"), publish=False)
        kb.backend.chroma().get_collection(candidate["collection"]).delete(ids=["0"])
        with self.assertRaises(ValueError):
            kb.publish_index(candidate["generation"], expected_revision=1)
        self.assertEqual(self.current_text(), "old handbook")

    def test_write_or_validation_failure_does_not_switch(self):
        kb.build_index(docs("old handbook"))
        for seam in ("add", "check_collection", "finish"):
            with patch.object(kb.backend, seam, side_effect=RuntimeError("synthetic storage failure")):
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    kb.build_index(docs("new handbook"))
            self.assertEqual(self.current_text(), "old handbook")
        states = [r["state"] for r in kb.index_status()["releases"]]
        self.assertEqual(states.count("failed"), 3)

    def test_legacy_collection_survives_first_publish_and_rollback(self):
        from langchain_chroma import Chroma
        legacy = Chroma(collection_name=kb.config.MILVUS_COLLECTION,
            persist_directory=kb.config.CHROMA_DIR, embedding_function=Vectors(),
            collection_metadata={"hnsw:space": "cosine"})
        legacy.add_documents(docs("old legacy handbook"))
        self.assertEqual(self.current_text(), "old legacy handbook")
        kb.build_index(docs("new handbook"))
        kb.rollback_index(expected_revision=1)
        self.assertEqual(self.current_text(), "old legacy handbook")

    def test_milvus_writer_preserves_dynamic_metadata_and_never_drops(self):
        from unittest.mock import MagicMock
        import pymilvus
        client = MagicMock()
        client.list_databases.return_value = [kb.config.MILVUS_DB_NAME]
        constructor = MagicMock(return_value=client)
        with patch.object(kb.config, "KB_BACKEND", "milvus"), patch.object(pymilvus, "MilvusClient", constructor):
            kb.backend.create_collection("candidate_only")
            kb.backend.add("candidate_only", docs("new handbook"), [[0., 1., 0.]], 0)
        self.assertTrue(constructor.create_schema.call_args.kwargs["enable_dynamic_field"])
        row = client.insert.call_args.kwargs["data"][0]
        self.assertEqual(row["source_type"], "manual_summary")
        self.assertEqual(client.create_collection.call_args.kwargs["collection_name"], "candidate_only")
        client.drop_collection.assert_not_called()
        self.assertEqual(client.close.call_count, 2)

    def test_database_browser_follows_published_and_rolled_back_collection(self):
        import database_browser
        kb.build_index(docs("old handbook"))
        second = kb.build_index(docs("new handbook"))
        rows, total, more, info = database_browser.index_page("", 0, 25)
        self.assertEqual([r["text"] for r in rows], ["new handbook"])
        self.assertEqual(info["generation"], second["generation"])
        self.assertEqual(info["revision"], 2)
        self.assertEqual(total, 1)
        self.assertFalse(more)
        kb.rollback_index(expected_revision=2)
        rows, _, _, info = database_browser.index_page("", 0, 25)
        self.assertEqual([r["text"] for r in rows], ["old handbook"])
        self.assertEqual(info["revision"], 3)

    def test_two_simultaneous_publishers_have_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        kb.build_index(docs("old handbook"))
        candidates = [kb.build_index(docs(text), publish=False) for text in ("new A", "new B")]

        def publish(candidate):
            try:
                kb.publish_index(candidate["generation"], expected_revision=1)
                return "published"
            except kb.releases.PublicationConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(publish, candidates)), ["published", "conflict"])
        self.assertEqual(kb.index_status()["revision"], 2)

    def test_self_query_and_pointer_write_failure_preserve_active(self):
        import sqlite3
        kb.build_index(docs("old handbook"))
        with patch.object(kb.backend.Reader, "similarity_search_with_score", return_value=[(docs("new bad")[0], float("nan"))]):
            with self.assertRaises(ValueError):
                kb.build_index(docs("new bad"))
        candidate = kb.build_index(docs("new candidate"), publish=False)
        with closing(sqlite3.connect(kb.config.KB_REGISTRY_PATH)) as conn, conn:
            conn.execute("CREATE TRIGGER reject_switch BEFORE UPDATE ON kb_heads BEGIN SELECT RAISE(ABORT, 'synthetic switch failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            kb.publish_index(candidate["generation"], expected_revision=1)
        self.assertEqual(kb.index_status()["revision"], 1)
        self.assertEqual(self.current_text(), "old handbook")

    def test_milvus_reader_uses_existing_collection_without_creation(self):
        from unittest.mock import MagicMock
        import pymilvus
        client = MagicMock()
        client.describe_collection.return_value = {"fields": [{"name": "vector", "params": {"dim": 3}}]}
        client.list_indexes.return_value = ["vector_index"]
        client.describe_index.return_value = {"metric_type": "COSINE"}
        client.search.return_value = [[{"entity": {"text": "old Milvus", "$meta": {"source_type": "manual_summary"}}, "distance": .9}]]
        with patch.object(kb.config, "KB_BACKEND", "milvus"), patch.object(pymilvus, "MilvusClient", return_value=client):
            hits = kb.get_vectorstore().similarity_search_with_score("old", k=1, expr='doc_type == "exam"')
        self.assertEqual(hits[0][0].page_content, "old Milvus")
        self.assertEqual(hits[0][0].metadata["source_type"], "manual_summary")
        self.assertEqual(hits[0][1], .9)
        self.assertEqual(client.search.call_args.kwargs["filter"], 'doc_type == "exam"')
        client.create_database.assert_not_called()
        client.create_collection.assert_not_called()
        client.drop_collection.assert_not_called()

    def test_cli_stage_publish_status_and_rollback(self):
        import build_kb
        from contextlib import redirect_stdout, redirect_stderr
        import io
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(output), \
             patch.object(build_kb, "load_markdown_docs", return_value=(["new handbook"], [{}])):
            self.assertEqual(build_kb.main(["--status"]), 0)
            self.assertFalse(Path(kb.config.KB_REGISTRY_PATH).exists())
            kb.build_index(docs("old handbook"))
            self.assertEqual(build_kb.main(["--stage-only"]), 0)
            candidate = kb.index_status()["releases"][0]
            self.assertEqual(self.current_text(), "old handbook")
            self.assertEqual(build_kb.main(["--publish", candidate["generation"], "--expected-revision", "1"]), 0)
            self.assertEqual(self.current_text(), "new handbook")
            self.assertEqual(build_kb.main(["--rollback", "--expected-revision", "1"]), 1)
            self.assertEqual(build_kb.main(["--rollback", "--expected-revision", "2"]), 0)
            self.assertEqual(self.current_text(), "old handbook")
            with self.assertRaises(SystemExit) as exc:
                build_kb.main(["--rollback"])
            self.assertEqual(exc.exception.code, 2)

    def test_milvus_publication_with_nested_dynamic_fields(self):
        from unittest.mock import MagicMock
        import pymilvus
        client = MagicMock()
        client.list_databases.return_value = [kb.config.MILVUS_DB_NAME]
        client.describe_collection.return_value = {"fields": [{"name": "vector", "params": {"dim": 3}}]}
        client.list_indexes.return_value = ["vector_index"]
        client.describe_index.return_value = {"metric_type": "COSINE"}
        client.query.return_value = [{"count(*)": 1}]
        client.search.return_value = [[{"entity": {"text": "new handbook", "$meta": {
            "title": "new handbook", "source_type": "manual_summary"}}, "distance": 1.}]]
        constructor = MagicMock(return_value=client)
        with patch.object(kb.config, "KB_BACKEND", "milvus"), patch.object(pymilvus, "MilvusClient", constructor):
            release = kb.build_index(docs("new handbook"))
            self.assertEqual(kb.index_status()["active"]["generation"], release["generation"])
            self.assertEqual(kb.index_status()["revision"], 1)
        client.drop_collection.assert_not_called()


if __name__ == "__main__":
    unittest.main()

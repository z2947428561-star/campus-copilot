"""Real temporary Chroma: failed builds keep the published version usable."""
from contextlib import ExitStack
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


if __name__ == "__main__":
    unittest.main()

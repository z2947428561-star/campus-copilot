"""离线验证 Chroma 重建不会累积重复知识库片段。"""
import sys
import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import kb


class FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class ChromaRebuildTest(unittest.TestCase):
    def test_fresh_removes_previous_chunks(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(kb.config, "KB_BACKEND", "chroma"), \
             patch.object(kb.config, "CHROMA_DIR", tmp), \
             patch.object(kb.config, "MILVUS_COLLECTION", "preflight_test"), \
             patch.object(kb, "get_embeddings", return_value=FakeEmbeddings()):
            kb.reset_cache()
            first = kb.get_vectorstore(fresh=True)
            first.add_documents([Document(page_content="one"), Document(page_content="two")])
            self.assertEqual(first._collection.count(), 2)
            second = kb.get_vectorstore(fresh=True)
            self.assertEqual(second._collection.count(), 0)
            second.add_documents([Document(page_content="new")])
            self.assertEqual(second._collection.count(), 1)
            kb.reset_cache()
            del first, second
            from chromadb.api.client import SharedSystemClient
            SharedSystemClient.clear_system_cache()
            gc.collect()


if __name__ == "__main__":
    unittest.main()

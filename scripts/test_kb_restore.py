"""Restore real Chroma and its publication registry after all writers have exited."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


def worker(root, action):
    from unittest.mock import patch

    os.environ["CAMPUS_SKIP_DOTENV"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ["LANGSMITH_TRACING"] = "false"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import kb
    from test_chroma_rebuild import Vectors, docs

    with (
        patch.object(kb.releases, "ROOT", Path(root)),
        patch.multiple(kb.config, KB_BACKEND="chroma", CHROMA_DIR="data/vectors",
                       KB_REGISTRY_PATH="data/releases.db", MILVUS_COLLECTION="restore_test", EMBED_DIM=3),
        patch.object(kb, "get_embeddings", return_value=Vectors()),
    ):
        if action == "build":
            kb.build_index(docs("old restored handbook"))
        state = kb.index_status()
        reader = kb.get_vectorstore()
        text = reader.similarity_search_with_score("old", k=1)[0][0].page_content if reader else None
        return {"status": state, "text": text}


class RestoreTest(unittest.TestCase):
    def run_worker(self, root, action):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(root), action],
            capture_output=True, text=True, encoding="utf-8", check=True,
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=60,
        )
        return json.loads(result.stdout.splitlines()[-1])

    def test_project_restore_keeps_published_generation(self):
        with tempfile.TemporaryDirectory(prefix="campus-kb-restore-") as tmp:
            source = Path(tmp) / "original-project"
            restored = Path(tmp) / "restored-project"
            before = self.run_worker(source, "build")
            # The writer process has exited: SQLite and Chroma files are closed.
            shutil.copytree(source, restored)
            after = self.run_worker(restored, "inspect")
            self.assertEqual(after["status"]["active"]["generation"],
                             before["status"]["active"]["generation"],
                             "换目录后丢失已发布版本，错误回退为 legacy")
            self.assertEqual(after["status"], before["status"])
            self.assertEqual(after["text"], "old restored handbook")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        print(json.dumps(worker(sys.argv[2], sys.argv[3]), ensure_ascii=False))
    else:
        unittest.main()

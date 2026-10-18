"""Restore real Chroma and its publication registry after all writers have exited."""
from contextlib import closing, nullcontext, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


def worker(root, action, options):
    from unittest.mock import patch

    os.environ["CAMPUS_SKIP_DOTENV"] = "1"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    os.environ["LANGSMITH_TRACING"] = "false"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    import kb
    import build_kb
    from test_chroma_rebuild import Vectors, docs

    class RestoreVectors(Vectors):
        def embed_query(self, text):
            if text.startswith("new staged handbook "):
                return [1., int(text[-3:]) / 10., 0.]
            return super().embed_query(text)

    real_relpath = os.path.relpath

    def different_drive(path, start=os.curdir):
        if Path(path) == Path(root) / "data/vectors":
            raise ValueError("synthetic different-drive paths")
        return real_relpath(path, start)

    with (
        patch.object(kb.releases, "ROOT", Path(root)),
        patch.multiple(kb.config, KB_BACKEND="chroma", CHROMA_DIR="data/vectors",
                       KB_REGISTRY_PATH="data/releases.db", MILVUS_COLLECTION="restore_test", EMBED_DIM=3),
        patch.object(kb.releases.os.path, "relpath", side_effect=different_drive)
        if options.get("absolute_location") else nullcontext(),
        patch.object(kb, "get_embeddings", return_value=RestoreVectors()),
    ):
        registry = kb.releases.absolute_path(kb.config.KB_REGISTRY_PATH)

        def text():
            reader = kb.get_vectorstore()
            return reader.similarity_search_with_score("old", k=1)[0][0].page_content if reader else None

        def cli(args):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    return build_kb.main(args)
                except SystemExit as exc:
                    return exc.code

        def rebind_args():
            return ["--rebind-from", options["old_directory"], "--expected-revision", "2"]

        extra = {}
        if action in {"build", "build_history", "build_legacy", "build_absolute"}:
            kb.build_index(docs("old restored handbook"))
            if action != "build":
                kb.build_index(docs("new restored handbook"))
                kb.build_index(docs(*(f"new staged handbook {i:03}" for i in range(205))), publish=False)
                try:
                    kb.build_index(docs("new incomplete", "FAIL"), publish=False, batch_size=1)
                except RuntimeError:
                    pass
            if action in {"build_legacy", "build_absolute"}:
                # Recreate the exact pre-fix on-disk format, independently of scope().
                location = str((Path(root) / "data/vectors").resolve())
                if action == "build_absolute":
                    location = ("absolute-v1", os.path.normcase(location))
                legacy = hashlib.sha256(json.dumps(("chroma", location,
                    "restore_test"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                with closing(sqlite3.connect(registry)) as conn, conn:
                    conn.execute("UPDATE kb_heads SET scope=?", (legacy,))
                    conn.execute("UPDATE kb_releases SET scope=?", (legacy,))
        elif action == "upgrade_legacy":
            original = registry.read_bytes()
            extra["before"] = kb.index_status()
            extra["readonly_unchanged"] = registry.read_bytes() == original
            kb.build_index(docs("new after upgrade"), publish=False)
        elif action == "workflow":
            if options.get("old_directory"):
                extra["rebind_exit"] = cli(rebind_args())
                if extra["rebind_exit"]:
                    return extra
            import database_browser
            extra["before"] = kb.index_status()
            rows, _, _, info = database_browser.index_page("", 0, 25)
            extra["browser_before"] = {"text": rows[0]["text"], **info}
            candidate = next(r for r in extra["before"]["releases"] if r["chunk_count"] == 205)
            extra["rollback"] = kb.rollback_index(expected_revision=2)
            extra["rollback_text"] = text()
            try:
                kb.publish_index(candidate["generation"], expected_revision=2)
                extra["stale_refused"] = False
            except kb.releases.PublicationConflict:
                extra["stale_refused"] = True
            kb.publish_index(candidate["generation"], expected_revision=3)
            rows, total, _, info = database_browser.index_page("", 0, 25)
            extra["browser_after"] = {"total": total, **info}
        elif action == "reject_rebind":
            source = options["old_directory"]
            mode = options["mode"]
            if mode == "missing":
                old = next(r for r in _old_records(registry, source) if r["chunk_count"] == 1)
                kb.backend.chroma().delete_collection(old["collection"])
            elif mode in {"content", "metadata"}:
                candidate = next(r for r in _old_records(registry, source) if r["chunk_count"] == 205)
                collection = kb.backend.chroma().get_collection(candidate["collection"], embedding_function=None)
                if mode == "content":
                    collection.update(ids=["104"], documents=["changed content"], embeddings=[[0., 1., 0.]])
                else:
                    collection.update(ids=["104"], metadatas=[{"title": "changed metadata"}])
            elif mode == "target":
                kb.build_index(docs("new existing target"))
            elif mode == "transaction":
                with closing(sqlite3.connect(registry)) as conn, conn:
                    conn.execute("""CREATE TRIGGER reject_rebind BEFORE UPDATE OF scope ON kb_releases
                                    BEGIN SELECT RAISE(ABORT, 'synthetic rebind failure'); END""")
            elif mode == "missing_vectors":
                kb.config.CHROMA_DIR = "data/missing-vectors"
            elif mode == "model":
                kb.config.EMBED_MODEL = "synthetic different model"
            original = registry.read_bytes()
            extra["before"] = kb.index_status()
            args = rebind_args()
            if mode == "stale":
                args[-1] = "1"
            if mode == "wrong_source":
                args[1] += "-not-the-backup"
            extra["rebind_exit"] = cli(args)
            extra["registry_unchanged"] = registry.read_bytes() == original
            extra["vectors_exist"] = kb.releases.absolute_path(kb.config.CHROMA_DIR).exists()
        elif action == "isolation":
            extra["before"] = kb.index_status()
            extra["text_before"] = text()
            missing_project = Path(root) / "registry-only-copy"
            (missing_project / "data").mkdir(parents=True)
            shutil.copy2(registry, missing_project / "data/releases.db")
            with patch.object(kb.releases, "ROOT", missing_project):
                extra["registry_only_reader_missing"] = kb.get_vectorstore() is None
                extra["registry_only_created_vectors"] = kb.releases.absolute_path(kb.config.CHROMA_DIR).exists()
            with patch.object(kb.config, "CHROMA_DIR", "data/different-vectors"):
                extra["other_store"] = kb.index_status()
                extra["other_reader"] = text()
                extra["created_other_store"] = kb.releases.absolute_path(kb.config.CHROMA_DIR).exists()
            with patch.object(kb.config, "MILVUS_COLLECTION", "other_collection"):
                extra["other_collection"] = kb.index_status()
            with patch.object(kb.config, "KB_BACKEND", "milvus"):
                expected = hashlib.sha256(json.dumps(("milvus", (kb.releases._endpoint(kb.config.MILVUS_URI),
                    kb.config.MILVUS_DB_NAME), kb.config.MILVUS_COLLECTION), sort_keys=True,
                    ensure_ascii=False).encode()).hexdigest()
                extra["milvus_scope_unchanged"] = kb.releases.scope() == expected
        elif action == "invalid_input":
            extra["missing_registry_exit"] = cli(rebind_args())
            extra["missing_revision_exit"] = cli(["--rebind-from", options["old_directory"]])
            extra["relative_path_exit"] = cli(["--rebind-from", "relative/path", "--expected-revision", "0"])
            extra["empty_path_exit"] = cli(["--rebind-from", "", "--expected-revision", "0"])
            with patch.object(kb.config, "KB_BACKEND", "milvus"):
                extra["milvus_exit"] = cli(rebind_args())
            extra["created_registry"] = registry.exists()
            extra["created_vectors"] = kb.releases.absolute_path(kb.config.CHROMA_DIR).exists()
        elif action == "race_rebind":
            from concurrent.futures import ThreadPoolExecutor

            def restore(_):
                try:
                    kb.rebind_chroma(options["old_directory"], expected_revision=2)
                    return "restored"
                except ValueError:
                    return "rejected"

            with ThreadPoolExecutor(max_workers=2) as pool:
                extra["outcomes"] = list(pool.map(restore, range(2)))
        state = kb.index_status()
        return {"status": state, "text": text(), **extra}


def _old_records(registry, old_directory):
    legacy = hashlib.sha256(json.dumps(("chroma", str(Path(old_directory).resolve()), "restore_test"),
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with closing(sqlite3.connect(registry)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM kb_releases WHERE scope=?", (legacy,))]


class RestoreTest(unittest.TestCase):
    def run_worker(self, root, action, **options):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", str(root), action, json.dumps(options)],
            capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
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

    def test_restored_history_supports_browser_rollback_and_staged_publication(self):
        for source_format in ("history", "legacy", "absolute"):
            with self.subTest(format=source_format), tempfile.TemporaryDirectory(prefix="campus-kb-workflow-") as tmp:
                source, restored = Path(tmp) / "source", Path(tmp) / "restored"
                source_options = {"absolute_location": True} if source_format == "absolute" else {}
                before = self.run_worker(source, "build_" + source_format, **source_options)
                shutil.copytree(source, restored)
                options = {"old_directory": str(source / "data/vectors")} if source_format != "history" else {}
                after = self.run_worker(restored, "workflow", **options)
                if source_format != "history":
                    self.assertEqual(after["rebind_exit"], 0)
                self.assertEqual(after["before"]["revision"], 2)
                self.assertEqual(after["before"]["active"]["generation"], before["status"]["active"]["generation"])
                self.assertEqual(len(after["before"]["releases"]), 4)
                self.assertEqual(after["browser_before"]["text"], "new restored handbook")
                self.assertEqual(after["browser_before"]["revision"], 2)
                self.assertEqual(after["rollback"]["revision"], 3)
                self.assertEqual(after["rollback_text"], "old restored handbook")
                self.assertTrue(after["stale_refused"])
                self.assertEqual(after["status"]["revision"], 4)
                self.assertEqual(after["status"]["active"]["chunk_count"], 205)
                self.assertEqual(after["browser_after"]["total"], 205)
                self.assertEqual(after["browser_after"]["generation"], after["status"]["active"]["generation"])
                self.assertTrue(after["text"].startswith("new staged handbook"))
                unchanged = self.run_worker(source, "inspect", **source_options)
                self.assertEqual(unchanged["status"], before["status"])

    def test_legacy_reads_are_unchanged_and_next_write_makes_records_portable(self):
        with tempfile.TemporaryDirectory(prefix="campus-kb-upgrade-") as tmp:
            source, restored = Path(tmp) / "source", Path(tmp) / "restored"
            before = self.run_worker(source, "build_legacy")
            upgraded = self.run_worker(source, "upgrade_legacy")
            self.assertTrue(upgraded["readonly_unchanged"])
            self.assertEqual(upgraded["before"], before["status"])
            self.assertEqual(upgraded["status"]["revision"], 2)
            self.assertEqual(upgraded["status"]["active"]["generation"], before["status"]["active"]["generation"])
            self.assertNotEqual(upgraded["status"]["active"]["scope"], before["status"]["active"]["scope"])
            shutil.copytree(source, restored)
            after = self.run_worker(restored, "inspect")
            self.assertEqual(after["status"], upgraded["status"])
            self.assertEqual(after["text"], "new restored handbook")

    def test_unsafe_rebinding_keeps_the_registry_unchanged(self):
        with tempfile.TemporaryDirectory(prefix="campus-kb-reject-") as tmp:
            source = Path(tmp) / "source"
            self.run_worker(source, "build_legacy")
            for mode in ("missing", "content", "metadata", "stale", "target", "transaction",
                         "missing_vectors", "model", "wrong_source"):
                with self.subTest(mode=mode):
                    restored = Path(tmp) / mode
                    shutil.copytree(source, restored)
                    after = self.run_worker(restored, "reject_rebind", mode=mode,
                                            old_directory=str(source / "data/vectors"))
                    self.assertEqual(after["rebind_exit"], 1)
                    self.assertTrue(after["registry_unchanged"])
                    self.assertEqual(after["status"], after["before"])
                    if mode == "missing_vectors":
                        self.assertFalse(after["vectors_exist"])

    def test_different_stores_and_collection_names_stay_isolated(self):
        with tempfile.TemporaryDirectory(prefix="campus-kb-isolation-") as tmp:
            root = Path(tmp) / "project"
            self.run_worker(root, "build")
            result = self.run_worker(root, "isolation")
            for key in ("other_store", "other_collection"):
                self.assertEqual(result[key]["revision"], 0)
                self.assertEqual(result[key]["releases"], [])
            self.assertIsNone(result["other_reader"])
            self.assertFalse(result["created_other_store"])
            self.assertTrue(result["registry_only_reader_missing"])
            self.assertFalse(result["registry_only_created_vectors"])
            self.assertTrue(result["milvus_scope_unchanged"])
            self.assertEqual(result["status"], result["before"])

    def test_rebinding_requires_chroma_absolute_path_registry_and_revision(self):
        with tempfile.TemporaryDirectory(prefix="campus-kb-input-") as tmp:
            result = self.run_worker(Path(tmp) / "missing", "invalid_input",
                                     old_directory=str(Path(tmp) / "old/vectors"))
            self.assertEqual(result["missing_registry_exit"], 1)
            self.assertEqual(result["missing_revision_exit"], 2)
            self.assertEqual(result["relative_path_exit"], 1)
            self.assertEqual(result["empty_path_exit"], 1)
            self.assertEqual(result["milvus_exit"], 1)
            self.assertFalse(result["created_registry"])
            self.assertFalse(result["created_vectors"])

    def test_simultaneous_rebinding_has_one_winner(self):
        with tempfile.TemporaryDirectory(prefix="campus-kb-race-") as tmp:
            source, restored = Path(tmp) / "source", Path(tmp) / "restored"
            before = self.run_worker(source, "build_legacy")
            shutil.copytree(source, restored)
            after = self.run_worker(restored, "race_rebind", old_directory=str(source / "data/vectors"))
            self.assertCountEqual(after["outcomes"], ["restored", "rejected"])
            self.assertEqual(after["status"]["revision"], 2)
            self.assertEqual(after["status"]["active"]["generation"], before["status"]["active"]["generation"])
            self.assertEqual(len(after["status"]["releases"]), 4)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        print(json.dumps(worker(sys.argv[2], sys.argv[3], json.loads(sys.argv[4])), ensure_ascii=False))
    else:
        unittest.main()

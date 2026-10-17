"""公开政策语料、检索证据与回答引用的离线契约测试。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["CAMPUS_SKIP_DOTENV"] = "1"
os.environ["LANGSMITH_TRACING"] = "false"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.documents import Document
import archive_docs
import build_kb
from tools import policy


def sample_doc(**metadata):
    return Document(page_content="Minimum attendance is 80%.", metadata={
        "title": "考勤要求", "source": "https://www.xmu.edu.my/handbook.pdf",
        "filename": "attendance.md", "doc_type": "attendance",
        "source_type": "manual_summary", "collected_at": "unknown",
        "effective_date": "unknown", "h1": "Attendance", **metadata,
    })


class ProvenanceTests(unittest.TestCase):
    def test_archived_snapshots_keep_honest_metadata(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(archive_docs, "DOCS_DIR", Path(tmp)), \
             patch.object(build_kb, "DOCS_DIR", Path(tmp)):
            archive_docs.main()
            bodies, metas = build_kb.load_markdown_docs()
        self.assertEqual(len(bodies), 16)
        for meta in metas:
            self.assertEqual(meta["source_type"], "manual_summary")
            self.assertEqual(meta["collected_at"], "unknown")
            self.assertEqual(meta["effective_date"], "unknown")

    def test_chunks_preserve_provenance_and_section_scope(self):
        chunks = build_kb.split_documents(
            ["# Attendance\n\n## Threshold\n\nMinimum attendance is 80%."],
            [sample_doc().metadata],
        )
        self.assertTrue(chunks)
        meta = chunks[0].metadata
        self.assertEqual(meta["source_type"], "manual_summary")
        self.assertEqual(meta["offset_scope"], "section")
        self.assertEqual(meta["h2"], "Threshold")

    def test_tool_carries_stable_citation_and_provenance(self):
        with patch.object(policy, "_search", return_value=[(sample_doc(), .9)]):
            first = json.loads(policy.search_policy.invoke({"query": "考勤"}))
            again = json.loads(policy.search_policy.invoke({"query": "出勤率"}))
        evidence = first["evidence"][0]
        self.assertEqual(evidence["source_type"], "manual_summary")
        self.assertEqual(evidence["collected_at"], "unknown")
        self.assertEqual(evidence["section"], "Attendance")
        self.assertEqual(evidence["id"], again["evidence"][0]["id"])
        self.assertRegex(evidence["id"], r"^P-[0-9a-f]{16}$")

    def test_legacy_index_never_claims_official_excerpt(self):
        with patch.object(policy, "_search", return_value=[(sample_doc(source_type=""), .99)]):
            output = policy.search_policy.invoke({"query": "考勤"})
        self.assertNotIn("以上为官方手册原文", output)
        self.assertIn("unknown", output)


if __name__ == "__main__":
    unittest.main()

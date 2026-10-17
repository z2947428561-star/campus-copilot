"""公开政策语料、检索证据与回答引用的离线契约测试。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

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


class EvidenceGateTests(unittest.TestCase):
    def test_milvus_client_preserves_dynamic_provenance(self):
        import langchain_milvus
        with patch.object(policy.kb, "_ensure_milvus_collection"), \
             patch.object(policy.kb, "get_embeddings"), \
             patch.object(langchain_milvus, "Milvus") as constructor:
            policy.kb._build_milvus()
        self.assertTrue(constructor.call_args.kwargs["enable_dynamic_field"])

    def test_milvus_nested_metadata_after_reconnect(self):
        doc = Document(page_content="Minimum attendance is 80%.", metadata={"$meta": sample_doc().metadata})
        store = Mock()
        store.similarity_search_with_score.return_value = [(doc, .8)]
        with patch.object(policy.kb, "get_vectorstore", return_value=store), \
             patch.object(policy.kb, "is_milvus", return_value=True):
            result = json.loads(policy.search_policy.invoke({"query": "考勤"}))
        self.assertEqual(result["evidence"][0]["source_type"], "manual_summary")

    def test_real_chroma_cosine_distance_is_normalized(self):
        import gc
        from langchain_core.embeddings import Embeddings

        class Vectors(Embeddings):
            def embed_documents(self, texts):
                return [[.6, .8] for _ in texts]

            def embed_query(self, text):
                return [1., 0.]

        kb = policy.kb
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(kb.config, "KB_BACKEND", "chroma"), \
             patch.object(kb.config, "CHROMA_DIR", tmp), \
             patch.object(kb.config, "MILVUS_COLLECTION", "policy_evidence_test"), \
             patch.object(kb, "get_embeddings", return_value=Vectors()):
            kb.reset_cache()
            store = kb.get_vectorstore(fresh=True)
            try:
                store.add_documents([sample_doc()])
                result = json.loads(policy.search_policy.invoke({"query": "考勤"}))
                self.assertEqual(result["status"], "evidence_found")
                self.assertAlmostEqual(result["evidence"][0]["score"], .8, places=5)
            finally:
                kb.reset_cache()
                del store
                from chromadb.api.client import SharedSystemClient
                SharedSystemClient.clear_system_cache()
                gc.collect()

    def invoke_hits(self, hits, **kwargs):
        with patch.object(policy, "_search", return_value=hits):
            return json.loads(policy.search_policy.invoke({"query": "考勤", **kwargs}))

    def test_invalid_candidates_never_become_evidence(self):
        for doc, score in [
            (sample_doc(), .69), (sample_doc(), float("nan")),
            (sample_doc(), float("inf")), (sample_doc(), 1.1),
            (sample_doc(), -.1), (sample_doc(), "invalid"),
            (sample_doc(source_type="student_experience"), .99),
            (sample_doc(source_type=""), .99), (sample_doc(source=""), .99),
            (sample_doc(source="https://www.xmu.edu.my.attacker.test/file"), .99),
            (sample_doc(source="javascript:alert(1)"), .99),
            (sample_doc(source="https://user:pass@www.xmu.edu.my/file"), .99),
            (Document(page_content="  ", metadata=sample_doc().metadata), .99),
        ]:
            with self.subTest(score=score, metadata=doc.metadata):
                result = self.invoke_hits([(doc, score)])
                self.assertEqual(result["status"], "insufficient_evidence")
                self.assertEqual(result["evidence"], [])

    def test_threshold_boundary_and_official_excerpt(self):
        result = self.invoke_hits([(sample_doc(source_type="official_excerpt"), .7)])
        self.assertEqual(result["status"], "evidence_found")
        self.assertEqual(len(result["evidence"]), 1)
        with patch.object(policy.config, "KB_MIN_RELEVANCE", .8):
            self.assertEqual(self.invoke_hits([(sample_doc(), .7)])["status"], "insufficient_evidence")

    def test_unavailable_and_empty_are_distinct_and_do_not_leak_errors(self):
        self.assertEqual(self.invoke_hits(None)["status"], "unavailable")
        self.assertEqual(self.invoke_hits([])["status"], "insufficient_evidence")
        with patch.object(policy, "_search", side_effect=RuntimeError("secret-connection")):
            output = policy.search_policy.invoke({"query": "考勤"})
        self.assertEqual(json.loads(output)["status"], "unavailable")
        self.assertNotIn("secret-connection", output)

    def test_global_fallback_survives_filter_failure_and_none(self):
        for failed in (None, [], RuntimeError("category offline")):
            with self.subTest(failed=failed), patch.object(
                policy, "_search", side_effect=[failed, [(sample_doc(), .9)]]
            ):
                result = json.loads(policy.search_policy.invoke({"query": "考勤", "doc_type": "exam"}))
                self.assertEqual(result["status"], "evidence_found")
                self.assertEqual(result["partial"], failed != [])

    def test_failed_global_search_preserves_valid_filtered_evidence(self):
        with patch.object(policy, "_search", side_effect=[[(sample_doc(), .9)], None]):
            result = json.loads(policy.search_policy.invoke({"query": "考勤", "doc_type": "attendance"}))
        self.assertTrue(result["partial"])
        self.assertEqual(len(result["evidence"]), 1)

    def test_full_content_deduplication_and_sorting(self):
        first, second = sample_doc(), sample_doc()
        first.page_content = "x" * 100 + "80%"
        second.page_content = "x" * 100 + "90%"
        with patch.object(policy, "_search", side_effect=[[(first, .8)], [(first, .9), (second, .95)]]):
            result = json.loads(policy.search_policy.invoke({"query": "考勤", "doc_type": "attendance"}))
        self.assertEqual([e["score"] for e in result["evidence"]], [.95, .9])

    def test_both_backend_scores_use_same_cosine_scale(self):
        for milvus, raw in [(True, .4), (False, .6)]:
            store = Mock()
            store.similarity_search_with_score.return_value = [(sample_doc(), raw)]
            with self.subTest(milvus=milvus), \
                 patch.object(policy.kb, "get_vectorstore", return_value=store), \
                 patch.object(policy.kb, "is_milvus", return_value=milvus):
                result = json.loads(policy.search_policy.invoke({"query": "考勤"}))
            self.assertAlmostEqual(result["evidence"][0]["score"], .7)

    def test_non_cosine_milvus_is_unavailable(self):
        with patch.object(policy.kb, "get_vectorstore", return_value=Mock()), \
             patch.object(policy.kb, "is_milvus", return_value=True), \
             patch.object(policy.config, "MILVUS_METRIC", "L2"):
            result = json.loads(policy.search_policy.invoke({"query": "考勤"}))
        self.assertEqual(result["status"], "unavailable")


class AnswerEvaluationTests(unittest.TestCase):
    def setUp(self):
        from policy_evidence import evidence_record
        self.evidence = evidence_record(sample_doc(), .9)
        self.payload = {"status": "evidence_found", "evidence": [self.evidence]}
        self.citation = f'[{self.evidence["id"]}]({self.evidence["source"]})'
        self.answer = f'人工整理快照《考勤要求》（时效未核实）：“Minimum attendance is 80%.” {self.citation}'

    def evaluate(self, answer, payload=None, **kwargs):
        from eval_policy import evaluate_answer
        return evaluate_answer(answer, self.payload if payload is None else payload, **kwargs)

    def test_valid_citation_and_exact_quote_pass(self):
        self.assertEqual(self.evaluate(self.answer), [])

    def test_fabricated_id_wrong_url_and_missing_citation_fail(self):
        for answer, reason in [
            (self.answer.replace(self.evidence["id"], "P-0000000000000000"), "unknown_citation"),
            (self.answer.replace(self.evidence["source"], "https://www.xmu.edu.my/other"), "wrong_source"),
            ("人工整理快照，时效未核实，出勤率为 80%。", "missing_citation"),
        ]:
            with self.subTest(reason=reason):
                self.assertIn(reason, self.evaluate(answer))

    def test_quote_must_match_the_cited_evidence_in_same_paragraph(self):
        self.assertIn("unsupported_quote", self.evaluate(self.answer.replace("80%", "90%")))
        self.assertIn("unsupported_quote", self.evaluate(self.answer.replace(self.citation, "\n\n" + self.citation)))

    def test_provenance_and_temporal_caveats_are_required(self):
        self.assertIn("missing_provenance", self.evaluate(self.answer.replace("人工整理快照", "官方原文")))
        self.assertIn("missing_freshness_caveat", self.evaluate(self.answer.replace("时效未核实", "当前有效")))

    def test_refusal_requires_no_invented_policy_details(self):
        payload = {"status": "insufficient_evidence", "evidence": []}
        self.assertEqual(self.evaluate("证据不足，无法确认。请咨询教务处。", payload, expect="refuse"), [])
        errors = self.evaluate("证据不足，但学校要求出勤率 90%。", payload, expect="refuse")
        self.assertIn("unsupported_policy_number", errors)
        self.assertIn("missing_refusal", self.evaluate("直接去办公室办即可。", payload, expect="refuse"))

    def test_current_policy_question_requires_refusal_even_with_snapshot(self):
        self.assertIn("missing_refusal", self.evaluate(self.answer, expect="refuse"))

    def test_offline_eval_fixtures_include_positive_and_negative_controls(self):
        from eval_policy import run_offline
        results = run_offline()
        self.assertGreaterEqual(len(results), 8)
        self.assertTrue(all(row["ok"] for row in results), results)
        self.assertTrue(any(row["expected_pass"] for row in results))
        self.assertTrue(any(not row["expected_pass"] for row in results))


if __name__ == "__main__":
    unittest.main()

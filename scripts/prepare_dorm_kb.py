"""Build and evaluate an isolated local Dorm policy index with real embeddings."""
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "data/local/xmumdorm"


def local_kb_environment():
    return {
        "CAMPUS_ENV_OVERRIDE": "0", "KB_BACKEND": "chroma",
        "CHROMA_DIR": str(PROFILE / "chroma"),
        "KB_REGISTRY_PATH": str(PROFILE / "kb_releases.db"),
        "LANGSMITH_TRACING": "false", "ANONYMIZED_TELEMETRY": "False",
    }


def main():
    os.environ.update(local_kb_environment())
    sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
    import kb
    import kb_backends
    from build_kb import load_markdown_docs, split_documents
    from policy_evidence import evidence_record, rejection_reason
    import config

    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "backend": "chroma",
              "published": False, "cases": []}
    PROFILE.mkdir(parents=True, exist_ok=True)
    report_path = PROFILE / "kb-check.json"
    try:
        bodies, metadata = load_markdown_docs()
        chunks = split_documents(bodies, metadata)
        report.update(documents=len(bodies), chunks=len(chunks))
        print(f"Building isolated candidate: {len(bodies)} documents, {len(chunks)} chunks", flush=True)
        candidate = kb.build_index(chunks, publish=False)
        report["generation"] = candidate["generation"]
        reader = kb_backends.Reader(candidate["collection"], kb.get_embeddings())
        cases = [
            ("根据归档手册，重修课程的要求是什么？", "retake_rules.md"),
            ("根据归档手册，出勤不达标为什么会被禁止考试？", "attendance.md"),
            ("根据归档手册，对成绩有疑问时如何申请成绩复查？", "result_review.md"),
        ]
        for question, expected in cases:
            accepted = []
            for doc, distance in reader.similarity_search_with_score(question, k=5):
                score = 1 - distance / 2
                if not rejection_reason(doc, score, config.KB_MIN_RELEVANCE):
                    item = evidence_record(doc, score)
                    accepted.append({key: item.get(key) for key in
                                     ("id", "filename", "title", "source", "source_type", "collected_at", "effective_date", "score")})
            passed = any(item["filename"] == expected for item in accepted)
            report["cases"].append({"question": question, "expected": expected, "passed": passed, "evidence": accepted})
            print(f"Candidate retrieval: {expected} {'PASS' if passed else 'FAIL'}", flush=True)
        if not all(case["passed"] for case in report["cases"]):
            report["error"] = "candidate_retrieval_failed"
            return 1
        kb.publish_index(candidate["generation"], expected_revision=candidate["base_revision"])
        report["published"] = True
        report["revision"] = kb.index_status()["revision"]
        print("Candidate verified and published to the isolated local profile.", flush=True)
        return 0
    except Exception as error:
        # Connection/driver error text can contain credentials; record only the class.
        report["error_type"] = type(error).__name__
        print("Local KB preparation failed: " + type(error).__name__, flush=True)
        return 1
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Report: data/local/xmumdorm/kb-check.json", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())

"""Check concise, question-focused Dorm answers against real model/tool runs."""
import argparse
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sys
import time

from prepare_dorm_kb import PROFILE, ROOT, local_kb_environment


def links_in(answer):
    return re.findall(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", answer)


def readable_text(answer):
    return re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", answer)


def style_checks(answer, *, limit=220, forbidden=()):
    links = links_in(answer)
    return {
        "concise": len(readable_text(answer)) <= limit,
        "no_process_narration": not re.match(r"\s*(我先|我来|正在|稍等|我查|让我|先为你|我会先)", answer),
        "no_source_preamble": not re.match(r"\s*(来自|根据.*(?:资料|手册|指南|快照|知识库)|按.*(?:资料|指南|快照)|依据.*(?:资料|手册|指南|知识库))", answer),
        "no_internal_metadata": not re.search(r"collected_at|effective_date|source_type|manual_summary|official_excerpt|\bunknown\b", answer, re.I),
        "no_report_headings": not re.search(r"(?m)^#{1,6}\s", answer),
        "no_source_details": not links and not re.search(r"https?://|来源|出处|参考资料|P-[a-f0-9]{16}|整理快照", answer),
        "no_appended_dates": not re.search(r"生效日期|时效未核实|适用日期|日期未.*核实", answer),
        "no_unasked_topics": not any(word in answer for word in forbidden),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", action="store_true", help="Check the previous recorded verbose answer without calling the model")
    args = parser.parse_args()
    if args.baseline:
        previous = json.loads((PROFILE / "live-check.json").read_text(encoding="utf-8"))
        checks = style_checks(previous["answer"], forbidden=("60%", "SFS", "另外说明"))
        print(json.dumps({"checks": checks, "readable_characters": len(readable_text(previous["answer"]))}, ensure_ascii=False))
        return 0 if all(checks.values()) else 1

    os.environ.update({**local_kb_environment(), "MEMORY_BACKEND": "sqlite",
        "MEMORY_DB_PATH": str(PROFILE / "live-memory.db"), "CAMPUS_AGENT_SHARED_SECRET": secrets.token_urlsafe(48),
        "LLM_FALLBACK_PROVIDER": "none", "LLM_MAX_RETRIES": "0", "LLM_TIMEOUT": "40",
        "LLM_MAX_TOKENS": "600", "MODEL_CALL_RUN_LIMIT": "4", "TOOL_CALL_RUN_LIMIT": "4"})
    sys.path.insert(0, str(ROOT / "src"))
    logging.disable(logging.CRITICAL)
    from fastapi.testclient import TestClient
    import config
    import server
    from test_dorm_integration import assertion
    from verify_dorm_live import reply_matches_history
    cases = [
        {"name": "greeting", "question": "你好", "limit": 60, "policy": False, "forbidden": ("未接通", "未接入", "时效", "教务处", "来源")},
        {"name": "personal_schedule", "question": "帮我查一下我自己的课表", "limit": 100, "policy": False, "forbidden": ("成绩", "订单", "知识库", "来源")},
        {"name": "attendance", "question": "出勤不够还能参加期末考试吗？", "limit": 220, "policy": True, "file": "attendance.md", "forbidden": ("60%", "SFS", "签证", "重修", "另外说明")},
        {"name": "result_review", "question": "成绩复查怎么申请？", "limit": 320, "policy": True, "file": "result_review.md", "allows_scope_clarification": True, "forbidden": ("考勤", "签证", "重修", "另外说明", "降分", "三周", "最终决定", "不保证")},
        {"name": "attendance_direct", "question": "出勤不足会怎样影响考试资格？只回答考试资格。", "limit": 180, "policy": True, "file": "attendance.md", "forbidden": ("60%", "SFS", "签证", "重修", "另外说明")},
    ]
    report = {"real_model": True, "cases": [], "passed": False}
    path = PROFILE / "answer-style-check.json"
    try:
        with TestClient(server.app) as client:
            for case in cases:
                start = time.monotonic()
                headers = {"X-Campus-Assertion": assertion(config.XMUMDORM_SHARED_SECRET, subject="1")}
                created = client.post("/internal/xmumdorm/conversations", headers=headers)
                created.raise_for_status()
                identifier = created.json()["id"]
                response = client.post("/internal/xmumdorm/chat", headers=headers, json={"message": case["question"], "conversation_id": identifier})
                events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
                answer = "".join(event.get("text", "") for event in events if event.get("type") == "token")
                checks = style_checks(answer, limit=case["limit"], forbidden=case["forbidden"])
                checks["completed"] = any(event.get("type") == "done" for event in events) and not any(event.get("type") in {"error", "limit"} for event in events)
                snapshot = server.agent_for_user("xmumdorm:1").get_state(server.conversation_config("xmumdorm:1", identifier))
                evidence = []
                calls = 0
                for message in (snapshot.values or {}).get("messages", []):
                    if getattr(message, "type", None) == "tool" and getattr(message, "name", None) == "search_policy":
                        calls += 1
                        evidence.extend(json.loads(message.content).get("evidence", []))
                if case["policy"]:
                    checks["relevant_evidence"] = any(item.get("filename") == case["file"] for item in evidence)
                else:
                    checks["no_policy_search_needed"] = calls == 0
                # Fresh assertions for follow-up reads after potentially slow model requests.
                headers = {"X-Campus-Assertion": assertion(config.XMUMDORM_SHARED_SECRET, subject="1")}
                history_response = client.get("/internal/xmumdorm/conversations/" + identifier, headers=headers)
                history_response.raise_for_status()
                checks["history_matches"] = reply_matches_history(answer, history_response.json()["messages"])
                item = {"name": case["name"], "question": case["question"], "answer": answer, "checks": checks,
                        "characters": len(readable_text(answer)), "policy_calls": calls, "conversation_id": identifier,
                        "passed": all(checks.values()), "seconds": round(time.monotonic() - start, 2)}
                report["cases"].append(item)
                print(json.dumps({key: item[key] for key in ("name", "passed", "characters", "checks")}, ensure_ascii=False), flush=True)
                path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["passed"] = all(item["passed"] for item in report["cases"])
    except Exception as error:
        report["error_type"] = type(error).__name__
        print("Failure: " + type(error).__name__, flush=True)
    finally:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

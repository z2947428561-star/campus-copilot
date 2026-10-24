"""Exercise the real Dorm Agent API and policy retrieval without a Dorm database."""
import json
import argparse
import logging
import os
from pathlib import Path
import secrets
import sys
import time

from prepare_dorm_kb import PROFILE, ROOT, local_kb_environment


def reply_matches_history(answer, messages):
    """A streamed turn may contain both pre-tool commentary and a final reply."""
    last_user = max((index for index, message in enumerate(messages) if message.get("role") == "user"), default=-1)
    visible = "".join(message.get("text", "") for message in messages[last_user + 1:]
                      if message.get("role") == "assistant")
    return visible == answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recheck-saved", action="store_true", help="Recheck saved synthetic history without another model call")
    args = parser.parse_args()
    PROFILE.mkdir(parents=True, exist_ok=True)
    if args.recheck_saved:
        import sqlite3
        report_path = PROFILE / "live-check.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        with sqlite3.connect((PROFILE / "live-memory.db").resolve().as_uri() + "?mode=ro", uri=True) as conn:
            rows = conn.execute('SELECT role,text FROM web_chat_messages WHERE user_id=? AND thread_id=? ORDER BY sequence',
                                ('xmumdorm:1', 'web:xmumdorm:1:' + report['conversation_id'])).fetchall()
        report["checks"]["reply_saved"] = reply_matches_history(report["answer"], [{"role": role, "text": text} for role, text in rows])
        report["passed"] = all(report["checks"].values())
        report["history_rechecked_without_model_call"] = True
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "checks": report["checks"], "model_called_again": False}, ensure_ascii=False))
        return 0 if report["passed"] else 1
    if not (PROFILE / "kb_releases.db").is_file():
        print("Run scripts/prepare_dorm_kb.py first.")
        return 1
    os.environ.update({**local_kb_environment(),
        "CAMPUS_AGENT_SHARED_SECRET": secrets.token_urlsafe(48),
        "MEMORY_BACKEND": "sqlite", "MEMORY_DB_PATH": str(PROFILE / "live-memory.db"),
        "LLM_FALLBACK_PROVIDER": "none", "LLM_MAX_RETRIES": "0", "LLM_TIMEOUT": "40",
        "LLM_MAX_TOKENS": "1200", "MODEL_CALL_RUN_LIMIT": "4", "TOOL_CALL_RUN_LIMIT": "4",
    })
    sys.path.insert(0, str(ROOT / "src"))
    logging.disable(logging.CRITICAL)
    started = time.monotonic()
    report = {"real_model": True, "real_embeddings": True, "dorm_database": False,
              "question": "出勤不足会怎样影响考试资格？",
              "checks": {}, "passed": False}
    try:
        from fastapi.testclient import TestClient
        import config
        import server
        from test_dorm_integration import assertion
        headers = {"X-Campus-Assertion": assertion(config.XMUMDORM_SHARED_SECRET, subject="1")}
        prefix = "/internal/xmumdorm"
        with TestClient(server.app) as client:
            created = client.post(prefix + "/conversations", headers=headers)
            created.raise_for_status()
            conversation_id = created.json()["id"]
            report["conversation_id"] = conversation_id
            response = client.post(prefix + "/chat", headers=headers,
                                   json={"message": report["question"], "conversation_id": conversation_id})
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            report["events"] = list(dict.fromkeys(event.get("type") for event in events))
            answer = "".join(event.get("text", "") for event in events if event.get("type") == "token")
            report["answer"] = answer
            user_id = "xmumdorm:1"
            snapshot = server.agent_for_user(user_id).get_state(server.conversation_config(user_id, conversation_id))
            evidence = {}
            searches = 0
            for message in (snapshot.values or {}).get("messages", []):
                if getattr(message, "type", None) == "tool" and getattr(message, "name", None) == "search_policy":
                    searches += 1
                    result = json.loads(message.content)
                    for item in result.get("evidence", []): evidence[item["id"]] = item
            report["policy_search_calls"] = searches
            report["evidence"] = [{key: item.get(key) for key in
                                   ("id", "filename", "title", "source", "source_type", "collected_at", "effective_date")}
                                  for item in evidence.values()]
            from eval_dorm_answers import style_checks
            state_response = client.get(prefix + "/conversations/" + conversation_id, headers=headers)
            state_response.raise_for_status()
            history = state_response.json()
            report["checks"] = {
                "sse_completed": response.status_code == 200 and "done" in report["events"] and not set(report["events"]) & {"error", "limit"},
                "policy_tool_used": searches > 0,
                "attendance_evidence_found": any(item.get("filename") == "attendance.md" for item in evidence.values()),
                **style_checks(answer, forbidden=("重修", "60%", "SFS")),
                "reply_saved": reply_matches_history(answer, history["messages"]),
                "run_finished": not history["running"],
            }
            report["passed"] = all(report["checks"].values())
    except Exception as error:
        report["error_type"] = type(error).__name__
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (PROFILE / "live-check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: report[key] for key in ("passed", "checks", "elapsed_seconds")}, ensure_ascii=False))
        if "error_type" in report: print("Failure: " + report["error_type"])
        print("Report: data/local/xmumdorm/live-check.json")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

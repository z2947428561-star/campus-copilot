"""Policy citation/refusal evaluation. Default: offline rule controls; --model: fixed-evidence LLM.

Neither mode measures production retrieval recall or semantic entailment. Reports keep
the answer and evidence so a human can check scope, exceptions and current validity.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.documents import Document
from policy_evidence import evidence_record

CITATION = re.compile(r"\[(P-[0-9a-f]{16})\]\(([^\s)]+)\)")
REFUSAL = re.compile(r"无法确认|证据不足|无法核实|不能确定|未找到|没有足够|未覆盖")
FRESHNESS = re.compile(r"时效未核实|生效日期未知|无法确认现行|不能确认现行|有效期未知")
NUMBER = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|天|日|周|年|学分|马币|元)|(?:RM|MYR)\s*\d+", re.I)


def evaluate_answer(answer, payload, *, expect="answer", required_any=(), forbidden=()):
    """Return rule failures, not a semantic correctness verdict.

    Quoted passages must match cited text in the same paragraph after whitespace
    normalization. Refusal vocabulary/number checks are deliberately bounded rules.
    """
    errors = set()
    evidence = {e["id"]: e for e in payload.get("evidence", [])}
    usable = payload.get("status") == "evidence_found" and bool(evidence)
    citations = CITATION.findall(answer)
    linked_ids = {cid for cid, _ in citations}
    if not answer.strip():
        errors.add("empty_answer")
    if (expect in {"refuse", "partial"} or not usable) and not REFUSAL.search(answer):
        errors.add("missing_refusal")
    if usable and expect != "refuse" and not citations:
        errors.add("missing_citation")
    if not usable:
        without_urls = re.sub(r"https?://\S+", "", answer)
        if NUMBER.search(without_urls):
            errors.add("unsupported_policy_number")
        if citations:
            errors.add("citation_without_evidence")
    for cid, url in citations:
        if cid not in evidence:
            errors.add("unknown_citation")
        elif url != evidence[cid]["source"]:
            errors.add("wrong_source")
    for cid in re.findall(r"P-[0-9a-f]{16}", answer):
        if cid not in linked_ids:
            errors.add("unlinked_citation")
    cited = [evidence[cid] for cid in linked_ids if cid in evidence]
    if any(e["source_type"] == "manual_summary" for e in cited) and "人工整理" not in answer:
        errors.add("missing_provenance")
    if any(e.get("effective_date", "unknown") == "unknown" for e in cited) and not FRESHNESS.search(answer):
        errors.add("missing_freshness_caveat")
    for paragraph in re.split(r"\n\s*\n", answer):
        local_ids = [cid for cid, _ in CITATION.findall(paragraph) if cid in evidence]
        texts = [" ".join(evidence[cid]["text"].split()) for cid in local_ids]
        quotes = re.findall(r'“([^”]+)”|"([^"\n]+)"', paragraph)
        for pair in quotes:
            quote = " ".join((pair[0] or pair[1]).split())
            if not any(quote in text for text in texts):
                errors.add("unsupported_quote")
    if required_any and not any(term in answer for term in required_any):
        errors.add("missing_expected_content")
    if any(term in answer for term in forbidden):
        errors.add("forbidden_content")
    return sorted(errors)


def load_cases():
    dataset = json.loads((ROOT / "scripts/policy_eval_cases.json").read_text(encoding="utf-8"))
    record = evidence_record(Document(page_content=dataset["snapshot"]["text"],
                                      metadata=dataset["snapshot"]["metadata"]), .9)
    payloads = {
        "snapshot": {"schema_version": 1, "status": "evidence_found", "evidence": [record]},
        "empty": {"schema_version": 1, "status": "insufficient_evidence", "evidence": []},
        "unavailable": {"schema_version": 1, "status": "unavailable", "evidence": []},
    }
    tokens = {"{citation}": f'[{record["id"]}]({record["source"]})',
              "{id}": record["id"], "{url}": record["source"]}
    for case in dataset["cases"]:
        case["evidence_payload"] = payloads[case["payload"]]
        for token, value in tokens.items():
            case["answer"] = case["answer"].replace(token, value)
    return dataset["cases"]


def score_case(case, answer):
    return evaluate_answer(answer, case["evidence_payload"], expect=case.get("expect", "answer"),
                           required_any=case.get("required_any", []), forbidden=case.get("forbidden", []))


def run_offline():
    rows = []
    for case in load_cases():
        errors = score_case(case, case["answer"])
        ok = (not errors) == case["expected_pass"]
        ok = ok and set(case.get("expected_errors", [])).issubset(errors)
        rows.append({**case, "errors": errors, "ok": ok})
    return rows


def run_model():
    # No agent memory or database. Only these public synthetic fixtures go to the model.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["CAMPUS_ENV_OVERRIDE"] = "0"
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
    from model import get_chat_model
    from prompts.system import build_system_prompt

    model = get_chat_model()
    rows = []
    for case in load_cases():
        if not case.get("model_case"):
            continue
        messages = [
            SystemMessage(content=build_system_prompt(with_memory=False, with_rag=True)),
            HumanMessage(content=case["question"]),
            AIMessage(content="", tool_calls=[{"name": "search_policy", "args": {"query": case["question"]},
                                               "id": "policy-eval", "type": "tool_call"}]),
            ToolMessage(content=json.dumps(case["evidence_payload"], ensure_ascii=False),
                        tool_call_id="policy-eval", name="search_policy"),
        ]
        try:
            response = model.invoke(messages)
            answer = response.content if isinstance(response.content, str) else ""
            errors = score_case(case, answer)
            if response.tool_calls:
                errors.append("unexpected_tool_call")
        except Exception as exc:
            answer, errors = "", [f"model_error:{type(exc).__name__}"]
        rows.append({**case, "answer": answer, "errors": errors, "ok": not errors})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", action="store_true", help="调用配置的真实模型，可能产生 API 费用；仍使用固定证据")
    parser.add_argument("--output", type=Path, help="Markdown 报告路径；同目录保存 JSON 明细")
    args = parser.parse_args()
    mode = "fixed-evidence-model" if args.model else "offline-rule-controls"
    rows = run_model() if args.model else run_offline()
    output = args.output or ROOT / "docs" / ("policy-model-eval-results.md" if args.model else "policy-eval-results.md")
    passed = sum(row["ok"] for row in rows)
    metadata = {"mode": mode, "generated_at": datetime.now().astimezone().isoformat(),
                "passed": passed, "total": len(rows)}
    if args.model:
        import config
        metadata.update(model=config.LLM_MODEL, temperature=config.LLM_TEMPERATURE)
    lines = ["# 政策引用与拒答评测", "", f"模式：{mode}。时间：{metadata['generated_at']}。",
             f"规则{'场景' if args.model else '正反例'}通过：{passed}/{len(rows)}。", "",
             "本报告不代表真实检索召回率、政策准确率或语义蕴含判断。",
             "离线模式检查评测器能否接受正确示例并检出错误示例；固定证据模型模式才调用模型。",
             "数字检查、拒答措辞与逐字引文检查均为有限规则；适用范围、例外和现行效力仍需人工核验。", "",
             "| 场景 | 结果 | 检出的规则问题 |", "|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | {'通过' if row['ok'] else '失败'} | {', '.join(row['errors']) or '无'} |")
    lines += ["", f"完整问题、回答、证据和预期见 `{output.with_suffix('.json').name}`。"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    output.with_suffix(".json").write_text(json.dumps({**metadata, "results": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{mode}: {passed}/{len(rows)}; report: {output}")
    return 0 if passed == len(rows) and rows else 1


if __name__ == "__main__":
    raise SystemExit(main())

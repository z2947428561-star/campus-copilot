"""Policy evidence records: provenance and reproducible citation identity."""
import hashlib
import json
import math
from urllib.parse import quote, urlsplit

SOURCE_TYPES = {"manual_summary", "official_excerpt", "student_experience", "unknown"}


def rejection_reason(doc, score, minimum: float) -> str:
    """A candidate gate, not a claim of entailment or current policy validity."""
    if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
        return "invalid_score"
    if score < minimum:
        return "below_threshold"
    if not doc.page_content.strip():
        return "empty_text"
    kind = doc.metadata.get("source_type")
    if kind not in {"manual_summary", "official_excerpt"}:
        return "unknown_or_non_policy_source"
    try:
        url = urlsplit(doc.metadata.get("source", ""))
        host = url.hostname or ""
        official = host == "xmu.edu.my" or host.endswith(".xmu.edu.my") or host == "zs.xmu.edu.cn"
        if url.scheme not in {"http", "https"} or not official or url.username or url.password:
            return "invalid_source_url"
    except (TypeError, ValueError):
        return "invalid_source_url"
    return ""


def evidence_record(doc, score: float) -> dict:
    """Do not infer authenticity or dates from an official-looking URL."""
    meta = doc.metadata
    source_type = meta.get("source_type", "unknown")
    record = {
        "title": meta.get("title") or meta.get("filename") or "未知文档",
        "source": quote(meta.get("source") or "", safe=":/?#[]@!$&'*+,;=%-._~"),
        "source_type": source_type if source_type in SOURCE_TYPES else "unknown",
        "collected_at": meta.get("collected_at") or "unknown",
        "effective_date": meta.get("effective_date") or "unknown",
        "filename": meta.get("filename", ""),
        "section": " / ".join(str(meta[k]) for k in ("h1", "h2", "h3") if meta.get(k)),
        "text": doc.page_content.strip(),
    }
    identity = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    record["id"] = "P-" + hashlib.sha256(identity).hexdigest()[:16]
    record["score"] = score
    # Header splitting normalizes whitespace; this is NOT an original-file offset.
    record["offset_scope"] = meta.get("offset_scope") or "unknown"
    if record["offset_scope"] == "section" and isinstance(meta.get("start_index"), int):
        if meta["start_index"] >= 0:
            record["section_offset"] = meta["start_index"]
    return record


def evidence_response(status: str, evidence=None, *, reason="", partial=False) -> str:
    return json.dumps({
        "schema_version": 1, "status": status, "reason": reason,
        "evidence": evidence or [], "partial": partial,
        "guidance": (
            "片段仅为候选证据，须核对是否覆盖问题、适用范围与时效。"
            "manual_summary 是人工整理，不能称为官方原文；unknown 表示未核实来源。"
            "日期 unknown 表示未记录，不代表当前有效。引用格式：[证据ID](source URL)。"
            "没有可用证据时说明无法确认，不猜数字、费用或流程。"
        ),
        "official_site": "https://www.xmu.edu.my",
        "contact_email": "xmumac@xmu.edu.my",
    }, ensure_ascii=False)

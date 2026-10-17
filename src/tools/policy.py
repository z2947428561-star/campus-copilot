"""教务政策向量检索工具。

RAG 链路:Embedding(云端,课件第10章 §2.4.2 p48-49)→ 向量检索 + 元数据过滤
→ 带来源返回。向量库与 embedding 的初始化统一在 src/kb.py(建库脚本共用同一份)。

课程对应:
    第10章 §2.5.2(p52)    向量库选型:课件用 Milvus
    第10章 §2.5.3(p62)    标量过滤 + 元数据回传(output_fields)
    第10章 §2.5.3(p63-65) 拼上下文 + 片段带来源
    第05章 §3.1(p16-18)   parse_docstring
    第05章 §3.3(p20-27)   args_schema(doc_type 用枚举)
    第05章 §6.4(p43)      工具返回字符串

设计要点:
- 工具首次调用时才加载向量库,失败时返回"未接入"提示而不是让 Agent 崩
- 返回片段附带 [片段N | 相关度 | 来源:《标题》 URL],模型据此引用
- 元数据过滤:doc_type 对应 front matter 的分类(attendance/exam/academic/
  finance/scholarship/visa/general)

关于"过滤召回 + 全库召回按分数合并"(自研逻辑,答辩时要说明):
    起因是评估集暴露的真实问题 —— 问"连续缺勤开除"时模型选 doc_type=attendance,
    而"连续缺勤 15 天开除"的原文在 leave_of_absence.md(academic 类),
    单靠过滤会漏。**课件第10章没有讲标准 Hybrid Retrieval**
    (EnsembleRetriever / BM25 / MMR / rerank 全章零匹配),
    所以这是本项目的自研补强,不要说成"课件教的混合检索"。
"""
import logging

from langchain_core.tools import tool

import config
import kb
from policy_evidence import evidence_record, evidence_response
from tools.schemas import PolicySearchInput

logger = logging.getLogger("campus")


def _search(query: str, doc_type: str):
    """按后端执行检索,返回 [(Document, score)]。

    两种后端的元数据过滤语法不同(实测):
        Chroma: filter={"doc_type": "exam"}   —— 字典
        Milvus: expr='doc_type == "exam"'     —— 字符串表达式
    """
    vs = kb.get_vectorstore()
    if vs is None:
        return None

    kwargs = {}
    if doc_type:
        kwargs = (
            {"expr": kb.metadata_expr(doc_type)}
            if kb.is_milvus()
            else {"filter": {"doc_type": doc_type}}
        )
    return vs.similarity_search_with_relevance_scores(query, k=config.KB_TOP_K, **kwargs)


@tool(
    parse_docstring=True,
    args_schema=PolicySearchInput,
    description=(
        "检索 XMUM 教务政策资料(补考、重修、缓考、考勤、请假、申诉、奖学金、签证等)。"
        "返回带来源类型、日期与证据 ID 的 JSON。人工整理快照不能当作官方原文。"
        "回答须核对片段覆盖范围，并以 [证据ID](来源URL) 引用。"
    ),
)
def search_policy(query: str, doc_type: str = "all") -> str:
    """检索教务政策资料。

    Args:
        query: 自然语言问题或关键词,如「补考和重修的区别」「出勤率要求」。
        doc_type: 可选分类过滤,取值见 schemas.DOC_TYPE_VALUES;不确定时留 all。

    Returns:
        带来源、证据状态与官网指引的 JSON 字符串。
    """
    # args_schema 里用 "all" 表示不过滤(便于模型理解);这里归一化成"不过滤"
    filter_type = "" if doc_type in ("", "all") else doc_type

    try:
        hits = _search(query, filter_type)
    except Exception as e:  # noqa: BLE001
        logger.warning("[政策检索] 出错: %r", e)
        return evidence_response("unavailable", reason="query_failed")

    if hits is None:
        return evidence_response("unavailable", reason="index_unavailable")

    fallback_note = ""
    if filter_type:
        # 过滤召回 + 全库召回,按相关度合并去重(见模块 docstring 说明)
        try:
            all_hits = _search(query, "")
        except Exception:  # noqa: BLE001
            all_hits = []

        def _key(pair):
            doc, _ = pair
            return (doc.metadata.get("filename"), doc.page_content[:80])

        filtered_keys = {_key(p) for p in hits}
        seen, merged = set(), []
        for pair in sorted(list(hits) + list(all_hits), key=lambda x: -x[1]):
            k = _key(pair)
            if k in seen:
                continue
            seen.add(k)
            merged.append(pair)
        # 只在全库召回确实带回了过滤召回没有的片段时才提示(旧版只看 Top1 分数高低)
        if any(k not in filtered_keys for k in seen):
            fallback_note = "(另外合并了全库检索结果)"
        hits = merged[: config.KB_TOP_K]

    if not hits:
        return evidence_response("insufficient_evidence", reason="no_hits")

    return evidence_response("evidence_found", [evidence_record(doc, score) for doc, score in hits])

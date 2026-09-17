"""教务政策向量检索工具(M5 升级版)。

旧版(占位)只按文件名匹配;现在走完整 RAG 链路:
Chroma 向量库(bge-m3 embedding)→ 相似度检索 + 元数据过滤 → 带来源返回。

设计要点:
- 向量库初始化放函数内 + 缓存:工具首次调用时才加载,失败时降级为
  "未接入"提示(知识库没建/Chroma 数据目录被删,不该让 Agent 崩)
- 返回片段附带 [来源: 文档标题 §片段序号 | 官方 URL],模型据此引用,
  这就是 DoD 里"回答附带来源引用"的数据基础
- metadata 过滤用 doc_type(attendance/exam/academic/finance/scholarship/visa),
  对应"元数据过滤"知识点

对应验收场景:"补考和重修有什么区别""奖学金怎么评"
"""
import threading
from pathlib import Path

from langchain_core.tools import tool

DB_DIR = Path("data/chroma_db")

_vectorstore = None
_lock = threading.Lock()


def _get_vectorstore():
    """懒加载向量库(进程内缓存;失败返回 None)。"""
    global _vectorstore
    if _vectorstore is not None:
        return _vectorstore
    with _lock:
        if _vectorstore is not None:
            return _vectorstore
        if not DB_DIR.exists():
            return None
        try:
            from langchain_chroma import Chroma
            from langchain_ollama import OllamaEmbeddings

            _vectorstore = Chroma(
                collection_name="xmum_policies",
                embedding_function=OllamaEmbeddings(
                    model="bge-m3", base_url="http://localhost:11434"
                ),
                persist_directory=str(DB_DIR),
            )
        except Exception:
            return None
    return _vectorstore


@tool
def search_policy(query: str, doc_type: str = "") -> str:
    """检索 XMUM 教务政策官方规定(补考、重修、缓考、考勤、请假、申诉、奖学金、签证等)。

    返回知识库命中的规定原文片段及其官方来源。回答政策问题时:
    - 以片段原文为准,不要自行发挥政策细节
    - 明确告知用户信息来源(文档标题与官方 URL)

    Args:
        query: 自然语言问题或关键词,如 "补考和重修的区别" "出勤率要求"
        doc_type: 可选过滤:attendance(考勤) exam(考试) academic(学籍成绩)
            finance(费用) scholarship(奖学金) visa(签证);留空检索全部
    """
    vs = _get_vectorstore()
    if vs is None:
        return (
            "教务政策知识库未接入(需先运行 scripts/build_kb.py 建库)。"
            "请如实告知用户当前无法查政策原文,建议访问官网 www.xmu.edu.my。"
        )

    k = 5
    fallback_note = ""
    try:
        if doc_type:
            # 混合检索(元数据过滤的可靠性设计):
            # 过滤检索保精准,全库检索保召回,按相关度合并去重取 Top-k。
            # 起因:问"缺勤开除"时模型选 doc_type=attendance,而"连续缺勤15天
            # 开除"的规定在 leave_of_absence(academic 类)——单靠过滤会漏。
            hits_f = vs.similarity_search_with_relevance_scores(
                query, k=k, filter={"doc_type": doc_type}
            )
            hits_a = vs.similarity_search_with_relevance_scores(query, k=k)
            seen, merged = set(), []
            for doc, score in sorted(hits_f + hits_a, key=lambda x: -x[1]):
                key = (doc.metadata.get("filename"), doc.page_content[:80])
                if key in seen:
                    continue
                seen.add(key)
                merged.append((doc, score))
            hits = merged[:k]
            if hits_a and (not hits_f or hits_a[0][1] > hits_f[0][1]):
                fallback_note = "(已自动合并全库检索结果)"
        else:
            hits = vs.similarity_search_with_relevance_scores(query, k=k)
    except Exception as e:
        return f"检索出错:{e!r}。请告知用户稍后再试,或访问 www.xmu.edu.my 查询。"

    if not hits:
        return (
            f"知识库中没有找到与「{query}」相关的规定片段。"
            "请如实告知用户,建议查阅官网 www.xmu.edu.my 或咨询教务处 xmumac@xmu.edu.my。"
        )

    parts = [f"命中 {len(hits)} 个相关规定片段(按相关度排序){fallback_note}:"]
    for i, (doc, score) in enumerate(hits, 1):
        title = doc.metadata.get("title", doc.metadata.get("filename", "未知文档"))
        source = doc.metadata.get("source", "")
        parts.append(
            f"\n[片段{i} | 相关度{score:.2f} | 来源:《{title}》 {source}]\n"
            f"{doc.page_content.strip()}"
        )
    parts.append(
        "\n(以上为官方手册原文摘录;回答时请引用来源,数字与流程以原文为准)"
    )
    return "\n".join(parts)

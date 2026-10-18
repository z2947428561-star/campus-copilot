"""Knowledge-base embedding, immutable builds and version-aware read access."""
import logging
import threading
from pathlib import Path

import config
import kb_backends as backend
import kb_releases as releases

logger = logging.getLogger("campus")

_vectorstore = None
_cache_key = None
_lock = threading.Lock()

# ---------------------------------------------------------------- Embedding
def get_embeddings():
    """创建 Embedding 模型(第10章 §2.4.2 p48-49)。

    课件用云端 OpenAI 兼容网关(CloseAI 的 text-embedding-3-large,
    或硅基流动的 bge-m3 / Pro_BAAI/bge-m3),第10章全程没有用 Ollama。
    因此默认走 cloud;`EMBED_BACKEND=ollama` 是本机开发兜底(无需 API key)。

    为什么默认 bge-m3:课件 p47 模型表里它的理由是"多语言 / 1024 维 / 8192",
    而本项目语料正是"英文原文 + 中文要点"混排,单文档上千字符。

    ✅ 实测结论:本机 Ollama 的 bge-m3 与硅基流动的 BAAI/bge-m3 是**同一个向量空间**
       (同文本余弦 1.0000,前提是云端按下面的方式正确调用)。
       所以两者可以互换,**不需要因为换后端而重建知识库**。

    ⚠️⚠️ 必须关闭 `check_embedding_ctx_length`(本函数最关键的一行):
        langchain_openai 的 OpenAIEmbeddings 默认 `check_embedding_ctx_length=True`,
        此时它会用 **tiktoken 把文本切成 token id 数组**再发给 API
        (源码:`response = self.client.create(input=batch_tokens, ...)`)。
        这对 OpenAI 自家模型是正常的,但 bge-m3 这类**非 OpenAI 模型**
        会把一串整数当成文本去编码 —— 得到语义错乱的向量,**而且不报错**。

        实测证据(本项目真实故障):
          - tiktoken 把「补考和重修有什么区别」切成 12 个 token id
            [13079, 98, 78698, ...]
          - 直连带数组 input 与直连带字符串 input,同文本向量余弦仅 **0.26**
          - 结果:同义句相似度 0.27(< 无关句 0.60),分数全挤在 0.60-0.71,
            "重修要交钱吗"返回奖学金/成绩复查/纪律申诉,检索命中率 **0/10**
          - 关掉该开关后:同义 0.9909、无关 0.2842、
            用库里原文自查询精确命中自己(score 0.9999),命中率回到 **10/10**

        注意区分:这与"账户余额不足"(402 / code 30001)是两个**不同**的问题,
        两者都会让检索质量崩掉,排查时都要看。
    """
    if config.EMBED_BACKEND == "ollama":
        from langchain_ollama import OllamaEmbeddings

        logger.info(
            "[知识库] Embedding 后端 = 本地 Ollama(%s @ %s)",
            config.EMBED_OLLAMA_MODEL,
            config.OLLAMA_BASE_URL,
        )
        return OllamaEmbeddings(
            model=config.EMBED_OLLAMA_MODEL,
            base_url=config.OLLAMA_BASE_URL,
        )

    from langchain_openai import OpenAIEmbeddings

    if not config.EMBED_API_KEY:
        raise RuntimeError(
            "Embedding 后端为 cloud 但缺少 EMBED_API_KEY"
            "(课件第10章 §2.4.2 p48-49 用云端网关)。二选一:\n"
            "  1) 在 .env 填 EMBED_API_KEY(硅基流动 https://cloud.siliconflow.cn 可免费领)\n"
            "  2) 本机开发兜底:设 EMBED_BACKEND=ollama 走本地 Ollama"
        )
    logger.info(
        "[知识库] Embedding 后端 = 云端(%s @ %s)",
        config.EMBED_MODEL,
        config.EMBED_BASE_URL,
    )
    kwargs = {
        "model": config.EMBED_MODEL,
        "api_key": config.EMBED_API_KEY,
        "base_url": config.EMBED_BASE_URL,
        # ⚠️ 关键:见 docstring。不关掉的话发给 API 的是 token id 数组,
        # bge-m3 会编码出语义错乱的向量,且不报错(实测导致 RAG 命中率 0/10)。
        "check_embedding_ctx_length": config.EMBED_CHECK_CTX_LENGTH,
    }
    # ⚠️ dimensions 不是所有网关都接受。实测硅基流动(siliconflow.cn)对
    #    `dimensions=1024` 直接返回 400(code 20015 "The parameter is invalid"),
    #    而 BAAI/bge-m3 本身输出就是 1024 维,根本不需要这个参数。
    #    所以只在显式打开 EMBED_SEND_DIMENSIONS 时才传。
    if config.EMBED_SEND_DIMENSIONS:
        kwargs["dimensions"] = config.EMBED_DIM
    return OpenAIEmbeddings(**kwargs)


def embedding_backend_desc() -> str:
    """给日志/报告用的一句话描述当前 embedding 后端。"""
    if config.EMBED_BACKEND == "ollama":
        return f"ollama:{config.EMBED_OLLAMA_MODEL}"
    return f"cloud:{config.EMBED_MODEL}"


def index_status():
    """Read publication metadata without connecting to vectors or an embedding service."""
    return releases.snapshot()


def build_index(documents, *, publish=True, batch_size=64):
    """Build an isolated candidate; any failure preserves the active collection."""
    documents = list(documents)
    if not documents or any(not d.page_content.strip() for d in documents):
        raise ValueError("A non-empty corpus is required")
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 256:
        raise ValueError("Batch size must be between 1 and 256")
    if config.MILVUS_METRIC.upper() != "COSINE":
        raise ValueError("Policy indexes require COSINE")
    candidate = releases.begin(documents)
    name = candidate["collection"]
    try:
        embeddings = get_embeddings()
        backend.create_collection(name)
        for offset in range(0, len(documents), batch_size):
            batch = documents[offset:offset + batch_size]
            vectors = backend.checked_vectors(embeddings.embed_documents([d.page_content for d in batch]), len(batch))
            backend.add(name, batch, vectors, offset)
        backend.finish(name)
        backend.check_collection(name)
        if backend.count(name) != len(documents):
            raise ValueError("Index chunk count validation failed")
        probe = documents[0]
        hits = backend.Reader(name, embeddings).similarity_search_with_score(probe.page_content, k=5)
        if not any(d.page_content == probe.page_content and all(d.metadata.get(k) == v for k, v in probe.metadata.items())
                   for d, _ in hits):
            raise ValueError("Index text/metadata self-query validation failed")
        releases.mark(candidate["generation"], "ready")
    except Exception:
        releases.mark(candidate["generation"], "failed")
        raise
    if publish:
        publish_index(candidate["generation"], expected_revision=candidate["base_revision"])
    return next(r for r in index_status()["releases"] if r["generation"] == candidate["generation"])


def publish_index(generation, *, expected_revision):
    status = index_status()
    release = next((r for r in status["releases"] if r["generation"] == generation), None)
    if not release or release["state"] != "ready" or release["embedding"] != releases.embedding_contract():
        raise ValueError("Release is not ready or embedding configuration differs")
    backend.check_collection(release["collection"])
    if backend.count(release["collection"]) != release["chunk_count"]:
        raise ValueError("Candidate collection changed or is incomplete")
    return releases.switch(generation, expected_revision)


def rollback_index(*, expected_revision):
    previous = index_status()["previous"]
    if previous is None:
        raise ValueError("There is no previous release")
    if previous["generation"] == "legacy":
        backend.check_collection(previous["collection"])
        return releases.switch("legacy", expected_revision)
    return publish_index(previous["generation"], expected_revision=expected_revision)


def get_vectorstore(fresh=False):
    """Attach read-only to the current version. Missing/invalid index returns None.

    Each call rechecks the small local pointer; an already-running query keeps its
    collection. Destructive ``fresh=True`` is rejected before any storage access.
    """
    global _vectorstore, _cache_key
    if fresh:
        raise ValueError("fresh=True was removed; use build_index() for safe publication")
    with _lock:
        try:
            state = index_status()
            active = state["active"]
            contract = releases.embedding_contract()
            if active["generation"] != "legacy" and active["embedding"] != contract:
                raise ValueError("Published index embedding configuration differs; rebuild before retrieval")
            key = (releases.scope(), state["revision"], active["collection"], contract)
            if _vectorstore is not None and key == _cache_key:
                return _vectorstore
            backend.check_collection(active["collection"])
            _vectorstore = backend.Reader(active["collection"], get_embeddings())
            _cache_key = key
            return _vectorstore
        except Exception as exc:
            _vectorstore = _cache_key = None
            logger.warning("[知识库] 只读连接失败 backend=%s error=%s", config.KB_BACKEND, type(exc).__name__)
            return None


def reset_cache():
    global _vectorstore, _cache_key
    with _lock:
        _vectorstore = _cache_key = None


def is_milvus():
    return config.KB_BACKEND == "milvus"


def metadata_expr(doc_type):
    import json
    return "doc_type == " + json.dumps(doc_type, ensure_ascii=False)



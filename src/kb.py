"""知识库访问层:Embedding + 向量库的统一入口。

课程对应:
    第10章 §2.4.1(p47)    模型选型表(bge-m3:多语言 / 1024 维 / 8192 序列长度)
    第10章 §2.4.2(p48-49) Embedding 走 OpenAI 兼容云端网关
    第10章 §2.5.2(p52)    向量库选型
    第10章 §2.5.3(p52-62) Milvus 完整用法:create_database → use_database →
                          create_collection(dimension=1024, metric_type="COSINE")
    第01章 §5.1(p18-19)   RAG 四个难点:文件解析 / 文件切割 / 知识检索 / 知识重排序

为什么单独抽一个模块(旧版的问题):
    旧版 policy.py 与 build_kb.py 各自维护一份向量库初始化代码,而且用的是
    OllamaEmbeddings + Chroma。按课件应改成云端 embedding + Milvus 之后,
    再写两份必然会漂移。这里把"怎么连向量库"收敛到一处,建库与检索共用。

**迁移状态(重要,不要误读)**:
    课件第10章用 Milvus,所以 KB_BACKEND 默认就是 "milvus";
    Milvus 需要 Docker 或 WSL2。本机已验证 Milvus；在尚未启动 Milvus 的环境中,
    把 .env 的 KB_BACKEND 设为 "chroma" 可沿用旧的本地 Chroma 库过渡 ——
    两边 LangChain 接口同构,只改 .env 一处,建库与检索会一起切换。

几个必须记住的踩坑点(实测得到,不是猜的):
1) Milvus 的元数据过滤参数是 **expr 字符串表达式**(如 'doc_type == "exam"'),
   不是 Chroma 那种字典 filter。所以检索层要按后端分支处理。
2) langchain-milvus 的 `_select_relevance_score_fn` 会**读取 index_params 里的
   metric_type** 来决定分数归一化方式;不传 index_params 会退化成 L2 口径并打
   警告。所以这里必须显式传 index_params(metric_type=COSINE),
   归一化才是 (score+1)/2 —— 与课件 p53 的 COSINE 口径一致。
3) Milvus 的 `similarity_search*` 不收字典 filter,只收 expr;而
   `similarity_search_with_relevance_scores` 把它 kwargs 透传下去,
   所以传 expr=... 是可行的。
"""
import logging
import threading
from pathlib import Path

import config

logger = logging.getLogger("campus")

_vectorstore = None
_lock = threading.Lock()

# 索引参数:必须显式给出 metric_type,否则相关性分数会退化成 L2 口径
_MILVUS_INDEX_PARAMS = {
    "index_type": "AUTOINDEX",
    "metric_type": config.MILVUS_METRIC,
    "params": {},
}


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


# ---------------------------------------------------------------- Milvus(课件默认后端)
def _ensure_milvus_collection(fresh: bool = False) -> None:
    """确保 database 与 collection 存在(第10章 §2.5.3 p53-54)。

    维度按 config.EMBED_DIM(默认 1024),度量按 config.MILVUS_METRIC(默认 COSINE),
    与课件 `create_collection(dimension=1024, metric_type="COSINE")` 一致。

    ⚠️ 实测踩坑:MilvusClient 的"当前库"是有状态的 ——
        `use_database()` 之后同一个 client 的后续操作才落在目标库;
        而**新构造一个 client 默认连的是 `default` 库**。
        所以验证/排查时若直接 `MilvusClient(uri=...)` 然后 `list_collections()`,
        会看到空列表并误判"collection 没建成功"。
        排查请用 `MilvusClient(uri=..., db_name=...)`。
        (本函数内部用 use_database 是正确的,已实测 collection 落在 MILVUS_DB_NAME 里;
         最后加一次断言把这个不变量固定下来,避免以后被改坏。)
    """
    from pymilvus import DataType, MilvusClient

    client = MilvusClient(uri=config.MILVUS_URI)
    try:
        if config.MILVUS_DB_NAME not in client.list_databases():
            client.create_database(db_name=config.MILVUS_DB_NAME)
        client.use_database(db_name=config.MILVUS_DB_NAME)

        exists = client.has_collection(collection_name=config.MILVUS_COLLECTION)
        if exists and not fresh:
            return
        if exists:
            client.drop_collection(collection_name=config.MILVUS_COLLECTION)

        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=True)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=config.EMBED_DIM)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        # ⚠️ 实测教训:collection 里**声明过的**字段,插入的每一行都必须给值,
        #    否则报 `Insert missed an field X ... without set nullable==true`。
        #    langchain-milvus 的行结构就是 `{"text":..., "vector":..., **metadata}`,
        #    所以这里既要把字段声明全(nullable=True 兜底),也要在 build_kb.py 里
        #    保证每个 chunk 的 metadata 都带上这些键。
        #    其余元数据(h1/h2/start_index 等)走 enable_dynamic_field 作为动态字段。
        for name, max_len in (
            ("title", 512),
            ("source", 1024),
            ("doc_type", 64),
            ("filename", 256),
        ):
            schema.add_field(name, DataType.VARCHAR, max_length=max_len, nullable=True)
        schema.add_field("chunk_id", DataType.INT64, nullable=True)

        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type=_MILVUS_INDEX_PARAMS["index_type"],
            metric_type=_MILVUS_INDEX_PARAMS["metric_type"],
        )
        client.create_collection(
            collection_name=config.MILVUS_COLLECTION,
            schema=schema,
            index_params=index_params,
        )

        # 自检:确认 collection 真的落在了目标库(而不是 default)—— 见上面踩坑说明
        if not client.has_collection(collection_name=config.MILVUS_COLLECTION):
            raise RuntimeError(
                f"Milvus collection 创建后校验失败:"
                f"db={config.MILVUS_DB_NAME} collection={config.MILVUS_COLLECTION}"
            )

        logger.info(
            "[知识库] 已创建 Milvus collection=%s db=%s dim=%s metric=%s",
            config.MILVUS_COLLECTION,
            config.MILVUS_DB_NAME,
            config.EMBED_DIM,
            config.MILVUS_METRIC,
        )
    finally:
        client.close()


def _build_milvus(fresh: bool = False):
    from langchain_milvus import Milvus

    _ensure_milvus_collection(fresh=fresh)
    return Milvus(
        embedding_function=get_embeddings(),
        collection_name=config.MILVUS_COLLECTION,
        connection_args={"uri": config.MILVUS_URI, "db_name": config.MILVUS_DB_NAME},
        auto_id=True,
        primary_field="id",
        text_field="text",
        vector_field="vector",
        # 关键:显式给 metric_type,相关性分数才按 COSINE 归一化(见模块 docstring 第 2 点)
        index_params=_MILVUS_INDEX_PARAMS,
    )


# ---------------------------------------------------------------- Chroma(过渡用)
def _build_chroma(fresh: bool = False):
    """旧的本地 Chroma 库(仅在 KB_BACKEND=chroma 时使用,过渡期)。

    修掉了旧版的一个真 bug:旧版建库时没指定距离度量,chromadb 默认 l2,
    导致 similarity_search_with_relevance_scores 走欧氏距离换算口径,
    对外展示的"相关度"与课件第10章 p53 的 COSINE 不是一回事。
    这里显式指定 hnsw:space=cosine。
    (注意:距离度量创建后不可更改,所以旧的 Chroma 目录需要重建。)
    """
    from langchain_chroma import Chroma

    store = Chroma(
        collection_name=config.MILVUS_COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(Path(config.CHROMA_DIR)),
        collection_metadata={"hnsw:space": "cosine"},
    )
    if fresh:
        store.delete_collection()
        store = Chroma(
            collection_name=config.MILVUS_COLLECTION,
            embedding_function=get_embeddings(),
            persist_directory=str(Path(config.CHROMA_DIR)),
            collection_metadata={"hnsw:space": "cosine"},
        )
    return store


# ---------------------------------------------------------------- 统一入口
def get_vectorstore(fresh: bool = False):
    """懒加载向量库(进程内缓存;失败返回 None,不抛异常)。

    返回 None 时调用方(policy.py)给出"知识库未接入"的诚实提示,
    而不是让 Agent 崩 —— 这也是 build_kb.py 能用它做"建库前先清空"的原因。
    """
    global _vectorstore
    if _vectorstore is not None and not fresh:
        return _vectorstore
    with _lock:
        if _vectorstore is not None and not fresh:
            return _vectorstore
        try:
            if config.KB_BACKEND == "milvus":
                _vectorstore = _build_milvus(fresh=fresh)
            else:
                _vectorstore = _build_chroma(fresh=fresh)
        except Exception as e:  # noqa: BLE001
            logger.warning("[知识库] 初始化失败(backend=%s): %r", config.KB_BACKEND, e)
            return None
    return _vectorstore


def reset_cache() -> None:
    """清掉进程内缓存(建库脚本重跑后用)。"""
    global _vectorstore
    _vectorstore = None


def is_milvus() -> bool:
    return config.KB_BACKEND == "milvus"


def metadata_expr(doc_type: str) -> str:
    """把 doc_type 转成 Milvus 的 expr 表达式。

    Milvus 用字符串表达式过滤(实测签名里的参数叫 expr),
    与 Chroma 的字典 filter={"doc_type": ...} 不同。
    """
    safe = doc_type.replace('"', "")
    return f'doc_type == "{safe}"'

"""M5 第二步:RAG 知识库构建管线。

管线:data/raw_docs/*.md → 解析 front matter → RecursiveCharacterTextSplitter
      → Ollama bge-m3 向量化 → Chroma(本地持久化,带元数据)

课程对应:P102-116(文档加载、切分、Embedding、向量库、元数据)。

后端说明(架构决策):
- 原计划 Milvus,但 Milvus 标准版必须 Docker(本机无),Milvus Lite 不支持 Windows。
  → 开发期用 Chroma:嵌入式、Windows 原生、持久化、支持元数据过滤,
    LangChain 接口与 Milvus 同构,以后迁移只换 from_documents 的向量库类。
- Embedding 用本机 Ollama 的 bge-m3(多语言,中英混合文档一把抓),
  不依赖云端 API —— 和项目"DeepSeek 主力 + Ollama 本地"的双通道故事一致。

运行(项目根目录):.venv\\python scripts\\build_kb.py
可重复执行:每次清空重建 collection。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_ollama import OllamaEmbeddings  # noqa: E402
from langchain_text_splitters import RecursiveCharacterTextSplitter  # noqa: E402

DOCS_DIR = ROOT / "data" / "raw_docs"
DB_DIR = ROOT / "data" / "chroma_db"
COLLECTION = "xmum_policies"

FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def load_markdown_docs():
    """读取 raw_docs 下所有 md,解析 YAML front matter 为元数据。

    手写解析而不用 PyYAML 的 frontmatter 库:我们的头只有
    title/source/doc_type/lang 四个键值对,不值得引入依赖。
    """
    docs, metadatas = [], []
    for path in sorted(DOCS_DIR.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        m = FM_RE.match(raw)
        if not m:
            print(f"[跳过] {path.name} 无 front matter")
            continue
        meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                meta[k.strip()] = v.strip()
        body = raw[m.end():]
        docs.append(body)
        meta["filename"] = path.name
        metadatas.append(meta)
    return docs, metadatas


def get_embeddings() -> OllamaEmbeddings:
    """bge-m3:本地多语言向量化模型(1024 维)。"""
    return OllamaEmbeddings(
        model="bge-m3",
        base_url="http://localhost:11434",
    )


def get_vectorstore() -> Chroma:
    """打开(或创建)持久化向量库。"""
    return Chroma(
        collection_name=COLLECTION,
        embedding_function=get_embeddings(),
        persist_directory=str(DB_DIR),
    )


def build():
    docs, metadatas = load_markdown_docs()
    if not docs:
        print("没有文档可入库,先运行 scripts/collect_docs.py")
        sys.exit(1)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=600,      # 政策条文段落短,600 字符保证一条规定不被腰斩
        chunk_overlap=100,   # 重叠让跨 chunk 的条文首尾还能拼上
    )
    chunks = splitter.split_documents(
        [Document(page_content=d, metadata=m) for d, m in zip(docs, metadatas)]
    )
    print(f"16 份文档 → {len(chunks)} 个片段")

    # 清空重建(先删 collection 再写,保证幂等)
    import chromadb

    client = chromadb.PersistentClient(path=str(DB_DIR))
    try:
        client.delete_collection(COLLECTION)
        print("已清空旧 collection")
    except Exception:
        pass

    vs = get_vectorstore()
    vs.add_documents(chunks)
    print(f"已写入 {DB_DIR} / collection={COLLECTION}")

    # 自检:预热 embedding 并做一次示例检索
    hits = vs.similarity_search_with_relevance_scores("补考和重修的区别", k=3)
    print("\n自检检索「补考和重修的区别」Top3:")
    for doc, score in hits:
        print(f"  [{score:.3f}] {doc.metadata['title']} | {doc.page_content[:50]}...")


if __name__ == "__main__":
    build()

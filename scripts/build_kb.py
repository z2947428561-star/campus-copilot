"""RAG 知识库构建管线(课件第10章)。

管线:data/raw_docs/*.md → 解析 front matter → 按标题切分 + 递归切分
      → 云端 Embedding 向量化 → Milvus(课件默认后端,带元数据)

课程对应:
    第10章 §2.2(p8-23)    文档加载器(DocumentLoader / DirectoryLoader)
    第10章 §2.3.4(p31-46) 文本切分:RecursiveCharacterTextSplitter 参数、
                          中文 separators、add_start_index、按标题切分
    第10章 §2.4.2(p48-49) Embedding 用云端 OpenAI 兼容网关
    第10章 §2.5.3(p52-62) Milvus:建库 → upsert → flush → 验数

本次修订(按课件 + 实测):
1) Embedding:本机 Ollama → 云端 API(第10章全程没有 Ollama)。向量库与
   embedding 统一由 src/kb.py 提供,建库与检索共用同一份配置,不会各切一半。
2) 向量库:Chroma → Milvus(第10章 §2.5.2 p52"这里我们使用 Milvus")。
   Milvus 需要 Docker/WSL2;尚未拉起时可把 .env 的 KB_BACKEND 设为 chroma 过渡。
3) 切分策略重做(实测结论,不是拍脑袋):
   - 旧配置 chunk_size=600 / overlap=100 在 16 份语料(共 19,194 字符)上
     **几乎不起作用**:最大块 593,从未真正触顶,边界完全由 Markdown 的
     空行决定。实测把 chunk_size 降到 300 才能真实约束粒度(48 块 → 97 块)。
   - 旧版没给中文 separators;实测在 chunk_size=600 下加中文 separators
     **输出逐块完全相同** —— 所以"加 separators"必须和"调小 chunk_size"一起做。
   - 补上 add_start_index=True(第10章 §2.3.3 p25-26、p31-33 专门演示了它),
     这样引用可以带原文偏移,不再只有"片段序号"。
   - Markdown 语料先按标题做一级切分(第10章 §2.3.4 p43-46),让每个 chunk
     自带标题路径,缓解"片段脱离上下文"。

运行(项目根目录):.venv\\python scripts\\build_kb.py
可重复执行:每次清空重建 collection。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.documents import Document  # noqa: E402
from langchain_text_splitters import (  # noqa: E402
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)

import config  # noqa: E402
import kb  # noqa: E402

DOCS_DIR = ROOT / "data" / "raw_docs"

FM_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

# 切分参数(见模块 docstring 第 3 条的实测依据)
CHUNK_SIZE = 300
CHUNK_OVERLAP = 80
# 第10章 §2.3.4(p36 举例5):中文等无空格语言必须自定义 separators
SEPARATORS = ["\n\n", "\n", "。", ";", ";", ",", ",", " ", ""]
# 第10章 §2.3.4(p43-46):Markdown 按标题切分
MD_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


def load_markdown_docs():
    """读取 raw_docs 下所有 md,解析 YAML front matter 为元数据。

    手写解析而不用 PyYAML 的 frontmatter 库:我们的头只有
    title/source/doc_type/lang 四个键值对,不值得引入依赖。

    注意**不要**换成 UnstructuredMarkdownLoader:它不解析 YAML front matter,
    会把 doc_type / title / source 全丢掉,而"元数据随 chunk 传播"正是
    第10章 §2.3.3(p26)、§2.5.3(p61)的核心考点。
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
        meta.setdefault("filename", path.name)
        docs.append(raw[m.end():])
        metadatas.append(meta)
    return docs, metadatas


def split_documents(docs, metadatas):
    """按标题 + 递归切分,并把 front matter 元数据传播到每个 chunk。

    产出每个 chunk 的 metadata 必须覆盖 Milvus collection 里**声明过的**字段
    (chunk_id / title / source / doc_type / filename),否则写入时会报
    `Insert missed an field ... without set nullable==true`(实测踩到)。
    其余元数据(如 h1/h2/start_index)走 enable_dynamic_field 作为动态字段带过去。
    """
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=MD_HEADERS,
        # strip_headers=False:保留标题行本身,避免"### 中文要点"这类标题被删掉后
        # 片段失去上下文(第10章 p43-44 的目的就是让分块继承标题信息)
        strip_headers=False,
    )
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        add_start_index=True,          # 第10章 p25-26 / p31-33
        separators=SEPARATORS,
    )

    chunks: list[Document] = []
    seq = 0
    for body, meta in zip(docs, metadatas):
        for section in md_splitter.split_text(body):
            # 标题层级(第10章 p43-44:让分块继承父级标题上下文)
            section_meta = {**meta, **section.metadata}
            for piece in text_splitter.split_documents(
                [Document(page_content=section.page_content, metadata=section_meta)]
            ):
                md = piece.metadata
                # Milvus 的 VARCHAR 有长度上限,做保护性截断
                md["title"] = str(md.get("title", ""))[:500]
                md["source"] = str(md.get("source", ""))[:1000]
                md["doc_type"] = str(md.get("doc_type", "general"))[:60]
                md["filename"] = str(md.get("filename", ""))[:250]
                # chunk_id:全局顺序号,便于在回答里定位片段(课件 p61/p64 用它做定位)
                md["chunk_id"] = seq
                seq += 1
                chunks.append(piece)
    return chunks


def build():
    docs, metadatas = load_markdown_docs()
    if not docs:
        print(
            "没有文档可入库。请先运行 scripts/archive_docs.py 写入文档快照\n"
            "  (该脚本是离线快照写入器,不含网络采集)"
        )
        sys.exit(1)

    total_chars = sum(len(d) for d in docs)
    print(f"语料:{len(docs)} 份文档,共 {total_chars} 字符")
    print(
        f"切分参数:chunk_size={CHUNK_SIZE}, chunk_overlap={CHUNK_OVERLAP}, "
        f"add_start_index=True, 中文 separators, Markdown 按标题预切"
    )

    chunks = split_documents(docs, metadatas)
    sizes = sorted(len(c.page_content) for c in chunks)
    capped = sum(1 for c in chunks if len(c.page_content) >= CHUNK_SIZE * 0.9)
    print(
        f"→ {len(chunks)} 个片段(最大 {sizes[-1]} / 中位 {sizes[len(sizes) // 2]} / "
        f"接近上限的 {capped} 个)"
    )

    # 清空重建,保证脚本可重复执行(第10章 p53-54:先 drop 再 create)
    print(f"\n后端:{config.KB_BACKEND} / 度量:{config.MILVUS_METRIC} / 维度:{config.EMBED_DIM}")
    # 在删除旧索引前先验证云端/本地 Embedding，避免缺 key、余额不足等
    # 确定性故障导致旧知识库被清空。建库过程仍需维护窗口与备份。
    probe = kb.get_embeddings().embed_query("知识库构建前检查")
    if len(probe) != config.EMBED_DIM:
        raise RuntimeError(f"Embedding 维度不匹配: expected={config.EMBED_DIM}, actual={len(probe)}")
    vs = kb.get_vectorstore(fresh=True)
    if vs is None:
        print(
            "\n[失败] 向量库不可用。请检查:\n"
            "  - .env 的 EMBED_API_KEY 是否已配置\n"
            f"  - KB_BACKEND={config.KB_BACKEND} 对应的服务是否已启动\n"
            f"    (milvus 需要 Docker/WSL2:docker compose up -d,URI={config.MILVUS_URI})"
        )
        sys.exit(1)

    # Milvus 的 schema 已由 kb.py 建好,这里只需把文本交给 LangChain 嵌入并写入。
    # 为兼容两种后端,统一走 add_documents(LangChain 底层会调 embedding_function)。
    ids = vs.add_documents(chunks)
    print(f"已写入 {len(ids)} 个片段 → {config.KB_BACKEND}")

    # 自检:预热 embedding 并做一次示例检索(第10章 p63-66 的验证思路)
    hits = vs.similarity_search_with_relevance_scores("补考和重修的区别", k=3)
    print("\n自检检索「补考和重修的区别」Top3:")
    for doc, score in hits:
        title = doc.metadata.get("title", "?")
        print(f"  [{score:.3f}] {title} | {doc.page_content[:50]}...")


if __name__ == "__main__":
    build()

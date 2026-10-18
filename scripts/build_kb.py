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
     偏移相对标题切分后的章节文本，不是原文件偏移。
   - Markdown 语料先按标题做一级切分(第10章 §2.3.4 p43-46),让每个 chunk
     自带标题路径,缓解"片段脱离上下文"。

运行(项目根目录):.venv\\python scripts\\build_kb.py
可重复执行：写入新版本，验证后原子切换；旧集合保留，可回滚。
"""
import argparse
import json
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
    单行字符串键值对（含来源类型和日期），不值得引入依赖。

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
        for key in ("source_type", "collected_at", "effective_date"):
            meta.setdefault(key, "unknown")
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
            section_meta["offset_scope"] = "section"
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


def build(*, stage_only=False, batch_size=64):
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

    # 候选集合完全独立；所有批次与校验完成前不改变生效指针。
    print(f"\n后端:{config.KB_BACKEND} / 度量:{config.MILVUS_METRIC} / 维度:{config.EMBED_DIM}")
    result = kb.build_index(chunks, publish=not stage_only, batch_size=batch_size)
    print(json.dumps({"result": "staged" if stage_only else "published", "release": result,
                      "revision": kb.index_status()["revision"]}, ensure_ascii=False, indent=2))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="构建候选政策索引、检查状态、发布或回滚")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status", action="store_true", help="只读发布记录，不连接向量库或模型")
    action.add_argument("--stage-only", action="store_true", help="构建并验证，但不切换生效版本")
    action.add_argument("--publish", metavar="GENERATION", help="发布已验证的候选版本")
    action.add_argument("--rollback", action="store_true", help="切回上一生效版本")
    action.add_argument("--rebind-from", metavar="OLD_CHROMA_DIR", help="校验恢复集合，将旧绝对路径登记迁移至当前 Chroma 目录")
    parser.add_argument("--expected-revision", type=int, help="发布/回滚/重绑定必须提供已确认的修订号")
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)
    if args.publish or args.rollback or args.rebind_from is not None:
        if args.expected_revision is None or args.expected_revision < 0:
            parser.error("发布、回滚或重绑定需要 --expected-revision 非负整数")
    elif args.expected_revision is not None:
        parser.error("--expected-revision 只适用于 --publish、--rollback 或 --rebind-from")
    try:
        if args.status:
            result = kb.index_status()
        elif args.publish:
            result = kb.publish_index(args.publish, expected_revision=args.expected_revision)
        elif args.rollback:
            result = kb.rollback_index(expected_revision=args.expected_revision)
        elif args.rebind_from is not None:
            result = kb.rebind_chroma(args.rebind_from, expected_revision=args.expected_revision)
        else:
            build(stage_only=args.stage_only, batch_size=args.batch_size)
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except kb.releases.PublicationConflict as exc:
        print(f"[发布冲突] {exc}。运行 --status 确认后再指定修订号。", file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver exceptions can contain connection credentials; don't echo them.
        print(f"[失败] {type(exc).__name__}。请检查后端、Embedding 配置和 --status；详见 docs/storage.md。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

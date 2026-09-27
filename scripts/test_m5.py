"""M5 DoD 自动验证:RAG 检索质量 + 带来源回答。

DoD 对照(docs/milestones.md):
- 问「补考和重修的区别」→ 回答命中规定原文段落并给出出处  → 主验收
- 人工抽查 10 问(本脚本自动替代人工逐问核验)

三层验证:
1. 检索层:10 个问题的 Top1 片段是否来自正确文档(不花 LLM 钱)
2. 回答层:真实 Agent 回答 DoD 问题,验证含关键事实 + 来源引用
3. 元数据过滤:doc_type 过滤是否工作

运行(项目根目录):.venv\\python.exe scripts\\test_m5.py
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

# 向量库入口从 build_kb 移到了 src/kb.py(建库脚本与检索层现在共用同一份配置)。
# 这里改用 kb.get_vectorstore(),避免测试与生产走两套初始化逻辑。
from kb import get_vectorstore  # noqa: E402

PASS = "  [通过] "
FAIL = "  [失败] "
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL}{name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures += 1


# ---------------------------------------------------------------- 0. 前置:向量自检
# ⚠️ 为什么必须有这一步(实战教训):
#     曾经出现过一次**静默的 RAG 全面失效**:检索 Top1 命中率 0/10,
#     "重修要交钱吗"返回奖学金/成绩复查/纪律申诉,所有分数挤在 0.60-0.71 窄带。
#     根因是 langchain OpenAIEmbeddings 默认 `check_embedding_ctx_length=True`,
#     会把文本用 tiktoken 切成 **token id 数组**再发给非 OpenAI 的 bge-m3。
#     服务端把一串整数当文本编码 → 向量语义错乱,**而且不报错**。
#     这种故障靠"看回答对不对"很难第一时间定位,所以在这里前置两道硬检查:
#       A. 用库里已存片段的原文当 query,必须能召回它自己(score≈1.0)
#       B. 同义句相似度必须明显高于无关句(排除"分数都差不多"的病征)
def test_embedding_sanity():
    print("\n[0/3] 前置自检:embedding 空间是否与库一致(防静默失效)")
    from pymilvus import MilvusClient

    import config
    import kb

    print(f"   embedding 后端: {kb.embedding_backend_desc()}")
    print(f"   KB 后端: {config.KB_BACKEND} / 度量 {config.MILVUS_METRIC} / 维度 {config.EMBED_DIM}")
    if config.EMBED_BACKEND == "cloud":
        print(f"   check_embedding_ctx_length = {config.EMBED_CHECK_CTX_LENGTH}(必须 False)")

    emb = kb.get_embeddings()
    client = MilvusClient(uri=config.MILVUS_URI, db_name=config.MILVUS_DB_NAME)

    # A. 自查询:取 3 条真实片段,用原文反查自己
    rows = client.query(
        collection_name=config.MILVUS_COLLECTION,
        filter="chunk_id >= 0",
        output_fields=["chunk_id", "text"],
    )
    if not rows:
        check("知识库非空", False, "collection 里没有片段,先跑 scripts/build_kb.py")
        client.close()
        return
    rows.sort(key=lambda r: r["chunk_id"])
    probes = [rows[0], rows[len(rows) // 2], rows[-1]]
    self_hits = 0
    for r in probes:
        vec = emb.embed_query(r["text"])
        res = client.search(
            collection_name=config.MILVUS_COLLECTION, data=[vec], limit=1,
            output_fields=["chunk_id"],
        )
        if res and res[0]:
            got = res[0][0]["entity"]["chunk_id"]
            sc = res[0][0]["distance"]
            self_hits += got == r["chunk_id"]
            if got != r["chunk_id"]:
                print(f"   × chunk {r['chunk_id']} 反查命中 chunk {got}(score={sc:.3f})—— 空间错配!")
        else:
            print(f"   × chunk {r['chunk_id']} 反查无结果")
    check(
        "自查询能召回自己(检索向量与库向量同空间)",
        self_hits == len(probes),
        f"{self_hits}/{len(probes)}",
    )

    # B. 同义 vs 无关:排除"分数都差不多"的病征
    va, vb, vc = emb.embed_documents(
        ["补考和重修有什么区别", "重修和补考的差别是什么", "今天天气很好适合出门"]
    )

    def _cos(x, y):
        import numpy as np

        x, y = np.array(x), np.array(y)
        return float(x @ y / (np.linalg.norm(x) * np.linalg.norm(y)))

    same, unrel = _cos(va, vb), _cos(va, vc)
    print(f"   同义句相似度 {same:.3f} / 无关句相似度 {unrel:.3f}")
    check(
        "同义句相似度明显高于无关句(区分度正常)",
        same > 0.8 and same > unrel + 0.2,
        f"同义 {same:.3f} vs 无关 {unrel:.3f}",
    )
    client.close()


# ---------------------------------------------------------------- 1. 检索层抽查
# (问题, 期望命中文档标题关键词)
SPOT_CHECKS = [
    ("补考和重修的区别", "重修"),
    ("重修要交钱吗", "重修"),
    ("出勤率低于多少会被禁考", "考勤"),
    ("生病了怎么申请缓考", "缓考"),
    ("对成绩不满意怎么复查", "复查"),
    ("毕业需要什么条件", "毕业"),
    ("奖学金怎么拿,怎么续", "奖学金"),
    ("签证续签有什么要求", "签证"),
    ("考试能带什么东西进考场", "考场"),
    ("连续缺勤几天会被开除", "请假"),
]


def test_retrieval():
    print("\n[1/3] 检索层:10 问抽查(Top1 是否命中正确文档)")
    vs = get_vectorstore()
    ok_count = 0
    for q, expect in SPOT_CHECKS:
        hits = vs.similarity_search(q, k=1)
        if not hits:
            check(f"「{q}」", False, "无结果")
            continue
        title = hits[0].metadata.get("title", "")
        ok = expect in title
        ok_count += ok
        print(f"  {'√' if ok else '×'} 「{q}」→《{title}》")
    check("10 问检索命中率 ≥ 8/10", ok_count >= 8, f"{ok_count}/10")


# ---------------------------------------------------------------- 2. 元数据过滤
def test_filter():
    print("\n[2/3] 元数据过滤:doc_type 过滤是否生效")
    import config
    import kb

    vs = get_vectorstore()
    # ⚠️ 两种后端的过滤语法不同:Milvus 用 expr 字符串表达式,Chroma 用字典 filter。
    #    旧版这里固定传 Chroma 风格的 filter={"doc_type": "visa"},切到 Milvus 后
    #    会静默失效(被当成动态字段过滤或直接报错),所以按后端分支。
    if config.KB_BACKEND == "milvus":
        hits = vs.similarity_search("要求", k=3, expr=kb.metadata_expr("visa"))
    else:
        hits = vs.similarity_search("要求", k=3, filter={"doc_type": "visa"})
    types = {h.metadata.get("doc_type") for h in hits}
    check("过滤 visa 后结果全部来自签证文档", types == {"visa"}, str(types))


# ---------------------------------------------------------------- 3. 回答层(真 Agent)
def test_answer():
    print("\n[3/3] 回答层:真实 Agent 回答 DoD 问题(会调用 LLM)")
    from agent.assistant import get_agent

    agent = get_agent()  # 裸 Agent 即可:RAG 检索在工具内完成
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "补考和重修有什么区别?"}]}
    )
    final = result["messages"][-1].content
    if isinstance(final, list):
        final = "".join(b.get("text", "") for b in final if isinstance(b, dict))
    print(f"        Agent 回答(节选):\n{final[:500]}\n")

    # 看整个消息链里是否真的调用了 search_policy
    tool_used = any(
        getattr(m, "name", "") == "search_policy"
        for m in result["messages"]
        if m.__class__.__name__ == "ToolMessage"
    )
    check("回答前调用了 search_policy 检索知识库", tool_used)

    # DoD:命中规定原文段落(体现为关键事实)+ 给出出处
    has_facts = ("重修" in final) and (
        ("缓考" in final) or ("retake" in final.lower()) or ("重新上课" in final)
    )
    check("回答含关键事实(重修=重新上课/缓考路径)", has_facts)
    has_source = ("手册" in final) or ("Handbook" in final) or ("xmu.edu.my" in final) or ("来源" in final)
    check("回答附来源引用", has_source)


if __name__ == "__main__":
    print("=" * 60)
    print("M5 DoD 自动验证(检索层调用 Embedding API,回答层调用 LLM)")
    print("=" * 60)
    test_embedding_sanity()   # 前置:向量空间自检(防 RAG 静默失效)
    test_retrieval()
    test_filter()
    test_answer()
    print("\n" + "=" * 60)
    if failures:
        print(f"结果:{failures} 项失败,看上面 [失败] 行")
        sys.exit(1)
    print("结果:全部通过 ✓")

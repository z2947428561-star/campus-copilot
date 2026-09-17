"""M5 DoD 自动验证:RAG 检索质量 + 带来源回答。

DoD 对照(docs/milestones.md):
- 问「补考和重修的区别」→ 回答命中规定原文段落并给出出处  → 主验收
- 人工抽查 10 问(本脚本自动替代人工逐问核验)

三层验证:
1. 检索层:10 个问题的 Top1 片段是否来自正确文档(不花 LLM 钱)
2. 回答层:真实 Agent 回答 DoD 问题,验证含关键事实 + 来源引用
3. 元数据过滤:doc_type 过滤是否工作

运行(项目根目录):.venv\\Scripts\\python scripts\\test_m5.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_kb import get_vectorstore  # noqa: E402

PASS = "  [通过] "
FAIL = "  [失败] "
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL}{name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures += 1


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
    vs = get_vectorstore()
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
    print("M5 DoD 自动验证(检索层不花钱,回答层调 LLM)")
    print("=" * 60)
    test_retrieval()
    test_filter()
    test_answer()
    print("\n" + "=" * 60)
    if failures:
        print(f"结果:{failures} 项失败,看上面 [失败] 行")
        sys.exit(1)
    print("结果:全部通过 ✓")

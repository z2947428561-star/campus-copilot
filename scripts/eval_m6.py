"""M6:评估集跑批 —— 全链路问答准确率测量。

读 scripts/eval_set.json,每题跑真实 Agent(DeepSeek + 工具 + RAG),
按三层打分:
1. 路由:expect_tool 是否被真实调用(ToolMessage 出现)
2. 内容:expect_any 关键词是否命中最终回答
3. 红线:expect_none 内容是否出现(出现即失败,如 PII 回显、编造)

HITL 题(hitl=true)自动放行后继续。
结果写入 docs/eval-results.md,给 README/简历回填真实数字。

运行:.venv\\python scripts\\eval_m6.py(约 30 次 LLM 调用,分币级成本)
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.assistant import get_agent  # noqa: E402
from langgraph.types import Command  # noqa: E402


def ask(agent, cfg, question, auto_approve):
    """跑一题:流式收集回答;遇 HITL 中断时(按需)自动放行,返回 (回答, 调用的工具集)。"""
    reply, tools = "", set()
    inputs = {"messages": [{"role": "user", "content": question}]}
    for _ in range(3):  # 最多 3 轮(interrupt → resume → done)
        interrupted = None
        for mode, data in agent.stream(inputs, cfg, stream_mode=["messages", "updates"]):
            if mode == "messages":
                chunk, metadata = data
                if metadata.get("langgraph_node") != "model":
                    continue
                text = chunk.content
                if isinstance(text, list):
                    text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
                reply += text or ""
                for tc in getattr(chunk, "tool_call_chunks", None) or []:
                    if tc.get("name"):
                        tools.add(tc["name"])
            elif mode == "updates" and data.get("__interrupt__"):
                interrupted = data["__interrupt__"][0]
        if interrupted is None:
            break
        if not auto_approve:
            break
        inputs = Command(resume={"decisions": [{"type": "approve"}]})
    return reply, tools


def run_eval():
    items = json.loads((ROOT / "scripts" / "eval_set.json").read_text(encoding="utf-8"))["items"]
    agent = get_agent(with_middleware=True, with_memory=True)

    results = []
    t0 = time.time()
    # 关键方法论:每轮评估用全新线程(时间戳后缀),否则 checkpointer 里的
    # 上一轮问答会让模型"复述而不调工具",污染路由测量
    run_id = time.strftime("%m%d%H%M%S")
    for it in items:
        thread = f"{it.get('thread') or 'eval'}-{run_id}"
        cfg = {"configurable": {"thread_id": thread, "user_id": "eval"}}
        try:
            reply, tools = ask(agent, cfg, it["q"], auto_approve=it.get("hitl", False))
        except Exception as e:
            results.append({**it, "ok": False, "reason": f"异常 {e!r}", "reply": "", "tools": []})
            print(f"  × {it['id']} 异常 {e!r}")
            continue

        reasons = []
        if "expect_tool" in it and it["expect_tool"] not in tools:
            reasons.append(f"路由未调 {it['expect_tool']}(实际:{sorted(tools) or '无'})")
        if "expect_any" in it and not any(kw in reply for kw in it["expect_any"]):
            reasons.append(f"关键词未命中 {it['expect_any']}")
        if "expect_none" in it and any(bad in reply for bad in it["expect_none"]):
            reasons.append(f"红线:出现不应有的内容 {it['expect_none']}")
        ok = not reasons
        results.append({**it, "ok": ok, "reason": "; ".join(reasons), "reply": reply, "tools": sorted(tools)})
        print(f"  {'√' if ok else '×'} {it['id']} {it['q'][:18]}" + ("" if ok else f" —— {reasons}"))

    n = len(results)
    n_ok = sum(r["ok"] for r in results)
    routed = [r for r in results if "expect_tool" in r]
    routed_ok = sum(r["ok"] and r["expect_tool"] in r["tools"] for r in routed)
    dur = time.time() - t0
    print(f"\n===== 总体:{n_ok}/{n}({n_ok/n:.0%}) | 路由:{routed_ok}/{len(routed)} | 用时 {dur:.0f}s =====")

    # 写结果报告
    lines = [
        "# M6 评估报告",
        "",
        f"- 评估时间:{time.strftime('%Y-%m-%d %H:%M')}",
        f"- 评估集:{n} 问(教学周/空教室/课表 {len(routed)} 问路由校验 + 内容/红线校验)",
        f"- 模型:DeepSeek-chat + 8 工具 + Chroma RAG(16 份官方文档)",
        f"- **总体通过率:{n_ok}/{n} = {n_ok/n:.0%}**",
        f"- 工具路由准确率:{routed_ok}/{len(routed)} = {routed_ok/len(routed):.0%}",
        f"- 单题平均耗时 {dur/n:.1f}s",
        "",
        "| ID | 问题 | 结果 | 说明 |",
        "|---|---|---|---|",
    ]
    for r in results:
        mark = "√" if r["ok"] else "×"
        lines.append(f"| {r['id']} | {r['q'][:20]} | {mark} | {r['reason'] or '-'} |")
    out = ROOT / "docs" / "eval-results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"报告已写入 {out}")
    return n_ok, n


if __name__ == "__main__":
    ok, total = run_eval()
    sys.exit(0 if ok >= total * 0.8 else 1)  # 80% 为通过线

"""评估集跑批 —— 全链路问答准确率测量。

读 scripts/eval_set.json,每题跑真实 Agent(DeepSeek + 8 工具 + RAG),
按三层打分:
1. 路由:expect_tool 是否被**真实执行**(以 ToolMessage 为准)
2. 内容:expect_any 关键词是否命中最终回答
3. 红线:expect_none 内容是否出现(出现即失败,如 PII 回显)

HITL 题(hitl=true)自动放行后继续。
结果写入 docs/eval-results.md,给 README/简历回填真实数字。

运行(项目根目录):.venv\\python scripts\\eval_m6.py
(约 30 次 LLM 调用,分币级成本)

课程对应:
    第03章 §1.2(p1-2)      课件把"评估"放在 LangSmith 的 Datasets & Experiments /
                           Evaluators。本项目用的是**自建跑批 + 关键词断言**
                           (规则评估器雏形),**未使用** LangSmith 的评估功能 ——
                           本文件与报告都会如实标注这一点。
    第03章 §3 举例3(p7-8)  config 带 run_name / tags / metadata(便于在 LangSmith 里
                           按用户与会话筛选这一轮评估的 trace)
    第08章 §2.2(p12-19)    HITL:中断 → 决策 → Command(resume=...)

本次修订(与旧版的差异):
1. 路由判定从 `chunk.tool_call_chunks` 改为**以 ToolMessage 为准**。
   旧版只看"模型在 token 流里声称要调哪个工具",无法区分"说要调"和"真的调了"。
2. 走统一的 `stream_turn`(第07章 §9.3 p80-81 的封装思路),不再自己写一遍
   流式 + 中断循环。
3. cfg 走 `agent.runtime.make_config` —— 带上 recursion_limit(第07章 §4.4 p26)
   与 LangSmith 的 run_name/tags/metadata(第02章 §6.4 p62-65)。
4. 传 `context=UserContext(...)`(第09章 §4.2 p74-80)—— 画像工具靠它拿身份。
5. 默认把记忆库切到**独立库**,不污染生产库(旧版直接写 campus 生产库)。
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

ROOT = Path(__file__).resolve().parent.parent

# ⚠️ 必须在 import config 之前设置:
#   .env 里 DATABASE_URL 指向**生产库 campus**,而 config.py 用
#   load_dotenv(override=True)。所以这里用 CAMPUS_ENV_OVERRIDE=0 让环境变量优先,
#   再用同一个 PG 实例上的**独立库 campus_eval**(或临时 SQLite)承接评估产生的会话。
os.environ.setdefault("CAMPUS_ENV_OVERRIDE", "0")
os.environ.setdefault(
    "DATABASE_URL", "postgresql://campus:campus_pw@127.0.0.1:5432/campus_test"
)
os.environ.setdefault("MEMORY_BACKEND", "postgres")
os.environ.setdefault("MEMORY_DB_PATH", str(Path(tempfile.mkdtemp(prefix="campus_eval_")) / "eval.db"))
# 评估不必要上报 trace(要开的话显式 EVAL_LANGSMITH_TRACING=true)
os.environ.setdefault("LANGSMITH_TRACING", os.environ.get("EVAL_LANGSMITH_TRACING", "false"))

sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
from agent.assistant import get_agent  # noqa: E402
from agent.runtime import make_config  # noqa: E402
from agent.streaming import InterruptInfo, stream_turn  # noqa: E402
from context import UserContext  # noqa: E402
from tools import ALL_TOOLS  # noqa: E402
from student_data import init_student_data, set_course, set_grade  # noqa: E402


def ask(agent, cfg, question, auto_approve, user_id):
    """跑一题:返回 (回答, 真实执行过的工具名集合)。

    工具名以 ToolMessage.name 为准 —— 这是"真的执行了"的证据;
    旧版从 tool_call_chunks 里捡"模型声称要调"的名字,会把"说了没做"也算成命中。
    """
    tools: set[str] = set()
    inputs = {"messages": [{"role": "user", "content": question}]}
    interrupted: dict = {}

    def on_decide(info: InterruptInfo):
        # 记录被拦截的工具;按题目标记决定放行还是拒绝
        for a in info.action_requests:
            interrupted["tool"] = a.get("name")
        if auto_approve:
            return [{"type": "approve"}] * max(len(info), 1)
        return [{"type": "reject", "message": "评估集未标记 hitl,默认拒绝"}] * max(len(info), 1)

    # 用 updates 流单独收集 ToolMessage(stream_turn 只负责文本与中断)
    reply = stream_turn(
        agent, inputs, cfg, on_decide=on_decide, context=UserContext(user_id=user_id)
    )

    # 从最终 state 里收真实执行过的工具(第09章 §2.1.2 p8 的 agent.get_state)
    state = agent.get_state(cfg)
    for m in (state.values.get("messages") if state.values else []) or []:
        if m.__class__.__name__ == "ToolMessage" and getattr(m, "name", None):
            tools.add(m.name)
    return reply, tools


def run_eval():
    items = json.loads((ROOT / "scripts" / "eval_set.json").read_text(encoding="utf-8"))["items"]
    run_id = time.strftime("%m%d%H%M%S")
    eval_user = f"eval-{run_id}"
    init_student_data()
    demo = json.loads((ROOT / "data" / "structured" / "seed_grades.json").read_text(encoding="utf-8"))
    for row in demo["records"]:
        set_grade(eval_user, row["course_id"], row["grade_point"], row["letter"])
    set_course(eval_user, "CS101")
    agent = get_agent(with_middleware=True, with_memory=True)

    results = []
    t0 = time.time()
    # ⚠️ 关键方法论:每题一个全新 thread(第09章 §2.1.3 p11 的 thread 隔离)。
    #
    # 这里踩过一个很隐蔽的坑:初版写的是 thread = f"{it.get('thread') or 'eval'}-{run_id}",
    # 于是**所有没显式标 thread 的题共用 "eval-{run_id}" 这一个会话**(实测 29 题
    # 全挤在一个 thread,产生 355 个 checkpoint)。后果不是"复述不调工具",
    # 而是更严重:ModelCallLimitMiddleware 的 thread_limit 是**按会话累计**的,
    # 累计到上限后每一轮都被 exit_behavior="end" 直接结束 —— 模型不再说话,
    # 回答变成空字符串,表现为"关键词未命中"大批失败(实测 81% 掉到 58%)。
    #
    # 所以现在:**默认用题目 id 作为 thread 名**(一题一会话);
    # 只有显式声明了同一个 `thread` 字段的题(如画像组 m01/m02)才共享会话 ——
    # 那正是它们要验证的"跨轮/跨会话记忆"。
    for it in items:
        shared = it.get("thread")
        thread = f"{shared}-{run_id}" if shared else f"item-{it['id']}-{run_id}"
        cfg = make_config(
            thread_id=thread,
            user_id=eval_user,
            run_name=f"eval:{it['id']}",
            tags=["eval", "m6"],
        )
        try:
            reply, tools = ask(agent, cfg, it["q"], auto_approve=it.get("hitl", False), user_id=eval_user)
        except Exception as e:
            results.append({**it, "ok": False, "reason": f"异常 {e!r}", "reply": "", "tools": []})
            print(f"  × {it['id']} 异常 {type(e).__name__}: {str(e)[:60]}")
            continue
        if os.environ.get("EVAL_DEBUG"):
            print(f"    [debug] reply_len={len(reply)} tools={sorted(tools)} reply={reply[:60]!r}")

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
    import kb

    lines = [
        "# M6 评估报告",
        "",
        f"- 评估时间:{time.strftime('%Y-%m-%d %H:%M')}",
        f"- 评估集:{n} 问(路由校验 {len(routed)} 问 + 内容/红线校验)",
        f"- 模型:{config.LLM_MODEL}(temperature={config.LLM_TEMPERATURE})+ {len(ALL_TOOLS)} 工具",
        f"- RAG:{config.KB_BACKEND} / Embedding {kb.embedding_backend_desc()}"
        f" / 度量 {config.MILVUS_METRIC} / 维度 {config.EMBED_DIM}",
        f"- 记忆后端:{config.MEMORY_BACKEND}(评估会话写在独立库,不碰生产库)",
        f"- **总体通过率:{n_ok}/{n} = {n_ok/n:.0%}**",
        f"- 工具路由准确率:{routed_ok}/{len(routed)} = {routed_ok/len(routed):.0%}",
        f"- 单题平均耗时 {dur/n:.1f}s",
        "- 评估口径:**自建跑批 + 关键词断言**(规则评估器雏形),"
        "**未使用** LangSmith 的 Datasets/Evaluators(课件第03章 §1.2 p1-2 的那条路)",
        "- 路由判定:**以 ToolMessage 为准**(真的执行过才算命中),而不是「模型声称要调」",
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
    print(f"评估隔离:记忆后端 {config.MEMORY_BACKEND} → {config.DATABASE_URL.split('@')[-1]}")
    print(f"RAG:{config.KB_BACKEND} / {config.EMBED_BACKEND}\n")
    ok, total = run_eval()
    sys.exit(0 if ok >= total * 0.8 else 1)  # 80% 为通过线

"""M4 DoD 自动验证:持久化记忆 + 多用户隔离 + 长期画像。

DoD 对照(docs/milestones.md):
1. 两个 session 互不串扰            → test_isolation()
2. 重启续聊(新进程同会话)          → test_restart_recovery()
3. 能答「我是大几的、常问什么」     → test_profile()

运行(项目根目录):.venv\\Scripts\\python scripts\\test_m4.py
会真实调用 DeepSeek(少量),并清空重建 data/memory.db。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent.assistant import get_agent  # noqa: E402
from agent.memory import DB_PATH, reset_memory  # noqa: E402

PASS = "  [通过] "
FAIL = "  [失败] "
failures = 0


def check(name, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL}{name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures += 1


def ask(agent, cfg, question) -> str:
    """单轮问答,返回最终文本(流式输出静默收集)。"""
    reply = ""
    for mode, data in agent.stream(
        {"messages": [{"role": "user", "content": question}]},
        cfg,
        stream_mode=["messages", "updates"],
    ):
        if mode == "messages":
            chunk, metadata = data
            if metadata.get("langgraph_node") != "model":
                continue
            text = chunk.content
            if isinstance(text, list):
                text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
            reply += text or ""
    return reply


# ---------------------------------------------------------------- 1. 会话隔离
def test_isolation():
    print("\n[1/3] 多用户会话隔离(同一进程)")

    agent = get_agent(with_middleware=True, with_memory=True)
    cfg_a = {"configurable": {"thread_id": "alice-main", "user_id": "alice"}}
    cfg_b = {"configurable": {"thread_id": "bob-main", "user_id": "bob"}}

    ask(agent, cfg_a, "请记住:我是大二学生,软件工程专业。")
    ask(agent, cfg_b, "请记住:我是大一新生,刚入学。")

    ans_a = ask(agent, cfg_a, "我是什么年级、什么专业?")
    ans_b = ask(agent, cfg_b, "我是什么年级?")
    print(f"        alice 得到: {ans_a[:60]}")
    print(f"        bob   得到: {ans_b[:60]}")
    check("alice 只看到自己的信息(大二/软件工程)", "大二" in ans_a and "软件工程" in ans_a)
    check("bob 只看到自己的信息(大一),看不到 alice", "大一" in ans_b and "大二" not in ans_b and "软件" not in ans_b)


# ---------------------------------------------------------------- 2. 重启恢复
def test_restart_recovery():
    print("\n[2/3] 重启续聊(新建 agent 实例模拟进程重启)")

    # 全新 agent 实例 = 新进程;数据全靠 data/memory.db
    agent2 = get_agent(with_middleware=True, with_memory=True)
    cfg = {"configurable": {"thread_id": "alice-main", "user_id": "alice"}}

    state = agent2.get_state(cfg)
    n = len(state.values.get("messages", [])) if state.values else 0
    print(f"        重启后 alice-main 会话消息数: {n}")
    check("短期会话已落盘(消息数 > 0)", n > 0, f"{n} 条")

    ans = ask(agent2, cfg, "我们刚才聊到哪了?一句话概括")
    print(f"        续聊回答: {ans[:60]}")
    check("重启后能接上话题(提到年级或专业)", ("大二" in ans) or ("软件" in ans))


# ---------------------------------------------------------------- 3. 长期画像
def test_profile():
    print("\n[3/3] 长期画像:我是大几的 / 我常问什么(跨会话)")

    agent3 = get_agent(with_middleware=True, with_memory=True)
    # 全新 thread:长期记忆跨 thread 生效,短期会话帮不上忙
    cfg = {"configurable": {"thread_id": "alice-new-topic", "user_id": "alice"}}

    ask(agent3, cfg, "请顺便记住:我平时最关心选课和空教室。")

    ans1 = ask(agent3, cfg, "我是大几的?")
    ans2 = ask(agent3, cfg, "我常问/关心什么?")
    print(f"        大几: {ans1[:60]}")
    print(f"        常问: {ans2[:60]}")
    check("跨 thread 答出年级(大二)", "大二" in ans1)
    check("跨 thread 答出关注话题(选课/空教室)", ("选课" in ans2) or ("空教室" in ans2))

    # 直接查 store 验证:GPA 工具是否把结果自动写进了画像
    agent4 = get_agent(with_memory=True)
    cfg4 = {"configurable": {"thread_id": "alice-check", "user_id": "alice"}}
    ask(agent4, cfg4, "用 calculate_gpa 工具算下我的 GPA")
    from agent.memory import get_store

    store = get_store()
    items = {i.key: i.value.get("value") for i in store.search(("profiles", "alice"))}
    print(f"        alice 画像全量: {items}")
    check("画像含年级", "grade" in items)
    check("画像含关注话题", "interests" in items)
    check("calculate_gpa 自动记录了 latest_gpa", "latest_gpa" in items)


if __name__ == "__main__":
    print("=" * 60)
    print("M4 DoD 自动验证(将清空重建 data/memory.db)")
    print("=" * 60)
    if DB_PATH.exists():
        reset_memory()
    test_isolation()
    test_restart_recovery()
    test_profile()
    print("\n" + "=" * 60)
    if failures:
        print(f"结果:{failures} 项失败,看上面 [失败] 行")
        sys.exit(1)
    print("结果:全部通过 ✓")

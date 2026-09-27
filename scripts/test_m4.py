"""M4 DoD 自动验证:持久化记忆 + 多用户隔离 + 长期画像。

DoD 对照(docs/milestones.md):
1. 两个 session 互不串扰            → test_isolation()
2. 重启续聊(新实例同会话)          → test_restart_recovery()
3. 能答「我是大几的、常问什么」     → test_profile()

课程对应:第09章 §2.1.3(p11)thread_id 隔离、§2.2(p14-18)外部持久化、
         §3.1.3(p39-41)namespace 隔离、§4.2(p74-80)context 注入身份

⚠️ 安全改动(为什么不再删生产库):
    旧版 `if DB_PATH.exists(): reset_memory()` 删的是 **data/memory.db 生产库** ——
    跑一次测试就把真实会话与画像全抹掉。
    现在改为:**必须在专用测试库上跑**。
      - postgres 后端 → 用 DATABASE_URL 指向 `campus_test` 库(本文件顶部强制设置)
      - sqlite 后端   → MEMORY_DB_PATH 指向临时文件
    课件没有"删数据库"这种教法;可迁移的依据是 §2.1.3(p11)/§3.1.3(p40)
    的 thread_id 与 namespace 隔离 —— 测试之间靠命名空间隔离,不靠清库。

运行(项目根目录):.venv\\python scripts\\test_m4.py
会真实调用 DeepSeek(少量),但只读写 campus_test 库。
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

ROOT = Path(__file__).resolve().parent.parent
_TMP_DIR = Path(tempfile.mkdtemp(prefix="campus_m4_"))

# ⚠️ 配置接管说明(实测踩过两个坑,这里一并写清楚):
#
# 坑 1:config.py 用 load_dotenv(override=True),而 .env 里的
#   MEMORY_BACKEND/DATABASE_URL 指向**生产库 campus**。若不拦住,
#   下面设置的测试库会被 .env 顶掉 —— 实测确实连到了生产库(campus_test 里
#   一张表都没建,而 campus 里多出了行),所以需要 CAMPUS_SKIP_DOTENV=1。
#
# 坑 2:但跳过 .env 就丢了 DEEPSEEK_API_KEY,而 middleware 组装摘要中间件时要
#   构造模型 → RuntimeError。所以这里先用 dotenv_values **读而不覆盖**,
#   把 API key 之类必需项显式搬进环境,再单独覆盖测试用的库配置。
from dotenv import dotenv_values  # noqa: E402

_env_file = dotenv_values(ROOT / ".env")
os.environ["CAMPUS_SKIP_DOTENV"] = "1"
for _k in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"):
    if _env_file.get(_k):
        os.environ[_k] = _env_file[_k]

# 测试专属覆盖:库指向 campus_test,且不上报 trace
os.environ["MEMORY_BACKEND"] = os.environ.get("TEST_MEMORY_BACKEND", "postgres")
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://campus:campus_pw@127.0.0.1:5432/campus_test",
)
os.environ["MEMORY_DB_PATH"] = str(_TMP_DIR / "test_memory.db")
os.environ["LANGSMITH_TRACING"] = os.environ.get("TEST_LANGSMITH_TRACING", "false")

sys.path.insert(0, str(ROOT / "src"))

import config  # noqa: E402
from agent.assistant import get_agent  # noqa: E402
from agent.memory import close_memory, get_store  # noqa: E402
from agent.runtime import make_config  # noqa: E402
from agent.streaming import stream_turn  # noqa: E402
from context import UserContext  # noqa: E402
from student_data import delete_grade, init_student_data, set_grade  # noqa: E402

PASS = "  [通过] "
FAIL = "  [失败] "
failures = 0

# 每轮用独立后缀:重复跑不互相污染,也顺便验证了 namespace 隔离
RUN = uuid.uuid4().hex[:6]
ALICE = f"alice-{RUN}"
BOB = f"bob-{RUN}"


def check(name, ok, detail=""):
    global failures
    print(f"{PASS if ok else FAIL}{name}" + (f" —— {detail}" if detail else ""))
    if not ok:
        failures += 1


def ask(agent, cfg, user_id, question) -> str:
    """单轮问答,返回最终文本(流式输出静默收集)。

    走统一的 stream_turn(第07章 §9.3 p80-81),身份经 context 传入
    (第09章 §4.2 p74-80)。
    """
    return stream_turn(
        agent,
        {"messages": [{"role": "user", "content": question}]},
        cfg,
        on_decide=lambda info: [{"type": "approve"}] * max(len(info), 1),
        context=UserContext(user_id=user_id),
    )


# ---------------------------------------------------------------- 1. 会话隔离
def test_isolation():
    print(f"\n[1/3] 多用户会话隔离(同一进程,用户 {ALICE} / {BOB})")

    agent = get_agent(with_middleware=True, with_memory=True)
    cfg_a = make_config(thread_id=f"{ALICE}-main", user_id=ALICE)
    cfg_b = make_config(thread_id=f"{BOB}-main", user_id=BOB)

    ask(agent, cfg_a, ALICE, "请记住:我是大二学生,软件工程专业。")
    ask(agent, cfg_b, BOB, "请记住:我是大一新生,刚入学。")

    ans_a = ask(agent, cfg_a, ALICE, "我是什么年级、什么专业?")
    ans_b = ask(agent, cfg_b, BOB, "我是什么年级?")
    print(f"        alice 得到: {ans_a[:60]}")
    print(f"        bob   得到: {ans_b[:60]}")
    check("alice 只看到自己的信息(大二/软件工程)", "大二" in ans_a and "软件工程" in ans_a)
    check(
        "bob 只看到自己的信息(大一),看不到 alice",
        "大一" in ans_b and "大二" not in ans_b and "软件" not in ans_b,
    )


# ---------------------------------------------------------------- 2. 重启恢复
def test_restart_recovery():
    print("\n[2/3] 重启续聊(新建 agent 实例模拟进程重启)")

    # 全新 agent 实例 = 新进程;数据靠外部存储(第09章 §2.3 p18-24 的对比结论)
    agent2 = get_agent(with_middleware=True, with_memory=True)
    cfg = make_config(thread_id=f"{ALICE}-main", user_id=ALICE)

    state = agent2.get_state(cfg)
    n = len(state.values.get("messages", [])) if state.values else 0
    print(f"        重启后 {ALICE}-main 会话消息数: {n}")
    check("短期会话已落盘(消息数 > 0)", n > 0, f"{n} 条")

    ans = ask(agent2, cfg, ALICE, "我们刚才聊到哪了?一句话概括")
    print(f"        续聊回答: {ans[:60]}")
    check("重启后能接上话题(提到年级或专业)", ("大二" in ans) or ("软件" in ans))


# ---------------------------------------------------------------- 3. 长期画像
def test_profile():
    print("\n[3/3] 长期画像:我是大几的 / 我常问什么(跨会话)")

    agent3 = get_agent(with_middleware=True, with_memory=True)
    # 全新 thread:长期记忆跨 thread 生效,短期会话帮不上忙(§3.1.3 p39-41)
    cfg = make_config(thread_id=f"{ALICE}-new-topic", user_id=ALICE)

    ask(agent3, cfg, ALICE, "请顺便记住:我平时最关心选课和空教室。")

    ans1 = ask(agent3, cfg, ALICE, "我是大几的?")
    ans2 = ask(agent3, cfg, ALICE, "我常问/关心什么?")
    print(f"        大几: {ans1[:60]}")
    print(f"        常问: {ans2[:60]}")
    check("跨 thread 答出年级(大二)", "大二" in ans1)
    check("跨 thread 答出关注话题(选课/空教室)", ("选课" in ans2) or ("空教室" in ans2))

    # 直接查 store 验证:GPA 工具是否把结果自动写进了画像
    init_student_data()
    set_grade(ALICE, "CS101", 3.7, "A-")
    agent4 = get_agent(with_memory=True)
    cfg4 = make_config(thread_id=f"{ALICE}-check", user_id=ALICE)
    ask(agent4, cfg4, ALICE, "用 calculate_gpa 工具算下我的 GPA")

    store = get_store()
    items = {i.key: i.value.get("value") for i in store.search(("profiles", ALICE))}
    print(f"        {ALICE} 画像全量: {items}")
    check("画像含年级", "grade" in items)
    check("画像含关注话题", "interests" in items)
    check("calculate_gpa 自动记录了 latest_gpa", "latest_gpa" in items)


def _cleanup():
    """清理本轮测试数据(按 namespace / thread_id 前缀),不动其他数据。"""
    print("\n[清理] 只删本轮测试数据")
    try:
        store = get_store()
        for key in ("grade", "major", "interests", "courses", "goal", "latest_gpa"):
            for uid in (ALICE, BOB):
                try:
                    store.delete(("profiles", uid), key)
                except Exception:  # noqa: BLE001 —— key 不存在时会抛,忽略
                    pass
        print(f"        已清理 profiles/{ALICE} 与 profiles/{BOB}")
    except Exception as e:  # noqa: BLE001
        print(f"        清理画像失败(不影响结论): {e!r}")
    finally:
        try:
            delete_grade(ALICE, "CS101")
        except Exception:
            pass
        close_memory()


if __name__ == "__main__":
    print("=" * 60)
    print("M4 DoD 自动验证")
    print(f"  记忆后端: {config.MEMORY_BACKEND}")
    if config.MEMORY_BACKEND == "postgres":
        print(f"  测试库  : {config.DATABASE_URL.split('@')[-1]}  (生产库不受影响)")
    else:
        print(f"  临时库  : {config.MEMORY_DB_PATH}")
    print("=" * 60)
    try:
        test_isolation()
        test_restart_recovery()
        test_profile()
    finally:
        _cleanup()
    print("\n" + "=" * 60)
    if failures:
        print(f"结果:{failures} 项失败,看上面 [失败] 行")
        sys.exit(1)
    print("结果:全部通过 ✓")

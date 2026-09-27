"""M6 服务端集成测试:通过真实 HTTP 验证 SSE 流式 + HITL 跨请求恢复。

前置:服务已在本机 8000 端口运行(run_web.cmd 或 uvicorn 命令)。
运行:.venv\\python scripts\\test_server.py

课程对应:第08章 §2.2(p12-19) HITL 中断 → 决策 → Command(resume=...) 三种决策语义;
         第07章 §8.2.3(p70) 流式 token 输出。

⚠️ 测试隔离(实测踩到的坑):
    旧版三次请求都用固定用户 "webtest",而服务端 thread_id = f"{user_id}-main",
    所以 checkpointer 会把上一轮的会话留着。第二次跑时,模型看到历史里有"重修要交钱吗"
    的问答,于是**直接复述而不调工具**,HITL 也不会触发 —— 断言"应收到 interrupt"就失败了。
    (现象:模型回答"这个问题你前面已经问过几次了,我直接给你结论,不再重复检索")
    这正是 docs/milestones.md M6 踩坑第 3 条说的"评估必须每轮全新 thread_id"。
    因此这里给每次运行生成唯一 user_id,并按需清理测试会话。
"""
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE = "http://127.0.0.1:8000"

# 每次运行一对独立用户 → 独立 thread_id → 独立会话,避免历史污染
RUN_ID = time.strftime("%m%d%H%M%S")
USER = f"webtest-{RUN_ID}"
PASSWORD = "test-pw-12345"


def post_json(path, body, token=None):
    """POST JSON,返回 (status, data)。"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def post_chat(body, token) -> list[dict]:
    """POST /api/chat 并收集全部 SSE 事件。"""
    req = urllib.request.Request(
        BASE + "/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    events = []
    import codecs

    decoder = codecs.getincrementaldecoder("utf-8")()  # 缓冲跨 chunk 的半截多字节字符
    with urllib.request.urlopen(req, timeout=180) as resp:
        buf = ""
        while True:
            chunk = resp.read(1024)
            if not chunk:
                break
            buf += decoder.decode(chunk)
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                if raw.startswith("data: "):
                    events.append(json.loads(raw[6:]))
    return events


def main():
    # Windows 控制台仍可能使用 GBK；模型回答含 emoji 时不要让测试因打印而中断。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    print(f"测试用户(独立会话): {USER}")

    print("\n[0/4] 鉴权:注册 / 登录 / 越权拦截")
    status, _ = post_json("/api/chat", {"message": "hi"})
    assert status == 401, f"无 token 应 401,实际 {status}"
    print("  √ 无 token 请求被 401 拦截")

    status, data = post_json("/api/register", {"username": USER, "password": PASSWORD})
    assert status == 200, f"注册失败: {data}"
    token = data["token"]
    assert data["user_id"] == USER
    print(f"  √ 注册成功并签发 token(前 8 位 {token[:8]}...)")

    status, data = post_json("/api/login", {"username": USER, "password": PASSWORD})
    assert status == 200, f"登录失败: {data}"
    token = data["token"]  # 用登录签发的 token 继续
    print("  √ 登录成功")

    status, _ = post_json("/api/login", {"username": USER, "password": "wrong-pw"})
    assert status == 401, f"错误密码应 401,实际 {status}"
    print("  √ 错误密码被 401 拦截")

    # 越权语义:token 决定身份,请求体无法冒充别人(ChatRequest 已无 user_id 字段)。
    # 只发 user_id 不带 message/resume:既不会被当成身份,也不会被当成输入
    status, data = post_json("/api/chat", {"user_id": "alice"}, token=token)
    assert status == 200 and "error" in data, f"应被当作空请求拒绝: {status} {data}"
    print("  √ 请求体塞 user_id 无法冒充他人(字段已移除)")

    # 成绩由当前登录用户录入；测试账号明确加载演示数据。
    demo_path = Path(__file__).resolve().parents[1] / "data" / "structured" / "seed_grades.json"
    demo = json.loads(demo_path.read_text(encoding="utf-8"))
    for row in demo["records"]:
        request = urllib.request.Request(
            BASE + "/api/me/grades",
            data=json.dumps({"course_id": row["course_id"], "grade_point": row["grade_point"],
                             "letter": row["letter"]}).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
            method="PUT",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200

    print("\n[1/4] 普通问题(RAG 政策检索走 HTTP)")
    ev1 = post_chat({"message": "重修要交钱吗?"}, token)
    tokens = "".join(e.get("text", "") for e in ev1 if e["type"] == "token")
    types1 = [e["type"] for e in ev1]
    print(f"  事件序列: {types1[:3]}...{types1[-1:]}")
    print(f"  回答(前 100 字): {tokens[:100]}")
    assert ev1[-1]["type"] == "done", "应以 done 结束"
    assert ("重修" in tokens) or ("RM" in tokens), "应含重修费用内容"
    assert len([e for e in ev1 if e["type"] == "token"]) > 5, "应是多个 token 增量(流式)"

    print("\n[2/4] HITL:GPA 问题应触发 interrupt 事件并断流")
    ev2 = post_chat({"message": "帮我算一下我的 GPA"}, token)
    intr = [e for e in ev2 if e["type"] == "interrupt"]
    print(f"  事件类型: {[e['type'] for e in ev2][:6]}... 共 {len(ev2)} 个")
    assert intr, "应收到 interrupt 事件"
    print(f"  拦截工具: {intr[0]['tool']} | {intr[0]['description']}")
    print(f"  允许的决策: {intr[0].get('allowed_decisions')}")
    assert intr[0]["tool"] == "calculate_gpa"
    assert not any(e["type"] == "done" for e in ev2), "interrupt 后不应有 done"

    print("\n[3/4] resume 放行 → 拿到最终回答")
    ev3 = post_chat({"resume": True}, token)
    tokens3 = "".join(e.get("text", "") for e in ev3 if e["type"] == "token")
    print(f"  回答(前 100 字): {tokens3[:100]}")
    assert ev3[-1]["type"] == "done", "应以 done 结束"
    assert tokens3.strip(), "放行后应有回答"
    assert "3.6" in tokens3 or "GPA" in tokens3, "应含 GPA 结果"

    print("\n===== 服务端集成测试全部通过 =====")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"[失败] {e}", file=sys.stderr)
        sys.exit(1)

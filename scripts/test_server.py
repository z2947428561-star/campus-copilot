"""M6 服务端集成测试:通过真实 HTTP 验证 SSE 流式 + HITL 跨请求恢复。

前置:服务已在本机 8000 端口运行(run_web.cmd 或 uvicorn 命令)。
运行:.venv\\python scripts\\test_server.py
"""
import json
import sys
import urllib.request


def post_chat(body) -> list[dict]:
    """POST /api/chat 并收集全部 SSE 事件。"""
    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/chat",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
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
    print("[1/3] 普通问题(RAG 政策检索走 HTTP)")
    ev1 = post_chat({"user_id": "webtest", "message": "重修要交钱吗?"})
    tokens = "".join(e.get("text", "") for e in ev1 if e["type"] == "token")
    types1 = [e["type"] for e in ev1]
    print(f"  事件序列: {types1[:3]}...{types1[-1:]}")
    print(f"  回答(前 100 字): {tokens[:100]}")
    assert ev1[-1]["type"] == "done", "应以 done 结束"
    assert ("重修" in tokens) or ("RM" in tokens), "应含重修费用内容"
    assert len([e for e in ev1 if e["type"] == "token"]) > 5, "应是多个 token 增量(流式)"

    print("\n[2/3] HITL:GPA 问题应触发 interrupt 事件并断流")
    ev2 = post_chat({"user_id": "webtest", "message": "帮我算一下我的 GPA"})
    intr = [e for e in ev2 if e["type"] == "interrupt"]
    print(f"  事件类型: {[e['type'] for e in ev2]}")
    assert intr, "应收到 interrupt 事件"
    print(f"  拦截工具: {intr[0]['tool']} | {intr[0]['description']}")
    assert intr[0]["tool"] == "calculate_gpa"
    assert not any(e["type"] == "done" for e in ev2), "interrupt 后不应有 done"

    print("\n[3/3] resume 放行 → 拿到最终回答")
    ev3 = post_chat({"user_id": "webtest", "resume": True})
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

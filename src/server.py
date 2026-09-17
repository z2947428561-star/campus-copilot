"""M6:FastAPI 服务 —— Campus Copilot 的 Web 化与部署形态。

接口设计:
- GET  /            → 聊天页面(static/index.html)
- GET  /api/health  → 健康检查(部署探活用)
- POST /api/chat    → SSE 流式对话,事件类型:
    token      正常输出的文本增量
    interrupt  HITL 高危工具确认(流到此为止,等用户决定)
    done       本轮结束
- 请求体 {"user_id": ..., "message": ...} 或 {"user_id": ..., "resume": true/false}

会话与 HITL 的 Web 化思路(与 CLI 的差异):
- CLI:input() 阻塞等确认;Web:SSE 流在 interrupt 处断开,
  前端弹确认条,用户点按针权再发一次 /api/chat 带 resume 字段。
  这之所以可行,是因为 checkpointer(SQLite/PG)把中断现场存在
  thread_id 上 —— HTTP 无状态,现场不丢。

运行(项目根目录,CMD):
    .venv\\python -m uvicorn src.server:app --host 127.0.0.1 --port 8000
或直接:run_web.cmd(双击)
"""
import json
import logging
import sys
from pathlib import Path

# uvicorn 以项目根为工作目录导入 src.server,此时 src/ 不在 sys.path,
# agent/ tools/ 这些兄弟包会找不到 —— 先把本文件所在目录塞进去
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from langgraph.types import Command

from agent.assistant import get_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

app = FastAPI(title="Campus Copilot", version="1.0.0")
STATIC_DIR = Path(__file__).parent / "static"

# Agent 单例:模型连接、向量库句柄都贵,进程内共享;
# 会话隔离靠 checkpointer 的 thread_id,不靠多实例
_agent = None


def get_web_agent():
    global _agent
    if _agent is None:
        _agent = get_agent(with_middleware=True, with_memory=True)
    return _agent


class ChatRequest(BaseModel):
    user_id: str = "default"
    message: str | None = None  # 新消息(与 resume 二选一)
    resume: bool | None = None   # HITL 决定:true=放行 false=拒绝


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "campus-copilot"}


@app.post("/api/chat")
def chat(req: ChatRequest):
    agent = get_web_agent()
    cfg = {
        "configurable": {
            "thread_id": f"{req.user_id}-main",
            "user_id": req.user_id,
        }
    }

    if req.message is not None:
        inputs = {"messages": [{"role": "user", "content": req.message}]}
    elif req.resume is not None:
        decision = (
            {"type": "approve"}
            if req.resume
            else {"type": "reject", "message": "用户在网页上选择了拒绝执行"}
        )
        inputs = Command(resume={"decisions": [decision]})
    else:
        return {"error": "message 与 resume 必须二选一"}

    def event_stream():
        pending_interrupt = None
        try:
            # 注意:多 stream_mode 产出 (mode, payload),mode 在前
            for mode, data in agent.stream(
                inputs, cfg, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = data
                    if metadata.get("langgraph_node") != "model":
                        continue
                    text = chunk.content
                    if isinstance(text, list):
                        text = "".join(
                            b.get("text", "") for b in text if isinstance(b, dict)
                        )
                    if text:
                        yield _sse({"type": "token", "text": text})
                elif mode == "updates" and data.get("__interrupt__"):
                    pending_interrupt = data["__interrupt__"][0]

            if pending_interrupt is not None:
                req_obj = (
                    pending_interrupt.value
                    if isinstance(pending_interrupt.value, dict)
                    else {}
                )
                actions = req_obj.get("action_requests", [])
                for a in actions:
                    yield _sse(
                        {
                            "type": "interrupt",
                            "tool": a.get("name"),
                            "description": a.get("description", ""),
                            "args": a.get("args", {}),
                        }
                    )
            else:
                yield _sse({"type": "done"})
        except Exception as e:
            logging.exception("chat stream error")
            yield _sse({"type": "error", "message": repr(e)[:200]})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

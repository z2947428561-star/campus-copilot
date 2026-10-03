"""本机 FastAPI 后端 —— 为 Campus Copilot 的 Web 界面提供同源 API。

接口设计:
- GET  /            → 聊天页面(frontend/index.html)
- GET  /api/health  → 本机进程健康检查
- POST /api/chat    → SSE 流式对话,事件类型:
    token      正常输出的文本增量
    interrupt  HITL 高危工具确认(流到此为止,等用户决定)
    done       本轮结束
    error      本轮出错
- 请求体:
    {"message": "..."}            发新消息
    {"resume": true}              放行上次中断(单个动作)
    {"decisions": [{...}, ...]}   完整决策列表(多动作 / edit)
    身份由 Authorization: Bearer token 解析，不从请求体读取。

会话与 HITL 的 Web 化思路(与 CLI 的差异):
- CLI:input() 阻塞等确认;Web:SSE 流在 interrupt 处断开,
  前端弹确认条,用户点按钮后再发一次 /api/chat 带 resume / decisions。
  这之所以可行,是因为 checkpointer 把中断现场存在 thread_id 上
  —— HTTP 无状态,现场不丢(第08章 §2.2 p13)。

本次修订(按课件):
1) 流式消费与中断处理改调 agent.streaming.stream_turn —— 旧版在 5 个文件里
   各写一份(第07章 §9.3 p80-81 建议封装)。
2) 用户身份改用 context=UserContext(...)(第09章 §4.2 p74-80),
   不再只从 configurable 掏 user_id。
3) 中断事件的 SSE 载荷补上 allowed_decisions 与动作总数
   (第08章 §2.2 p16-17 的 review_configs),前端才能按动作渲染按钮。
4) 支持多动作决策与 edit(第08章 §2.2 p12-18);旧版固定只发 1 个 decision,
   一旦有第二个受保护工具就会数量错配。
5) cfg 走 agent.runtime.make_config —— 带上 recursion_limit(第07章 §4.4 p26)
   与 LangSmith 的 run_name / tags / metadata(第02章 §6.4 p62-65、第03章 §3 p7-8)。

运行(项目根目录,CMD):
    .venv\\python -m uvicorn src.server:app --host 127.0.0.1 --port 8000
或直接:run_web.cmd(双击)
"""
import json
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# uvicorn 以项目根为工作目录导入 src.server,此时 src/ 不在 sys.path,
# agent/ tools/ 等兄弟包会找不到 —— 先把本文件所在目录塞进去
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from pydantic import BaseModel, Field

import auth
from agent.assistant import get_agent
from agent.memory import close_memory
from agent.runtime import default_thread_id, make_config, setup_langsmith
from agent.streaming import stream_turn
from context import UserContext
from student_data import (
    delete_course, delete_grade, init_student_data, list_courses, list_grades,
    set_course, set_grade,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

# 第03章 §2.3(p6):LangSmith 四个环境变量必须在创建 agent 之前就位
setup_langsmith()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """启动建鉴权表;退出释放 checkpointer / store 的连接(优雅停机)。"""
    auth.init_auth()
    init_student_data()
    yield
    close_memory()


app = FastAPI(title="Campus Copilot", version="1.0.0", lifespan=lifespan)
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="frontend-assets")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path == "/" or request.url.path.startswith(("/api/", "/assets/")):
        response.headers["Cache-Control"] = "no-store"
    return response

# Agent 单例:模型连接、向量库句柄都贵,进程内共享;
# 会话隔离靠 checkpointer 的 thread_id,不靠多实例
_agent = None


def get_web_agent():
    global _agent
    if _agent is None:
        _agent = get_agent(with_middleware=True, with_memory=True)
    return _agent


class ChatRequest(BaseModel):
    # ⚠️ 不再有 user_id 字段:身份只能从 Bearer token 解析,
    # 请求体自报身份就是水平越权入口(见 auth.py  docstring)
    message: str | None = Field(default=None, max_length=4000)  # 限制单次模型输入成本
    resume: bool | None = None          # 单个动作的放行/拒绝(true/false)
    decisions: list[dict] | None = None # 完整决策列表(多动作 / edit 时用)


class AuthRequest(BaseModel):
    username: str = Field(max_length=32)
    password: str = Field(max_length=128)


class GradeRequest(BaseModel):
    course_id: str
    grade_point: float = Field(ge=0, le=4, allow_inf_nan=False)
    letter: str = Field(min_length=1, max_length=8)


class CourseRequest(BaseModel):
    course_id: str


def current_user(authorization: str = Header(default="")) -> str:
    """FastAPI 依赖:从 Authorization: Bearer <token> 解析用户身份。"""
    token = authorization.removeprefix("Bearer ").strip()
    username = auth.authenticate(token)
    if username is None:
        raise HTTPException(status_code=401, detail="未登录或登录已过期")
    return username


@app.post("/api/register")
def register(req: AuthRequest):
    try:
        token = auth.register(req.username, req.password)
    except auth.AuthError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"token": token, "user_id": req.username.strip()}


@app.post("/api/login")
def login(req: AuthRequest):
    try:
        token = auth.login(req.username, req.password)
    except auth.AuthRateLimit as e:
        raise HTTPException(status_code=429, detail=str(e), headers={"Retry-After": str(auth.config.LOGIN_FAILURE_WINDOW_SECONDS)}) from e
    except auth.AuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return {"token": token, "user_id": req.username.strip()}


@app.post("/api/logout")
def logout(authorization: str = Header(default="")):
    auth.revoke(authorization.removeprefix("Bearer ").strip())
    return {"ok": True}


@app.get("/api/me/grades")
def my_grades(user_id: str = Depends(current_user)):
    return {"grades": list_grades(user_id)}


@app.put("/api/me/grades")
def save_my_grade(req: GradeRequest, user_id: str = Depends(current_user)):
    try:
        return set_grade(user_id, req.course_id, req.grade_point, req.letter)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/me/grades/{course_id}")
def remove_my_grade(course_id: str, user_id: str = Depends(current_user)):
    delete_grade(user_id, course_id)
    return {"ok": True}


@app.get("/api/me/courses")
def my_courses(user_id: str = Depends(current_user)):
    return {"courses": list_courses(user_id)}


@app.put("/api/me/courses")
def save_my_course(req: CourseRequest, user_id: str = Depends(current_user)):
    try:
        return set_course(user_id, req.course_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/me/courses/{course_id}")
def remove_my_course(course_id: str, user_id: str = Depends(current_user)):
    delete_course(user_id, course_id)
    return {"ok": True}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "campus-copilot"}


def _build_inputs(req: ChatRequest):
    """把请求体翻译成 agent 的输入(第04章 §1.6.1 p16)。"""
    if req.message is not None:
        from messages import user_turn

        return user_turn(req.message)
    if req.decisions is not None:
        # 前端直接给完整决策列表(多动作 / edit)
        return Command(resume={"decisions": req.decisions})
    if req.resume is not None:
        decision = (
            {"type": "approve"}
            if req.resume
            else {"type": "reject", "message": "用户在网页上选择了拒绝执行"}
        )
        return Command(resume={"decisions": [decision]})
    return None


@app.post("/api/chat")
def chat(req: ChatRequest, user_id: str = Depends(current_user)):
    agent = get_web_agent()
    thread_id = default_thread_id(user_id)
    cfg = make_config(
        thread_id=thread_id,
        user_id=user_id,
        run_name=f"campus-chat:{user_id}",
        tags=["campus-copilot", "web"],
    )
    user_context = UserContext(user_id=user_id)

    inputs = _build_inputs(req)
    if inputs is None:
        return {"error": "message 与 resume / decisions 必须提供其中之一"}

    def event_stream():
        # 真流式:旧版把事件攒在 emitted 列表里、stream_turn 跑完才一次性 yield,
        # 长回答期间连接上几十秒没有字节,容易被浏览器/中间代理判超时断连
        # (前端就表现为"[连接失败]")。改为队列 + 工作线程,事件边产生边发。
        import queue
        import threading

        q: queue.Queue = queue.Queue()
        _DONE = object()  # 正常结束哨兵

        def on_decide(info):
            for i, action in enumerate(info.action_requests):
                q.put(
                    {
                        "type": "interrupt",
                        "tool": action.get("name"),
                        "description": action.get("description", ""),
                        "args": action.get("args", {}),
                        # 第08章 §2.2 p16-17:每个动作允许的决策集合,前端据此渲染按钮
                        "allowed_decisions": info.allowed_decisions(i),
                        "index": i,
                        "total": len(info),
                        # 多动作时前端需要按顺序回传同样数量的 decisions
                        "requires_all": len(info) > 1,
                    }
                )
            # Web 端 HITL 是"发完 interrupt 就断流",由前端下一次请求恢复,
            # 返回 None 让 stream_turn 立即收束本轮
            return None

        def on_token(text: str):
            q.put({"type": "token", "text": text})

        def run_turn():
            try:
                stream_turn(
                    agent,
                    inputs,
                    cfg,
                    on_decide=on_decide,
                    on_token=on_token,
                    context=user_context,
                )
                q.put(_DONE)
            except Exception as e:  # noqa: BLE001
                logging.exception("chat stream error")
                q.put(e)

        threading.Thread(target=run_turn, daemon=True).start()

        saw_interrupt = False
        while True:
            item = q.get()
            if item is _DONE:
                break
            if isinstance(item, Exception):
                # 详细异常只写服务端日志，避免 API key、数据库地址等泄漏给浏览器。
                yield _sse({"type": "error", "message": "服务暂时不可用，请稍后再试"})
                return
            saw_interrupt = saw_interrupt or item["type"] == "interrupt"
            yield _sse(item)
        # 有中断时不发 done(等用户决定);没有中断则正常收尾
        if not saw_interrupt:
            yield _sse({"type": "done"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

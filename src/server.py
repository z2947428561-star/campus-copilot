"""本机 FastAPI 后端 —— 为 Campus Copilot 的 Web 界面提供同源 API。

接口设计:
- GET  /            → 聊天页面(frontend/index.html)
- GET  /api/health  → 本机进程健康检查
- GET/POST /api/conversations → 列出/新建当前用户的会话
- GET /api/conversations/{id} → 历史、待确认状态、执行状态与额度
- POST /api/chat    → SSE 流式对话,事件类型:
    token      正常输出的文本增量
    interrupt  HITL 高危工具确认(流到此为止,等用户决定)
    done       本轮结束
    error      本轮出错
    limit      调用或推理步数达到上限
- 请求体:
    {"message": "..."}            发新消息
    {"resume": true}              放行上次中断(单个动作)
    {"decisions": [{...}, ...]}   完整决策列表(多动作 / edit)
    身份由 Authorization: Bearer token 解析，不从请求体读取。
    conversation_id 省略时兼容原有会话；确认恢复必须携带 checkpoint_id。

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
import threading
from contextlib import asynccontextmanager
from pathlib import Path

# uvicorn 以项目根为工作目录导入 src.server,此时 src/ 不在 sys.path,
# agent/ tools/ 等兄弟包会找不到 —— 先把本文件所在目录塞进去
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command
from langgraph.errors import GraphRecursionError
from pydantic import BaseModel, Field, model_validator

import auth
from agent.assistant import get_agent
from agent.conversation_state import conversation_state
from agent.memory import close_memory
from agent.runtime import make_config, setup_langsmith
from agent.streaming import stream_turn
from agent.web_runs import EventStream, RunRegistry
from context import UserContext
import conversations
import database_browser
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
    conversations.init_conversations()
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
    if request.url.path in {"/", "/database"} or request.url.path.startswith(("/api/", "/assets/")):
        response.headers["Cache-Control"] = "no-store"
    return response

# Agent 单例:模型连接、向量库句柄都贵,进程内共享;
# 会话隔离靠 checkpointer 的 thread_id,不靠多实例
_agent = None
_agent_lock = threading.Lock()
_runs = RunRegistry()


def get_web_agent():
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = get_agent(with_middleware=True, with_memory=True)
    return _agent


class ChatRequest(BaseModel):
    # ⚠️ 不再有 user_id 字段:身份只能从 Bearer token 解析,
    # 请求体自报身份就是水平越权入口(见 auth.py  docstring)
    message: str | None = Field(default=None, max_length=4000)  # 限制单次模型输入成本
    resume: bool | None = None          # 单个动作的放行/拒绝(true/false)
    decisions: list[dict] | None = None # 完整决策列表(多动作 / edit 时用)
    conversation_id: str = Field(default="main", min_length=1, max_length=64)
    checkpoint_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def one_operation(self):
        if sum(value is not None for value in (self.message, self.resume, self.decisions)) != 1:
            raise ValueError("message、resume、decisions 必须且只能提供一项")
        if self.message is not None and not self.message.strip():
            raise ValueError("消息不能为空")
        return self


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


def owned_conversation(user_id: str, conversation_id: str):
    try:
        return conversations.get_conversation(user_id, conversation_id)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="会话不存在") from e


@app.get("/api/conversations")
def conversation_list(user_id: str = Depends(current_user)):
    return {"conversations": conversations.list_conversations(user_id)}


@app.post("/api/conversations")
def conversation_create(user_id: str = Depends(current_user)):
    return conversations.create_conversation(user_id)


def conversation_config(user_id, conversation_id):
    return make_config(
        thread_id=conversations.thread_id_for(user_id, conversation_id),
        user_id=user_id, run_name=f"campus-chat:{user_id}", tags=["campus-copilot", "web"],
    )


@app.get("/api/conversations/{conversation_id}")
def conversation_detail(conversation_id: str, user_id: str = Depends(current_user)):
    item = owned_conversation(user_id, conversation_id)
    agent = get_web_agent()
    cfg = conversation_config(user_id, conversation_id)
    state, running = _runs.snapshot(
        cfg["configurable"]["thread_id"], lambda: conversation_state(agent, cfg))
    return {**item, **state, "running": running}


def validate_operation(req, state):
    pending = state["pending"]
    if req.message is not None:
        if pending:
            raise HTTPException(status_code=409, detail="请先处理待确认操作，或新建会话")
        return
    if not pending:
        raise HTTPException(status_code=409, detail="当前没有待确认操作，请刷新会话")
    if not req.checkpoint_id or req.checkpoint_id != state["checkpoint_id"]:
        raise HTTPException(status_code=409, detail="确认状态已改变，请刷新会话后重新决定")
    decisions = req.decisions if req.decisions is not None else [
        {"type": "approve" if req.resume else "reject"}]
    if len(decisions) != len(pending):
        raise HTTPException(status_code=422, detail="决定数量必须与待确认动作数量一致")
    for decision, action in zip(decisions, pending):
        if decision.get("type") not in action["allowed_decisions"]:
            raise HTTPException(status_code=422, detail="该动作不允许此决定")
        if decision["type"] == "edit":
            edited = decision.get("edited_action", {})
            if (not isinstance(edited, dict) or edited.get("name") != action["tool"]
                    or not isinstance(edited.get("args"), dict)):
                raise HTTPException(status_code=422, detail="修改必须保留工具名并提供参数对象")


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/database")
def database_page():
    return FileResponse(FRONTEND_DIR / "database.html")


@app.get("/api/database")
def database_catalog(user_id: str = Depends(current_user)):
    return database_browser.catalog(user_id)


@app.get("/api/database/{source}/{table}")
def database_table(source: str, table: str, user_id: str = Depends(current_user),
                   q: str = Query(default="", max_length=120), page: int = Query(default=1, ge=1, le=10000),
                   page_size: int = Query(default=25, ge=1, le=100),
                   sort: str = Query(default="", max_length=64), direction: str = Query(default="asc", pattern="^(asc|desc)$")):
    try:
        return database_browser.table_page(source, table, user_id, q=q, page=page,
                                            page_size=page_size, sort=sort, direction=direction)
    except database_browser.MissingTable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except database_browser.StoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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
    owned_conversation(user_id, req.conversation_id)
    cfg = conversation_config(user_id, req.conversation_id)
    thread_id = cfg["configurable"]["thread_id"]
    if not _runs.claim(thread_id):
        raise HTTPException(status_code=409, detail="该会话正在处理请求，请稍后刷新，或新建会话")
    try:
        agent = get_web_agent()
        state = conversation_state(agent, cfg)
        validate_operation(req, state)
        if req.message is not None and state["exhausted"]:
            raise HTTPException(status_code=429, detail="当前会话额度已用完，请新建会话；原记录仍保留")
        inputs = _build_inputs(req)
        if req.message:
            conversations.name_conversation(user_id, req.conversation_id, req.message)
    except BaseException:
        _runs.release(thread_id)
        raise

    delivery = EventStream()

    def run_turn():
        saw_interrupt = False

        def on_decide(info):
            nonlocal saw_interrupt
            saw_interrupt = True
            checkpoint_id = conversation_state(agent, cfg)["checkpoint_id"]
            for index, action in enumerate(info.action_requests):
                delivery.publish({
                    "type": "interrupt", "tool": action.get("name"),
                    "description": action.get("description", ""), "args": action.get("args", {}),
                    "allowed_decisions": info.allowed_decisions(index),
                    "index": index, "total": len(info), "requires_all": len(info) > 1,
                    "checkpoint_id": checkpoint_id,
                })
            return None

        try:
            stream_turn(
                agent, inputs, cfg, on_decide=on_decide,
                on_token=lambda text: delivery.publish({"type": "token", "text": text}),
                on_limit=lambda kind: delivery.publish({
                    "type": "limit", "kind": kind,
                    "message": "已达到调用上限，请简化问题重试；会话额度耗尽时请新建会话。",
                }),
                context=UserContext(user_id=user_id),
            )
            final_state = conversation_state(agent, cfg)
            if not saw_interrupt:
                delivery.publish({"type": "done", "exhausted": final_state["exhausted"],
                                  "usage": final_state["usage"]})
        except GraphRecursionError:
            delivery.publish({"type": "limit", "kind": "steps",
                              "message": "本轮推理步数已达上限，请新建会话并简化问题。"})
        except Exception:
            logging.exception("chat stream error")
            delivery.publish({"type": "error", "message": "服务暂时不可用，请稍后刷新会话再试"})
        finally:
            # The worker retains ownership even when the browser disconnects.
            _runs.release(thread_id)
            delivery.finish()

    async def event_stream():
        events = delivery.events()
        try:
            async for event in events:
                yield ": keep-alive\n\n" if event is None else _sse(event)
        finally:
            await events.aclose()

    try:
        threading.Thread(target=run_turn, daemon=True).start()
    except BaseException:
        _runs.release(thread_id)
        raise
    return StreamingResponse(
        event_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

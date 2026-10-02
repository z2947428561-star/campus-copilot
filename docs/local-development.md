# 本地开发与验证

## 环境与首次启动

使用 Python 3.13，从项目根目录运行命令。首先参考 [README 快速开始](../README.md#快速开始)创建环境并复制 `.env.example`。应用只在本机 Python 环境运行；Docker 仅在使用容器化本机数据库时需要。

| 环境 | Python 路径 | 说明 |
| --- | --- | --- |
| Windows 标准 venv | `.venv\Scripts\python.exe` | `python -m venv .venv` 创建 |
| Windows Conda 前缀环境 | `.venv\python.exe` | 现有 `run_*.cmd` 使用此布局 |
| macOS / Linux venv | `.venv/bin/python` | 激活后可直接运行 `python` |

PowerShell 不允许执行激活脚本时，可以直接用 `.\.venv\Scripts\python.exe -m pip ...` 或 `-m uvicorn ...`，不必修改系统执行策略。不要在已有 Conda `.venv` 上再次运行 `python -m venv .venv`。

最低配置分两层：

- 页面、注册和个人数据 API：Python 依赖、公共种子库，`MEMORY_BACKEND=sqlite`。
- 完整问答：有效对话模型配置；政策问答另外需要 Embedding 配置和已构建的向量库。

`.env` 默认优先于进程环境变量；`CAMPUS_ENV_OVERRIDE=0` 切换为环境变量优先，`CAMPUS_SKIP_DOTENV=1` 完全跳过 `.env`。这些开关必须在导入配置前设置。

## 选择存储路径

轻量本地运行：

```dotenv
MEMORY_BACKEND=sqlite
KB_BACKEND=chroma
LANGSMITH_TRACING=false
LLM_FALLBACK_PROVIDER=none
```

已有本机 PostgreSQL 和 Milvus 时，在 `.env` 中设置：

```dotenv
MEMORY_BACKEND=postgres
DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/<database>
KB_BACKEND=milvus
MILVUS_URI=http://127.0.0.1:19530
```

数据库需要先存在，账号/个人数据表在应用启动时创建，Agent 记忆表按需初始化。URL 中凭据需按连接字符串规则编码；不要把真实连接串复制到 Issue。

连接已有本机 PostgreSQL / Milvus 即可，不需要重新创建应用容器。容器化数据库的端口应仅映射到 `127.0.0.1`；已有环境的绑定说明见[本机基础设施](../ops/README.md)。`ops/milvus-local-ports.yml` 是已有 Milvus 编排的覆盖文件，不是独立启动配置。项目不再提供根目录的整套应用 Compose 编排。

改变 `MEMORY_BACKEND` / `DATABASE_URL` 不会自动迁移用户，更换 Embedding 模型后应重新建索引。请保持建库与查询的模型、维度和存储配置一致。

## 初始化与运行

```bash
python -m pip install -r requirements.txt
python scripts/init_db.py
python scripts/build_kb.py
python -m uvicorn src.server:app --host 127.0.0.1 --port 8000
```

这是新克隆的初始化顺序。`init_db.py` 会删除并重建 `data/campus.db` 中的公共表；`build_kb.py` 会重建当前配置指向的向量集合。两者都应在确认目标和保留必要数据后运行，日常启动无需重复执行。

浏览器访问 [本机页面](http://127.0.0.1:8000/)，API 文档位于 [Swagger UI](http://127.0.0.1:8000/docs)。`/api/health` 只证明 Web 进程可响应，不检查模型额度、向量库可用性或回答质量。

注册成功后，在“个人数据”录入自己的课程与成绩。当前个人数据学期由 `src/student_data.py` 中的 `SEMESTER` 决定。GPA 分析需要先录入成绩并批准页面上的确认操作。

## 测试与评估

### 离线回归检查

```bash
python scripts/check_offline.py
```

该命令只复制 `src/`、`scripts/` 和公开种子/政策文件到临时目录，不复制 `.env`、个人数据库或向量目录。先在副本中建公共种子库，再以独立进程运行六个离线测试文件，结束后清理临时目录。依赖需事先安装。

它覆盖账号规则、登录限流、个人数据隔离、API 错误边界、密码重置和 Chroma 重建。不会调用模型 API，也不需要 PostgreSQL / Milvus 服务。GitHub Actions 仅运行这些代码检查，不执行部署。

### 真实服务集成验证

`test_m3.py`、`test_m4.py`、`test_m5.py`、`test_server.py`、`eval_m6.py` 不包含在离线检查中。它们可能调用收费 API、访问配置的数据库/索引、创建测试账号或更新评估报告。

- `test_m3.py`：中间件与确认流程。
- `test_m4.py`：持久化和用户隔离；使用 `TEST_MEMORY_BACKEND`、`TEST_DATABASE_URL` 配置专用测试库。
- `test_m5.py`：当前配置的向量库和 Embedding 真实检索。
- `test_server.py`：向 `127.0.0.1:8000` 的真实服务注册测试账号并检查 SSE/HITL；仅针对隔离测试服务运行。
- `eval_m6.py`：固定 32 问跑批，写入 `docs/eval-results.md`；运行前核对测试数据库配置、API 额度和种子日期适用范围。

当前脚本含历史默认测试库连接参数，请先阅读各脚本开头的环境变量处理，再运行在线测试。离线 CI 通过不能替代这些集成验证。

## 常见问题

| 现象 | 排查顺序 |
| --- | --- |
| `ModuleNotFoundError` | 检查 `python` 指向项目环境，再用同一解释器安装依赖 |
| 登录页网络错误 | 确认访问 `http://127.0.0.1:8000/`，检查服务终端与 `/api/health` |
| 页面还是旧版 | 刷新标签页；首页响应设置了 `Cache-Control: no-store`，已打开的 DOM 仍需刷新 |
| 用户名或密码错误 | 确认数据库配置未变化、账号已注册、输入正确；忘记密码时见下方本机维护命令 |
| 登录请求返回 429 | 达到该用户名的进程内限流，等待配置的窗口结束后重试 |
| 政策检索不可用 | 核对 Embedding 配置、服务额度、向量服务和索引是否已建立 |
| 查询个人成绩为空 | 新注册账号没有种子成绩，先在“个人数据”录入 |
| 同一问题的历史评估不再通过 | 检查模型变化、知识库版本、种子日期、会话隔离和配置差异 |

本机已有账号忘记密码时，使用当前项目环境：

```bash
python scripts/reset_local_password.py
```

该维护工具直接使用当前配置的数据库。先确认目标是自己的本地库；输入用户名两次确认后，再输入两次新密码。密码输入不会回显字符，重置后旧 token 失效。它不是网页上的自助找回密码功能。

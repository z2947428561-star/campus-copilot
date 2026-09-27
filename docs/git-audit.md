# Git 提交范围审计（2026-09-27）

基准：`4b3b72a` 之后的未提交工作区。这里判断的是**是否属于可版本化的项目内容**，
不把 32/32 自建评估解释成真实用户准确率，也不把本机 HTTPS 演练解释成公网部署。
“提交”表示已检查用途并纳入本轮提交；“停止跟踪”只改 Git 索引，不删除磁盘文件。

| 文件 | 决定 | 审核依据 |
|---|---|---|
| `.dockerignore` | 提交 | 排除本机数据库和构建临时文件 |
| `.env.example` | 提交 | 仅占位配置；真实 `.env` 继续忽略 |
| `.gitignore` | 提交 | 忽略凭据、向量库、备份和 `.workbuddy/` |
| `Dockerfile` | 提交 | 安装依赖并从种子数据构建 SQLite |
| `docker-compose.yml` | 提交 | app/PG/Milvus/Caddy 编排与持久化卷 |
| `Caddyfile` | 提交 | 可选正式部署的反向代理配置 |
| `requirements.txt` | 提交 | 本轮模块和容器构建所需依赖 |
| `README.md` | 提交 | 本机运行方式与验证口径 |
| `data/memory.db-shm` | 停止跟踪 | SQLite 运行时共享内存文件；磁盘原件保留 |
| `data/memory.db-wal` | 停止跟踪 | SQLite 运行时日志；磁盘原件保留 |
| `docs/data-plan.md` | 提交 | 数据策略；已修正“建库待写/增量重建”旧描述 |
| `docs/eval-results.md` | 提交 | 32 题真实跑批记录，注明自建断言口径 |
| `docs/milestones.md` | 提交 | 历史进度与最新本机验证记录 |
| `docs/resume.md` | 提交 | 项目素材；已将旧 31 题/8 工具数字更新 |
| `docs/course-map.md` | 提交 | 课件映射；已修正 Milvus/PG/路由旧状态 |
| `docs/deploy.md` | 提交 | 部署步骤、验收与备份恢复说明 |
| `scripts/collect_docs.py` → `scripts/archive_docs.py` | 提交重命名 | 实际是离线快照写入器，不应叫网络采集 |
| `scripts/build_kb.py` | 提交 | 知识库建库与删除前 Embedding 自检 |
| `scripts/eval_m6.py` | 提交 | 隔离用户/会话的 32 题评估器 |
| `scripts/eval_set.json` | 提交 | 与评估器配套的版本化题集 |
| `scripts/test_m3.py` | 提交 | 中间件验收；Windows 输出兼容已修 |
| `scripts/test_m4.py` | 提交 | 专用测试库验证多用户记忆 |
| `scripts/test_m5.py` | 提交 | Milvus/Embedding/RAG 检索与引用验收 |
| `scripts/test_server.py` | 提交 | Web SSE/HITL HTTP 集成测试 |
| `scripts/backup_postgres.sh` | 提交 | PostgreSQL 可恢复备份脚本 |
| `scripts/preflight.py` | 提交 | 不泄露密钥的正式部署配置检查 |
| `scripts/test_auth_rate_limit.py` | 提交 | 登录限流回归测试 |
| `scripts/test_chroma_rebuild.py` | 提交 | 防 Chroma 重建重复片段 |
| `scripts/test_preflight.py` | 提交 | 配置预检单元测试 |
| `scripts/test_server_security.py` | 提交 | API 长度、响应头和错误脱敏测试 |
| `scripts/test_student_data.py` | 提交 | 成绩/选课用户隔离测试 |
| `src/agent/assistant.py` | 提交 | Agent 组装、提示词与工具配置 |
| `src/agent/memory.py` | 提交 | SQLite/PG Checkpointer 与 Store 生命周期 |
| `src/agent/middleware.py` | 提交 | PII、限额、路由、HITL 与审计中间件 |
| `src/agent/runtime.py` | 提交 | 会话 config 和追踪初始化 |
| `src/agent/streaming.py` | 提交 | CLI/Web 共用流式与 HITL 逻辑 |
| `src/chat_agent_cli.py` | 提交 | 基础 Agent 命令行入口 |
| `src/chat_agent_mw_cli.py` | 提交 | 中间件版命令行入口 |
| `src/chat_memory_cli.py` | 提交 | 记忆版命令行入口 |
| `src/model.py` | 提交 | 主模型、独立备胎及本地 Ollama 选择 |
| `src/prompt.py` | 提交 | 兼容旧入口的提示词接口 |
| `src/messages.py` | 提交 | 共用消息构造 |
| `src/prompts/__init__.py` | 提交 | 提示词包导出 |
| `src/prompts/common.py` | 提交 | 共用纪律与措辞 |
| `src/prompts/discipline.py` | 提交 | 场景行为约束 |
| `src/prompts/system.py` | 提交 | 分阶段系统提示词 |
| `src/server.py` | 提交 | 鉴权 API、个人数据与 SSE Web 服务 |
| `src/static/index.html` | 提交 | Web 聊天与个人数据界面 |
| `src/auth.py` | 提交 | 注册、登录、token 与限流 |
| `src/bootstrap.py` | 提交 | 入口初始化 |
| `src/config.py` | 提交 | 集中配置与环境覆盖规则 |
| `src/context.py` | 提交 | 用户身份上下文 |
| `src/kb.py` | 提交 | Milvus/Chroma 后端与 Embedding 入口 |
| `src/student_data.py` | 提交 | 按用户隔离的课程/成绩存储 |
| `src/tools/__init__.py` | 提交 | 9 个工具及场景分组 |
| `src/tools/academic.py` | 提交 | 教学周查询 |
| `src/tools/courses.py` | 提交 | 课程与先修关系查询 |
| `src/tools/gpa.py` | 提交 | 仅根据当前用户成绩计算 GPA |
| `src/tools/policy.py` | 提交 | 政策 RAG 与来源引用 |
| `src/tools/profile.py` | 提交 | 当前用户长期画像读写 |
| `src/tools/timetable.py` | 提交 | 教室、课程和本人课表查询 |
| `src/tools/schemas.py` | 提交 | 工具参数模型 |

不纳入提交：`.env`（真实密钥）、`.workbuddy/`（本地工作记录）、
`backups/`、`data/chroma_db/`、`*.db` 等运行数据。两个 WAL 文件虽从当前
版本停止跟踪，旧 Git 历史仍保留曾提交过的内容；若其中含真实个人数据，
需要另行评估历史清理与密钥轮换，不能把本次停止跟踪当作历史擦除。

本轮核验：M3/M4/M5、个人数据隔离、登录限流、API 安全、Chroma 重建、
预检测试通过；`compileall`、`git diff --check`、Compose config 通过。
最新完整 32 题评估记录见 `docs/eval-results.md`（2026-09-26）。

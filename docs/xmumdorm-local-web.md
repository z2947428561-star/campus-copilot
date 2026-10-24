# XMUMDorm Web 本地接入

本地已接通 Dorm 登录、政策与指南问答、会话历史，以及个人课表、待办和共享“放假日”的只读查询。订单尚未接入。查询配置与使用见 [课表、待办与放假日](dorm-personal-data.md)。

校园助手入口现位于左侧导航首位、“万能墙”上方，使用 `/agent`；“我的 → 工具”已移除该入口。旧 `/myzone/agent` 链接自动跳转，登录返回及原有聊天记录正常保留。

## 启动

先准备两个项目的既有依赖、Dorm 本地 MySQL 与已迁移的本地账号库，以及 Campus 对话模型 / Embedding / 知识索引配置。在 Campus 项目根运行：

```powershell
.\run_dorm_web.cmd
# 使用 Dorm 已有数据库配置登录真实账号，并复用本地政策/指南知识库：
.\run_dorm_web.cmd --existing-database --local-kb
# 自定义 Dorm 路径或本地 MySQL 端口：
.\.venv\python.exe scripts\run_dorm_web.py --dorm 'C:\path\XMUMDorm-2.0.0-LYZZ' --db-port 3306
```

启动器仅绑定 `127.0.0.1`，使用 8001（Agent）、4040（Dorm）、5173（Web）。端口被占用时先报错，不结束其他进程。它为本次运行生成随机内部凭证密钥，仅通过子进程环境共享，无须修改两边 `.env`。Ctrl+C 关闭本次启动的三个进程。

打开 <http://127.0.0.1:5173/myzone/agent>，使用 Dorm 本地账号登录。也可从“我的 → 工具 → 校园助手”进入。访客可以看到登录提示；接口仍独立校验登录和账号状态。

启动器强制使用本机 MySQL，忽略云数据库连接串；本地数据库名、用户和密码由 Dorm 原有配置填充。不会运行数据库迁移或创建账号。Agent 对话存储独立放在 `data/local/xmumdorm/memory.db`。现有模型与知识索引沿用 Campus 配置，模型和 Embedding 仍可能调用外部服务。

上述本机数据库限制适用于默认模式。显式传入 `--existing-database` 时改用 Dorm 本机已有 `.env`/进程中的数据库配置，不改写凭据、不运行迁移或创建账号，后台任务保持关闭。真实账号登录页为 `http://127.0.0.1:5173/login`，正式身份的本地聊天存储与测试身份使用的 `live-memory.db` 分开。

## 接口与身份

Dorm 只代理四个接口：会话列表、新建、详情，以及聊天。路径为 `/api/agent/conversations`、`/api/agent/conversations/:id`、`/api/agent/chat`。普通响应包装为 Dorm 的 `{status:0,data}`，聊天使用 SSE。

Express 验证现有 JWT 和账户状态后签发 60 秒内部断言，接收方固定为 `campus-copilot`，用户映射为 `xmumdorm:<users.id>`。Python 只在 `/internal/xmumdorm/*` 接受该断言；它不能用于本地账号、成绩管理或数据库浏览接口。两边分别配置 `CAMPUS_AGENT_SHARED_SECRET`（至少 32 字符），Express 的 `CAMPUS_AGENT_URL` 默认为 `http://127.0.0.1:8001`。推荐使用启动器统一设置。

Agent 使用独立提示词和仅含 `search_policy` 的工具集合。官方来源门槛保持原有规则。历史记录按用户隔离，没有把独立 Campus 用户与 Dorm 用户自动合并。

## 运行行为

- 流断开仅停止接收，后台推理可能继续。页面会读取会话状态，不自动重新发送问题。
- 点击“稍后查看”断开接收；刷新可恢复历史，后台执行时每 1.5 秒查询状态。
- 同会话执行互斥保留。Gateway 本地每用户每分钟最多 20 次聊天请求，同时最多 2 个转发请求、全局 8 个；这些不是按日费用预算，断线后台计算也不由转发计数追踪。
- 保持单 Python 进程。本轮不提供多实例协调。

## 验证

```powershell
.\.venv\python.exe scripts\test_dorm_integration.py
.\.venv\python.exe scripts\check_offline.py
# 在 Dorm 根目录：
npm test -- --runInBand
npm run build:web
```

浏览器联调应覆盖：访客提示、两个账号隔离、中文分块、刷新历史、新建切换、断线恢复、不可用服务与过期身份。离线测试和模拟模型不证明真实政策回答质量；真实模型与本地 MySQL 的验证需单独记录。

## 首轮 Web 接入执行记录（2026-10-23）

| 检查 | 结果 |
| --- | --- |
| Dorm 新增接口/流解析专项 | 2 个套件、15 项通过，退出码 0 |
| Dorm 完整 Jest 回归 | `npm test -- --runInBand --silent`：66 个套件、951 项通过，退出码 0 |
| Web 构建 | `npm run build:web` 通过，退出码 0；保留既有 Shop 混合静态/动态导入警告 |
| 新页面 ESLint | 无错误，退出码 0 |
| Agent 身份/会话专项 | 临时账号库与假模型验证通过，退出码 0 |
| Agent 完整离线回归 | `scripts/check_offline.py`：20 个检查文件全部通过，退出码 0 |
| 浏览器 | 真实构建页 → Express → FastAPI，全链路使用虚构账号和假模型；访客、流式、新建/切换/恢复、账户隔离、确认取消、断线恢复、手机布局和服务不可用均通过，无页面脚本异常 |

首次并行全量测试中既有商城图片测试出现一次 5 秒超时；该套件单独重跑 99 项通过，随后完整回归 951 项全部通过，未修改商城代码。浏览器注入服务不可用时会产生预期的 HTTP 503 控制台记录，不是页面脚本异常。

浏览器复验：先在 Dorm 运行构建，再从 Campus 运行 `python scripts/run_dorm_web_test.py`，然后执行 `playwright-cli -s=dorm-agent-local open http://127.0.0.1:18766/myzone/agent` 与 `playwright-cli -s=dorm-agent-local run-code --filename=scripts/test_dorm_web.js`。测试使用 18765/18766，虚构账号和临时数据，不加载真实 Dorm `.env` 或调用模型 API。截图位于 Campus `.playwright-cli/dorm-agent-desktop.png` 和 `dorm-agent-mobile.png`。

首轮验收未连接真实 Dorm MySQL 或模型服务，没有运行迁移、索引构建或部署。用户已有 App、设计令牌及 Campus 采集相关工作保留；修改留在本地工作区，没有提交或推送。

## 真实模型与知识检索联调（2026-10-23）

用户选择暂不准备 MySQL，先验证真实模型和知识检索。本轮使用固定的本地测试身份；Dorm 账号检查是测试替身，模型、Embedding、知识索引与 Agent 会话存储均实际执行。

1. 真实对话模型连通性检查通过，用时约 9 秒。
2. 旧 Chroma 的 48 个片段缺少 `source_type` 等字段，不能通过当前政策证据门槛。原索引保留。
3. 使用现有 16 份公开政策快照，在 `data/local/xmumdorm/chroma` 构建 106 个片段；以独立 `kb_releases.db` 管理发布。重修、考勤、成绩复查三个候选召回检查全部通过，再发布到该隔离配置。
4. 真实 Agent 问答检查通过：SSE 完成、执行政策工具、召回考勤依据、引用 ID 对应真实证据、含来源链接、说明未知生效日期、保存完整历史、运行结束，共 8 项。单次问答约 16 秒，执行了两次政策检索；这是一条样例，不是整体准确率评估。
5. Web 通过测试身份恢复该真实回答，显示 8 个来源链接；刷新后内容一致，390px 手机无横向溢出，页面脚本异常为 0。页面验证只读已有结果，没有再次调用模型。

历史完整性最初的检查误把一整轮流式文本与单条历史比较。该轮包含检索前说明和最终回答两条 AI 消息，合计 2,009 字符，与流式文本逐字一致。已修正验收脚本为比较本轮所有 AI 消息，并新增回归用例；没有修改历史存储逻辑。

### 无 MySQL 的真实模型预览

```powershell
# 已准备好索引后，启动实际模型与测试身份页面：
.\run_dorm_live.cmd
# 打开 http://127.0.0.1:18766/__fixture，选择“测试身份一”或“测试身份二”。

# 首次准备或主动更新隔离索引（会调用 Embedding）：
.\.venv\python.exe scripts\prepare_dorm_kb.py
# 真实模型问答验证（会调用模型与 Embedding）：
.\.venv\python.exe scripts\verify_dorm_live.py
# 只复查已保存的测试历史，不再次调用模型：
.\.venv\python.exe scripts\verify_dorm_live.py --recheck-saved
```

预览使用 Agent 18765、Web/代理 18766。`/__fixture` 是仅用于本地联调的身份入口，没有挂载到正式 Dorm 服务。预览中的新提问会调用真实模型和 Embedding；当前资料是人工整理快照，日期未核实，不能据此保证现行政策。

将来准备好本地 MySQL 后，使用 `run_dorm_web.cmd --local-kb` 可让正式 Dorm 登录链路复用该隔离 Chroma；不加该参数仍沿用 Campus 原有知识后端配置。

机器报告在 `data/local/xmumdorm/kb-check.json`、`live-check.json`；真实回答截图在 `.playwright-cli/dorm-agent-live-desktop.png` 和 `dorm-agent-live-mobile.png`。配置文件未改，未连接 Dorm MySQL，未运行迁移或部署。

## 回答方式收敛

按用户要求，Dorm 助手默认先给直接答案，普通问题用一个短段落，办理流程用少量步骤。仅保留与当前问题相关的条件，不附带处罚后果、无关政策、功能清单、重复建议或检索过程。用户要求详细时再展开。

按最新要求，回答不再附来源、引用链接、生效日期、快照或时效说明，也不使用“来自……”或“根据……资料”等开头；直接给答案。用户单独询问日期时才回答该日期。适用对象确实决定不同流程时只问一个澄清问题，不先列出两套制度。页面上的来源与日期提示同步移除。

该规则仅作用于 Dorm 专用提示词，检索证据门槛保持不变。`scripts/eval_dorm_answers.py` 检查问候、个人课表、考试资格、成绩复查等五种真实问法，验证不再附出处和日期、仍检索到相关证据、历史与流式一致。报告保存到 `data/local/xmumdorm/answer-style-check.json`。

最新五种问法全部通过，考试资格回答为 61、62 字符，无来源或日期附加说明；内部检索和历史一致性检查通过。旧长回答会话的真实 Web 追问为 58 字符、零来源，验证旧会话后续回答也使用新格式。相关集成回归 3 项和 Web 构建通过。旧历史不重写。

按最新页面要求，标题下不再显示整行会话工具栏。右上角提供“历史会话”按钮，点击可按标题和时间选择旧聊天，也可新建对话。每次离开后重新进入或刷新页面，默认空白新对话；发送第一条消息时才保存会话，避免空记录堆积。旧聊天仅通过历史记录打开，不自动恢复。加载失败时可重试，历史弹窗支持 Escape 和点击遮罩关闭。

每条历史会话右侧提供删除按钮；删除后持久移出列表，并在当前页面提供“撤销”。这是可撤销删除，保留消息和检查点；不是彻底擦除数据。删除当前会话会回到空白新对话，正在回答中的会话返回 409；删除和撤销均按当前账号校验，旧主会话不会因兼容初始化再次出现。

## 团队预览网关核验（2026-10-24）

只更新 `origin/main` 引用并阅读源码，未切换或合并工作分支。`6a8b8d1b` 已含课程资料只读预览网关；协作者配置位置为 Dorm 的 `frontend/.env.local`，令牌由 Vite 服务端作为 `X-Preview-Token` 注入，不能加 `VITE_` 前缀。当前工作分支尚无该实现，单独添加变量不会启用。现有 `.env` 和数据库配置保留。

使用用户提供的凭据，健康检查、课程列表（限 1 条）和资料列表（限 1 条）均返回 HTTP 200。验证脚本 `scripts/check_dorm_preview_gateway.py` 仅从进程环境取凭据，禁止跟随重定向，报告 `data/local/xmumdorm/preview-gateway-check.json` 不含令牌或响应行内容。没有写入生产业务数据。

当时线上部署的网关没有指南路由。`freshman-guide` 是旧分类 slug，迁移后为 `campus-guide`，不能将按旧分类查询的 0 条解释为没有内容。进一步匿名实测：`/api/handbook/tabs` 返回 11 个分类，`/api/handbook/articles?tab=all&pageSize=1&page=1` 正常返回 1 条已发布文章。列表仅有摘要，现有详情接口会递增浏览量，未批量读取。

本地已在上游网关基础上增加 `/api/preview/handbook/export`，同步工具为 `sync_dorm_guides.cmd`，并为 Dorm 助手挂载独立 `search_guides`。操作和部署前置条件见 [指南知识的导入与更新](dorm-guide-knowledge.md)。尚未部署或将生产文章导入默认指南索引。

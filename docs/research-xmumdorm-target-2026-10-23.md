# XMUMDorm Web 接入 Campus Copilot：目标仓库核查

研究日期：2026-10-23。目标仓库：`C:\Users\阴沛森\Desktop\XMUMDorm-2.0.0-LYZZ`。本次只读目标代码；不读取 `.env`、不访问数据库、不运行服务、不修改目标仓库。范围按用户最新选择：先接 Web，App 后续复用接口。

## 1. 结论与事实边界

**建议保留 Python Agent 独立服务，在 Dorm Express 增加受保护的 `/api/agent/*` 网关，在 React Web 增加原生页面。** 首版入口放「我的 → 工具」，建议路由 `/myzone/agent`。这是接入提案，当前代码尚未实现。

Dorm 是校园社区与工具平台，不能因名称包含 Dorm 就假设已有住宿管理、维修报单、床位分配、宿费查询接口。在本次路由挂载核查中，已有课表、待办、新生指南、食堂、二手、社团、通知、商城等；没有据此确认学校住宿事务系统。证据：[server.js:158](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:158>)。

目标的 `CLAUDE.md`、部分规则/索引文档存在历史口径：例如仍有 React 18、`frontend/src/api`、App 已废弃等描述。当前依赖与实现应单独记录；不能把历史文档当当前运行实测。新 App 源码存在，且共享 API 已包含宿主注入点。本报告不裁决旧文档冲突，也不改 App。

| 已确认事实 | 代码证据 | 对接入的影响 |
|---|---|---|
| 后端 Node/Express 4 + MySQL2 + JWT | [package.json:35](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/package.json:35>)；[database.js:43](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/database.js:43>) | Python Agent 作为独立进程/服务，不直接塞进 Node 运行期 |
| Web React 19 + Router 7 + TanStack Query 5 + Vite 7 | [frontend/package.json:12](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/package.json:12>) | 新建 React 页面；复用现有组件、语言/认证上下文 |
| Web API 已在 `shared/api`，Vite 配置 `@shared` | [frontend/vite.config.js:29](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/vite.config.js:29>)；[shared/api/request.js:48](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:48>) | API 契约放共享层，页面与 React DOM 逻辑留 Web |
| Web 工具入口在「我的」 | [MyZone.jsx:309](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/pages/MyZone.jsx:309>) | 首版加工具卡即可，无需先重排全站导航 |
| Web 桌面/手机使用同套路由壳，按断点切外壳 | [SiteShellRoute.jsx:23](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/components/shell/SiteShellRoute.jsx:23>) | 对话页应作为 Topic Content；不能只在桌面右栏提供必需操作 |
| 已有二手私聊是轮询会话 | [MarketplaceChat.jsx:29](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/pages/Marketplace/MarketplaceChat.jsx:29>) | 可参考视觉，但不能视为已有 LLM/SSE 基础设施 |

## 2. 最小可行接入面

```text
Dorm React Web /myzone/agent
  → Authorization: Bearer <Dorm JWT>
  → Dorm Express /api/agent/*
       现有账户校验 + Agent 配额 + 路径白名单
       短期内部身份票据（新建信任边界）
  → Campus Copilot FastAPI /api/*
       现有 LangGraph / 会话 / 知识检索 / 工具
  → 模型与 Agent 自有存储

后续 App → 相同 Dorm /api/agent/* 契约
```

以下均为建议新增，目标仓库目前没有这些文件：

| 层 | 建议改动 | 已有接入位置 |
|---|---|---|
| React 页面 | `frontend/src/pages/Agent/AgentChat.jsx` 与组件/样式；显示消息、引用、运行状态、待确认动作、错误与恢复 | [layoutRoutes.jsx:93](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/routes/layoutRoutes.jsx:93>) 有统一 lazy/Suspense/错误边界；[同文件:164](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/routes/layoutRoutes.jsx:164>) 是 `myzone/*` 路由群 |
| 入口 | MyZone 工具区增加「校园助手」，路径 `/myzone/agent` | [MyZone.jsx:315](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/pages/MyZone.jsx:315>)；若以后要常驻桌面导航，修改 [siteShellNav.js:15](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/components/shell/siteShellNav.js:15>) 的注册表 |
| 共享协议 | `shared/api/agent.js` 提供普通 JSON 接口；独立 stream transport 支持增量事件 | [request.js:75](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:75>) 当前会 `res.json()` 或把非 JSON 完整读成错误，不可直接承担 SSE |
| Express 网关 | `routes/agent.js`、`services/agentProxy.js`，在主服务显式挂载 `/api/agent` | [server.js:158](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:158>) 的模块路由区 |
| FastAPI 身份适配 | 接受受验证的内部身份，仍由服务端构建 `UserContext` | [Campus server.py:165](<E:/Campus Copilot/src/server.py:165>) 当前只认本地 opaque token；[context.py:25](<E:/Campus Copilot/src/context.py:25>) 管理记忆身份 |

首版只转发主方案列出的聊天、会话列表/创建/状态/历史接口。学期列表、个人资料或成绩功能按后续启用的能力逐项增加，不默认开放。不要将 FastAPI 整个 `/api/*` 无差别公开，否则会把独立账号注册、数据库浏览等能力一起带入 Dorm。当前 Agent 存在 `/api/register`、`/api/login`、`/api/database` 等路由，需由主研究的接口清单逐项决定。证据：[Campus server.py:174](<E:/Campus Copilot/src/server.py:174>)；[Campus server.py:345](<E:/Campus Copilot/src/server.py:345>)。

## 3. 账户桥接是第一项必须改造的功能

### 现有身份完全不同

Dorm：登录签发 JWT，包含 `id/student_id/username/email/role`；`id` 来自 MySQL `users.id`。Web 将 JWT 放在 `localStorage['token']`，共享请求用 `Authorization: Bearer` 携带；没有采用 Cookie 会话。证据：[routes/auth.js:570](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/auth.js:570>)；[AuthContext.jsx:132](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/context/AuthContext.jsx:132>)；[request.js:24](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:24>)、[request.js:63](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:63>)。

Campus Copilot：Bearer 是随机 opaque token，服务端以哈希查 `web_tokens`，查出 username，再用 username 隔离画像和会话；它不会自动识别 Dorm JWT。证据：[auth.py:12](<E:/Campus Copilot/src/auth.py:12>)；[auth.py:172](<E:/Campus Copilot/src/auth.py:172>)；[server.py:165](<E:/Campus Copilot/src/server.py:165>)。

### 建议方案

1. Web 继续使用现有 Dorm 登录，不新增第二套账号密码。
2. Express 每次请求先运行现有 `authenticateToken`；它验证 JWT、校验正整数 id，并查数据库复核 `users.status`，被注销账户会被挡住。证据：[middleware/auth.js:19](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/middleware/auth.js:19>)、[同文件:43](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/middleware/auth.js:43>)。
3. Express 给 Agent 签发短期、限定 audience 的内部票据，至少包含 issuer、subject、expiry；Agent 验证后生成稳定身份。例如 `xmumdorm:<users.id>`，或在 Agent 侧保存 `(issuer, external_id) → internal_user_id` 唯一映射。
4. 不向浏览器暴露内部票据，不共享 Dorm 的长期 JWT 签名密钥；不信任来自客户端的 `user_id`、`role`、`X-User-Id`。网关删除客户端伪造的内部身份头。
5. 若要迁移现有 Copilot 账号历史，需要明确验证和迁移流程；不能因为用户名/邮箱相似就自动合并。Dorm 用户名和邮箱作为展示属性，主键绑定使用 `users.id`。
6. 所有会话读取、恢复、确认动作仍按服务端身份检查归属。不能为了接入去掉 Copilot 的 `owned_conversation`。证据：[Campus server.py:392](<E:/Campus Copilot/src/server.py:392>)；[conversations.py:74](<E:/Campus Copilot/src/conversations.py:74>)。

权限细节：Dorm `AuthGuard` 允许「暂不登录」用户继续进入全站，因此把页面挂在该组件下面不等于已登录；Agent 首版建议要求真实登录，API 必须独立保护。证据：[AuthGuard.jsx:7](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/src/components/AuthGuard.jsx:7>)。

现有 `authenticateToken` 只复核注销状态，不自动复核 ban/mute。`checkBan`/`checkSanction` 是另一个中间件，且查库失败会放行。Agent 使用被封禁/被禁言账号的产品规则要明确：可建议禁用封禁账号、私下问答不自动等同公共发帖；任何写入帖子/评论工具必须沿用原业务权限。证据：[checkSanction.js:16](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/middleware/checkSanction.js:16>)、[同文件:40](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/middleware/checkSanction.js:40>)。

错误兼容：Dorm 缺 token 返回 401，token 无效/过期返回 403，封禁/禁言也返回 403 并带 `banned/muted`。新客户端要保留响应体，不能见 403 就清除登录。证据：[request.js:95](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/request.js:95>)。

## 4. 流式聊天需要独立传输层

Copilot 当前协议是 POST `/api/chat`，请求体支持 `message` 或 `resume` 或 `decisions` 三选一；含 `conversation_id/checkpoint_id/semester_id`，响应是 SSE。中断事件含工具名、参数、允许的决定和检查点；启用受保护工具时，UI 必须呈现所需确认/拒绝操作，不能只显示最终文本。参数编辑是后续可选交互，现有 Campus 网页尚未提供编辑界面。证据：[server.py:130](<E:/Campus Copilot/src/server.py:130>)、[server.py:457](<E:/Campus Copilot/src/server.py:457>)。

建议 Web 使用 `fetch` POST + 增量解析 SSE；请求头携带 Dorm JWT。复用共享 API 的 base URL 与 token getter，但不要把流交给现有 JSON `request()`。SSE parser 需要覆盖分包、UTF-8 跨块、空行事件边界、心跳、EOF、非 2xx JSON 错误、异常流结束。协议仍由 shared 层定义，浏览器 reader 由 Web transport 承担；后续 App 独立验证其运行期流式能力。

Express 网关必须逐块传递，不先 `response.json()/text()` 聚合；在响应开始前传播 401/403/409/422/429/5xx；响应开始后的异常用既有流内 error 事件或明确断流恢复状态。需要处理首字节/空闲/总超时、断线和背压，代理层禁止缓冲，并保留 no-cache/no-transform 等流式语义。具体平台超时与缓冲能力属于部署验证项，本次未联网或运行链路验证。

特别注意：**关闭页面/Abort 仅中断传输，不等于取消工具或模型执行。** Copilot 的后台 worker 持有运行锁直到历史保存完成；`EventStream` 明确写着 disconnect stops delivery, not execution。UI 应提示恢复会话，避免断线后自动重发用户消息造成重复操作。证据：[web_runs.py:62](<E:/Campus Copilot/src/agent/web_runs.py:62>)；[server.py:492](<E:/Campus Copilot/src/server.py:492>)。

## 5. 从 Dorm 扩展知识的边界

| 数据类别 | 建议方式 | 原因与证据 |
|---|---|---|
| 经核验的公开学校规章、官方指南、稳定办事流程 | RAG，记录原始来源/版本/有效期 | 适合解释性问答；校方来源需另行核验，目标 repo 名字不证明其官方性 |
| Dorm 新生指南/攻略正文 | 可选 RAG，独立「社区经验」来源等级 | Markdown/外链、source_name/source_link 均来自投稿；公开发布不等于管理员审核，见下 |
| 课程公开资料正文 | 选定文件入 RAG，保留课程/学期/版本/文件锚点 | `materials` 由外部 GitHub index 驱动；公开 main 文件与待审核上传记录分开 |
| 我的课表、待办、通知、订单 | 授权工具 API | 数据实时且属个人，不能写入所有用户可检索的公共向量库 |
| 食堂菜品、店铺、价格、库存、订单状态、活动名额等动态字段 | 工具 API | 保留查询时刻/来源；避免旧向量索引给出过期交易状态 |
| 学生帖子、树洞、评论、二手私聊、个人日记 | 首版不做全量公共入库 | 权限、删除、可见性与来源可信度差异大；若将来做个性化检索，必须独立授权并保持用户隔离 |
| 宿舍维修、床位、宿费等 | 先确认真实上游系统和授权 | 本次未找到可直接接入这些事项的现有路由，不能生成不存在的工具 |

### 新生指南：最容易误判的信任问题

- 列表默认只读 `status='published' AND deleted_at IS NULL`，但 admin 可包括草稿，作者可包括自己的草稿。公共索引应使用专门导出权限，不能带管理员凭据直接把列表全采集。证据：[handbook.js:223](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/handbook.js:223>)。
- 文件头写「普通用户投稿默认 draft；admin 可发布」，**实际创建逻辑允许普通用户直接提交 `published`**。因此 `published` 只表示可见，不能映射成 `official=true` 或 `reviewed=true`。证据：[handbook.js:1](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/handbook.js:1>)、[handbook.js:445](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/handbook.js:445>)。
- `source_name/source_link` 由投稿请求直接提供，不是验证标记；`external_link` 可指向外部页面，文章记录本身不一定有正文。应单独安排来源核验、正文提取与抓取白名单。证据：[handbook.js:422](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/handbook.js:422>)。
- 详情查询会为 published 文章递增浏览数；周期同步若复用详情接口会污染阅读统计，建议独立只读导出服务或受限内部批量接口。证据：[handbook.js:372](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/handbook.js:372>)。
- 同步键建议 `dorm:handbook:<id>`，记录 `updated_at`、内容 hash、status、原站链接、来源等级；隐藏/删除后撤回对应 chunks。现有详情包含必要时间和来源字段。证据：[handbook.js:340](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/handbook.js:340>)。

### 学习资料：利用现有发布链路，不重复造上传入口

- `/api/materials` 读取 GitHub index；可按课程、类型、考试节点、课时和关键词筛选，支持 `stale` 快照回退。正文读取只允许 index 已登记路径；Markdown/TXT 代理返回，其他格式 302 跳 CDN。证据：[materials.js:139](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:139>)、[materials.js:310](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:310>)。
- 已有上传 → GitHub PR → merged/rejected 状态，不应把 pending 上传或仅 DB 元数据当已发布正文。建议 ingest 固定 main commit SHA 版本的 index 和对应文件；校验文件 hash，保留课程与学期，再进入独立 KB 发布流程。证据：[materials.js:468](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:468>)、[materials.js:589](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:589>)。
- 上传的 `source`、semester、description 等是元数据，不自动证明校方真实性。`official` 分类需要外部证据或人工确认；公开教学资料还应按其允许的用途选择是否导入。证据：[materialValidation.js:248](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/services/materialValidation.js:248>)、[materials.js:479](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:479>)。
- 公开 index 故意不写上传者信息；Agent 导出也应保持该边界，不能把 admin 统计里的 uploaderByPath 填入公共索引。证据：[materials.js:494](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:494>)、[materials.js:700](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:700>)。
- GitHub 访问集中在 `services/githubMaterials.js`，PAT 不应下发前端或放到模型提示中；新同步可复用这个模块提供的受限导出能力。证据：[githubMaterials.js:1](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/services/githubMaterials.js:1>)。

### 可优先增加的只读工具

1. `get_my_schedule(week)` → 现有 `/api/schedule/week`，它依据 `req.user.id` 查询 Dorm 保存的个人课表，并返回学期上下文；Agent 应复用该数据源，避免维护互相冲突的第二份课表。此接口读取平台已保存的数据，不代表实时查询学校系统，也不保证导入内容仍然最新。证据：[schedule.js:151](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/schedule.js:151>)。
2. `list_my_todos(date,status)` → `/api/todos` 或 `/api/todos/today`，保留用户隔离和分页。证据：[todos.js:47](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/todos.js:47>)。
3. `search_canteen(query)` → `/api/canteen/search`，返回当前店铺/菜品链接。证据：[canteen.js:2007](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/canteen.js:2007>)。
4. `search_materials(course,query)` → `/api/materials`，可先只返回资料链接，不要求所有 PDF 都向量化。证据：[materials.js:163](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/routes/materials.js:163>)。

工具不接受任意 user_id/SQL/URL；由受信任上下文传入主体。Agent 调 Dorm 时需要单独的受限内部调用契约，或只在请求运行上下文内使用经过验证的用户授权；不能把短期凭据写进 LangGraph checkpoint、长期记忆或工具参数日志。写待办、发帖、下单等写工具另设显式用户确认、幂等键与原业务校验，首版可以只做读取。

## 6. 部署与运行风险

| 项目 | 当前证据 | 建议与待验证 |
|---|---|---|
| 本地路径 | Vite `/api` 代理到 `127.0.0.1:4040`：[vite.config.js:48](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/vite.config.js:48>) | 新 `/api/agent/*` 自然经 Express；Agent 监听另一个内部端口 |
| 生产入口 | `VITE_API_BASE_URL` 可配置独立后端：[config.js:14](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/config.js:14>)；Vercel 仅 SPA catch-all：[vercel.json:1](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/frontend/vercel.json:1>) | 当前不能声称生产已同源代理。需明确走现有 API origin，或增加置于 SPA catch-all 前的网关路由；验收部署链路是否缓冲 SSE |
| 运行进程 | Express 常驻监听；默认端口 4040：[server.js:62](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:62>)、[server.js:202](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:202>) | Agent 独立 Python 服务；不每次 HTTP 请求启动 Python |
| 并发 | Copilot `RunRegistry` 是进程内锁/集合：[web_runs.py:15](<E:/Campus Copilot/src/agent/web_runs.py:15>) | 首版限定单 Agent 进程/单副本；横向扩容前增加跨进程会话互斥与运行所有权，不能仅加 Uvicorn workers |
| 成本限流 | Dorm 生产全站按 IP 每 15 分钟 2500 次，开发不限：[server.js:80](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:80>) | 另按验证后的 users.id 限并发、模型 token/日配额、消息长度；校园 NAT 场景不可只靠 IP；轮询状态不能挤占聊天额度 |
| 长请求日志 | 全 `/api` 在 finish 后按耗时记 slow-api：[server.js:128](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:128>) | SSE 正常也会很慢；分别观测首 token 时间、整轮时间、模型成本和异常，不把全部长流当故障 |
| 数据层 | Dorm MySQL 参数查询；Copilot 有独立记忆/会话存储 | 首版不合并数据库；业务事实通过受限 API，Agent 保管对话和记忆；上线时落实持久卷/备份/恢复 |
| CORS / 代理信任 | Dorm 当前 `cors()` 全开，`trust proxy=1`：[server.js:57](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/server.js:57>) | 部署时确认真实代理层数和允许 origin；Agent 服务保持内部可达，内部票据仍必须校验 |

## 7. 实施次序与验收建议

1. **定接口与身份**：列出允许代理的端点、事件 schema、内部身份验证、用户 id 映射、异常 envelope；以双账户隔离测试为第一门。
2. **完成 Web 聊天闭环**：先保留现有知识源；做文字流、会话历史、刷新恢复、待确认动作、断线状态与成本限额。首版不自动扩展所有业务写工具。
3. **增加精选公开知识同步**：优先来源可核验的指南；社区经验分层；发布/隐藏/删除同步，引用可点回原文；资料按 commit/hash 固定版本。
4. **加只读业务工具**：课表、待办、食堂搜索、资料检索；分别验权限、分页、错误和过期数据语义。
5. **App 复用**：复用 `/api/agent/*` 和共享事件/请求契约；使用 [shared/api/platform.js:31](<C:/Users/阴沛森/Desktop/XMUMDorm-2.0.0-LYZZ/shared/api/platform.js:31>) 的 base URL/token 注入。App UI 与流读取实现单独开发，不把 DOM 代码放 shared。App 当前 API 版本及流式能力届时按 `app/AGENTS.md` 指引查对应官方文档。

必要验收：未登录/过期/注销账号、伪造内部头、跨用户会话 id、确认过期 checkpoint、消息重复提交、并发同会话、UTF-8 分块、代理缓冲、断流后恢复、KB 撤回、社区与官方来源冲突、工具越权与写操作幂等。实施时遵守目标项目新增路由测试与迁移规则；本次纯研究没有运行测试，不能给出系统已可运行/已部署的结论。

## 8. 本次工作与未验证项

- 已做：只读核查项目指引、实际依赖、Web 路由/外壳/工具入口、共享请求层、JWT 鉴权、限流、部署入口、手册/资料/课表/待办与现有私聊；形成本文。
- 证据：本文每项核心结论链接至本地源文件和行号；工具读取均未执行真实服务或数据库请求。
- 未做：没有改目标代码、迁移数据、安装依赖、联网抓取资料、验证线上平台配置、建立 SSO 或运行端到端测试。
- 风险口径：表中标为现有的是代码事实；架构、接口名称、路径和实施次序是提案；生产 origin、代理限制、正式知识源名单、现有 Copilot 历史迁移策略仍待实施前确定。
- 需产品确定：首版是否只允许登录用户（建议是）；「校园助手」入口是否先放「我的→工具」（建议是）；哪些指南能经来源核验进入首批知识库；是否保留并迁移独立 Copilot 账号历史。先接 Web 已由用户确认。

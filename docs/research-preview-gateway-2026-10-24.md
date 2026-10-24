# 预览网关与指南知识导入核查

日期：2026-10-24。范围：只读检查目标仓库 Git 对象；未读取 `.env` 的实际值、未请求线上服务、未修改目标工作树，也未执行 fetch、checkout、merge。线上可用性由主任务另行验证。本记录不含访问令牌或数据库连接串。

## 结论

群消息给出的四个变量对应真实存在的功能，但它目前只支持**学习资料模块的只读预览**，不能直接读取新生指南或扩展助手知识库。预期配置位置是目标仓库的 `frontend/.env.local`，不是仓库根目录。

当前工作树 HEAD 为 `bd8956d6bdc87103cbcd4e1b98068e019d110ff8`，该提交中没有 `routes/preview.js`、`services/previewGateway.js` 或预览网关团队文档。研究期间主任务更新了远端引用；下文统一固定到 `origin/main` 的 `6a8b8d1b4e9d3c63d5e6163493448027e9b5c427`，避免将新远端代码误称为已在本地工作树生效。

来源：上述两个提交的 `git rev-parse`、`git ls-tree`；新版本 `docs/team/生产只读预览网关.md`。

## 网关实现与协议

| 项目 | 源码证据（均为提交 `6a8b8d1b4e9d3c63d5e6163493448027e9b5c427`） | 查证结果 |
| --- | --- | --- |
| 功能引入 | `fdc0248e`，`feat(materials): add read-only preview gateway` | 新增路由、服务、Vite 代理、资料页预览模式及测试。 |
| 账号配置脚本 | `dd38d4df`，`chore(materials): add preview reader provisioning script` | 提供数据库管理员创建最小读取账号的脚本；协作者不需要运行。 |
| 环境文件 | `docs/team/生产只读预览网关.md:33`；`frontend/vite.config.js:30`；`.gitignore:5` 起 | `loadEnv(mode, __dirname, '')` 从 frontend 目录读变量；文档明确 `frontend/.env.local`；环境文件受忽略规则覆盖。 |
| 请求代理 | `frontend/vite.config.js:31-42` | `PREVIEW_GATEWAY_URL` 和 `TOKEN` 同时存在才设置 `/api/preview` 代理；服务器侧注入 `X-Preview-Token`、`Origin`。Origin 默认 `http://localhost:5173`。 |
| 浏览器开关 | `shared/api/materials.js:44-52,109-122` | `VITE_MATERIALS_PREVIEW_GATEWAY=1` 只切换资料与课程列表 GET 到当前 Vite 来源；`skipAuth: true`，不沿用用户 JWT。令牌没有 VITE 前缀，不进入浏览器 bundle。 |
| 后端挂载 | `server.js:53,181` | 网关挂在 `/api/preview`，与普通业务 `/api/handbook` 分开。 |
| 网关启用条件 | `services/previewGateway.js:42-51` | 必须同时存在专用 `PREVIEW_DATABASE_URL`、有效客户端哈希登记及来源白名单；不回退到应用数据库连接。 |
| 鉴权 | `services/previewGateway.js:23-64`；`routes/preview.js:20-35` | 对传入令牌计算 SHA-256，与登记哈希定时安全比较；Origin 必须匹配白名单。未启用返回 404；未授权返回 403。 |
| 限流与缓存 | `routes/preview.js:12-18,29-32` | 每个客户端每 15 分钟 300 次；响应 `private, no-store`。 |
| 查询限制 | `services/previewGateway.js:81-186` | 固定 SELECT 和参数；资料必须未删除且 `status='merged'`；页面大小最多 100。无 SQL、表名、任意排序接口。 |

目前允许的网关 GET 路由只有三条：

- `/api/preview/health`：返回当前授权客户端标识，仅证明鉴权可用，不会实际查询数据库。
- `/api/preview/materials/courses`：课程字典与合并资料数量。
- `/api/preview/materials`：资料分页元数据和公开文件 URL。

来源：固定提交 `routes/preview.js:39-70`。服务只返回 `enabled, authorize, listCourses, listMaterials`，没有 handbook 方法（`services/previewGateway.js:188`）。

“连接生产数据库”在这里的准确含义是：Vite 请求已部署的网关，再由网关通过专用读取连接查询固定课程资料数据。它不向本机暴露数据库 URL，也不使所有本地业务接口自动可用。数据库权限是否确实只有 SELECT，必须由部署环境保证；源码约束本身不能证明线上账号权限。

来源：固定提交 `docs/team/生产只读预览网关.md:3-25,44-59`、`services/previewGateway.js:43,66-78`。

## 已有指南接口能否导入

`server.js:164` 将普通指南 API 挂在 `/api/handbook`。下列行为来自固定提交 `routes/handbook.js`，不是预览网关提供的能力。

| 接口 | 匿名读取范围 | 对知识导入的限制 |
| --- | --- | --- |
| `GET /api/handbook/tabs`、`/tags` | 已启用分类、标签；无登录中间件。 | 目录信息，不含文章正文。源码 `:100-148`。 |
| `GET /api/handbook/articles` | 默认只返回未删除且已发布文章；支持 tab、tag、q、sort、page、pageSize；pageSize 上限 30，返回 hasMore。无登录时 includeMine/includeDraft 不扩大权限。 | 仅标题、摘要、类型、外链、公开作者、统计等列表 DTO，不含 content；该处理器没有增加浏览量的 UPDATE。源码 `:223-323`。 |
| `GET /api/handbook/articles/:id` | published 可匿名读；草稿与隐藏文章仅作者/管理员可读。 | 有 content、contentType、externalUrl、sourceName、sourceLink、updated_at 等导入所需字段，但每次读 published 都异步执行 `views_count + 1`。批量读正文会增加生产浏览量。源码 `:330-412`，关键写入 `:372-373`。 |

指南详情最近相关提交是 `6035125b432db9992f7040fe5fc4a0f2cd7f38c4`（`feat(handbook): add external guide links`）。文章分 `markdown` 与 `external_link`：外链文章的 URL 或摘要不能当作已取得目标页面全文。来源：固定提交 `routes/handbook.js:385-393,426-439`；`shared/api/handbook.js:1-46`。

因此，普通公开列表可用来验证目录；目前没有现成的、零计数写入的公开指南正文导出接口。本次没有请求任何指南详情接口。

分类需要特别注意：`freshman-guide` 是旧分类 slug。固定提交 `migrations/024_handbook_tabs_xmu.sql:14-17` 将其改为 `campus-guide`，同一迁移还设置了 `food`、`explore`、`durian`、`study-tips` 等分类；`migrations/025_handbook_tabs_order.sql:7-13` 进一步调整排序。页面仍保留 `/about/freshman-guide` 路径，但 `frontend/src/pages/Handbook/HandbookHome.jsx:40,48-53,81-90` 默认查询 `tab=all`，分类来自 `/api/handbook/tabs`。因此不能将页面路由名当作当前分类 slug。生产迁移是否已执行，应以实际 tabs 响应为准。

## 主任务提供的线上验证结果

主任务通过独立操作完成了下列请求，本研究代理没有发出这些请求。结果保存在 [preview-gateway-check.json](../data/local/xmumdorm/preview-gateway-check.json)，未保存令牌和响应数据行。

| 请求 | 结果 | 可证明的范围 |
| --- | --- | --- |
| 带网关令牌 `GET /api/preview/health` | HTTP 200 | 令牌和指定 Origin 被部署服务接受。 |
| 带网关令牌 `GET /api/preview/materials/courses?limit=1` | HTTP 200，1 条 | 课程只读查询实际可用。 |
| 带网关令牌 `GET /api/preview/materials?pageSize=1&page=1` | HTTP 200，1 条 | 资料只读查询实际可用。 |
| 匿名 `GET /api/handbook/articles?tab=freshman-guide&pageSize=1&page=1` | HTTP 200，0 条 | 普通指南列表接口可响应；只说明这个筛选无结果，不能推断全站无指南，且该 slug 在新迁移中已改名。 |
| 匿名 `GET /api/handbook/tabs` | HTTP 200，11 个分类 | 实际分类目录可读取。未保存分类响应行。 |
| 匿名 `GET /api/handbook/articles?tab=all&pageSize=1&page=1` | HTTP 200，1 条 | 使用全部分类查询可取得已发布文章；只读取列表，未请求详情。 |

主任务保留当前本地分支和工作树改动，未 merge、未更改 `.env`。上述线上结果是主任务反馈的实测事实；其余限制来自前述固定版本源码。

## 对下一步实现的建议

建议在预览网关增加固定的“已发布指南导出”读接口，再让 Campus Copilot 本地同步器导入，不直接调用会增加浏览量的普通详情接口。

1. 固定查询只允许 `deleted_at IS NULL AND status='published'`，保持现有网关令牌、来源白名单、限流和专用只读数据库账号。不要接受 includeDraft/includeMine 或客户端传入 SQL；按指南所需表单独补最小 SELECT 权限。
2. 固定最小 DTO 为文章 id、分类、标题、摘要、正文、内容类型、外链、发布时间和修改时间；可保留内部 sourceName/sourceLink。无需导出作者账号、收藏/点赞、评论或个人信息，也不执行浏览量 UPDATE。
3. 支持有界分页及稳定排序。同步器应先取完整快照再替换本地索引，清理已隐藏/删除文章的旧分块；仅按 updated_at 增量而无删除标记会留下已撤稿内容。
4. 外链型条目先记录链接和摘要；未经实际抓取与核对，不将其视为全文。站内用户指南与教务政策需保留不同知识类型，不能把用户经验提升为校方规定。
5. 增加固定测试：匿名/错误令牌/错误 Origin 被拒、只读 SQL、无草稿与删除内容、分页上限、无浏览量写入、字段白名单、隐藏文章从索引移除。发布部署后，才可用提供的令牌验证新接口。

以上为本研究根据源码提出的实现建议，尚未修改业务代码或部署服务；它不会由现有四个环境变量自动完成。如果暂不部署新增接口，次选方案是由有权限维护者导出已发布文章的离线 JSON/Markdown，再导入本地知识库。

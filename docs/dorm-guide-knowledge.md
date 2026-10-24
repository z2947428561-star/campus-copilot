# 指南知识的导入与更新

校园助手现在有两个独立检索入口：教务政策走 `search_policy`，新生报到、住宿、交通、校园周边等社区指南走 `search_guides`。社区指南不会进入政策证据库。回答继续直接给答案，不附来源、生效日期或“来自……”开场。

## 已导入的真实正文

本机已将完整保存的 SurviveXMUM 快照 `20261003T030225654751Z` 中入学、生活和学习三个分类的 24 篇实质正文导入默认库，共 89 个知识片段。导入前校验全部 73 条下载记录与清单、正文 SHA-256 和原文 URL；核心分类中跳过 8 篇空白、仅有标题、仅有图片或贡献占位页，剔除文章内的待完善提示，其他分类暂未导入。

这些资料保留 `student_wiki` 类型、真实 Wiki URL、站点更新时间和抓取时间，未伪装成 Dorm 自有文章或官方政策。它们是已有本地快照，不代表本次重新核实了现行内容；本轮没有请求 Wiki、使用代理或访问生产数据库。资料和向量均在 Git 忽略的本地目录。

再次导入该本地快照：

```powershell
.\.venv\python.exe scripts\import_local_wiki_guides.py --snapshot-dir data\local\survivexmum\20261003T030225654751Z
```

该命令替换完整指南库，未变内容复用向量；日后如需混合其它来源，应先准备合并后的完整快照，避免只导入新增来源而覆盖现有内容。默认助手查询会读取最新索引，不必逐次重启。

导入报告为 `data/local/xmumdorm/wiki-import.json`；真实 Embedding 检索检查为 `wiki-retrieval-check.json`，AC 系统、生活软件、学校网站账号三组问题均命中对应真实正文。新增来源和转换器回归现为 14 项。

### 真实账号的新增指南问答验收

已在真实账号页面测试 Moodle/AC 登录账号、迎新系统账号、健身房楼栋、LY3 G 层用途、指南列出的外卖软件五个问题。五题均实际检索了新导入的 `student_wiki` 正文，回答与对应内容相符，刷新后仍能恢复。

用户最新确认的回答风格是：先直接回答，再补充紧密相关的实用信息，一个简洁自然段。例如询问健身房所在楼栋时，保留有直接正文依据的楼层、分区与开放时间。已撤销此前对设施回答只保留楼栋的裁剪，并同步调整提示词、检索指引和验收标准；不拼接其它设施的信息。账号问题仍不主动展开初始密码或重置流程。流输出和用户可见历史使用相同处理。

`scripts/check_dorm_guide_questions.py` 对首次捕获的两题范围判定为失败，修正后五题全部通过；最终指南回归 15 项、历史回归 7 项、Dorm 集成 3 项通过。报告与截图在 `data/local/xmumdorm/imported-guide-questions.json`、`imported-guide-questions.jpg`，不含登录令牌。

Dorm 对外只发送完成的、未携带工具调用的模型回答，工具调用前的说明留在内部上下文，不写入新用户可见历史。这会在该次模型回答完成后显示正文；其他 Campus 入口保留原有逐 token 输出。旧历史不重写。

## 日常操作

在 Campus Copilot 根目录运行。现有 MySQL 不是本地指南索引的必需项。

### 已有完整离线导出

```powershell
.\sync_dorm_guides.cmd --from-json "D:\exports\published-guides.json"
.\sync_dorm_guides.cmd --status
```

离线 JSON 应来自有权导出内容的维护者，只含已发布文章。顶层格式为 `schema_version: 1`、`complete: true`、`origin` 和 `articles`。每篇至少包含正整数 `id`、`status: published`、`title`、`category`、`contentType: markdown`、`content`。外链型文章使用 `contentType: external_link`，仅导入 `summary`，不会抓取外部页面或把摘要说成全文。

格式示例见 `examples/dorm-guides.example.json`。示例明确是虚构数据，工具禁止将它导入默认使用中的知识库。若只想试格式：

```powershell
.\sync_dorm_guides.cmd --from-json examples\dorm-guides.example.json --db data\local\xmumdorm\guide-format-test.db --snapshot-file data\local\xmumdorm\guide-format-test.json
```

这会调用现有 Embedding 服务，测试库不被默认助手使用。实际指南库默认为 `data/local/xmumdorm/guides.db`，可用 `DORM_GUIDE_DB_PATH` 指定；数据位于 Git 忽略目录。

### 线上只读导出接口部署后

复用已有预览网关配置，不把令牌写入文档、源码或浏览器环境变量：

```powershell
.\sync_dorm_guides.cmd --env-file "C:\Users\阴沛森\Desktop\XMUMDorm-2.0.0-LYZZ\frontend\.env.local"
# 只下载完整快照，不调用 Embedding：
.\sync_dorm_guides.cmd --env-file "C:\Users\阴沛森\Desktop\XMUMDorm-2.0.0-LYZZ\frontend\.env.local" --export-only
```

也可通过当前进程的 `PREVIEW_GATEWAY_URL`、`PREVIEW_GATEWAY_TOKEN`、`PREVIEW_GATEWAY_ORIGIN` 提供配置。现有 `.env` 不会被改写；本轮没有替用户创建或覆盖凭据文件。

每次同步都导出完整已发布快照，再原子替换索引：更新文章会替换旧分块，隐藏、删除或停用分类的内容会从下次快照中移除；未变化分块复用已有向量。下载中断、分页版本变化、非法内容或向量生成失败时保留原有索引。索引发布后下次查询读取新版本，不需要重建政策库。首次为已有服务增加 `search_guides` 工具时需重启 Agent。

## Dorm 侧待部署改动

本地新增 `GET /api/preview/handbook/export`，复用网关的令牌、Origin 白名单、限流和 no-store。参数仅有 `afterId`、`snapshot`、`limit`（1—30）。第一页取得快照摘要，后续页携带该摘要；快照发生变化返回 409，需从第一页重试。客户端拿齐所有条目并校验总数后才导入。

导出只执行一次固定 SELECT，条件为已发布、未删除、分类启用；不查账号表，不导出作者、邮箱、互动或评论，也不增加浏览量。当前整批上限 1,000 篇、序列化后 10 MiB，超限明确返回 413，不静默截断。为保证跨页一致性，每页会从同一个有界 SELECT 重算完整快照摘要；若日后超过该规模，需要独立的快照存储或服务端导出任务。

部署需要维护者完成两项操作：部署这次 Dorm 代码，并给现有专用预览数据库账号增加 `handbook_articles` 和 `handbook_tabs` 的 SELECT 权限（可按导出所需字段限制）。不需要 INSERT、UPDATE、DELETE 或迁移权限。`scripts/materials/create-preview-reader.js` 的新账号创建列表已包含这两张表，但它不会覆盖已存在账号。本轮没有执行账号创建、授权、数据库迁移、推送或部署。

在部署完成前，现有线上网关仍不能导出指南正文；可以先使用维护者提供的完整离线导出。

## 本地验证

```powershell
.\.venv\python.exe scripts\test_dorm_guides.py
.\.venv\python.exe scripts\test_dorm_integration.py
# 实际 Embedding 和模型；启动隔离 Node 导出接口，使用虚构测试指南：
.\.venv\python.exe scripts\verify_dorm_guides.py
```

真实模型验证使用 `data/local/xmumdorm/guide-verification/` 下的独立索引与对话库，不将虚构资料放入默认指南库。机器报告为该目录的 `check.json`。验证通过也不代表已经导入生产指南。

本轮结果：完整离线检查 21 个文件通过，新增指南回归最终 12 项通过，Dorm 内部集成 3 项和原有历史回归 7 项通过；Node 网关与原代理相关 21 项通过，所有路由 CommonJS 语法检查通过。真实 Embedding/模型联调通过，原有五种问法回归通过。实际 Web 对尚未导入指南的提问简短说明无法确认，67 字符，刷新后文本一致，已删除工具栏未出现。

为维护者准备的导出接口补丁为 `data/local/xmumdorm/guide-export.patch`，基于 Dorm 主分支 `6a8b8d1b`；只包含该网关的指南扩展、只读新账号表列表和对应测试，不含令牌、其他本地 UI 或 App 修改。补丁准备不代表已经部署。

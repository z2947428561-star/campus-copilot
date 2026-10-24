# Campus Copilot Agent 部署交接（2026-10-24）

> 给负责部署的同学：本文档假设你把 Agent 部署到 **Railway**（与 XMUMDorm 后端同平台）。
> 全程约 15 分钟。部署完成后需要回填 2 个变量到 Dorm 后端，见文末。

## 0. 部署源

- 仓库：`https://github.com/z2947428561-star/campus-copilot`
- 分支：`codex/portable-chroma-releases`（如已合并则用 `main`）
- Railway 会自动识别仓库里的 **Dockerfile**（Python 3.13 + 依赖 + 知识库数据），无需额外配置启动命令。
- 知识库三件套已随仓库提供（`kb_data/`），**不需要**再传数据文件。

## 1. 在 Railway 新建服务

1. Railway 项目里 **New → GitHub Repo**，选上面的仓库和分支。
2. Railway 检测到 Dockerfile 后自动构建（首次约 5-8 分钟）。
3. （可选）Settings → Healthcheck Path 填 `/api/health`。

## 2. Agent 服务环境变量

| 变量 | 值 | 说明 |
|---|---|---|
| `CAMPUS_AGENT_SHARED_SECRET` | **见第 4 节生成** | 服务间鉴权，≥32 字符 |
| `XMUMDORM_API_URL` | `https://xmumdorm-200-lyzz-production.up.railway.app` | Dorm 后端根地址，不加 `/api` |
| `CAMPUS_ENV_OVERRIDE` | `0` | 平台变量优先 |
| `LLM_PROVIDER` | `openai` | DeepSeek 兼容接口 |
| `LLM_MODEL` | `deepseek-chat` | |
| `DEEPSEEK_API_KEY` | 向项目作者索取 | 对话模型 key |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | |
| `LLM_FALLBACK_PROVIDER` | `none` | 无备胎，关闭降级 |
| `EMBED_BACKEND` | `cloud` | |
| `EMBED_API_KEY` | 向项目作者索取 | 硅基流动 key |
| `EMBED_BASE_URL` | `https://api.siliconflow.cn/v1` | |
| `EMBED_MODEL` | `BAAI/bge-m3` | 必须与已建索引一致，**换模型要重建索引** |
| `EMBED_DIM` | `1024` | |
| `EMBED_SEND_DIMENSIONS` | `false` | |
| `EMBED_CHECK_CTX_LENGTH` | `false` | ⚠️ 保持 false，改 true 会静默产出垃圾向量 |
| `KB_BACKEND` | `chroma` | |
| `CHROMA_DIR` | `/app/kb_data/chroma` | 镜像内路径，勿改 |
| `KB_REGISTRY_PATH` | `/app/kb_data/kb_releases.db` | 镜像内路径，勿改 |
| `DORM_GUIDE_DB_PATH` | `/app/kb_data/guides.db` | 镜像内路径，勿改 |
| `MEMORY_BACKEND` | `sqlite` | |
| `MEMORY_DB_PATH` | `/data/agent/memory.db` | 挂载卷路径，见第 3 节 |
| `LANGSMITH_TRACING` | `false` | |

温度 / token / 检索条数等其余参数不用设，代码默认值即可。

## 3. 挂持久卷（只为了 memory.db）

Railway 服务 → **Volumes → New Volume**，挂载点 `/data/agent`。
`memory.db`（历史会话）会自动创建在这里；知识库文件在镜像里，不依赖卷。

## 4. 共享密钥（两边一致，独立生成）

在**你自己的终端**执行一次：

```
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

把输出值同时填到两处（不要复用 JWT_SECRET，不要提交进仓库/发群里）：

- Agent 服务（Railway）：`CAMPUS_AGENT_SHARED_SECRET`
- Dorm 后端（Railway）：`CAMPUS_AGENT_SHARED_SECRET`

## 5. 部署完成后回填 Dorm 后端 2 个变量

| 变量（配在 Dorm 后端） | 值 |
|---|---|
| `CAMPUS_AGENT_URL` | Railway 分配给 Agent 的公网域名，如 `https://campus-copilot-production-xxxx.up.railway.app`（根地址，不加 `/api`） |
| `CAMPUS_AGENT_SHARED_SECRET` | 与 Agent 完全相同 |

## 6. 验收清单

1. `curl https://<agent域名>/api/health` → `{"status":"ok","service":"campus-copilot"}`
2. 在 Dorm 网页/App 里发起对话，问「重修要交钱吗？」→ 回答应包含重修费用规则（RM200/RM240 等细节来自政策库）。
3. 登录 Dorm 账号问「我有哪些未完成的待办？」→ 能回查到本人数据（验证 Dorm→Agent→Dorm 回查链路）。

有问题联系项目作者。密钥类信息不要写进任何文档或代码里。

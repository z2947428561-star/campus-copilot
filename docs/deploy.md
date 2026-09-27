# 云部署指南 —— 让同学能用

> 目标:把本机这套 `app + PostgreSQL + Milvus` 搬到云服务器,发链接给同学。
> 鉴权和个人成绩/课程隔离已内置。正式对外发布需要域名和 HTTPS。

## 一、服务器要求

| 项 | 最低配置 | 说明 |
|---|---|---|
| 规格 | 2 核 4G | Milvus 常驻约 1G,应用 + PG 约 1G;2G 内存会 swap |
| 系统 | Ubuntu 22.04 / Debian 12 | 任何能跑 Docker 的 Linux 都行 |
| 磁盘 | 20G | 镜像约 3-4G(python 基础镜像 + 依赖 + Milvus + PG) |
| 带宽 | 3-5 Mbps | SSE 流式文本流量很小 |
| 端口 | 正式环境只放行 80/443 | 8000 只绑定 127.0.0.1；19530/9091 不映射宿主机 |

实际费用与网络延迟会因地区、时间、服务商而变化；选服务器前应按目标同学所在地实测。

### 低配替代:2C2G 可尝试（必须实际监控内存）

2G 内存塞不下「app + PG + Milvus」三件套,但本项目知识库只有 **106 个片段**,
这个量级根本不需要独立向量库服务 —— 切到项目自带的 **Chroma 过渡后端**
(嵌入 app 进程,无需独立服务),2C2G 可作为小流量试运行起点:

- `.env` 设 `KB_BACKEND=chroma`(Embedding 走云端网关,不吃本机内存)
- 启动时跳过 milvus 服务:`docker compose --profile production up -d --build app postgres caddy`
- `chroma_data` 卷持久化 `/app/data/chroma_db`；重建 app 容器不会丢索引
- 建库同样跑 `docker compose exec app python scripts/build_kb.py`(自动写到 Chroma)
- 加 2G swap 兜底(见下),防构建/高峰期 OOM

加 swap(服务器上执行一次):

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

⚠️ 这不是降级凑合,是合理的架构权衡:"百万级片段以下用嵌入式向量库,
规模上来再切 Milvus"本身就是面试能讲的决策点;且 Milvus 路径在本地已完整验证,
课程证据链不受影响。以后换 4G 机器,`KB_BACKEND` 改回 `milvus` + 重跑建库即切回。

## 二、一次性准备(在服务器上)

```bash
# 1. 装 Docker(Ubuntu 一键)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # 重新登录生效

# 2. 拉代码
git clone <你的仓库地址> campus-copilot
cd campus-copilot

# 3. 配环境
cp .env.example .env
# 编辑 .env,必填:DEEPSEEK_API_KEY、EMBED_API_KEY、CAMPUS_DOMAIN、POSTGRES_PASSWORD
# POSTGRES_PASSWORD 使用至少 20 位随机字母数字串，不要包含 URL 特殊字符
# 云上建议:LANGSMITH_TRACING=false(trace 含同学真实问答,不该默认外传)
python scripts/preflight.py  # 配置预检；不会打印密钥
```

## 三、启动(三条命令)

```bash
docker compose --profile production up -d --build  # 起 app + postgres + milvus + Caddy
docker compose ps                     # 等 postgres/app healthy、milvus healthy(约 1-2 分钟)
docker compose exec app python scripts/build_kb.py   # 建知识库(必须!向量数据不随镜像走)
```

验证:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","service":"campus-copilot"}
```

将域名 DNS A/AAAA 记录指向服务器后，浏览器打开 `https://<CAMPUS_DOMAIN>`。
个人成绩和已选课程需在网页「个人数据」中自行录入；种子成绩不会自动分配给注册用户。

## 四、上线前检查清单

- [ ] `curl http://localhost:8000/api/health` 返回 ok
- [ ] `docker compose exec app python scripts/test_m5.py` 检索 10/10(验证 Milvus + Embedding 链路)
- [ ] 无 token 调 `/api/chat` 返回 401(鉴权生效)
- [ ] 安全组只放行 80/443；确认 8000/19530/9091/5432 无公网入口
- [ ] 域名 HTTPS 证书生效，登录和聊天均通过 HTTPS
- [ ] `.env` 里的 `LANGSMITH_TRACING=false`(除非明确要云端 trace)
- [ ] `python scripts/preflight.py` 通过；若失败，先修配置，不要发布
- [ ] `scripts/test_auth_rate_limit.py`、`test_student_data.py`、`test_server_security.py`、`test_chroma_rebuild.py` 通过
- [ ] `docker compose logs app` 无异常堆栈

## 五、HTTPS

`Caddyfile` 已纳入项目。设置 `CAMPUS_DOMAIN` 并启用 production profile 后，
Caddy 在 80/443 接入并代理至内部 app。证书签发要求域名解析与 80/443 入站可达。
没有域名时可在服务器本机访问 `http://127.0.0.1:8000` 做探活，勿将该端口暴露给同学。

## 六、日常运维

```bash
docker compose logs -f app        # 看日志
docker compose restart app        # 改代码后重启(数据在卷里,不丢)
docker compose down               # 停全部(数据保留)
docker compose down -v            # ⚠️ 连数据卷一起删(慎用)
bash scripts/backup_postgres.sh     # 备份账号、个人成绩/课程、会话和画像
```

数据持久化卷：`pgdata`(会话、画像、账号、个人成绩/课程)、`milvus_data` 或
`chroma_data`(知识库向量)，以及 Caddy 证书卷。`down` 不丢，`down -v` 会删除。
`backups/` 默认被 Git 忽略，但请把备份另存到服务器以外的受控位置；备份含个人数据。

恢复前先在新部署的空库上演练。确认备份文件与目标库后，停止 app 写入，执行：

```bash
docker compose stop app
docker compose exec -T postgres pg_restore -U campus -d campus --clean --if-exists --no-owner < backups/campus-YYYYMMDDTHHMMSSZ.XXXXXX.dump
docker compose start app
```

`pg_restore --clean` 会覆盖目标库现有表，切勿直接在仍有用户写入的生产库试运行。
向量知识库可由版本化政策文档重新运行 `scripts/build_kb.py` 构建，不含个人数据。
重建会替换现有索引，应在维护窗口执行；脚本会先检查 Embedding API 与维度，
但无法保证重建中途的外部 API 永不失败。Chroma 重建现会清空旧 collection，避免重复片段。
建议至少每日自动备份 PostgreSQL，并定期在隔离环境验证可恢复性。

登录接口默认按用户名在 15 分钟内允许 5 次尝试，超限返回 429；这是单进程防护。
新注册密码至少 12 位；已有账号不会因门槛提高而被强制改密。
公网发布若增加 app 副本，需在可信网关或共享存储增加统一限流；登录被恶意锁定的风险仍需监控。

## 八、本机发布演练记录（2026-09-26）

- 独立 Compose 项目：app/PostgreSQL healthy，Caddy 本机 HTTPS 探活 200；未登录聊天 401。
- 容器内从 16 份文档构建 Chroma 106 个片段；重启 app 后仍为 106 个。
- HTTP 集成测试：注册/登录、SSE 政策问答、GPA HITL 中断与恢复通过。
- PostgreSQL 非空备份恢复：清空 10 条测试成绩后恢复为 10 条，应用重新探活成功。
- 测试容器、数据卷、含测试账号的备份已清理；原有本地 PostgreSQL/Milvus 保留。

这不是公网验收：真实域名证书、服务器防火墙、学生真实数据与用户反馈仍待部署时检查。
当前本机 `.env` 配置预检有 3 项未通过：`POSTGRES_PASSWORD`、`CAMPUS_DOMAIN`
和 `LANGSMITH_TRACING=false`。不要把开发机 `.env` 直接复制到公网服务器。

## 七、常见问题

| 现象 | 原因与处理 |
|---|---|
| 政策问题回「知识库未接入」 | 没跑 `build_kb.py`,或 `EMBED_API_KEY` 没配/余额不足 |
| `build_kb.py` 报 402/code 30001 | 硅基流动余额不足,充值后重跑 |
| 启动后 app 反复重启 | `docker compose logs app` 看原因;多为 `.env` 缺 key |
| 同学注册不了 | 检查 `docker compose logs app` 是否有 PG 连接错误 |
| 想换 Embedding 模型 | 改 `.env` 的 `EMBED_MODEL` 后必须重跑 `build_kb.py`(向量空间变了) |

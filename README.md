# Campus Copilot — 校园智能助手

> 面向大学生的校园生活智能体:教务政策问答(RAG)+ 课表/校历/成绩等结构化查询(Tools)+ 个性化记忆。
> 兼作尚硅谷 LangChain 课程(BV1rv7A6oEeP)的毕业项目 —— 课件 **10 章 565 页**逐章有落点,
> 形成可核验的"学完证据链",见 **`docs/course-map.md`**。

## 项目定位

一句话:**把散落在教务处网站、通知公告、培养方案里的信息,变成一个能对话的助手。**

它不是玩具的理由:
1. **双数据源**:非结构化文档(RAG,Milvus 向量检索)+ 结构化数据库(SQLite)—— 两套检索范式在一个 Agent 里协同
2. **多用户场景**:部署后同学真的能用,有真实反馈迭代(会话隔离、个性化画像因此不是摆设)
3. **完整工程链路**:中间件治理(7 个内置中间件 + Hook 审计)+ LangSmith 全链路追踪 + Docker 部署 —— 面试官问"生产化考虑"有得答

## 用户故事

| # | 场景 | 背后技术 |
|---|---|---|
| 1 | 「挂科了怎么补考?重修和补考有什么区别?」 | RAG 检索教务规定文档 |
| 2 | 「大二下能修大数据导论吗?先修课是什么?」 | RAG(培养方案)+ 工具(课程库查询) |
| 3 | 「这学期第 10 周是几号?还剩几周放假?」 | 工具:校历/教学周计算 |
| 4 | 「帮我算算这学期 GPA,哪门课拉分了」 | 工具:成绩计算 + Pydantic 结构化输出报告 |
| 5 | 「明天上午哪栋楼有空教室?」 | 工具:空教室查询(结构化数据) |
| 6 | 「我大三了,帮我规划下还差的学分」 | 长期记忆(培养进度画像)+ Agent 规划 |

## 课程模块 → 项目落点(证据链)

> 完整映射见 **`docs/course-map.md`**(逐章逐节,含页码锚点与"课件未覆盖"清单)。
> 下表只给主线条目;引用格式统一为 `第0X章 §X.Y(pN)`,
> 页码锚点取自课件 PDF 页脚 —— 课件共 **10 章 565 页**。

| 课程章节(课件锚点) | 落点 | 状态 |
|---|---|---|
| 第02章 模型的创建与调用 §2.2/§3/§3.3(p8、p11-16) | `src/model.py` + `src/config.py`:`init_chat_model` 统一入口、temperature/timeout/max_retries | ✅ |
| 第03章 LangSmith §2.3(p6)、§3(p7-8) | `src/agent/runtime.py`:四个环境变量 + run_name/tags/metadata | ✅ |
| 第04章 消息与提示词模板 §1.6(p16-19)、§2.4(p37-42) | `src/prompts/`(模板库 + 按阶段组装)、`src/messages.py` | ✅ |
| 第05章 Tools §3.1(p15-18)、§3.3(p20-27)、§6.4(p43) | `src/tools/*.py` 9 个工具:`parse_docstring` + `args_schema` + 返回 JSON 字符串 | ✅ |
| 第06章 结构化输出 §2.1(p2-16) | `src/tools/gpa.py` 的 Pydantic 数据契约(含 `Field(description)` 与范围约束) | ✅ |
| 第07章 智能体 §1.4(p2-4)、§5(p26-28)、§8(p68-76)、§9.3(p80-81) | `src/agent/assistant.py`、`src/agent/streaming.py` | ✅ |
| 第08章 中间件 §2.1-2.3(p7-24)、§3.1-3.3(p34-53)、§3.8(p73)、§5.4(p99-111) | `src/agent/middleware.py`:7 个内置中间件 + 2 个 wrap Hook | ✅ |
| 第09章 上下文与记忆 §2.1(p6-13)、§3(p39-52)、§4.2(p74-80) | `src/agent/memory.py`、`src/tools/profile.py`、`src/context.py` | ✅ PostgreSQL 主路径,SQLite 备用 |
| 第10章 RAG §2.3(p24-46)、§2.4(p46-49)、§2.5(p51-65) | `scripts/build_kb.py`、`src/kb.py`、`src/tools/policy.py` | ✅ Milvus + 云端 embedding |
| **课件未覆盖(超纲自主决策)** | FastAPI/SSE 服务化、Docker Compose、32 问自建评估集、元数据+全库混合召回 | 见 `docs/course-map.md` §二 |

## 架构

```
用户 ─ Web/FastAPI(SSE 流式)
        └─ Agent(create_agent + system_prompt + 9 tools + context_schema)
             ├─ [RAG] 教务文档 → Milvus 向量检索(expr 元数据过滤)+ 云端 Embedding
             ├─ [DB] SQLite:课表/校历/教室/课程库
             ├─ 中间件管道:PII 脱敏→摘要压缩→上下文清理→审计→调用限额→模型降级→HITL
             ├─ Hook:wrap_model_call / wrap_tool_call 审计 + 耗时
             └─ 记忆:checkpointer(短期会话)+ store(长期画像,按 user_id 隔离)
        模型:DeepSeek(主)+ 独立备胎(Ollama 或另一个云服务商) · LangSmith 全链路追踪
```

**依赖说明**:向量库按课件用 **Milvus**(第10章 §2.5.2 p52),Embedding 走
**云端 OpenAI 兼容网关**(第10章 §2.4.2 p48-49,第10章全程未用 Ollama)。
Milvus 需要 Docker/WSL2;尚未拉起时可把 `.env` 的 `KB_BACKEND` 设为 `chroma` 过渡。
本机 Ollama 仅保留给"本地验证模型降级"这一条路径。

## 本地运行(在 cmd 里跑不起来看这里)

项目环境是一个 **conda 环境**(`conda create -p .venv` 创建)。新开的 cmd 里默认的 `python` 是 **conda base**(`E:\developTools`),那里 **没装 langchain**,所以直接 `python src\chat_cli.py` 会报:

```
ModuleNotFoundError: No module named 'langchain_core'
```

两种正确启动方式:

**方式一:一键启动(推荐)**

```
run_chat.cmd
```

双击 `run_chat.cmd` 也行。它内部固定使用项目自己的解释器,不受当前 PATH 和是否 `conda activate` 影响,并且会把 cmd 码页切成 UTF-8(否则中文输入输出会乱码)。

M3 中间件版 Agent(PII 脱敏/长对话压缩/模型降级/GPA 前确认/审计日志):

```
run_mw.cmd
```

M4 记忆版 Agent(多用户登录/会话落盘重启续聊/长期画像):

```
run_mem.cmd
```

M6 Web 版(浏览器聊天,流式输出 + 敏感操作网页确认):

```
run_web.cmd
```

然后浏览器打开 http://127.0.0.1:8000。
登录后在右上角「个人数据」录入自己的课程与成绩；GPA 只根据该账号录入的成绩计算。
课程时间来自演示排课，尚未连接学校选课系统。
新注册用户名采用「3 位大写专业缩写 + 7 位数字」格式；密码至少 8 位，
且同时包含字母和数字。旧账号仍可按原凭证登录。

**方式二:手动激活环境**

```
conda activate "E:\Campus Copilot\.venv"
python src\chat_cli.py
```

**坑位备忘**

| 现象 | 原因 |
|---|---|
| `ModuleNotFoundError: No module named 'langchain_core'` | 用的是 conda base 或系统 Python,不是项目环境 |
| `.venv\Scripts\python` 报「不是内部或外部命令」 | conda 环境的解释器在 **`.venv\python.exe`**,没有 `Scripts\python.exe` |
| 中文乱码 | cmd 默认码页是 GBK,先用 `chcp 65001`,或直接用 `run_chat.cmd` |
| PyCharm 里运行报同样的模块错误 | 项目 SDK 目前是 `Python 3.11`(没装依赖),要改成 `E:\Campus Copilot\.venv\python.exe` |
| `KeyError: 'DEEPSEEK_API_KEY'` | 当前目录下找不到 `.env`,请在项目根目录运行 |
| 政策类问题回「知识库未接入」 | 知识库还没建:需 Milvus 已启动 + `.env` 配好 `EMBED_API_KEY`,再跑 `scripts/build_kb.py` |
| 想先跳过 Milvus 试用 | `.env` 设 `KB_BACKEND=chroma` 走本地 Chroma 过渡后端 |

对话中退出:输入「退出」或 `quit`。

## 质量与部署

- **评估**:2026-09-26 完整重跑 **32/32(100%)**,工具路由 **27/27(100%)**,
  报告见 `docs/eval-results.md`;
  评估方法与失败归因记录在 `docs/milestones.md`。
  口径说明:评估为**自建跑批 + 关键词断言**(规则评估器雏形),
  **未使用** LangSmith 的 Datasets/Evaluators(课件第03章 §1.2 p1-2 讲的那条路);
  路由判定以 **ToolMessage 为准**(真的执行过才算命中)
- **追踪**:LangSmith 全链路 tracing(四个环境变量见 `.env.example`;
  调用处带 `run_name`/`tags`/`metadata`,可按用户与会话筛选)
- **简历素材**:`docs/resume.md`(数字均来自实测)
- **课程对齐**:`docs/course-map.md`(逐章页码锚点 + 课件未覆盖清单)
- **Docker 部署**:`Dockerfile` + `docker-compose.yml`(app + PostgreSQL + Milvus;
  production profile 另启 Caddy/HTTPS)。本机已验证 Compose 构建、独立
  app + PostgreSQL + Chroma + Caddy 启动、本机 HTTPS、SSE/HITL、106 片段持久化及
  10 条非空成绩的 PostgreSQL 备份恢复；
  Milvus/Embedding 链路另通过 M5 实测。真实域名证书与云服务器尚未验证，见 `docs/deploy.md`。

## 数据策略(本项目的真正难点,先看 docs/data-plan.md)

- 非结构化:**只采集学校官网公开信息**(学籍管理规定、培养方案、奖学金办法等),爬取即合规
- 结构化:课表/教室/校历先手工构造模拟数据,格式对齐真实 schema,后续可接真实数据源
- 详见 `docs/data-plan.md`

## 里程碑

M0-M6 按课程章节顺序滚动开发,学到哪做到哪 → `docs/milestones.md`

## 简历预览(项目完工后回填真实数字)

> 独立开发校园智能助手(基于 LangChain 1.x):双数据源架构 —— 教务文档 RAG(Milvus 向量检索 + 元数据过滤)与结构化课程数据(SQLite)经多工具 Agent 路由协同;PostgreSQL 多用户会话隔离与长期用户画像;中间件治理(长对话摘要/HITL/PII/模型降级);LangSmith 全链路追踪与评估集(N 个问答对,准确率 X%);Docker Compose 部署,服务 N 名同学。

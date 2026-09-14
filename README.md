# Campus Copilot — 校园智能助手

> 面向大学生的校园生活智能体:教务政策问答(RAG)+ 课表/校历/成绩等结构化查询(Tools)+ 个性化记忆。
> 兼作尚硅谷 LangChain 课程(BV1rv7A6oEeP)的毕业项目 —— 课程 11 个核心模块各有落点,形成"学完证据链"。

## 项目定位

一句话:**把散落在教务处网站、通知公告、培养方案里的信息,变成一个能对话的助手。**

它不是玩具的理由:
1. **双数据源**:非结构化文档(RAG)+ 结构化数据库(SQLite)—— 两套检索范式在一个 Agent 里协同
2. **多用户场景**:部署后同学真的能用,有真实反馈迭代(会话隔离、个性化画像因此不是摆设)
3. **完整工程链路**:中间件治理 + Hook 审计 + LangSmith 评估 + Docker 部署 —— 面试官问"生产化考虑"有得答

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

| 课程模块 | 落点 | 状态 |
|---|---|---|
| 模型调用(P11-24) | DeepSeek API + Ollama 双通道、init_chat_model、流式 | 未开始 |
| 提示词模板(P25-32) | 系统提示词模板化、MessagesPlaceholder 注入历史 | 未开始 |
| 工具(P33-40) | 5 个自定义工具(@tool + args_schema):课表查询 / 教学周计算 / GPA 计算 / 空教室 / 课程先修关系 | 未开始 |
| 结构化输出(P41-50) | GPA 分析报告(Pydantic schema:总绩点/拉分课程/建议)、课程推荐结果 | 未开始 |
| Agent(P51-63) | create_agent 组装 + 错误处理 + 流式;工具路由混合 RAG 与 DB | 未开始 |
| 中间件(P64-78) | Summarization(长对话)/ HITL(敏感操作确认)/ PII / ModelFallback(DeepSeek→Ollama) | 未开始 |
| Hook(P79-85) | wrap_model_call / wrap_tool_call:日志 + 耗时审计 | 未开始 |
| 短期记忆(P86-95) | PostgreSQL 多用户会话持久化 + 消息裁剪 | 未开始 |
| 长期记忆(P96-101) | 用户画像(年级/专业/培养进度/常问话题)在工具内读写 | 未开始 |
| RAG(P102-116) | 教务文档管线:加载→切分→Embedding→Milvus(带 school/doc_type 元数据过滤) | 未开始 |
| 部署(P89-91,117-120) | FastAPI + Docker Compose(app + Milvus + PG)上云 | 未开始 |

## 架构

```
用户 ─ Web/FastAPI(流式)
        └─ Agent(create_agent, system_prompt, 5 tools)
             ├─ [RAG] 教务文档 → Milvus 向量检索(元数据过滤)
             ├─ [DB] SQLite:课表/校历/教室/课程库
             ├─ 中间件管道:摘要 / HITL / PII / 降级 / 限流
             ├─ Hook:调用审计 + 耗时统计
             └─ 记忆:PG 短期会话 + 长期用户画像
        模型:DeepSeek(主)+ Ollama(备) · 全链路 LangSmith 追踪
```

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

对话中退出:输入「退出」或 `quit`。

## 数据策略(本项目的真正难点,先看 docs/data-plan.md)

- 非结构化:**只采集学校官网公开信息**(学籍管理规定、培养方案、奖学金办法等),爬取即合规
- 结构化:课表/教室/校历先手工构造模拟数据,格式对齐真实 schema,后续可接真实数据源
- 详见 `docs/data-plan.md`

## 里程碑

M0-M6 按课程章节顺序滚动开发,学到哪做到哪 → `docs/milestones.md`

## 简历预览(项目完工后回填真实数字)

> 独立开发校园智能助手(基于 LangChain 1.x):双数据源架构 —— 教务文档 RAG(Milvus 向量检索 + 元数据过滤)与结构化课程数据(SQLite)经多工具 Agent 路由协同;PostgreSQL 多用户会话隔离与长期用户画像;中间件治理(长对话摘要/HITL/PII/模型降级);LangSmith 全链路追踪与评估集(N 个问答对,准确率 X%);Docker Compose 部署,服务 N 名同学。

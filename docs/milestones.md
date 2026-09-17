# 里程碑与进度

> 顺序 = 课程章节顺序,学到哪做到哪。每个里程碑有验收标准(DoD),全勾完才算完成。
> 状态:未开始 / 进行中 / 完成

## M0 环境就绪(前置:P7-P24)- 完成(2026-09-07)

- [x] conda 虚拟环境 `campus-copilot`,Python 版本锁定(项目内 .venv,Python 3.13.15,conda-forge)
- [x] `.env` 配置 DEEPSEEK_API_KEY,.gitignore 生效(已验证 check-ignore)
- [x] 脚本一:调 DeepSeek 完成对话(invoke)+ 流式(stream)——src/hello_stream.py 验证通过
- [x] LangSmith 接入,trace 可见(tracing 开启,项目名 campus-copilot,上报无报错)
- [x] git 初始化,首个 commit(fa6aefc,身份:Kiyotaka)

**DoD**:终端与模型流式对话 3 轮,LangSmith 有完整 trace。

## M1 多轮对话 CLI(前置:P25-P32)- 完成(2026-09-08)

- [x] ChatPromptTemplate 系统提示词(校园助手人设)——src/prompt.py
- [x] MessagesPlaceholder 注入对话历史,内存版多轮——src/chat_cli.py
- [x] CLI 循环交互(input 循环 + 退出指令 + Ctrl+C 处理)

**DoD**:连续对话记得上文;改提示词只动模板。——三轮管道测试通过(第 2 轮准确回答用户姓名与专业);人设集中在 prompt.py。

## M2 Agent + 结构化数据工具(前置:P33-P63)- 完成(2026-09-14)

- [x] 造种子数据 + 建库脚本:`data/structured/seed_*.json` → SQLite(5 张表;scripts/init_db.py 可重跑,6 张库表 105 行)
- [x] 工具 1 `query_timetable`:查课表/空教室(timetable.py:find_empty_classrooms + query_course_schedule)
- [x] 工具 2 `get_academic_week`:今天第几教学周/距假期周数(含开学前/复习/考试/假期边界)
- [x] 工具 3 `calculate_gpa`:Pydantic 结构化分析报告(GpaReport:总学分/GPA/最强/最弱/建议)
- [x] 工具 4 `query_course`:课程信息/先修链(递归展开 + 反向依赖查询)
- [x] 工具 5 `search_policy`(占位):文件名关键词匹配,无库时诚实声明
- [x] create_agent 组装 + 错误处理 + 流式(assistant.py;stream_mode="messages" + 节点过滤)

**DoD**:「明天上午哪有空教室」「现在第几周」「这些成绩 GPA 多少、哪门拉分」全部正确路由。——管道实测通过:空教室 22 间(24-2 占用验算一致)、GPA 3.6(手算一致)、CS301 先修链 CS301←DS201←CS101 正确。

## M3 中间件 + Hook(前置:P64-P85)- ✅ 完成(2026-09-16)

- [x] SummarizationMiddleware 长对话压缩(trigger: 30 条消息,keep 最近 10 条)
- [x] HumanInTheLoopMiddleware:calculate_gpa(敏感成绩数据)执行前确认
- [x] PIIMiddleware:自定义检测器过滤中国/马来手机号 + 8 位学号(redact 策略)
- [x] ModelFallbackMiddleware:DeepSeek→Ollama(qwen3:0.6b)自动切换
- [x] wrap_model_call / wrap_tool_call:审计日志 + 耗时(stderr)
- [x] 多中间件执行顺序验证(PII→压缩→模型审计→降级→工具审计→HITL)

**实现文件**:`src/agent/middleware.py`(全部中间件)、`src/chat_agent_mw_cli.py`(M3 CLI,
含 HITL 中断处理)、`run_mw.cmd`(一键启动)、`scripts/test_m3.py`(DoD 自动验证,全部通过)。

**踩坑记录(面试素材)**:
1. `PIIMatch` 不在 `langchain.agents.middleware` 顶层,要从 `.pii` 子模块导入
2. `ModelFallbackMiddleware(first, *others)` 是位置参数,不接受关键字
3. HITL 的 `interrupt_on` 配置里 `allowed_decisions` 是必填,漏了会静默不生效
4. HITL 的 resume 必须有 checkpointer——`Command(resume=...)` 没有持久化层会直接 RuntimeError;
   因此 M3 提前引入 `InMemorySaver`,M4 换 PostgreSQL 即可
5. 多 stream_mode 时产出是 `(mode, payload)`,mode 在前,和直觉相反
6. resume 格式:`Command(resume={"decisions": [{"type": "approve"}]})`
7. 备胎模型必须支持工具调用:deepseek-r1 系列没有 tools 模板,Agent 场景 400,
   换 qwen3:0.6b(ollama pull)
8. deepseek-chat 偶发英文过渡句(非确定性),提示词已加固但无法 100% 消除

**DoD**:配错 API key 不崩自动降级 ✓(错误 key→qwen3 兜底回答);20 轮对话不超限 ✓
(10 轮喂入后压缩至 8 条,暗号记忆保留);工具耗时在日志可见 ✓(`[工具] calculate_gpa 耗时 0.004s`)。

## M4 记忆与多用户(前置:P86-P101)- ✅ 完成(2026-09-16)

- [x] 短期记忆持久化:按 session 隔离,重启可恢复(SQLite 落盘 `data/memory.db`)
- [x] 消息裁剪治理:由 M3 的 SummarizationMiddleware 承担(trigger 30 条/keep 10 条)
- [x] 长期记忆 Store:用户画像(年级/专业/常问话题)按 user_id 隔离
- [x] 工具内读写长期记忆:`save_profile`/`read_profile` 两个工具 +
      `calculate_gpa` 分析后自动把 GPA 结果写进画像

**实现文件**:`src/agent/memory.py`(checkpointer+store 工厂,`MEMORY_BACKEND` 开关)、
`src/tools/profile.py`(画像工具)、`src/chat_memory_cli.py`(多用户 CLI)、
`run_mem.cmd`(一键启动)、`scripts/test_m4.py`(DoD 自动验证,全部通过)。

**架构决策(重要偏离说明)**:原计划 PostgreSQL,但本机无 Docker、无 PG 服务,
且 pgserver 无 Windows 包 → 开发期改用 **SQLite**(langgraph-checkpoint-sqlite 的
SqliteSaver + SqliteStore,同一个 langgraph 接口)。M6 Docker Compose 起 PG 后,
设 `MEMORY_BACKEND=postgres` + 加装 langgraph-checkpoint-postgres 即切换,业务代码零改动。

**踩坑记录(面试素材)**:
1. `create_agent(middleware=None)` 会崩(内部迭代 None),不挂时必须整个省略参数
2. 工具内访问 store 用 `langgraph.config.get_store()`、用户身份用 `get_config()
   ["configurable"]["user_id"]`——CLI 传什么 configurable 键,工具里就能读什么
3. 让模型"记住信息"的测试话术里别加"回复好的即可"之类约束,会把 save_profile 挤掉
4. SQLite 落盘后,同一进程内多 agent 实例共享同一 db 文件,测试"重启恢复"用
   新建 agent 实例即可模拟,不必真重启进程

**DoD**:两个 session 互不串扰 ✓(alice 大二/bob 大一,无串扰);重启续聊 ✓
(新进程恢复 9 条消息接上话题);能答「我是大几的、常问什么」✓
(跨 thread 从画像答出年级/专业/选课/空教室,GPA 工具自动落 latest_gpa)。

## M5 RAG 知识库(前置:P102-116)- ✅ 完成(2026-09-16)

- [x] 收集 16 份公开教务文档进 `data/raw_docs/`(全部来自 www.xmu.edu.my
      官方手册/页面,`scripts/collect_docs.py` 归档,含来源 URL 元数据)
- [x] 管线:加载(md + front matter)→ RecursiveCharacterTextSplitter(600/100)
      → Ollama bge-m3 向量化 → Chroma 持久化(元数据:source/doc_type/title)
- [x] `search_policy` 升级:向量检索 + doc_type 元数据过滤(无命中回退全库)
- [x] 回答附带来源引用(片段带《文档标题》+ 官方 URL,提示词强制引用)
- [x] 抽查 10 问:检索层 10/10 命中正确文档(自动验证,`scripts/test_m5.py`)

**实现文件**:`scripts/collect_docs.py`(文档归档)、`scripts/build_kb.py`(建库,
16 文档 → 48 片段)、`src/tools/policy.py`(向量检索版)、`scripts/test_m5.py`。

**架构决策(偏离说明)**:原计划 Milvus,但其标准版必须 Docker(本机无),
Milvus Lite 不支持 Windows → 开发期用 **Chroma**(嵌入式、Windows 原生、
持久化、元数据过滤),LangChain 接口与 Milvus 同构,M6 上 Docker 后可换。
Embedding 用本机 Ollama 的 **bge-m3**(多语言,中英混合文档一把抓),
不依赖云端 API,与"DeepSeek 主力 + Ollama 本地"的双通道故事一致。

**数据采集说明**:官网手册 PDF 是图片版无文本层(pypdf 抽不出字),
通过搜索引擎已建好的 PDF 索引收割官方手册原文片段 + 官网页面直接抓取,
每份文档标注来源 URL,合规红线(只用公开信息)未破。

**踩坑记录(面试素材)**:
1. langchain-chroma 1.1.0 的元数据过滤参数叫 `filter`,`where` 会报
   "got multiple values for keyword argument 'where'"(内部已有 where)
2. 官网 PDF 手册是图片型:工具链抽不出文本时,搜索引擎索引是有效来源
3. Chroma 的 collection 清空要删了重建(`client.delete_collection`),
   没有"先查再增量"的 upsert 语义
4. 手动解析 front matter 而非引入 python-frontmatter 依赖:四个键值对而已,
   依赖最小化也是工程判断

**DoD**:问「补考和重修的区别」→ 回答准确指出 XMUM 无独立补考制度,
区分缓考(deferment,下学期第 1 周)与重修(retake,重新上课、费用规则),
命中《重修规定与费用》原文段落并给出官方 PDF 出处 ✓;10 问抽查 10/10 ✓;
doc_type 元数据过滤生效 ✓。

## M6 部署与收官(前置:P117-120 + 少量超纲)- ◐ 本地部分完成(2026-09-17)

- [x] FastAPI:对话接口 + SSE 流式 + session 管理(src/server.py;
      thread_id 会话隔离,HITL 中断跨 HTTP 请求恢复,`scripts/test_server.py` 集成测试通过)
- [x] 简单 Web 页面(src/static/index.html,零依赖手写:流式渲染/确认条/多用户入口)
- [x] Docker Compose:app + PostgreSQL(Dockerfile/compose/.dockerignore 已写,
      本机无 Docker 未验证,首次部署检查清单写在 compose 头部注释)
- [x] LangSmith 评估集 31 问答对,记录准确率(scripts/eval_set.json + eval_m6.py;
      综合通过率 81%(两轮 84%/81%,差异来自 LLM 工具调用非确定性),
      路由 22/26,报告 docs/eval-results.md)
- [x] README 完工:映射表全勾 + 运行指南 + 评估数字
- [x] 简历段落回填真实数字(docs/resume.md)
- [ ] **部署云服务器,同学可用(需要用户操作:买/租服务器 → Docker 部署 → 公网访问)**
- [ ] 发链接收集同学反馈(依赖上一步)

**实现文件**:`src/server.py`、`src/static/index.html`、`run_web.cmd`、
`scripts/test_server.py`、`scripts/eval_set.json`、`scripts/eval_m6.py`、
`docs/eval-results.md`、`docs/resume.md`、`Dockerfile`、`docker-compose.yml`。

**M6 踩坑记录(面试素材)**:
1. uvicorn `src.server:app` 只把项目根放进 sys.path,`agent` 等兄弟包解析不到
   —— server.py 顶部手动 sys.path.insert
2. SSE 按 1024 字节读流会把 UTF-8 多字节字符劈断,要用 codecs 增量解码器
3. 评估方法论:必须每轮全新 thread_id,否则 checkpointer 里的旧问答会让
   模型"复述而不调工具",路由测量被污染(实测从 90% 掉到 32% 的教训)
4. 评估集抓出 PII 真 bug:中文紧贴数字(「手机138…」)时 `\b` 失效
   (汉字也算词字符),改用 `(?<!\d)/(?!\d)` 数字环视修复
5. 元数据过滤的双刃剑:模型按问题表面选 doc_type(费用→finance),
   真条文却在别的类(重修费→academic)——解法是过滤+全库混合检索按分数合并
6. LLM 工具调用非确定性:同一评估集两轮失败集合不同(84%/81%),
   属模型行为问题,加固方向 tool_choice 强制/降温,已记录为已知问题

**DoD**:发链接同学能玩并给出反馈(待云部署);简历项目段落定稿 ✓(docs/resume.md)。

## 进度日志

| 日期 | 事项 |
|---|---|
| 2026-09-02 | study-buddy 立项(后被替换) |
| 2026-09-03 | 用户判断 study-buddy 偏 toy,重新立项 campus-copilot;骨架搭建完成 |
| 2026-09-07 | 基建第 1 项:项目落位 E:\Campus Copilot,conda 环境(Python 3.13.15)+ git 身份配置 + 首个 commit。坑:Git Bash 传 POSIX 路径给 conda 需转 Windows 风格;defaults 频道缺 py3.13,改用 conda-forge |
| 2026-09-07 | 基建第 2、3 项:DeepSeek key 配置并验证;依赖锁定安装(langchain 1.2.12 全家桶);src/hello_stream.py 跑通 invoke + stream。坑:.env 预置 LANGSMITH_TRACING=true 但无 key 导致 401 报错刷屏,已改 false 待接入后再开 |
| 2026-09-07 | M0 收尾:LangSmith key 接入,tracing 开启(LANGSMITH_PROJECT=campus-copilot),上报验证通过,M0 闭环 |
| 2026-09-08 | M1 完成:model.py(模型工厂)+ prompt.py(ChatPromptTemplate + MessagesPlaceholder)+ chat_cli.py(消息列表内存历史 + CLI 循环)。三轮管道测试:记忆(答出姓名专业)、人设(承认能力边界)、退出全部通过。参考实现由向导编写,用户自写一遍吸收中 |
| 2026-09-14 | 学校确认:厦门大学马来西亚分校(XMUM)。种子数据完成:校历用官网真实数据(九月学期 2026,14 教学周),课程/教室/课表/成绩为参考真实结构的模拟数据;JSON 合法性与先修链完整性已验证 |
| 2026-09-14 | M2 完成:scripts/init_db.py(6 表 105 行)→ 6 个工具(timetable/academic/gpa/courses/policy)→ create_agent 组装。管道验收:三类指令路由正确,空教室 22 间与 GPA 3.6 均手算复核一致。已知待优化:Agent 工具调用前偶有英文前言,已在 system_prompt 加中文约束 |
| 2026-09-16 | M3/M4/M5 一日连完:中间件栈 6 层 + HITL(发现 resume 必须有 checkpointer,提前引入 InMemorySaver)→ SQLite 持久记忆 + 多用户画像 → Chroma RAG(16 官方文档,检索抽查 10/10)。架构偏离:无 Docker → PG 换 SQLite、Milvus 换 Chroma、DeepSeek 无 embedding 换本地 bge-m3 |
| 2026-09-17 | M6 本地部分完成:FastAPI/SSE/Web 页/HITL 跨请求恢复;31 问评估集两轮 84%/81%(差异定位为 LLM 非确定性);评估抓出 PII `\b` 中文失效真 bug 并修复;Docker 三件套已写未本机验证;简历段落定稿。剩余:云服务器部署 + 同学反馈(用户操作) |

# 里程碑与进度

> 顺序 = 课程章节顺序,学到哪做到哪。每个里程碑有验收标准(DoD),全勾完才算完成。
> 状态:未开始 / 进行中 / 完成

> 当前范围（2026-10-02）：仅保证本机运行。服务器部署、HTTPS 代理与上线任务已移出当前计划；旧提交可用于追溯已移除的实现。本文件早期日志是历史记录，不代表当前待办。

---

## ⚠️ 本文件的修订说明(2026 改造)

按课件全量改造后,本文件有两处历史写法需要修正,阅读时请注意:

1. **页码引用已废弃**。原先每个里程碑写"前置:P7-P24 / P25-P32 / P33-P63 / P64-P85 /
   P86-P101 / P102-116",这套编号**在课件里不存在**(全课件检索 `P11`~`P120` 零命中),
   且按章内页码解释会越界(如"结构化输出 P41-50",而第 06 章总共只有 35 页)。
   现在统一改为 `第0X章 §X.Y(pN)` 形式,完整映射见 **`docs/course-map.md`**。
   下表给出对照:

   | 里程碑 | 原写法 | 实际对应 |
   |---|---|---|
   | M0 | P7-P24 | 第01章 概述(p1-25)、第02章 §1-§3(p1-18) |
   | M1 | P25-P32 | 第04章 §2.3-§2.4(p28-42);MessagesPlaceholder 实际在 §2.4.2 p38 |
   | M2 | P33-P63 | 第05章(p1-44)、第06章(p1-35)、第07章 §1-§6(p1-34) |
   | M3 | P64-P85 | 第08章 §2.1-§2.3(p7-24)、§3(p34-53)、§5(p80-115) |
   | M4 | P86-P101 | 第09章 §2(p6-37)、§3(p38-59) |
   | M5 | P102-116 | 第10章(p1-66) |
   | M6 | P117-120 | **课件无"部署"章**;仅 ch01 p4 / ch02 §4 p19 / ch03 p2 三处概念性提及 |

2. **技术选型的偏离说明已更新**。原先为了绕开"本机无 Docker / 无 PG"而改用
   Chroma + SQLite,并写进了 M4/M5 节。**课件第10章 §2.5.2(p52)明确用 Milvus**,
   §2.2(p14-18)实操的是 PostgresSaver。现按课件回正,迁移状态见各节末尾的
   "🔁 改造状态"。

---

## M0 环境就绪(第01章 p1-25 + 第02章 §1-§3 p1-18)- 完成(2026-09-07)

- [x] conda 虚拟环境 `campus-copilot`,Python 版本锁定(项目内 .venv,Python 3.13.15,conda-forge)
- [x] `.env` 配置 DEEPSEEK_API_KEY,.gitignore 生效(已验证 check-ignore)
- [x] 脚本一:调 DeepSeek 完成对话(invoke)+ 流式(stream)——src/hello_stream.py 验证通过
- [x] LangSmith 接入,trace 可见(tracing 开启,项目名 campus-copilot,上报无报错)
- [x] git 初始化,首个 commit(fa6aefc,身份:Kiyotaka)

**DoD**:终端与模型流式对话 3 轮,LangSmith 有完整 trace。

## M1 多轮对话 CLI(第04章 §2.3-§2.4 p28-42)- 完成(2026-09-08)

- [x] ChatPromptTemplate 系统提示词(校园助手人设)——src/prompt.py
- [x] MessagesPlaceholder 注入对话历史,内存版多轮——src/chat_cli.py
- [x] CLI 循环交互(input 循环 + 退出指令 + Ctrl+C 处理)

**DoD**:连续对话记得上文;改提示词只动模板。——三轮管道测试通过(第 2 轮准确回答用户姓名与专业);人设集中在 prompt.py。

## M2 Agent + 结构化数据工具(第05章 p1-44 + 第06章 p1-35 + 第07章 §1-§6 p1-34)- 完成(2026-09-14)

- [x] 造种子数据 + 建库脚本:`data/structured/seed_*.json` → SQLite(5 张表;scripts/init_db.py 可重跑,6 张库表 105 行)
- [x] 工具 1 `query_timetable`:查课表/空教室(timetable.py:find_empty_classrooms + query_course_schedule)
- [x] 工具 2 `get_academic_week`:今天第几教学周/距假期周数(含开学前/复习/考试/假期边界)
- [x] 工具 3 `calculate_gpa`:Pydantic 结构化分析报告(GpaReport:总学分/GPA/最强/最弱/建议)
- [x] 工具 4 `query_course`:课程信息/先修链(递归展开 + 反向依赖查询)
- [x] 工具 5 `search_policy`(占位):文件名关键词匹配,无库时诚实声明
- [x] create_agent 组装 + 错误处理 + 流式(assistant.py;stream_mode="messages" + 节点过滤)

**DoD**:「明天上午哪有空教室」「现在第几周」「这些成绩 GPA 多少、哪门拉分」全部正确路由。——管道实测通过:空教室 22 间(24-2 占用验算一致)、GPA 3.6(手算一致)、CS301 先修链 CS301←DS201←CS101 正确。

## M3 中间件 + Hook(第08章 §2.1-§2.3 p7-24、§3 p34-53、§5 p80-115)- ✅ 完成(2026-09-16)

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

## M4 记忆与多用户(第09章 §2 p6-37、§3 p38-59)- ✅ 完成(2026-09-16)

- [x] 短期记忆持久化:按 session 隔离,重启可恢复(SQLite 落盘 `data/memory.db`)
- [x] 消息裁剪治理:由 M3 的 SummarizationMiddleware 承担(trigger 30 条/keep 10 条)
- [x] 长期记忆 Store:用户画像(年级/专业/常问话题)按 user_id 隔离
- [x] 工具内读写长期记忆:`save_profile`/`read_profile` 两个工具 +
      `calculate_gpa` 分析后自动把 GPA 结果写进画像

**实现文件**:`src/agent/memory.py`(checkpointer+store 工厂,`MEMORY_BACKEND` 开关)、
`src/tools/profile.py`(画像工具)、`src/chat_memory_cli.py`(多用户 CLI)、
`run_mem.cmd`(一键启动)、`scripts/test_m4.py`(DoD 自动验证,全部通过)。

**架构决策(偏离说明)**:原计划 PostgreSQL,但本机无 Docker、无 PG 服务,
且 pgserver 无 Windows 包 → 开发期改用 **SQLite**(langgraph-checkpoint-sqlite 的
SqliteSaver + SqliteStore,同一个 langgraph 接口)。设 `MEMORY_BACKEND=postgres` 即切换,
业务代码零改动。

**🔁 改造状态(按课件回正)**:课件第09章 §2.2(p14-18)实操的是 **PostgresSaver**,
SQLite 只是本地替代(课件 §2.1.3 p11 也提到 SqliteSaver 属合法选项)。
**第三批已完成**,`.env` 默认 `MEMORY_BACKEND=postgres`:
- `src/agent/memory.py` 重写:PG 为主路径,SQLite 保留给无 PG 环境;
  连接仍用 ExitStack 缓存,但新增 **`close_memory()`**,由 `src/server.py` 的
  FastAPI lifespan 调用(旧版从不 close,没有优雅停机)
- 用户身份从 `get_config()["configurable"]["user_id"]` 改为
  **`context_schema` + `ToolRuntime.context`**(课件 §4.2 p74-80),
  并去掉旧版 `"default"` 兜底 —— 那是一条真实的跨用户画像泄漏路径
- `gpa.py` 的静默 `except: pass` 改为 log + 结构化返回(课件 §4.2 p77 的示范)
- `DB_PATH` 从相对路径改为项目根绝对路径 + `MEMORY_DB_PATH` 可注入
- `scripts/test_m4.py` 改为**在专用测试库 campus_test 上跑**,
  不再删生产库;实测跑完 campus 库行数保持 0,隔离成立
- ✅ **PG 路径首次验证通过**:`PostgresSaver`/`PostgresStore` 落库可读,
  setup() 建出课件 p16-17 的那几张表(checkpoints / checkpoint_blobs /
  checkpoint_writes / checkpoint_migrations + store / store_migrations)

**踩坑记录(面试素材)**:
1. `create_agent(middleware=None)` 会崩(内部迭代 None),不挂时必须整个省略参数
2. 工具内访问 store:`langgraph.config.get_store()` / `get_config()["configurable"]["user_id"]`
   **是旧写法**。课件第09章 §4(p60-80)教的是 `runtime.store` + `runtime.context`,
   且 `get_store()`/`get_config()` 在整章 6303 行里零出现。
   改造后统一走 `ToolRuntime[UserContext]`(§4.2 p74-80);
   课件 p80 第 5 条还提醒:工具里必须显式写第一个泛型,否则底层认为 context 为 None
3. 让模型"记住信息"的测试话术里别加"回复好的即可"之类约束,会把 save_profile 挤掉
4. SQLite 落盘后,同一进程内多 agent 实例共享同一 db 文件,测试"重启恢复"用
   新建 agent 实例即可模拟,不必真重启进程
5. `SqliteSaver/SqliteStore.from_conn_string()` **都是上下文管理器**,课件给的
   `with ... as ...` 写法才是标准用法;项目的模块级 `ExitStack` 是"进程级长连接",
   功能可行但需要显式 close,否则异常路径会漏连接(第三批一并处理)

**DoD**:两个 session 互不串扰 ✓(alice 大二/bob 大一,无串扰);重启续聊 ✓
(新进程恢复 9 条消息接上话题);能答「我是大几的、常问什么」✓
(跨 thread 从画像答出年级/专业/选课/空教室,GPA 工具自动落 latest_gpa)。

## M5 RAG 知识库(第10章 p1-66)- ✅ 完成(2026-09-16)

- [x] 收集 16 份公开教务文档进 `data/raw_docs/`(全部来自 www.xmu.edu.my
      官方手册/页面,`scripts/archive_docs.py` 写入快照,含来源 URL 元数据)
- [x] 管线:加载(md + front matter)→ 按标题 + 递归切分(300/80 + `add_start_index`)
      → 云端 bge-m3 向量化 → Milvus 持久化(元数据:source/doc_type/title/filename)
      ※ 旧记录为"600/100 → Ollama bge-m3 → Chroma",已按课件回正,见下方改造状态
- [x] `search_policy` 升级:向量检索 + doc_type 元数据过滤(无命中回退全库)
- [x] 回答附带来源引用(片段带《文档标题》+ 官方 URL,提示词强制引用)
- [x] 抽查 10 问:检索层 10/10 命中正确文档(自动验证,`scripts/test_m5.py`)

**实现文件**:`scripts/archive_docs.py`(文档快照写入器)、`scripts/build_kb.py`(建库)、
`src/kb.py`(向量库与 Embedding 统一入口,建库与检索共用)、
`src/tools/policy.py`(向量检索版)、`scripts/test_m5.py`。

**🔁 改造状态(按课件回正)**:
- **向量库**:Chroma → **Milvus**(课件 §2.5.2 p52"这里我们使用 Milvus")。
  代码已切(默认 `KB_BACKEND=milvus`),**待第二批**在 Docker 起来后重建库。
- **Embedding**:Ollama bge-m3 → **云端 OpenAI 兼容网关**(课件 §2.4.2 p48-49;
  **第10章全程未用 Ollama**)。模型仍选 bge-m3(课件 §2.4.1 p47 模型表:
  多语言 / 1024 维 / 8192 序列长度),与语料"英文原文 + 中文要点"混排匹配良好。
- **切分策略重做**(实测依据):旧配置 `chunk_size=600 / overlap=100` 在 16 份语料
  (共 19,194 字符)上**几乎不起作用**(最大块 593,从未触顶,边界完全由 Markdown 空行决定);
  且实测在 600 下**加中文 separators 输出逐块完全相同**。现改为
  **300/80 + 中文 separators + Markdown 按标题预切 + `add_start_index=True`**
  (课件 §2.3.3 p25-26/p31-33、§2.3.4 p36/p43-46),产出 106 片段(旧 48),
  每个片段都带 `h1`/`start_index`/`doc_type`。
- **距离度量修正**:旧版建 Chroma 时没指定度量,chromadb 默认 l2,导致
  `similarity_search_with_relevance_scores` 走欧氏换算 —— 对外展示的"相关度"
  与课件 p53 的 `metric_type="COSINE"` 不是一回事。已在 `src/kb.py` 显式设
  `hnsw:space=cosine`(Chroma)与 `metric_type=COSINE`(Milvus)。
- **脚本命名**:原 `collect_docs.py` 名实不符(474 行里唯一 import 是 `pathlib`,
  16 份文档硬编码在 `DOCS` 常量),已**更名为 `archive_docs.py`** 并在 docstring
  写明"不含网络采集",同时删掉两个从未被生成过的"抓取临时文件"的清理代码。

**架构决策(偏离说明)**:课件用 Milvus,其标准版必须 Docker(本机原先无),
Milvus Lite 不支持 Windows —— 这是当初改用 Chroma 的原因。现按课件回正,Chroma
仅作为 Milvus 未就绪时的过渡后端保留(`.env` 一行切换,建库与检索共用同一开关)。

**数据采集说明**:官网手册 PDF 是图片版、无文本层(pypdf 抽不出字),
这正是课件第10章 §2.2.4(p12-16)列出的"扫描版 PDF"挑战;课件给的解法是
**MinerU 在线解析**(p13-16,需 `MINERU_API_TOKEN`)。本项目暂未接入,
因此正文以**人工整理并固化为快照**的形式落库,保证离线可复现、不依赖网络,
来源 URL 逐个标注在 front matter 里。⚠️ 注意:快照是整理稿,
不应表述为"逐字摘录官方原文"。

**踩坑记录(面试素材)**:
1. langchain-chroma 1.1.0 的元数据过滤参数叫 `filter`,`where` 会报
   "got multiple values for keyword argument 'where'"(内部已有 where)。
   ⚠️ 但**别归因给课件**:课件 p62 用的 `filter` 是 **pymilvus 原生字符串表达式**
   (`client.query(filter="id >= 0")`),与 Chroma 的字典 `filter` 只是同名不同源 ——
   课件没用 LangChain 的向量库封装,对此没有结论
2. 官网 PDF 手册是图片型:工具链抽不出文本时,搜索引擎索引是有效来源
3. Chroma 的 collection 清空要删了重建(`client.delete_collection`),
   没有"先查再增量"的 upsert 语义
4. **Milvus 的元数据过滤参数是 `expr` 字符串表达式**(如 `doc_type == "exam"`),
   不是 Chroma 那种字典 `filter` —— 检索层必须按后端分支处理
5. **langchain-milvus 的 `_select_relevance_score_fn` 会读取 index_params 里的
   `metric_type`** 来决定分数归一化;不传 index_params 会退化成 L2 口径并打警告,
   所以初始化时必须显式传 `index_params={"metric_type": "COSINE", ...}`
6. 手动解析 front matter 而非引入 python-frontmatter 依赖:四个键值对而已,
   依赖最小化也是工程判断

**DoD**:问「补考和重修的区别」→ 回答准确指出 XMUM 无独立补考制度,
区分缓考(deferment,下学期第 1 周)与重修(retake,重新上课、费用规则),
命中《重修规定与费用》原文段落并给出官方 PDF 出处 ✓;10 问抽查 10/10 ✓;
doc_type 元数据过滤生效 ✓。

## M6 本机 Web 与评估收官 - 本地验证记录（2026-09-26，范围更新于 2026-10-02）

> FastAPI / SSE 全课程无教学，本机 Web 入口属**超纲自主决策**，
> 详见 `docs/course-map.md` §二。

- [x] FastAPI:对话接口 + SSE 流式 + session 管理(src/server.py;
      thread_id 会话隔离,HITL 中断跨 HTTP 请求恢复,`scripts/test_server.py` 集成测试通过)
- [x] 简单 Web 页面(src/static/index.html,零依赖手写:流式渲染/确认条/多用户入口)
- [x] 自建评估集现有 32 问答对,记录准确率(scripts/eval_set.json + eval_m6.py)
      ⚠️ 口径:这是**自建跑批 + 关键词断言**(规则评估器雏形),
      **未使用** LangSmith 的 Datasets/Evaluators(课件 ch03 §1.2 p1-2 的那条路);
      路由判定以 **ToolMessage 为准**(真的执行过才算命中)
- [x] **改造后重跑:综合通过率 97%(30/31),路由 25/26 = 96%**(2026-09-19)
      历史数字:改造前 81%(两轮 84%/81%)。提升主要来自三处:
      ①温度 0.2 + `recursion_limit` 收敛 ②工具层补 `args_schema`/`parse_docstring`
      ③Milvus 知识库重建后检索 Top1 从 2/10 回到 10/10。
      剩余 2 题失败(w04 只调了 get_academic_week、g02 未调 calculate_gpa)
      均为**工具路由未触发**,属 LLM 非确定性(同一评估集两遍失败集合不同)
- [x] **最新回归:32/32、工具路由 27/27**(2026-09-26；自建关键词断言，非真实用户验收)
- [x] 登录尝试限流、本机健康检查、请求长度限制与异常脱敏
- [x] 本机 PostgreSQL / Milvus 连接、记忆持久化、SSE/HITL 验证
- [x] README 完工:映射表改为可核验的章节锚点 + 运行指南 + 评估数字
- [x] 简历段落回填真实数字(docs/resume.md)
- [ ] 完善本机启动与故障恢复体验
- [ ] 多学期数据支持、政策更新时间和本机多标签页请求验证

**实现文件**:`src/server.py`、`src/static/index.html`、`run_web.cmd`、
`scripts/test_server.py`、`scripts/eval_set.json`、`scripts/eval_m6.py`、
`docs/eval-results.md`、`docs/resume.md`。

**本机依赖与验证记录**:
| # | 事项 | 状态 |
|---|---|---|
| 1 | Python 依赖 | ✅ 已包含 fastapi / uvicorn / pymilvus / psycopg |
| 2 | 可选本机模型 | ✅ 通过 `OLLAMA_HOST` 配置；不作为 Embedding 的必需依赖 |
| 3 | 可选追踪 | ✅ LangSmith 四变量齐全，默认关闭 tracing |
| 4 | 本机 Milvus | ✅ 历史 M5 检索与引用测试通过 |
| 5 | 本机 PostgreSQL | ✅ 历史 M4 及 Web HTTP 集成测试通过 |
| 6 | 本机账号隔离 | ✅ 注册/登录/Bearer token，密码加盐哈希，身份由 token 解析 |

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
   ⚠️ 这套"混合检索"是**自研**:课件第10章未涉及 Hybrid Retrieval /
   EnsembleRetriever / BM25 / MMR / rerank(全部零命中),不要说成"课件教的"
6. LLM 工具调用非确定性:同一评估集两轮失败集合不同(84%/81%),
   属模型行为问题。加固方向中"**降温**"其实课件早有答案 ——
   ch02 §3.3(p15-16)指出 temperature 0.0-0.3 适合数据提取与分类,
   第一批已落地为 `LLM_TEMPERATURE=0.2`;另一方向是 ch05 §5(p35-39)的 `tool_choice`

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
| 2026-09-17 | **按课件全量改造 · 第一批完成**(不依赖 Docker/PG)。先还原课件素材:10 份 PDF(565 页)全文提取 + 从 `03-代码.rar`(RAR5)解出嵌套 zip,拿到官方配套代码 46 个 notebook。核心改动:①`src/model.py` 换 `init_chat_model` 并补齐 temperature/max_tokens/timeout/max_retries(课件 ch02 §3.3 p15-16)②8 个工具全部 `parse_docstring=True`,4 个加 `args_schema`(ch05 §3.1/§3.3 p15-27)③工具返回值统一 JSON 字符串(ch05 §6.4 p43)④新增 `src/prompts/` 模板库并按阶段组装,修掉"M2 裸 Agent 被要求调 save_profile"的矛盾(ch04 §2.4 p37-42)⑤新增 `src/agent/streaming.py`,消灭 5 份重复的 stream+HITL 逻辑(ch07 §9.3 p80-81)⑥用户身份改 `context_schema`+`ToolRuntime`,消灭 `profile.py` 的 `"default"` 跨用户泄漏(ch09 §4.2 p74-80)⑦中间件工厂化 + 补 ModelCallLimit/ToolCallLimit/ContextEditing(ch08 §3.1/§3.2/§3.8)⑧LangSmith 四变量补齐 + trace 带 run_name/tags/metadata(ch03 §2.3 p6、§3 p7-8)⑨`recursion_limit` 与 cfg 集中(ch07 §4.4 p26)⑩requirements/compose/.dockerignore 补齐(原先 fastapi/uvicorn 全写在注释里) |
| 2026-09-17 | 改造中实测发现的真问题:①`args_schema` 会让 Pydantic 类的 docstring **顶掉**工具描述,必须显式传 `description=` ②`model_provider="deepseek"` 需额外装 langchain-deepseek,默认改走 ch02 §2.2 p8 的 OpenAI 兼容写法 ③Chroma 建库时未指定度量 → 默认 l2,`relevant_score` 口径不是余弦,已改为 `hnsw:space=cosine` ④`chunk_size=600` 在 16 份语料上几乎不生效(最大块 593),且加中文 separators 输出逐块不变;改 300/80+按标题切+`add_start_index` 后 48→106 片段 ⑤`langgraph-store-postgres` 这个包 **不存在**(核实 PyPI 后从 requirements 移除)⑥`data/memory.db-wal`(4.1MB)曾被 git 跟踪,已补 `*.db-wal`/`*.db-shm` 并移出 |
| 2026-09-17 | 文档收尾:`docs/course-map.md` 新建(逐章页码锚点 + 课件未覆盖清单);README 映射表从不可核验的 `P11-24` 式页码改为 `第0X章 §X.Y(pN)`,并修掉"方式二"被"质量与部署"劈开的结构错位;`collect_docs.py` → `archive_docs.py` 更名,docstring 写明"不含网络采集",删掉两个从未被生成的临时文件的清理代码 |
| 2026-09-19 | **第三批完成(PostgreSQL 记忆后端)** + 两个真 bug 定位。基础设施已就绪(Docker 装好、Milvus 19530 与 PG 5432 均可达);`memory.py` 按课件 §2.2(p14-18)重写为 PG 主路径 + `close_memory()` 优雅停机;`test_m4.py` 改到专用测试库 campus_test,跑完生产库行数保持 0;**PG 路径首次验证通过**(PostgresSaver/PostgresStore 建表与读写均正常)。**两个真 bug**:①`recursion_limit=12` 导致任何带工具的请求都抛 `GraphRecursionError` —— 根因是 LangChain 1.x 把**每个中间件钩子算作一个 super-step**,实测纯聊天 8 步、单个工具 26-35 步,7 层中间件下 12 根本不够;已改为 100(兜底),真正的次数约束交给 ModelCallLimit/ToolCallLimit 两个中间件。②**`ContextEditingMiddleware(ClearToolUsesEdit(trigger=50, keep=0))` 会破坏功能** —— 工具确实被调用且返回正确画像,但结果在模型作答前被清掉,模型答"画像是空的";消融测试证实关掉它即恢复,已改为默认不启用并把踩坑写进 docstring(trigger 单位是 token、keep 默认 3) |
| 2026-09-19 | **第二批完成(Milvus 知识库)**。用户提供硅基流动 key 后:①修 `dimensions` 参数 bug —— 硅基流动对 `dimensions=1024` 直接 400(code 20015),而 bge-m3 本来就是 1024 维,已改为默认不发送(`EMBED_SEND_DIMENSIONS` 开关);②修 Milvus schema 字段缺失 bug —— `chunk_id` 被声明但元数据没有,报 `Insert missed an field`;已改为 build_kb 补齐全部已声明字段 + schema 字段 nullable + 其余走动态字段;③**106 片段成功写入 Milvus**(替代旧 48 片段 Chroma),维度 1024 / 度量 COSINE / 索引 Finished;④`get_collection_stats` 返回 row_count=0 而实际 106 行 —— 又一次印证**必须用 `query(filter=...)` 精确认数**(课件 p62 的坑) |
| 2026-09-19 | 排查检索退化(Top1 从 10/10 掉到 2/10,分数挤在 0.83-0.87,间隔仅 0.002)。定位到**硅基流动账户余额不足**(402 / code 30001),已改用本地 Ollama bge-m3 重建,Top1 恢复 10/10。⚠️ 本条当时的结论有一处**后经实测推翻**,见下方"排查方法论教训":当时写下"云端与 Ollama 同文本余弦 0.9999、两者等价",该测量本身受 token 化错误干扰,不足为据 |
| 2026-09-19 | `test_server.py` 端到端验收通过(三条全过):SSE 流式 + RAG 走 HTTP 附来源 ✓;HITL 拦截 `calculate_gpa` 且 `allowed_decisions=[approve, edit, reject]` ✓;resume 放行拿到 GPA 3.60 ✓。同时修掉该脚本的**会话污染**问题:旧版固定用户 `webtest`,checkpointer 留下历史导致模型"复述而不调工具"、HITL 不触发(实测报"这个问题你前面已经问过几次了");现改为每次运行生成唯一 user_id |
| 2026-09-19 | **重跑评估集(修复 P0 后):97%(30/31),路由 25/26(96%)** —— 较改造前 81% 提升 13 个点。但过程中先踩到一个**严重且隐蔽的 bug**:评估一度掉到 58%,表现为 11 道政策题 + 3 道聊天题"关键词未命中"(回答是**空字符串**)。逐层排查:Agent 单独跑正常 → 加 `run_name` 正常 → 子集正常,最终查到 **`ModelCallLimitMiddleware` 的 `thread_limit` 是"按会话累计"语义**(计数存 `state["thread_model_call_count"]`,由 checkpointer 持久化),一旦触顶且 `exit_behavior="end"`,该会话**后续每一轮都被立即结束、模型不再输出、且不报错**。压到 3 复现时第 3 题就开始返回空。两头都修:①`eval_m6.py` 改为**每题一个 thread**(旧版把没标 thread 的 29 题全塞进同一个 `eval-{run_id}`,355 个 checkpoint),只有显式声明同 thread 的题(如画像组 m01/m02)才共享会话;②会话级上限从 30 放宽到 200(本项目有持久化多用户会话,一轮问答约 2-3 次模型调用,30 对"聊 10 轮"就会误伤),单轮失控保护交给 `recursion_limit`。两个语义差异已写进 `middleware.py` docstring 与 `config.py` 注释 |
| 2026-09-19 | **P0 故障修复:embedding 调用方式错误导致 RAG 全面失效**。现象:问"重修要交钱吗"返回奖学金续领/成绩复查/纪律申诉;`test_m5.py` 命中率 **0/10**;所有相关度分数挤在 0.60-0.71 窄带。**根因(比"空间错配"更精确)**:`langchain_openai.OpenAIEmbeddings` 默认 `check_embedding_ctx_length=True`,此时它会用 **tiktoken 把文本切成 token id 数组**再发给 API(源码 `self.client.create(input=batch_tokens, ...)`);bge-m3 这类非 OpenAI 模型会把一串整数当文本编码,**产出语义错乱的向量而且不报错**。实测:直连带数组 input 与带字符串 input,同文本向量余弦仅 **0.26**;tiktoken 把「补考和重修有什么区别」切成 12 个 token id。**修复**:`kb.get_embeddings()` 显式传 `check_embedding_ctx_length=False`(`EMBED_CHECK_CTX_LENGTH=false`)。修复后:自查询 3/3 精确命中自己(score 0.9999)、同义 0.9910 / 无关 0.2849、10 问命中率回到 **10/10**、完整评估 **30/31(97%)**。**并且推翻了此前"两条路径向量空间不同、换后端必须重建库"的错误结论** —— 正确调用后云端与 Ollama 的 bge-m3 同文本余弦 **1.0000**,是同一个空间,云端的库可直接查 Ollama 建的库 |
| 2026-09-19 | 加**回归防线**:`test_m5.py` 新增 `[0/3] 前置自检` 两道硬检查 —— ① 用库里已存片段的**原文当 query 反查它自己**,必须召回自己(防向量空间错配);② 同义句相似度必须明显高于无关句(防"分数都差不多"的病征)。这类故障不报错、只表现为"回答不对",靠端到端问答很难第一时间定位,所以前置成断言。同时修掉 `test_filter()` 的过滤语法:旧版固定传 Chroma 风格的 `filter={"doc_type":...}`,切到 Milvus 后按后端分支改用 `expr` 字符串表达式 |
| 2026-09-19 | 记录一个**排查方法论教训**:我曾用"同一文本在两条路径下的向量余弦"来判断空间是否等价,得到 0.9999 并据此写下"两者等价"的注释 —— 但那次两条路径**都经过了同样的 token 化错误**(Ollama 走 langchain-ollama 正常,云端走 OpenAIEmbeddings 错乱,而我当时比较的不是同一对),结论是错的。**正确判据是自查询**:拿库里的原文去检索它自己,命中即同空间。这条已写进 `test_m5.py` 与 `kb.py` 的注释 |
| 2026-09-19 | **修一个我自己引入的假降级**。第一批我把降级备胎从"本机 Ollama"改成"云端同厂商便宜模型",理由是"云上不该回连开发机"。**实测证明那等于没有降级**:主备共用同一个 `DEEPSEEK_API_KEY`,而降级要应对的恰恰是"key 失效 / 余额不足 / 厂商故障"——同一个 key 一坏,主备一起挂。实测证据(坏 key 场景):`备=同厂商模型` → **401 崩掉**;`备=Ollama qwen3:0.6b` → **兜住**(实际模型 `qwen3:0.6b`)。已改为三级解析:①`LLM_FALLBACK_PROVIDER=cloud` + `LLM_FALLBACK_API_KEY`(另一家厂商的 key,跨厂商真降级,云部署推荐)②默认本机 Ollama(独立于云端)③都不可用 → **不挂中间件并打 warning** —— "没有降级"比"挂个同源备胎假装有降级"诚实,后者在真出故障时会给出同一个 401 却让人以为有兜底。`test_m3.py` 的降级用例同步改为走 `get_fallback_model()` 并打印实际模型 |
| 2026-09-19 | 交付前做了一轮**独立健康检查**(非"凭印象确认"),覆盖配置 / 知识库(含 P0 自查询防线)/ 结构化数据 / PG 记忆 / 工具层回归 / 中间件栈,七项全部通过;并清空了生产库 `campus` 里我历次测试留下的会话与画像(checkpoints/store 均为 0),交付状态干净 |

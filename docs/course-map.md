# 课程映射表(课件 ↔ 项目落点)

> 本表是"学完证据链"的唯一索引。引用格式统一为
> **`第0X章 §X.Y 小节名`**,页码锚点取自课件 PDF 的页脚
> (后文用 `pN` 简写,等于课件的第 N 页)。
>
> 素材范围:尚硅谷《LangChain 从入门到实战(2026 版)》课件 10 章,共 **565 页**
> (ch01 概述 25 · ch02 模型的创建与调用 66 · ch03 LangSmith 的使用 9 ·
> ch04 消息与提示词模板 42 · ch05 Tools 44 · ch06 结构化输出 35 ·
> ch07 智能体 83 · ch08 中间件 115 · ch09 上下文与记忆 80 · ch10 RAG 66)。
>
> ⚠️ 本文件**取代**原先 README 里那套 `P11-24 / P25-32 / … / P102-116` 的页码写法。
> 那套编号在课件里不存在(全课件 grep `P11`~`P120` 零命中),按"章内页码"
> 解释会越界(如"结构化输出 P41-50",而第 06 章总共只有 35 页)。
> 保留它只会让评审无法回溯,故整体废弃。

---

## 一、正文证据链(逐章)

### 第02章 模型的创建与调用

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §1.2 模型初始化的三个角度(p2) | `src/config.py`(参数集中在配置文件) | ✅ |
| §2.2 兼容写法:ChatOpenAI + base_url(p8) | `src/model.py:get_chat_model` | ✅ 默认走这条 |
| §2.1.1 DeepSeek 官方库 ChatDeepSeek(p4-6) | `src/model.py:_provider_kwargs` 的 `deepseek` 分支 | ◐ 需装 `langchain-deepseek` 后切 `LLM_PROVIDER=deepseek` |
| §3 init_chat_model 统一入口(p11-13) | `src/model.py:get_chat_model` | ✅ |
| §3.3 参数表:temperature / max_tokens / timeout / max_retries(p15-16) | `src/config.py` + `src/model.py` | ✅ 默认 temperature=0.2(抽取类任务) |
| §4.4 本地模型 Ollama(p24-25) | `src/model.py:get_ollama_model` | ✅ 仅本地开发/降级验证 |
| §5.1 invoke 输入三形态(p26-31) | 各 CLI 与 `src/messages.py` | ✅ |
| §5.2 流式调用(p35-36) | `src/hello_stream.py`、`src/agent/streaming.py` | ✅ |
| §5.5 失败处理 try/except(p47) | `src/model.py` 的 `RuntimeError` 指引、`src/tools/gpa.py` 工具内兜底 | ✅ |
| §6.2 profile 能力画像(p50-53) | `src/model.py` 的 `__main__` 自检 | ✅ |
| §6.3 完整参数 / model_kwargs / extra_body(p53-62) | — | ⬜ 未用(暂无需求) |
| §6.4 config / configurable_fields(p62-65) | `src/agent/runtime.py:make_config`、`src/model.py` 的 `configurable_fields` | ✅ |

### 第03章 LangSmith 的使用

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §2.3 四个环境变量(p6) | `.env.example`、`src/agent/runtime.py:setup_langsmith` | ✅ 含 `LANGSMITH_ENDPOINT`，追踪默认关闭 |
| §3 举例 3:config 里的 run_name/tags/metadata(p7-8) | `src/agent/runtime.py:make_config`,由各入口传入 | ✅ |
| §1.2 评估:Datasets & Experiments / Evaluators(p1-2) | `scripts/eval_set.json` + `scripts/eval_m6.py`(自制) | ⚠️ 见下"口径说明" |

### 第04章 消息与提示词模板

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §1.2 系统消息 = 行为说明书(p2) | `src/prompts/common.py`、`src/prompts/system.py` | ✅ |
| §1.3 消息的两种格式(p3) | `src/messages.py` | ✅ |
| §1.5.4 ToolMessage 的 tool_call_id 匹配(p13-15) | 由框架处理;项目统一用对象格式而非 dict | ✅ |
| §1.6.1 必须传完整历史(p16-17) | `src/chat_agent_cli.py`(M2 教学版) | ◐ M2 仍为手工历史,已标注代价;M3+ 由 checkpointer 托管 |
| §1.6.2 历史优化:保留最近 N 轮(p17-18) | `src/chat_agent_cli.py:keep_recent` | ✅ |
| §1.7 content / content_blocks(p20-25) | `src/agent/streaming.py:extract_text` | ✅ |
| §2.3.1 ChatPromptTemplate 两种实例化(p28-30) | `src/prompt.py` | ✅ |
| §2.3.2 三种调用方式(p30-31) | `src/prompts/system.py`(用 `format_messages()` 而非 `format()`) | ✅ |
| §2.4.1 partial 预填充(p37-38) | `src/prompts/system.py:build_prompt` | ✅ |
| §2.4.2 MessagesPlaceholder(p38-40) | `src/prompt.py`(M1 路径) | ✅ |
| §2.4.3 可复用模板库(p40-41) | `src/prompts/`(common / discipline / system 三文件) | ✅ |
| §2.4.4 模板组合(p41-42) | `src/prompts/system.py` 按阶段拼接 | ✅ |

### 第05章 Tools

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §1.2 两种调用方式(p2) | `@tool` 定义 + `create_agent(tools=…)` | ✅ |
| §2.2.3 docstring 规范 Google 风格 Args/Returns(p10-11) | `src/tools/*.py` 全部补齐 `Returns:` | ✅ |
| §3.1 description 参数 / parse_docstring(p15-18) | 9 个工具使用显式说明与参数文档 | ✅ |
| §3.3 自定义 args_schema(p20-27) | `src/tools/schemas.py`(4 个 Pydantic 模型) | ✅ |
| §5 tool_choice 强制调用(p35-39) | `GpaToolChoiceHook` 对明确 GPA 问句强制路由 | ◐ 仅覆盖 GPA 场景 |
| §6.2 功能单一(p41-42) | `src/tools/` 9 个单一职责工具 | ✅ |
| §6.3 工具失败三层防护(p42-43) | 第 1 层:工具内 try/except 返回错误串(`gpa.py`) | ◐ 第 3 层(tenacity)未用 |
| §6.4 强烈建议返回字符串(p43) | `src/tools/*.py` 全部返回 `json.dumps(..., ensure_ascii=False)` | ✅ |
| §6.5 同步 vs 异步(p44) | 全部同步 | ⬜ `search_policy` 属 IO 密集,可改 async 作加分 |

### 第06章 结构化输出

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §2.1 Pydantic + Field(description)(p2-5) | `src/tools/gpa.py:CourseGrade/GpaReport` | ✅ 已补 `Field(description=…)` |
| §2.1.2 嵌套 / 范围约束(p12-16) | `GpaReport` 嵌套 `CourseGrade`,含 `ge/le/gt` | ✅ |
| §4.1 with_structured_output(p33-34) | — | ⬜ 见下"术语纠正" |

### 第07章 智能体

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §1.4 create_agent 统一入口(p2-4) | `src/agent/assistant.py:get_agent` | ✅ |
| §2 模型传入方式(p3-5) | `model=get_chat_model()` 传实例 | ✅ |
| §4.1 工具绑定 + "2-5 个最佳"(p11-21) | `src/tools/__init__.py:TOOL_GROUPS` 按场景分组 | ◐ 全量仍 8 个,已提供裁剪入口 |
| §5 name 参数 / 流式归因(p26-28) | `src/agent/assistant.py:AGENT_NAME` | ✅ |
| §6 system_prompt(p28-34) | `src/prompts/system.py:build_system_prompt` | ✅ |
| §7.1-7.3 Agent 结构化输出 / ToolStrategy(p35-67) | `get_agent(response_format=…)` 留出参数 | ◐ 未默认启用(会污染通用问答,见代码注释) |
| §8.2 stream_mode 七种取值(p68-73) | `src/agent/streaming.py` 用 `["messages","updates"]` | ✅ |
| §8.3 多模式产出 (mode, payload)(p74-76) | `src/agent/streaming.py:stream_turn` | ✅ 与课件一致 |
| §9.3 封装成类而非四处复制(p80-81) | `src/agent/streaming.py`(消灭 5 份重复) | ✅ |

### 第08章 中间件(115 页,本项目用得最多的一章)

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §2.1 SummarizationMiddleware(p7-11) | `src/agent/middleware.py:get_summarization` | ✅ 加 token 触发 + 便宜模型 |
| §2.2 HumanInTheLoopMiddleware(p12-19) | `get_hitl`(开放 approve/edit/reject) | ✅ |
| §2.3 PIIMiddleware 自定义 detector(p20-24) | `get_pii_middleware` + `_detect_pii` | ✅ |
| §2.4 TodoListMiddleware(p24-25) | — | ⬜ 未用 |
| §3.1 ModelCallLimitMiddleware(p34) | `get_call_limit_middlewares` | ✅ |
| §3.2 ToolCallLimitMiddleware(p44) | `get_call_limit_middlewares` | ✅ |
| §3.3 ModelFallbackMiddleware(p53) | `get_fallback_middleware` | ✅ 备胎默认云端,`local_ollama` 可切本地 |
| §3.4 LLMToolSelectorMiddleware(p55) | — | ⬜ 未用(工具增至 8 个,可考虑) |
| §3.5 ToolRetryMiddleware(p64) | — | ⬜ 未用 |
| §3.6 ModelRetryMiddleware(p70) | — | ⬜ 未用(靠 ch02 §3.3 的 `max_retries`) |
| §3.8 ContextEditingMiddleware(p73) | `get_context_editing` | ⚠️ 已实现但**默认不启用**:实测 `trigger=50/keep=0` 会在模型作答前清空工具结果,导致模型答"查不到"(详见 `middleware.py` 的踩坑说明) |
| §5.3 Node-style hooks(p83-98) | — | ⬜ 未用 |
| §5.4 Wrap-style hooks(p99-111) | `_model_timing_hook` / `_tool_timing_hook` | ✅ |
| §5.6 执行顺序(p112-115) | `src/agent/middleware.py` 模块 docstring | ✅ |

### 第09章 上下文与记忆

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §2.1 InMemorySaver(p6-13) | `get_agent(with_middleware=True)` 分支 | ✅ |
| §2.2 外部持久化 PostgresSaver(p14-18) | `src/agent/memory.py`(SQLite 实现,PG 待第三批) | ⏳ 第三批 |
| §2.1.3 thread_id 隔离 / 多用户(p11) | `src/agent/runtime.py:default_thread_id` | ✅ |
| §2.4.1-2.4.3 裁剪 / 删除 / 摘要(p25-34) | 摘要见 `get_summarization`;裁剪由摘要承担 | ◐ 未用 `@before_model` 手写裁剪 |
| §3.1.3 store→namespace→key→value(p39-41) | `src/tools/profile.py:NAMESPACE_ROOT` | ✅ |
| §3.2 put/get/search(p41-52) | `src/tools/profile.py` | ✅ |
| §3.3.1 工具内访问 store(p52-56) | `src/tools/profile.py`、`src/tools/gpa.py` | ✅ |
| §4.2 context_schema + ToolRuntime(p74-80) | `src/context.py`、各工具签名、`get_agent(context_schema=…)` | ✅ 取代旧的 `get_config()["configurable"]` |
| §4.1.3 dynamic_prompt(p71-74) | — | ⬜ 未用 |

### 第10章 RAG

| 课件 | 项目落点 | 状态 |
|---|---|---|
| §2.2 文档加载器(p8-23) | `scripts/build_kb.py:load_markdown_docs`(手写 front matter) | ◐ 见下"刻意偏离" |
| §2.3.3 TextSplitter 参数 / add_start_index(p24-28) | `scripts/build_kb.py`(已开 `add_start_index=True`) | ✅ |
| §2.3.4 切分实现 + 中文 separators + 按标题切(p28-46) | `scripts/build_kb.py`(300/80 + 中文 separators + MarkdownHeaderTextSplitter) | ✅ |
| §2.4.1 嵌入模型选型表(bge-m3 = 多语言/1024维)(p46-47) | `src/config.py:EMBED_MODEL/EMBED_DIM` | ✅ |
| §2.4.2 选型与初始化(云端 OpenAI 兼容网关)(p48-49) | `src/kb.py:get_embeddings` | ✅ 占位配置,待 key |
| §2.5.2 常用向量数据库(p52) | `src/config.py:KB_BACKEND` | ✅ 默认 milvus,可切 chroma 过渡 |
| §2.5.3 Milvus 建库 / upsert / 检索(p52-62) | `src/kb.py`、`scripts/build_kb.py` | ⏳ 第三批(待 Docker) |
| §2.5.3 片段带来源拼上下文(p63-65) | `src/tools/policy.py` | ✅ |

---

## 二、课件未覆盖(本项目的超纲与自主决策)

这一节是**给评审看的边界声明**:以下内容课件全书没有,不要当成"课件教的"。
数据来源:对 10 章全文做过关键词检索确认零命中。

| 项目内容 | 实现文件 | 说明 |
|---|---|---|
| FastAPI + SSE 服务化 | `src/server.py`、`frontend/index.html`、`frontend/js/` | 课件只讲 LangChain/LangGraph,全课程无 Web 服务化与部署章节 |
| 32 问评估集与自建跑批 | `scripts/eval_set.json`、`scripts/eval_m6.py` | ch03 §1.2(p1-2)讲的是 LangSmith 的 Datasets/Evaluators,本项目未用该平台功能,理由见下 |
| 元数据过滤 + 全库召回合并 | `src/tools/policy.py` | 自研。课件第10章未涉及 Hybrid Retrieval / EnsembleRetriever / BM25 / MMR / rerank(全部零命中) |
| 马来西亚手机号 PII 正则 | `src/agent/middleware.py:_PHONE_MY` | 课件 §2.3(p23-24)只演示了 11 位数字检测器,马来西亚号段是本地化扩展 |
| Chroma 过渡后端 | `src/kb.py:_build_chroma` | 课件用 Milvus;Chroma 仅作为 Milvus 未就绪时的过渡,由 `KB_BACKEND` 一行切换 |
| SQLite 记忆后端 | `src/agent/memory.py` | 课件 §2.2(p14-18)实操的是 PostgresSaver;本机运行可选 PostgreSQL 或 SQLite |

**口径说明(LangSmith 的评估)**:
课件把"评估"放在 LangSmith 的 Datasets & Experiments 与 Evaluators(ch03 §1.2 p1-2)。
本项目用的是自制 JSON 评估集 + 关键词断言打分,属于**规则评估器的雏形**,
但**没有**接 LangSmith 的 Experiments/Evaluators。
因此文中不应写"使用 LangSmith 做评估",准确说法是
"LangSmith 全链路 tracing;评估集为自建"。

---

## 三、已知偏差与待办

| 项 | 现状 | 计划 |
|---|---|---|
| 向量库 Milvus | 本机 Docker 已运行，106 个片段可检索 | ✅ 历史 M5 的 10/10 检索抽查通过；更新资料或 Embedding 后重新建库验证 |
| 记忆后端 PostgreSQL | 本机已验证 `PostgresSaver`/`PostgresStore` | ✅ M4 与 Web 集成测试通过；SQLite 保留为本地替代 |
| 工具数量 9 个 | 课件 §4.1(p21)建议 2-5 个 | 已提供 `tools_for(...)` 按场景裁剪；可再考虑动态筛选 |
| 工具调用路由稳定性 | 中间件钩子使单次工具调用可能占用 26-35 个 super-step | 已加 `recursion_limit` 与两个 CallLimit 中间件；最近一次自建评估路由 **27/27**、综合 **32/32**，但模型行为仍有非确定性，不能等同真实用户准确率 |
| `archive_docs.py`(原 `collect_docs.py`) | 原文件名暗示"采集",实际 474 行里无任何网络代码,16 份文档硬编码在 `DOCS` | ✅ 已更名 + docstring 写明"不含网络采集",并删掉两个从未被生成的临时文件的清理代码。可选:加 `--online` 分支走 MinerU(课件 §2.2.4 p12-16) |
| 工具重排序(rerank) | 课件第10章未涉及 | 不做的理由:语料仅 16 份,召回集合很小;第01章 §5.1(p18-19)也指出"响应时间要求高时用 reranker 可能不合适" |

---

## 四、复核方式

想核对本表的任意一行:

1. 打开对应章的课件 PDF,翻到标注的页码;
2. 或对提取出的课件全文做检索(本地有 `.tmp_course/ch0X_*.txt`,
   每页以 `===== [P0X] page N/M =====` 开头);
3. 按"项目落点"列的文件名与符号名查代码。

例:

```bash
grep -n "parse_docstring" src/tools/*.py     # 第05章 §3.1 p15-18
grep -n "context_schema" src/agent/assistant.py src/context.py   # 第09章 §4.2 p74-80
grep -n "hnsw:space\|metric_type" src/kb.py   # 第10章 §2.5.3 p53(p53 的 COSINE)
```

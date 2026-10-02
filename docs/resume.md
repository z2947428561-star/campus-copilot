# 简历项目段落(campus-copilot)

> 回填规则:所有数字均来自 docs/eval-results.md 与里程碑实测记录,不编造。
> 面试可按「一句话 → 亮点 → 数字」三层展开。

## 项目名(一行)

**Campus Copilot —— 校园教务智能助手(Agent + RAG)**|个人独立开发|2026.09

## 一句话介绍

面向厦门大学马来西亚分校学生的多用户智能助手:LangChain Agent 驱动,
结构化数据工具(校历/课表/教室/GPA)与教务政策 RAG 双数据源协同,
带记忆、脱敏、降级、人工确认等工程治理；最近一次自建评估 32/32 通过。

## 技术栈

Python · LangChain 1.x(create_agent / Middleware / Hook)· LangGraph(Checkpointer / Store /
context_schema)· Milvus 向量库 + 云端 bge-m3 Embedding · SQLite / PostgreSQL · FastAPI / SSE 流式 · Pydantic

## 亮点(按面试价值排序,数字为实测)

1. **Agent 工具路由**:9 个工具(教学周计算/空教室查询/个人课表/GPA 结构化报告/
   课程先修/政策向量检索/长期记忆读写),最近一次 27 项路由评估 **27/27**,
   32 项自建评估 **32/32**;口径为关键词断言与 ToolMessage 检查，不等同真实用户准确率;
   temperature 为 0.2，`recursion_limit` 与调用次数限制分别防单轮/会话失控
2. **RAG 全链路**:16 份学校官方公开教务文档(含来源 URL 与 doc_type 元数据)→
   按标题 + 递归切分(带 `start_index` 可回溯偏移)→ 云端 Embedding 入 **Milvus**
   (COSINE 度量)→ 相似度 + 元数据混合检索(过滤召回与全库召回按分数合并,
   解决"问题表面类型 ≠ 文档分类"的过滤陷阱)→ 回答强制附官方出处,
   10 项检索抽查 **10/10 命中**正确文档
3. **工程治理(默认中间件栈 9 层,备胎可用时)**:PII 自定义检测器(中/马手机号 + 学号,
   修复过中文紧贴数字导致 `\b` 失效的真实 bug)、长对话条数+token 双阈值压缩、
   可选上下文编辑(默认关闭)、模型/工具调用次数限额、独立来源模型故障降级、
   敏感工具(成绩分析)执行前人工确认(支持 approve/edit/reject,HITL 中断跨 HTTP 请求恢复)、
   全链路调用耗时审计日志
4. **多用户持久记忆**:短期会话(Checkpointer 按 thread 隔离,重启续聊)+
   长期画像(Store 按 user_id 隔离);用户身份经 **`context_schema` + `ToolRuntime`**
   显式注入,并拒绝空身份 —— 修掉了旧实现里 `"default"` 兜底造成的跨用户画像泄漏路径;
   最近一次 32 项自建评估全部通过,PII 红线零回显
5. **本机 Web 应用**:FastAPI + SSE 流式接口 + 无独立构建步骤的 Web 聊天页;
   本机 PostgreSQL / Milvus，或 SQLite / Chroma，后端均可环境变量切换;
   可选 LangSmith 追踪(带 run_name/tags/metadata；涉及真实用户时默认应关闭)

## 面试常问 & 你的答法

- *为什么双数据源?* 教务信息天然两半:课表/教室/成绩是结构化的,精确查;
  政策规定是非结构化的,必须检索原文并引用,不能让 LLM 背政策。
- *为什么用 Milvus 而不是 Chroma/FAISS?* 跟课件走(第10章 §2.5.2 p52),
  且 Milvus 是云原生向量库,生产形态更完整。开发期因为本机没 Docker 用过 Chroma,
  现在两边接口同构,`.env` 一个 `KB_BACKEND` 开关切换,建库与检索共用同一份配置。
- *为什么 Embedding 用云端而不是本地?* 课件第10章 §2.4.2(p48-49)用的是
  CloseAI / 硅基流动的 OpenAI 兼容网关,全章没有用 Ollama。
  本地 Ollama 保留给验证模型降级的路径；项目当前仅在本机运行。
- *最大的坑?* 有三个值得一提:
  ① 给 `@tool` 传了 `args_schema` 之后,langchain 会拿 **Pydantic 类的 docstring**
  当工具描述、把函数自己的 docstring 忽略掉 —— 表现是模型看到的工具说明变成了
  "查询空教室的参数",必须显式传 `description=` 才恢复;
  ② 元数据过滤反而降低召回的案例(费用问题被过滤到 finance 类,漏掉 academic 类的重修费条款),
  用"过滤召回 + 全库召回按分数合并"解决;
  ③ HITL 的 resume 依赖 checkpointer 存现场,没有持久化层就无法恢复。
- *历史评估为什么曾有未通过?* 曾有**工具路由没触发**:w04「明天上午哪有空教室」
  只调了 get_academic_week 确认日期语境,没接着调 find_empty_classrooms
  (而 w05「周三10点哪些教室空着」是通过的)。
  实测属 LLM 工具调用非确定性 —— 旧评估两轮失败集合不同。
  已增加 GPA 路由钩子，最近一次评估 32/32；仍需真实用户反馈验证稳定性。

## 一页浓缩版(可直接贴简历)

**Campus Copilot —— 校园教务智能助手**(个人项目,2026.09)
基于 LangChain/LangGraph 构建多用户校园助手:9 工具 Agent(课表/校历/GPA/课程先修)+ 16 份
官方文档 RAG 知识库(Milvus + 云端 Embedding,回答附出处);实现 PII 脱敏、长对话压缩、
上下文清理、调用限额、模型降级、敏感操作人工确认等中间件治理与全链路审计;
多用户持久化记忆(会话隔离 + 用户画像,身份经 context_schema 显式注入);
FastAPI/SSE 本机 Web 应用;最近一次 32 项自建评估 32/32,
RAG 检索抽查 10/10 命中。

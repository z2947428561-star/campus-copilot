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

## M3 中间件 + Hook(前置:P64-P85)- 未开始

- [ ] SummarizationMiddleware 长对话压缩
- [ ] HumanInTheLoopMiddleware:高风险动作前确认(预留:改课表类写操作)
- [ ] PIIMiddleware:过滤用户输入中的学号/手机号
- [ ] ModelFallbackMiddleware:DeepSeek→Ollama 自动切换
- [ ] wrap_model_call / wrap_tool_call:审计日志 + 耗时
- [ ] 多中间件执行顺序验证

**DoD**:配错 API key 不崩自动降级;20 轮对话不超限;工具耗时在日志可见。

## M4 记忆与多用户(前置:P86-P101)- 未开始

- [ ] PostgreSQL 短期记忆:按 session 隔离,重启可恢复
- [ ] 消息裁剪治理
- [ ] 长期记忆 Store:用户画像(年级/专业/常问话题)
- [ ] 工具内读写长期记忆(如 GPA 分析后更新画像)

**DoD**:两个 session 互不串扰;重启续聊;能答「我是大几的、常问什么」。

## M5 RAG 知识库(前置:P102-116)- 未开始

- [ ] 手工收集 10-20 份公开教务文档进 `data/raw_docs/`
- [ ] 管线:加载(md/pdf)→ RecursiveCharacterTextSplitter → Embedding → Milvus(元数据:source/doc_type)
- [ ] `search_policy` 升级为向量检索 + 元数据过滤
- [ ] 回答附带来源引用
- [ ] 人工抽查 10 问

**DoD**:问「补考和重修的区别」,回答命中规定原文段落并给出出处。

## M6 部署与收官(前置:P117-120 + 少量超纲)- 未开始

- [ ] FastAPI:对话接口 + SSE 流式 + session 管理
- [ ] 简单 Web 页面
- [ ] Docker Compose:app + Milvus + PostgreSQL
- [ ] 部署云服务器,同学可用
- [ ] LangSmith 评估集 30+ 问答对,记录准确率
- [ ] README 完工:映射表全勾 + 截图 + 复盘
- [ ] 简历段落回填真实数字

**DoD**:发链接同学能玩并给出反馈;简历项目段落定稿。

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

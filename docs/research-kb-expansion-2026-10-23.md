# XMUMDorm 接入前的知识库扩展研究

研究日期：2026-10-23。范围：当前 `E:\Campus Copilot` 工作区的源码和仓库文档；未读取 `.env`，未调用模型、Embedding、爬虫或真实数据库，未构建或发布索引。以下区分“已有能力”和“建议扩展”。目标项目经并行代码研究确认为校园社区平台，具有新生指南、选课评价、课表、待办和订单等功能；具体接口与权限证据见 [目标项目研究](<E:/Campus Copilot/docs/research-xmumdorm-target-2026-10-23.md>)。

## 1. 结论

现有知识库可以复用来回答**有来源的学校规定与校园指南**，但当前实现仍以教务政策为中心。要接入 XMUMDorm 校园助手，应分三条数据通道：

| 内容 | 建议承载方式 | 原因 |
|---|---|---|
| 正式学校规定、教务办理流程、已核实收费说明；以后可扩展宿舍规则 | 政策知识库，保留官方出处、版本和适用日期 | 当前 `search_policy` 已有来源类型、官方域名和相似度门槛 |
| 新生指南、学生生活与选课经验、SurviveXMUM 文章 | 独立的社区知识工具与索引/检索范围 | 现有政策门槛明确排除非政策来源，不能靠改标签混入 |
| 我的课表、待办、订单状态 | 调用 XMUMDorm 业务 API 的工具 | 这些是实时、有权限范围的业务事实；现有 RAG 是全量版本化快照，没有用户级过滤契约 |

以上分层是基于当前实现作出的设计建议。政策门槛见 [policy_evidence.py:10](<E:/Campus Copilot/src/policy_evidence.py:10>)；当前检索只接受 `query`、`doc_type`，见 [policy.py:89](<E:/Campus Copilot/src/tools/policy.py:89>)；版本快照流程见 [kb.py:128](<E:/Campus Copilot/src/kb.py:128>)。仓库现有的“公共课程/校历 SQL + 个人数据按用户隔离 + 政策 RAG + 学生经验独立工具”也已经体现类似边界，见 [data-plan.md:21](<E:/Campus Copilot/docs/data-plan.md:21>)、[data-plan.md:111](<E:/Campus Copilot/docs/data-plan.md:111>)。

## 2. 当前真正支持哪些输入

### 2.1 政策 RAG 输入不是通用文件上传

`scripts/build_kb.py` 固定读取项目根目录的 `data/raw_docs`，仅使用 `glob("*.md")`，不递归子目录。每个文件必须以 front matter 开头；没有 front matter 会打印“跳过”并继续。它没有 PDF、Word、HTML、CSV、Excel 或 JSONL 的直接加载分支，也没有 `--docs-dir` 参数。见 [build_kb.py:50](<E:/Campus Copilot/scripts/build_kb.py:50>)、[build_kb.py:63](<E:/Campus Copilot/scripts/build_kb.py:63>)、[build_kb.py:170](<E:/Campus Copilot/scripts/build_kb.py:170>)。

front matter 是手写的单行 `key: value` 字符串解析器，**不是完整 YAML**：按首个冒号切开，值只去首尾空白，不解析引号、数组、嵌套对象、多行值或注释。因此应写 `source_type: manual_summary`，不能照完整 YAML 的习惯写成 `source_type: "manual_summary"`；后者会把双引号保留在值中，无法通过来源类型匹配。文件开头的 BOM 或 front matter 前的其他文字也不匹配当前正则。见 [build_kb.py:52](<E:/Campus Copilot/scripts/build_kb.py:52>)、[build_kb.py:75](<E:/Campus Copilot/scripts/build_kb.py:75>)。

当前 16 份文档属于人工整理快照，不能当成逐字官方摘录。仓库记录过扫描版 PDF 无文本层的问题，OCR/MinerU 尚未接入；`archive_docs.py` 是内置快照写入器，会覆盖那 16 个同名文件，并非新资料采集器。见 [policy-evidence.md:3](<E:/Campus Copilot/docs/policy-evidence.md:3>)、[policy-evidence.md:63](<E:/Campus Copilot/docs/policy-evidence.md:63>)、[data-plan.md:71](<E:/Campus Copilot/docs/data-plan.md:71>)。

### 2.2 元数据契约

| 字段 | 当前行为 | 校园知识扩展时的处理 |
|---|---|---|
| `title` | 缺少时切分器补空字符串，最长 500 字符 | 明确文档名称 |
| `source` | 最长 1000 字符；检索要求 HTTP(S) 且为允许的官方域名 | 填具体原文地址，不能仅填本地文件名 |
| `doc_type` | 默认 `general`，最长 60 字符 | 可先用现有分类；正式增加校园生活或 `housing` 等分类时同步工具说明和评测 |
| `filename` | 默认原文件名，最长 250 字符 | 避免名称碰撞，保留可定位的来源标识 |
| `source_type` | 缺失为 `unknown`；只有 `manual_summary`、`official_excerpt` 可通过政策门槛 | 原文核验后才能标 `official_excerpt`；学生经验保持其真实类别 |
| `collected_at`、`effective_date` | 缺失为 `unknown`；目前只记录/回传，不校验过期 | 增加有效期、适用对象的处理逻辑，不能只添加字段 |
| `lang` 等自定义标量 | loader 原样保留，随分块写入；证据输出未必包含 | 需要展示或过滤的字段必须同时扩展证据输出与检索 |
| `h1`、`h2`、`h3` | 标题切分生成 | 使用业务意义清楚的标题 |
| `start_index`、`offset_scope` | 章节内偏移，`offset_scope=section` | 不宣称是原 PDF 页码或原文件字节偏移 |
| `chunk_id` | 每次全量构建重新生成的顺序号 | 不把它当跨版本稳定文档 ID |

字段读取/截断和分块元数据来自 [build_kb.py:80](<E:/Campus Copilot/scripts/build_kb.py:80>)、[build_kb.py:117](<E:/Campus Copilot/scripts/build_kb.py:117>)；证据输出字段与章节偏移来自 [policy_evidence.py:32](<E:/Campus Copilot/src/policy_evidence.py:32>)。Milvus 使用动态字段，只有 `id`、`vector`、`text` 在当前 schema 显式声明；建库脚本关于旧版固定 metadata schema 的注释不应当作现状，见 [kb_backends.py:42](<E:/Campus Copilot/src/kb_backends.py:42>)。

新字段建议包括 `source_id`、`source_version`、`document_kind`、`effective_from`、`effective_to`、`audience`、`campus`、`building_scope`、`reviewed_at`、`review_status`。这些是**待设计能力**：当前代码不会自动按照它们过滤、判断新旧版本或避免跨楼栋误用。当前证据记录只输出固定字段，新增字段也不会自然显示给模型。[policy_evidence.py:35](<E:/Campus Copilot/src/policy_evidence.py:35>)

### 2.3 切分与向量化

当前先按 Markdown 的 `#` / `##` / `###` 切章节，保留标题；再按字符数递归切分，`chunk_size=300`、`chunk_overlap=80`、`length_function=len`，并记录章节内起点。不是 300 tokens，也没有按表格/条款语义保持完整的专用逻辑。见 [build_kb.py:54](<E:/Campus Copilot/scripts/build_kb.py:54>)、[build_kb.py:101](<E:/Campus Copilot/scripts/build_kb.py:101>)。

对教务办理流程、校园指南及以后扩展的宿舍规则，建议按“事项—适用对象—条件—例外—费用/期限—办理入口”组织小节，避免把费用与其例外分到互不关联的块里。长表格和多步流程应增加专门切分验收；先用现有 300/80 基线测召回，再决定是否改变参数。切分改动会产生新的正文/元数据哈希与证据 ID，应重建完整候选并回归引用。[kb_releases.py:60](<E:/Campus Copilot/src/kb_releases.py:60>)、[policy_evidence.py:46](<E:/Campus Copilot/src/policy_evidence.py:46>)

代码默认配置为 Milvus、`BAAI/bge-m3`、1024 维、COSINE，支持 Chroma 和本地 Ollama 作为配置分支；这只说明默认值，**本研究未读取本机实际 `.env` 配置或确认服务在运行**。见 [config.py:118](<E:/Campus Copilot/src/config.py:118>)、[config.py:145](<E:/Campus Copilot/src/config.py:145>)、[kb.py:50](<E:/Campus Copilot/src/kb.py:50>)。

## 3. 检索、证据与现有限制

`search_policy` 按指定类别召回一次，再从全库召回一次；无类别时只召回全库。默认每次取 5 条，合并后按证据 ID 去重、保留最高分，最终最多 5 条。Milvus 原值为余弦相似度，Chroma 为余弦距离，统一成 `(cosine + 1) / 2`。默认门槛 0.70，相当于余弦相似度至少 0.40；它不是正确概率，也没有经过目标平台新增题集校准。见 [policy.py:40](<E:/Campus Copilot/src/tools/policy.py:40>)、[policy.py:100](<E:/Campus Copilot/src/tools/policy.py:100>)、[config.py:164](<E:/Campus Copilot/src/config.py:164>)、[policy-evidence.md:42](<E:/Campus Copilot/docs/policy-evidence.md:42>)。

候选必须满足：分数有限且在 `[0,1]`、达到门槛、正文不空、来源类型是 `manual_summary` 或 `official_excerpt`、`source` 是 HTTP(S)，域名为 `xmu.edu.my`、其子域或 `zs.xmu.edu.cn`，URL 不含用户名密码。这里只验证元数据形态与域名，不核验来源网页、发布日期或文本真实性。[policy_evidence.py:10](<E:/Campus Copilot/src/policy_evidence.py:10>)

响应区分 `evidence_found`、`insufficient_evidence`、`unavailable`；部分检索失败时可返回 `partial=true`。证据带标题、来源、类型、日期、章节、正文和 `P-…` ID。ID 由证据内容和来源字段确定，不依赖问题或排名；正文、来源或日期变化会改变 ID。见 [policy.py:114](<E:/Campus Copilot/src/tools/policy.py:114>)、[policy_evidence.py:32](<E:/Campus Copilot/src/policy_evidence.py:32>)。

扩展前应处理以下具体问题：

1. **学生 Wiki 会被明确拒绝。** `SOURCE_TYPES` 有 `student_experience`，没有 `student_wiki`；政策 gate 对二者都不接受，Wiki 域名也不在官方域名范围。应增加独立社区检索与证据模型，不应把学生文章改成 `official_excerpt` 以绕过过滤。[policy_evidence.py:7](<E:/Campus Copilot/src/policy_evidence.py:7>)
2. **混入同一集合可能降低政策召回。** 当前在 top-k 召回以后才筛来源类型；大量相关社区文档可能挤掉政策候选。若共享物理集合，至少在检索前强制按知识类别/信任范围过滤，并让所谓“全库补召回”仍限于该范围。更清楚的初版是独立社区集合及工具。[policy.py:61](<E:/Campus Copilot/src/tools/policy.py:61>)、[policy.py:117](<E:/Campus Copilot/src/tools/policy.py:117>)
3. **`doc_type` 不是访问控制。** 类别请求还会补全库召回，因此不能用它隔离租户、个人待办/订单或不同权限人群。任何个人业务信息不应进入当前共享政策库。[policy.py:100](<E:/Campus Copilot/src/tools/policy.py:100>)
4. **分类说明与校验不一致。** 存在 `DOC_TYPE_VALUES` 常量，但 `PolicySearchInput.doc_type` 实际类型是普通 `str`，并未用 Literal/validator 限制；传入新类别不一定被 schema 拒绝，但模型说明仍只列旧类别。新增校园生活类别，以及以后可能增加的 `housing`，需同时修改说明、路由和用例。[schemas.py:45](<E:/Campus Copilot/src/tools/schemas.py:45>)、[schemas.py:84](<E:/Campus Copilot/src/tools/schemas.py:84>)
5. **日期不执行约束。** 目前没有 `effective_to`、废止/取代关系和适用楼栋筛选；“高分旧规则”仍可能成为候选。当前提示词要求模型核对范围与时效，但没有最终回答语义强制拦截。[policy_evidence.py:32](<E:/Campus Copilot/src/policy_evidence.py:32>)、[policy-evidence.md:46](<E:/Campus Copilot/docs/policy-evidence.md:46>)
6. **本系统帮助文档可能不是官方政策。** 如果校园平台自己的使用手册在其他域名，现有 gate 会拒绝；应引入单独的 `platform_documentation` 类别、明确归属和允许范围，或使用独立帮助工具，不能泛化为任何域名都算官方。[policy_evidence.py:22](<E:/Campus Copilot/src/policy_evidence.py:22>)
7. **证据不足时的指引仍固定为教务。** 当前统一返回学校首页和 `xmumac@xmu.edu.my`，未按校园生活或平台使用场景区分联系渠道。应由各业务提供已核实的联系信息，避免直接复用教务指引。[policy_evidence.py:57](<E:/Campus Copilot/src/policy_evidence.py:57>)

## 4. SurviveXMUM 快照如何接进来

现有 crawler 保存 `data/local/survivexmum/<UTC时间>/` 独立目录，含 `manifest.json`、`snapshot.json`、`pages.jsonl` 以及哈希命名的 Markdown。JSONL 记录 `path`、`title`、`category`、`version`、`lastUpdated`、`source_url`、`fetched_at`、`source_type=student_wiki`、`sha256`、`content`、`markdown_file`。它只下载，不调用 RAG 构建。见 [crawl_survivexmum.py:145](<E:/Campus Copilot/scripts/crawl_survivexmum.py:145>)、[crawl_survivexmum.py:172](<E:/Campus Copilot/scripts/crawl_survivexmum.py:172>)、[crawl_survivexmum.py:217](<E:/Campus Copilot/scripts/crawl_survivexmum.py:217>)。

直接把这些文件交给现有 build 不可行：目录不在固定输入路径，JSONL 没有 loader，Markdown 原始正文没有由 crawler 补上建库所需 front matter；即使手工转成可加载 Markdown，也会遇到来源类型和域名 gate。完整性标志也是采集快照级别，现有 builder 不读取它。[build_kb.py:63](<E:/Campus Copilot/scripts/build_kb.py:63>)、[crawl_survivexmum.py:184](<E:/Campus Copilot/scripts/crawl_survivexmum.py:184>)、[crawl_survivexmum.py:192](<E:/Campus Copilot/scripts/crawl_survivexmum.py:192>)

建议新增明确的导入适配层，按以下映射生成社区 `Document`：

| crawler 字段 | 建议标准字段/用途 |
|---|---|
| `source_url` | `source` |
| `fetched_at` | `collected_at` |
| `path` | 稳定 `source_id` 的组成部分 |
| `version` | `source_version`，不能当日期 |
| `lastUpdated` | `source_updated_at`，不能当政策生效日期 |
| `category` | 保留原分类；另映射标准 `doc_type` |
| `source_type=student_wiki` | 原始层保留；标准层可映射为 `student_experience` 并增加 `origin_type=student_wiki`，或统一扩展正式枚举 |
| `sha256` | 验证正文未变、识别更新 |
| `content` | 分块正文 |

建议只消费 `snapshot.status=complete`、`saved=selected` 且内容哈希验证通过的快照；若刻意使用部分内容，应显式记录范围，不把 `incomplete` 当成完整知识版本。初版限定新生、校园生活与学习相关分类并人工核对文章清单，排除网站开发文档。上述均为拟议导入约束，当前 crawler 只是提供对应字段和完成状态。[crawl_survivexmum.py:153](<E:/Campus Copilot/scripts/crawl_survivexmum.py:153>)、[crawl_survivexmum.py:161](<E:/Campus Copilot/scripts/crawl_survivexmum.py:161>)、[docs/survivexmum.md:38](<E:/Campus Copilot/docs/survivexmum.md:38>)

## 5. 已有 import 脚本的边界

| 现有入口 | 实际输入/输出 | 能否当通用知识库扩展入口 |
|---|---|---|
| `import_semester.py` | 单个学期完整 JSON → 公共校园 SQLite | 不能；模型限定学期、周、事件、排课 |
| `import_course_recommendations.py` | 特定布局的 XLSX → `.local.json` | 不能；依赖 Art/Business/Science、课程/教师/FAQ 标题及列布局 |
| `build_kb.py` | 根层 Markdown + 简化 front matter → 新向量集合 | 可用于经过整理的政策文档 |
| `crawl_survivexmum.py` | 两个公开接口 → 原始 Markdown/JSONL 快照 | 仅采集；仍缺标准化和社区检索 |

学期导入使用 Pydantic 禁止未知字段，校验日期/周次/排课引用，更新已有学期需 `expected_version`；在事务中替换该学期完整快照，不是部分补丁。[import_semester.py:13](<E:/Campus Copilot/scripts/import_semester.py:13>)、[semesters.py:68](<E:/Campus Copilot/src/semesters.py:68>)、[semesters.py:243](<E:/Campus Copilot/src/semesters.py:243>)

选课经验导入用 ZIP/XML 读 XLSX，拒绝公式单元格，保留 sheet/row/cell 原文位置及来源 SHA-256；输出 `official=False` 的本机种子。它不是任意 Excel 表自动入库能力，也不是向量索引。其后续数据库导入只替换两张经验表。[import_course_recommendations.py:21](<E:/Campus Copilot/scripts/import_course_recommendations.py:21>)、[import_course_recommendations.py:58](<E:/Campus Copilot/scripts/import_course_recommendations.py:58>)、[course-recommendations.md:7](<E:/Campus Copilot/docs/course-recommendations.md:7>)

可复用的是这些模式：完整输入校验、来源追溯、版本比较、事务替换和原始材料保留；个人待办、订单等数据不能直接塞进学期或选课导入 schema。

## 6. 发布、回滚和部署约束

已有知识库发布链路值得保留：每次全量创建独立物理集合 → 分批生成/校验向量 → 写入完成 → 校验数量、COSINE、自查询正文和元数据 → 标记 `ready` → 比较 `expected_revision` 后切换指针。构建失败标记 `failed`，现有 active 保持不变。见 [kb.py:128](<E:/Campus Copilot/src/kb.py:128>)、[kb_releases.py:176](<E:/Campus Copilot/src/kb_releases.py:176>)、[kb_releases.py:202](<E:/Campus Copilot/src/kb_releases.py:202>)。

脚本已支持以下操作（本研究没有执行）：

```powershell
# 只看发布登记，不连接模型或向量库
.venv\python.exe scripts/build_kb.py --status

# 构建候选；会调用已配置的 Embedding 与向量服务
.venv\python.exe scripts/build_kb.py --stage-only

# GENERATION / N 是占位值，必须替换为刚读取的实际 generation / revision
.venv\python.exe scripts/build_kb.py --publish GENERATION --expected-revision N
.venv\python.exe scripts/build_kb.py --rollback --expected-revision N
```

命令和语义见 [build_kb.py:170](<E:/Campus Copilot/scripts/build_kb.py:170>)；标准 venv 使用其实际 Python 路径，仓库同时记录 Conda 式 `.venv\python.exe` 和标准 `.venv\Scripts\python.exe` 的区别。[survivexmum.md:29](<E:/Campus Copilot/docs/survivexmum.md:29>)

需要注意：

- 目前是**全量构建**，没有按 `source_id` 更新/删除片段、复用未变文档向量或自动清理历史集合。添加一份文档也会重嵌入本次加载的整个语料；旧版本继续占空间。[build_kb.py:138](<E:/Campus Copilot/scripts/build_kb.py:138>)、[kb.py:142](<E:/Campus Copilot/src/kb.py:142>)、[storage.md:85](<E:/Campus Copilot/docs/storage.md:85>)
- `--stage-only` 的 ready 验收证明存储完整性，不代表校园问答质量。自查询只探测第一份 chunk；当前 `search_policy` 总是连 active，不能直接用它验收未发布候选。建议补充接受指定 generation 的只读评测入口，在发布前评估候选。[kb.py:150](<E:/Campus Copilot/src/kb.py:150>)、[policy.py:47](<E:/Campus Copilot/src/tools/policy.py:47>)
- 发布与回滚会检查目标集合，不生成新向量；运行时每次检索重新读小型发布登记，修订变化后换 Reader。旧查询保留此前 Reader，旧集合不删除。[kb.py:165](<E:/Campus Copilot/src/kb.py:165>)、[kb.py:186](<E:/Campus Copilot/src/kb.py:186>)
- Embedding 指纹包括后端、模型、端点、维度及相关参数。切换 cloud/Ollama 即使模型名字相近也改变当前代码的指纹，运行时拒绝配置不匹配的新索引；应以这段执行逻辑为准，不能照 `kb.py` 早期注释的“不必重建”承诺部署。[kb_releases.py:64](<E:/Campus Copilot/src/kb_releases.py:64>)、[kb.py:199](<E:/Campus Copilot/src/kb.py:199>)
- 注册表是本地 SQLite，当前契约针对同机 Web/CLI/build；多个 Agent 服务副本不能各保留独立登记库然后假定自动同时切换。跨主机发布协调尚未实现。[kb_releases.py:73](<E:/Campus Copilot/src/kb_releases.py:73>)、[storage.md:3](<E:/Campus Copilot/docs/storage.md:3>)、[storage.md:85](<E:/Campus Copilot/docs/storage.md:85>)
- `kb` 依赖全局配置并缓存一个当前 Reader；注册表虽以 scope 隔离不同配置，当前 API 仍不能方便地在一个进程内同时指定“政策库”和“社区库”。增加独立社区集合时，应把索引身份/配置作为显式依赖，或在初版使用独立服务实例。[kb.py:12](<E:/Campus Copilot/src/kb.py:12>)、[kb.py:186](<E:/Campus Copilot/src/kb.py:186>)、[kb_releases.py:36](<E:/Campus Copilot/src/kb_releases.py:36>)
- Chroma 备份须成套保留注册表和整个向量目录；只复制其一不能恢复发布状态。迁移保持相对布局或使用已有 `--rebind-from` 校验迁移，不能把复制目录等同完成恢复。[storage.md:56](<E:/Campus Copilot/docs/storage.md:56>)、[kb.py:106](<E:/Campus Copilot/src/kb.py:106>)

## 7. 建议实施顺序与验收

### 第一轮：校园公开知识 MVP

1. 列出一份小规模、经核实的核心资料清单：教务办理、选课规定、新生指南、校园设施与平台使用说明；每项记录来源和适用范围，区分官方资料与社区指南。宿舍规则可作为后续扩展资料之一。这里列的是资料类别，不代表已核实任何学校具体规则。
2. 官方资料整理成现有可读取的 Markdown；社区指南按下一轮的独立通道接入，不应混用来源身份。新增校园生活类别时同步 `schemas.py`、工具描述、系统路由和评测。工具注册扩展点在 [tools/__init__.py:20](<E:/Campus Copilot/src/tools/__init__.py:20>)，政策回答纪律在 [prompts/discipline.py:43](<E:/Campus Copilot/src/prompts/discipline.py:43>)。
3. 增加来源/字段静态检查和按 generation 评测入口，构建候选，验证后发布。不要用重跑 `archive_docs.py` 更新新增政策。
4. 验收：带原文来源、来源性质和日期；费用/期限没有证据就明确无法确认；同一问题中有证据的部分可答，欠缺部分不补造；后台故障和证据不足区分返回。

### 第二轮：社区生活指南

1. 从已完成的 crawler 快照导入，实施第 4 节的字段映射、内容校验和去重。
2. 增加 `search_campus_guide` 一类独立工具、社区证据格式及清晰的“学生经验”表述；保留政策工具的官方来源门槛。
3. 检索范围先按来源类别限制，再考虑向量召回、关键词/混合检索、重排；这些增强当前均未实现，是否加入应由真实失败用例决定。
4. 验收：社区资料不能被答成规定；Wiki 与官方内容冲突时呈现各自身份，不以相关度分数选择哪条“有效”；旧版本/重复文章不占满候选。

### 第三轮：动态业务工具

1. 由 XMUMDorm 服务器提供身份与权限上下文，优先设计读取本人课表、待办的工具，再按需求接订单状态；例如 `get_my_timetable`、`list_my_todos`、`get_my_order_status`，这些工具名只是建议，具体适配须使用目标项目真实 API 和权限语义。
2. 修改待办、课程安排或订单等作为后续业务命令，沿用目标系统权限、状态机、幂等和确认要求；不把写入动作包装成知识检索。报修、宿舍分配等仅是假设的未来业务，不能由项目名称推断其已经存在。
3. 验收：无法通过提示词切换成别人的用户 ID；每次从业务服务获取当前状态；业务 API 失败时不会用旧 RAG 文本猜测；公共使用说明与本人课表、待办、订单查询结果在回答中清楚对应。

### 横向质量与维护

新增校园用例应覆盖：正确来源命中、错误类别仍能召回、英文/中文/同义表达、同一条款条件与例外、过期文档、社区与官方混淆、无答案、检索故障、引用错 ID/错 URL。已有专项测试覆盖基本 metadata、gate、双后端分数、容错和引用纪律；现有离线评测/固定模型场景不证明新增校园资料的真实召回率。见 [policy-evidence.md:65](<E:/Campus Copilot/docs/policy-evidence.md:65>)。

后续再考虑 `source_id + source_version + content_hash` 文档登记、变化检测与去重、过期/撤回规则、嵌入缓存、版本清理和跨主机发布协调。初版继续用不可变完整候选发布，可以先控制复杂度；这些能力不能只靠向现有 front matter 多加几个字段完成。

## 8. 本次研究未验证的内容

- 未验证当前 active 版本、运行中的向量后端、API 凭据与服务可达性。
- 未重查官网政策有效性、SurviveXMUM 当前接口或文章数量；仓库中的历史检查记录只作为现有代码背景。
- XMUMDorm 的指南来源、课表/待办/订单模块及鉴权已有并行静态研究，见 [目标项目研究](<E:/Campus Copilot/docs/research-xmumdorm-target-2026-10-23.md>)；本笔记没有独立运行这些接口，身份桥接、用户数据完整度与业务工具适配仍需联调验证。
- 未运行现有测试、建库、采集或评测；本次交付是源码研究与扩展建议，不是上线验收。

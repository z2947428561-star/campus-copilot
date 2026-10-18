# 政策证据与评测

更新：2026-10-17。政策检索现在返回来源明确的候选证据，并区分证据不足和检索故障。
当前 16 份公开资料仍是人工整理快照；本次没有重新抓取或逐句核验官网文档。

## 来源和引用

归档脚本和公开 Markdown 均记录以下字段，建库时随每个分块传播。

| 字段 | 当前含义 |
|---|---|
| source | 整理时记录的参考来源 URL，不代表已验证逐字一致 |
| source_type | 当前快照为 manual_summary；不能称为官方原文 |
| collected_at | unknown；历史采集日期没有记录 |
| effective_date | unknown；不能保证当前有效 |
| h1 / h2 / h3 | 快照章节标题，不等同于 PDF 页码 |
| offset_scope / start_index | section；标题切分后章节文本内偏移 |

`official_excerpt` 仅供以后核实过的官方摘录使用；标记本身不能替代人工核验。
`student_experience` 和 `unknown` 不进入政策证据，社区经验仍走选课经验工具。
当前接受 `xmu.edu.my` 及其子域和 `zs.xmu.edu.cn` 的 HTTP(S) 参考链接。
域名检查只保证引用地址落在配置范围内，不验证链接可用性、发布主体或内容真实性。

工具返回 JSON，包括 `status`、`evidence`、`reason` 和 `partial`。
证据有标题、来源类型、日期、正文、章节和内容相关的稳定 `P-…` ID。
引用格式为 `[P-完整ID](source)`；带空格或括号的 URL 会编码，避免破坏 Markdown 链接。
相同证据的 ID 不随问题或排名改变；正文、来源或日期改变会产生新 ID。

## 证据门槛

| 状态 | 含义 | 回答要求 |
|---|---|---|
| evidence_found | 有候选通过基本过滤 | 核对覆盖范围；引用并说明整理方式和时效 |
| insufficient_evidence | 查询完成，但没有合格候选 | 说明无法确认，不猜数字、费用或流程 |
| unavailable | 查询均不可用 | 说明暂时无法核实，引导官网或教务处 |

类别检索与全库检索仍会合并，按完整证据 ID 去重并保留最高分。
其中一路失败时 `partial=true`，另一路的合格结果仍可使用。
未知来源类型、非政策来源、空文本、无效 URL、异常分数和低分均被过滤。
不把内部异常、连接字符串或配置排查步骤交给用户。

Milvus 返回余弦相似度，Chroma 返回余弦距离，工具统一换算为 `(cosine + 1) / 2`。
`KB_MIN_RELEVANCE=0.70` 是尚未按真实题集校准的初始候选阈值，不是正确率。
非 COSINE 的 Milvus 配置和已知非 COSINE 的旧 Chroma 索引不能用于这一门槛。

高相关度不能证明片段包含答案。系统提示词要求逐项核对适用对象、例外与日期，
只回答有支持的部分；现行要求、资料冲突或时效不明时说明无法确认。
这部分依赖模型遵循提示词，尚未增加运行时语义裁判或最终回答强制拦截。

## 旧索引迁移

旧索引缺少来源类型时会保守过滤，更新 Python 文件不会自动更新已存向量。
此前 Milvus 客户端还会忽略未声明的动态字段；现已启用动态元数据写入和读取。
本次没有清空或重建现用知识库，也没有向云端发送 Embedding 请求。

准备更新本机知识库时，在项目根目录按以下顺序操作：

1. 确认公开快照内容、来源和待使用的向量后端。
2. 运行 `.venv\python.exe scripts/build_kb.py --stage-only`；此命令构建独立候选集合，并可能调用云端 Embedding。
3. 按[安全发布说明](storage.md)检查状态、发布候选；Web/CLI 下一次检索自动发现切换，无需重启。
4. 检查 `search_policy` 返回的来源类型和日期，再使用真实问题校准阈值。

`archive_docs.py` 只在需要恢复内置快照时运行；它会覆盖那 16 个同名文件，不会抓取新政策。

## 如何评测

在项目根目录运行：

```powershell
.venv\python.exe scripts/test_policy_evidence.py
.venv\python.exe scripts/eval_policy.py
.venv\python.exe scripts/check_offline.py
```

专项回归覆盖归档、分块、检索过滤、容错、双后端分数契约和引用规则。
Chroma 使用临时真实集合和确定性向量；Milvus 使用客户端配置及返回值替身，未连接真实服务。
离线评测默认写 `docs/policy-eval-results.md` 与同名 JSON 明细，包含正确与故意错误的回答。
检查内容包括有效证据 ID、对应 URL、同段逐字引文、来源与时效说明，以及有限的拒答规则。

需要实际调用已配置模型时，可运行：

```powershell
.venv\python.exe scripts/eval_policy.py --model
```

它使用当前系统提示词和六个固定证据场景，不调用检索服务、不写个人数据库。
可能产生 API 费用，结果另存 `docs/policy-model-eval-results.md` 与 JSON，不覆盖离线报告。
输出中保留问题、证据和原始回答，供人工检查适用范围、例外条件、时效和语义蕴含。

规则正反例通过不等于真实模型通过，更不等于真实召回率或政策准确率。
原有 M6 历史报告保留原口径，不能用其旧关键词通过率替代上述检查。

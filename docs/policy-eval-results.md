# 政策引用与拒答评测

模式：offline-rule-controls。时间：2026-10-17T22:28:48.279705+08:00。
规则正反例通过：14/14。

本报告不代表真实检索召回率、政策准确率或语义蕴含判断。
离线模式检查评测器能否接受正确示例并检出错误示例；固定证据模型模式才调用模型。
数字检查、拒答措辞与逐字引文检查均为有限规则；适用范围、例外和现行效力仍需人工核验。

| 场景 | 结果 | 检出的规则问题 |
|---|---|---|
| summary_supported | 通过 | 无 |
| exact_quote | 通过 | 无 |
| unknown_id | 通过 | unknown_citation |
| wrong_source | 通过 | wrong_source |
| changed_quote | 通过 | unsupported_quote |
| missing_citation | 通过 | missing_citation |
| overstated_origin | 通过 | missing_provenance |
| missing_freshness | 通过 | missing_freshness_caveat |
| empty_refusal | 通过 | 无 |
| unavailable_refusal | 通过 | 无 |
| number_after_refusal | 通过 | unsupported_policy_number |
| fabricated_process | 通过 | forbidden_content |
| current_policy_unknown | 通过 | 无 |
| partial_coverage | 通过 | 无 |

完整问题、回答、证据和预期见 `policy-eval-results.json`。

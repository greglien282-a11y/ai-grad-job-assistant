# Pathwise 经历挖掘离线检查 V1

仅工程检查与 DRAFT 标签匹配；不是人工语义评分或真实模型成绩。
划分：development；来源：authored_oracle；模型标签：offline-authored-example-not-a-model。
计划 12，提供 12，缺失 0。
业务门禁案例 0（不计模型质量分母）；意外提供输出 0。
严重风险规则信号 0；人工语义分数 null；真实模型质量 null。

- strict_schema: 12/12 = 1.0000；不可评分 0；不适用 0；单位 planned_outputs。
- runtime_validation: 11/12 = 0.9167；不可评分 0；不适用 0；单位 planned_outputs。
- literal_citations: 9/9 = 1.0000；不可评分 0；不适用 5；单位 raw_candidates。
- draft_candidate_precision: 9/9 = 1.0000；不可评分 0；不适用 5；单位 raw_candidates。
- draft_candidate_recall: 9/9 = 1.0000；不可评分 0；不适用 5；单位 draft_reference_facts。
- draft_positive_recall: 8/8 = 1.0000；不可评分 0；不适用 6；单位 draft_positive_facts。
- draft_boundary_recall: 1/1 = 1.0000；不可评分 0；不适用 11；单位 draft_boundary_facts。
- draft_runtime_accepted_recall: 8/9 = 0.8889；不可评分 0；不适用 5；单位 draft_reference_facts。
- stop_structure: 12/12 = 1.0000；不可评分 0；不适用 0；单位 planned_outputs。
- draft_stop_alignment: 12/12 = 1.0000；不可评分 0；不适用 0；单位 planned_outputs。
- draft_question_purpose: 12/12 = 1.0000；不可评分 0；不适用 0；单位 raw_questions。
- draft_goal_coverage: 12/12 = 1.0000；不可评分 0；不适用 0；单位 draft_question_goals。
- exact_nonduplicate_questions: 12/12 = 1.0000；不可评分 0；不适用 0；单位 raw_questions。
- supported_numeric_tokens: 1/1 = 1.0000；不可评分 0；不适用 11；单位 numeric_tokens。

## 逐例结果
- GQ01: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ02: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ03: runtime_validation_rejected；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ04: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ05: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ06: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ07: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ08: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ09: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ10: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ11: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。
- GQ12: runtime_valid；风险：未触发已实现规则（不证明无语义错误）；human_review=unreviewed。

## 局限
- Exact reference matching uses Codex DRAFT labels, not human truth/quality.
- Business-gate cases have no model-output scores and are excluded from all quality denominators; missing supplied output does not prove no dispatch.
- Runtime atomicity is a conservative lexical guard; mismatches are reported, not fixed.
- Purpose/numeric-token/exact-duplicate checks do not score semantic question usefulness.
- Missing outputs stay in planned-output denominators; unknown candidate counts are separate.
- Empty/no-reference denominators yield null, never perfect accuracy.
- All generation provenance is supplied, not independently authenticated; no real quality claims.
- Public DRAFT holdout is frozen and excluded from examples; not a secret/blind benchmark.

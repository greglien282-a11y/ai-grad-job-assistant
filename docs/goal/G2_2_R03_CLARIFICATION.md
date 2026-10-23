# G2.2 — R03 人工澄清体验候选

基线 main `b96581175f4a2a307a7cfcfb7d60d1609d83983d`；独立研究候选，非持久化、无 HTTP、无数据库、无 Provider。#46 的 24 条对抗案例与 `overnight_research.r03.assess` 原样复用；#49 的模型仍只是内存参考，不是正式 writer。本 PR 不改变它们或任何生产行为。

## 可运行协议

`research/clarification/flow.py` 接受调用者安排的合成 Claim 和带 fact_id/version 的完整 HistoricalFact 列表。来源、身份和历史完整性未认证。begin 对每条历史调用已存在的 M2 诊断，输出冲突事实 ID、版本、所有曾 rejected 原句、风险标签及原因。保留全部历史，包括后来 pending/confirmed 的历史拒绝。不会只显示当前标签后丢弃原拒绝。

数字写法、同义词、数量变化、团队归属变化只能标为 possible_reassertion_not_proven；固定诊断词族不是通用语义等价算法。存在 rejected 但看似无关的贡献明确标为 unrelated_blocked_by_rejected_history。原有 24 例中 6 条标注无关，5 条有当前/历史拒绝，5 条均被最保守政策阻断。这是合成用例可用性代价，不是线上准确率。

用户可提交原样保留的解释和证据描述。explain 要求当前模拟 revision，追加记录，不能覆盖或删除前一解释与历史；不会访问 URL、读取附件或认证证据。状态转为 awaiting_independent_review，语义独立性始终 NOT_PROVEN。重复解释、换 Turn、同义改写、模拟 key 名称均不解锁。

request_save 始终返回 not_saved / transaction_review_and_policy_approval_required。没有 approved、force、ignore_duplicate、人工确认即保存等转换。即使空历史、无风险标签，也不构成独立性或持久化授权。truth_verified=false、persistence_authorized=false、history_completeness_verified=false、evidence_class=SIMULATED_NOT_SAVED 固定，不接受调用者覆盖。

## 验证

`python -B -m unittest discover -s research/clarification -p "test_*.py" -v`：9 项通过，包含全部 24 条既有对抗案例子项、数字/同义/责任归属、无关保守阻断、原拒绝历史、追加解释、并发模拟版本冲突、非法输入、无覆盖参数、不可变值与生产导入隔离。独立 Windows/Linux CI 执行相同命令。无数据库/线程/进程崩溃保障宣称。

G2.4 将提供显式合成浏览器体验；本 PR 是可单独执行的纯函数协议，不宣称已存在前端或正式人工审核者。未来人工审核权限、独立性判定标准、证据真实性、事务级记录、幂等和恢复、隐私与删除仍需单独批准。

## 持续限制

R03 未解决。D4/D5 正式政策、D6 剩余、D8 继续 BLOCK。没有 typed writer/classify/related_plan、迁移、ACL、旧 writer 截止、真实分类依据写入或生产工厂。用户声明、有限词法规则、原话来源、人工解释与平台独立认证是不同能力。保持 Draft，不 Ready/Merge/Deploy。

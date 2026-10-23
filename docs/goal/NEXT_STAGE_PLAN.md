# G1/G2 下一阶段工程计划

更新于 2026-10-23：#44/#45/#46/#49 已合并，main 为 `b96581175f4a2a307a7cfcfb7d60d1609d83983d`，同 SHA main CI 39963621888 全绿。**G1 已由 #49 完成；#47 已关闭，不重做。G2.1/#50、G2.2/#51、G2.3/#52、G2.4/#53 已交付独立 Draft 候选及精确 HEAD 全绿 CI；#53 依赖 #50。仅隔离工程候选完成，等待独立审查，不启动正式 writer。旧未提交隔离候选保留。** 原生 get_goal 返回 null；不凭文档设置或恢复 Goal。用户已授权本轮工程候选，最新状态见 GOAL_STATE.md。

## G1：已完成的五文件移植记录（不再执行）

以下保留原验收方案供核对。已交付 #49 源 HEAD `ca056063c66ca94ec6e8c73744897d149e77ac6a`，CI 39953860759 全绿；main 已包含其 squash。原 #47 后由用户/外部关闭，本代理未关闭或删除它。文中的条件式实施步骤是历史，不是下一次恢复指令。

源 HEAD 固定 `2dc0c6158072438f16eeca181be1d882c77b20a0`，源父基线 `fc9286e8f1b8e0e62f6d59d2821584391d03fd88`。`git diff --name-status <parent> <head>` 实际得到以下五个新增文件，Git blob 身份如下：

- `apps/api/tests/overnight_research/typed_model.py` — `ca87113219816e62382885727aeaa28d64663bec`
- `apps/api/tests/test_overnight_failures.py` — `ac2e7dc663aa91b8ef78da47e150ea84e37e98bf`
- `apps/api/tests/test_overnight_typed_model.py` — `c89745503c5ae9db1ec47b80a963cf3f5ee2f1c7`
- `docs/overnight/TYPED_FAILURE_MODEL.md` — `ef4aa6a006d3c7493ee0075c89a31a67985f70fa`
- `docs/overnight/TYPED_REFERENCE_MODEL.md` — `376e61ea894573932d0e1b941f11855fef39776d`

满足 #46 merge + 新 main 同 SHA workflow/FastAPI/React/Chromium success 后，重新 fetch/核验工作区，再从这个 main 建独立 worktree/分支。用显式五路径从源 HEAD 复制，不 cherry-pick 整个 stack、不 merge #47、不搬入 #46 的已合并文件或提交。复制后先比对 blob；然后只修正两份文档中的基线/依赖/证据描述，并在新 PR 解释这部分有意差异。

必保留 M3 的真实 typed fid 读取、空 classification_citations、not_recorded、legacy 独立断言和三投影全表零效果。核验 test-only 包导入、新 main 已包含 c3b、旧测试隔离要求和测试数量变化；不得用 #47 原先不含 c3b 的全绿结果替代移植后的集成结果。

首选新的 Draft PR（五文件，检查点记录放 G0 分支另提交，避免污染五文件范围）。原 #47 留存并关联新 PR，不擅自关闭或删除；不 force push，不直接 retarget 造成历史 diff 混乱。若需重整原 PR，先给用户具体非强推方案与差异再决定。

验证：M3/M4 专项；完整后端、React/build/E2E types、真实 Chromium/PostgreSQL E2E、隔离迁移、12/48、质量脚手架及 Mock。仅专用合成 DB，random Schema 与实际受限 LOGIN；每项结果记录实际命令和 SHA。新 PR 的 main 基线与 CI head_sha 均重新检查。

## G2：四项独立审查候选

### G2.1 分类声明/依据读取合同

检查现有 FactV3 的 max_length=0 与 basis_status 合同，保留缺失依据的诚实表达。设计独立版本候选（版本号/路由待审），区分：用户类型/阶段声明、文本来源绑定、校验器版本及结果、人工核实与真实性；声明源不能冒充平台独立认证。原始来源、当前文字来源、分类声明来源分别表达，不回填历史 JSON。

交付：固定字段/枚举与拒绝规则、Python/TS 隔离解析器及合成正反例、旧读拒绝/未知版本/分类依据缺失兼容矩阵。解析器不进入 HTTP、不改变已审查的 FactV3/summary v2/export v2，不新增数据库数据。验收特别涵盖伪造引用、原文不一致、旧历史缺键和用户声明/审核混淆。

### G2.2 R03 人工澄清体验

沿用 #46 的实证区分 exact/source/history/suspected/unproven。展示为何需要澄清、原始用户表述及曾拒绝历史；无关新贡献误阻断必须有明确出口候选。保存前只在隔离原型展示“尚未保存”；不得伪造 clarification receipt、自动删 rejected、复用新 Turn 作为独立性证明或提供 force/history_safe。

交付：交互文案、无关贡献误阻断流程、责任与决策候选、非持久化状态机测试。任何“人工决定后能否保存”的持久语义单独审批，不能用确认框解除 R03。

### G2.3 正式写入数据库与最小权限设计

设计文档表达 N 项 Fact/created FC/FS/FCS/声明依据/单 CO3/单 Turn 的约束证明，明确哪些是 DDL/CHECK、哪些需延迟完整性校验，版本隔离与旧合法历史、鉴权/锁/幂等顺序、受限 LOGIN/owner/ACL/安全降级/整会话删除边界。正式类型化写入依旧不实现；不新增迁移、角色或新表，也不扩展现有 writer 的授权。

交付：逐不变量责任清单、最小权限提案、事务/恢复/崩溃/并发测试规格及隔离可执行参考检查。模型证明不能替代 PostgreSQL COMMIT/进程崩溃证据；此阶段不能报告原子写入已实现。

### G2.4 前端录入—审核—来源—恢复原型

独立合成界面，不接入旧 02/03 或 /typed-read、不接真实 API。展示声明类型/阶段、完整 code-point 引用核对、pending/审核、缺失分类依据、R03 澄清、提交不确定与 GET-only 恢复候选。任何演示结果标明“合成演示，未保存”，不使用平台认证措辞；计划/进行中/背景/限制不能变成已完成贡献。

交付：隔离可打开原型、浏览器验收与无网络/无业务写入证据；必须区分模拟操作键、模拟回执和真实恢复合同。按 G2.1 固定候选 DTO，未知版本、缺来源、409/503/断网均安全展示；不构造新 typed POST/PATCH。

## 交付审计与决策

每个候选先收敛为可独立审查 diff、真实验证，再 Commit/Push/Draft PR；记录 PR/HEAD/CI 到检查点。源版本或基线改变后不复用旧结果。运行失败原样记录，平台 skip 说明原因；不放宽冻结测试，不新增 xfail。

下一天独立审查优先级：G0 是否诚实区分“支持 exec”和“实测自动恢复”、共享 runtime/双实例/额度/暂停的原子边界；G1 五文件移植是否遗漏 M3 修复或重复 #46；G2 声明依据是否被误当真实性，R03 澄清是否暗含绕过，权限/DDL 是否只停留候选，原型是否有真实请求路径。

所有生产政策、D4/D5/D6/D8、R03、writer/classify/related_plan、数据库迁移/角色、真实 Provider/付费/部署继续由用户和独立审查决定。任何已批准设计都不能被解释成生产准入。

最终命令、HEAD、CI、文件及模拟边界见 [G2_DELIVERY_REPORT.md](G2_DELIVERY_REPORT.md)。四阶段候选已交付，后续生产政策和 writer 不在授权内；收到独立审查修正后再按明确范围继续。

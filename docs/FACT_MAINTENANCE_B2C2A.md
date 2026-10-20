# B2-c2a 类型基础与兼容隔离候选

基线 main `49a538b2893bff5a9b5e7ae0f5b21024a532ba83`。依据
[B2-c0 §4.2、§9、§10、M/C 矩阵](FACT_MAINTENANCE_B2C_DESIGN.md)。
本候选仅供独立 Draft PR 审查；不部署、不启用 typed 写入，不授权 c2b。

## 已实现的有限基础

- 单链迁移 `0013_fact_maintenance → 0014_append_batch → 0015_fact_classification`。
  0001–0014 不修改。0015 只增加三个 NOT NULL varchar(24) 正式列和组合 CHECK；
  legacy_unspecified/legacy_unknown 可配 legacy-v0 或 unclassified-v1；其余种类
  只能配 explicit-typed-v1，阶段严格按 §4.2 的矩阵。无默认 completed。
- 旧资料仅获得数据库常量默认值。没有 UPDATE 正文/状态/版本/时间戳/revision，
  没有扫描正文分类、改历史 JSON 或新增 FactChange。旧入口新建仍为 legacy-v0；
  这不是“所有新资料都已分类”的承诺。
- 共享 snapshot 对 owner 合成夹具中的非 legacy-v0 记录保存全部分类字段。
  纯 legacy-v0 快照保持原形状；旧 JSON 缺全部三个键才按 legacy 解释。
  有任一键时必须完整、类型正确且组合合法，不能把 null/部分字段当 legacy。
- 新延迟触发器验证非 legacy 当前版本、正文、状态、材料指针与明确分类快照一致，
  并要求唯一 created 历史及原始来源 ID/citations 对应。来源变更也有提交时复检，
  不只依赖较早的即时检查。旧合法 JSON 不追溯重写或全表重新裁定。
- 本阶段没有 classify/退级命令。数据库拒绝已有分类列变化和 typed 记录的旧式
  修改；typed/typed 历史的来源和历史不能单独擦除，整会话删除继续可用。
  受限运行身份不能凭既有表 INSERT 权限创建 typed 行。只有可信表 owner 合成夹具
  可直接 INSERT 并满足延迟约束；它不是服务端 typed 写入口，更不构成语义校验证明。
- 新 helper/trigger 函数沿用 maintenance 的受审查 owner，固定 search_path=pg_catalog；
  PUBLIC 及 CREATE 时继承的具名 EXECUTE ACL 都撤销。没有生产角色或新运行授权。
  运行准入同时检查原六个函数和新增三个函数；不更改原 B2-b 的 DML 白名单。

## 旧读取与写入边界

鉴权后才检查当前分类和 before/after 历史标记。任何曾含 typed/unclassified 分类
的数据不能仅靠当前标签改回 legacy 来获得旧读取资格。

- 纯 legacy FactView、SessionView、summary 和 format_version=1 export 保持原字段、
  内容及排序语义；旧历史 JSON 原样返回。
- 旧 FactView/会话聚合：409 fact_contract_upgrade_required。
- 旧 summary：409 summary_contract_upgrade_required；旧 export：409
  export_contract_upgrade_required。均不省略记录后伪称成功。
- fresh 旧事实/Turn/会话结束/维护/append/mining 写入口遇到 typed 会话，在产生
  Turn、Fact、历史、回执或 Run 前拒绝。旧成功回执仍优先按原合同恢复、零效果重放。
- 旧 MiningContext 构建也拒绝 typed 会话；不把新列注入历史 payload、Prompt、
  Provider 或冻结请求 bytes/SHA，不产生真实模型调用。
- 旧 React Zod 会忽略 extra 字段，无法证明类型语义完整。因此不向它发送 typed
  FactView，不修改前端来猜测协议。现有 legacy React/E2E 验收保持原断言。

Schema 准入使用 catalog 中的版本标记、完整列集合、有效 CHECK、三个函数及八个
启用触发器核验。标记是表 comment 中的独立行
`pathwise-classification-schema-v1`，保留已有 comment；安全 downgrade 去掉该行。
这样不需要扩大 B2-b 身份的 alembic_version SELECT 权限。与 §10 一致，只有
无新标记/列/函数、且具备既有 mining/answer-question 读取基础的真正旧 Schema 有明确
legacy 分支（真实测试覆盖 0005、0010–0014 的创建/确认/会话与导出升级对照）；
部分升级、未知新标记、缺列/约束/触发器、缺 SELECT 均拒绝。不能捕获任意 SQL 错误
后默认 legacy；迁移版本拓扑另外由 Alembic 和隔离迁移测试核验。

0015 降级锁定相关表并检查当前记录与全部分类历史；存在 typed/unclassified
即拒绝。空库及纯 legacy 无新分类历史可降至 0014 并重新升级。
0014 的 v2 CO/墓碑保护继续负责阻止再降至 0013；0015 不丢弃或改动该回执。
失败注入必须证明列、标记、函数、ACL、旧行和迁移版本在同一事务回滚。

## 待独立审查的 D4/D5/D6；本 PR 到此停止

本候选选择“旧客户端对 typed 资料固定拒绝”，不自动升级旧响应。
这牺牲混合会话在旧 UI 中的可用性，但避免旧 Zod 丢分类后把计划当成果。
以下协议仍未定稿，本 PR 没有对应新路由、DTO、写入工厂或能力开关：

1. D4：typed 原话/否定/计划有限校验；related_plan 是否纳入、关系的不可变与删除合同。
   c2a 不含 FactProgressLink，不宣称完成 GQ08。
2. D5：classify 命令及旧 typed 文字编辑的 unclassified-v1 退级。
   本阶段一律拒绝，不能直接修改列或把它洗回 legacy-v0。
3. D6：FactView/来源 v3 的显式路由或协商方式、current_statement_citations 和
   classification_citations、DTO 固定版本、权限及前端真实消费。
4. 建议后续按 §9 独立审查 summary v2：仅确认且 explicit-typed-v1 的
   personal_action/completed 进入贡献正文；legacy-v0 保持旧兼容；pending、
   reviewed_non_contributions 及固定排除原因须另行定稿。当前没有实现这些新字段。
   待审查的有限 reason 候选为：unclassified-v1 → classification_unreviewed，
   personal_action/in_progress → action_in_progress，plan → plan_not_contribution，
   background → background_context，boundary → boundary_limitation。
   reviewed_non_contributions 只收当前已确认/材料支持但不具正文资格的记录；pending
   单列，rejected 和历史版本不进入该列表；incomplete 只按正文资格计算。
5. 建议后续 export v2 为完整技术备份，保留所有类型、历史、来源及未来关系，
   不套 summary 过滤；无法完整读取时 503，不退回 format_version=1。
6. 旧 writer 的 legacy-v0 截止策略、新 UI 的版本校验、Provider/MiningContext
   新合同尚未批准。任何一项未完成都不具备开启 typed 生产写入的条件。

## 验证范围与保留 BLOCK

新增真实 PostgreSQL M01/M02 与 C01–C06 适用子集：合法/非法组合、快照匹配、
旧资料升级与 JSON/读取相等、鉴权优先、旧入口零写拒绝、直接受限 SQL、缺权限/
Schema、owner/ACL、来源/历史不可变、危险降级与失败回滚。命令、数量和本次 CI
结果记录于 Draft PR，未执行的部分不标为通过。

C01 中自动退级、C05 完整 typed 新投影/前端、P01–P04/GQ08 不在此候选完成范围。
R03 全入口语义防复活、新读合同/前端兼容、真实 Provider 上下文、生产 owner/ACL/
运行角色部署、工厂启用及 D8 生产授权全部仍为 BLOCK。
原 B2-c1 rejected 临时阻断和全部已批准边界继续保留。

## PR #38 第一轮独立审查：typed 快照一致性

在审核 HEAD `655932914815a2399fd52e77d775d1b9bf0291fe` 的原 0015 上，真实隔离
PostgreSQL 负例先复现 27 个错误 COMMIT，再复现 10 个缺键/非空 run UUID 类型
错误 COMMIT。当前 evidence_id 不一致原已被 `classification_current()` 拒绝；
重复 created 原已被该函数的计数检查拒绝，非法 actor 和不存在的 run 分别由
`ck_change_actor`、`fk_fact_ai_run` 拒绝。保留这些检查，不重复建立规则。

0013 的 `maintenance_original_fact()` 仅处理已有 FCS 的事实；
`maintenance_current_fact()` 的同版本复检也只处理 FCS 关联的记录。
`uq_change_fact_session` 唯一化的是 (id, fact_id, session_id)，并非 (fact_id, version)。
因此不能用它们证明无 FCS 的 synthetic typed 历史一致，也不新增每版本唯一限制。

仅加强 0015 typed 分支：唯一 created 必须是 system、空 before、pending/v1、
unspecified memory、无 evidence、原始 conversation_turns 来源；origin 和 ai_run_id
锚定建档元数据。当前快照按 `facts.snapshot()` 的所有字段逐键、精确 JSON 比较，
包括记忆、来源和 run UUID，区别缺键、JSON null、字符串及其他 JSON 类型。
当前版本的每条快照都必须匹配，不能以一条正确记录遮蔽另一条错误记录；内容一致的
同版本记录仍允许。数字版本与同值字符串版本也进入复检范围。

statement/status/memory_state/evidence 只与当前版本比对，不要求旧版本等同当前状态。
created 保留原始来源；当前来源按最新 edited 选择，确认/记忆变化不恢复原引用。
合成夹具改用 pending/v1 → confirmed/v2 历史，并验证记忆合法跨版本变化、真实
非空合成 run UUID、SQL NULL/JSON null 的空 before。没有新增运行 writer，
未修改 0001–0014、旧 JSON、API、角色授权、工厂或评测合同。

本轮命令、最终数量和 CI 结果记入同一 Draft PR；上述生产 BLOCK 全部保留。

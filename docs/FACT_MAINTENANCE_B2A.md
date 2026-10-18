# B2-a：事实维护数据库基础与 rejected 编辑保护

基线：B1 合并 `2bb29fad172c4893c5ae1439098ab1c1577d5325`。依据为阶段 A、产品审核和 `FACT_MAINTENANCE_B1_DESIGN.md` 最终版本。本 PR 不提供 ConversationOperation HTTP API，没有自然语言解释器或生产写入者。

## 已实现的边界

共享 `facts.change_fact()` 在持有会话锁、刷新事实并检查 expected_version 后，拒绝 rejected 的 statement 编辑。旧 PATCH 返回既有脱敏 `409 state_conflict`；过时版本仍为 `409 version_conflict`。未来命令复用同一函数也不能绕过。纯 memory_state 修改保留原行为，不改变正文或 rejected 信任状态。pending、user_confirmed、evidence_supported 的合法编辑仍增加版本、回到 pending 并清空当前材料指针。

不回写历史、恢复旧 pending 或自动推定资料真伪。旧手工 AddFact、自动挖掘的跨入口精确去重与新维护回执协作尚属 B2-b；本修复不宣称解决所有换来源/改写后的语义复活。

## 0013 Schema 与约束

迁移链：`0012_request_manifest → 0013_fact_maintenance`。不修改 0001–0012。

- `ConversationOperation`：版本、键摘要、原文提交 HMAC 标签及完整请求 HMAC 标签、root/resolution、动作、会话/Turn/目标版本、有限 proposal_spans、效果数量、固定结果码和恢复期限。不存在持久 running/reserved。只存摘要和引用，不存原始操作键、Bearer、模型响应或自由结果 JSON。
- `FactChangeSource`：与操作、FactChange、Fact 和用户 Turn 的同会话组合外键；intent/statement、原因、Unicode code-point 区间、逐字符 quote、前后版本和效果槽位。FactChange 补 `(id,fact_id,session_id)` 唯一键，不修改旧 JSON。
- 全局 key_digest 唯一；同会话 root submission_tag 唯一；一个 parent 最多一个有效 resolution。resolution 只能引用 needs_clarification 根回执并复用其 Turn、动作和冻结区间；父回执不被覆盖为 resolved。
- 延迟触发器在事务末核对当前会话、结果 revision、用户角色、引用区间、真实效果数量、连续 effect_slot、同一效果的来源角色和唯一 Fact。非法提交整笔回滚，不能只提交新回答。
- append 的初始 FactSource、来源 quote、FactChange.after.statement 和提交时当前 Fact.statement 必须逐字符一致；correct 的新 statement 必须满足同样关系。JSON 缺字段、null、非字符串不能通过 SQL 三值逻辑漏检。现有 created 历史的 SQL NULL / JSON null before 均兼容。
- 版本和状态与 FactChange 快照一致；correct 为 pending、withdraw 为 rejected，旧状态必须允许变更，不能复活 rejected；不自动确认/材料核实。withdraw 不要求其 intent 通过正向贡献动作词表。
- 新 root Turn 和所引用的 FactChange 必须由当前顶层事务创建，利用 PostgreSQL xmin 与当前顶层 XID 比较拒绝补挂旧记录。xmin 本身只证明本次写入：因此同时禁止跨事务 UPDATE 旧 Turn（包括仅更新时间）及旧 FactChange，防止先 touch 旧记录再冒充 INSERT；现有业务只追加这些记录，不更新旧记录。此约束没有重写任何旧行。**当前基础不支持在 SAVEPOINT 子事务中构造来源效果**，会 fail-closed；B2-b 应使用单一顶层事务、每会话每事务一个维护操作，不能把异常捕获后提交部分效果。此检查不替代 HMAC/鉴权。
- 回执关联的变更数还必须与本会话在该事务内真正新增的 FactChange 数量一致；root 恰好保存一条 user Turn，resolution 不再保存原回答。额外未关联效果或第二份回答都会回滚，不能用一个表面匹配的来源数量掩盖部分处理。
- 后续合法编辑不把旧来源与最新正文比较；同版本正文/状态篡改、没有对应新历史的版本跳升和版本回退会被拒绝。旧来源继续对应自己的不可变 after 快照。保护来源和它所引用的 FactChange，禁止单独 UPDATE/DELETE/TRUNCATE 抹除审计。

GQ08 的类型/进度合同未获 B2-a 实施授权，progress / progress_stage 当前明确拒绝，保留为 B2-c 扩展点；不能用 memory_state 冒充计划进度。跨职责 withdraw+append 复合事务、语义身份判断也未实现。GQ12 历史同 ID 表示、GQ03 动作词表和 quality-v1 全部不改。

## 删除、恢复与降级

会话 BEFORE DELETE 触发器在同一事务将整组父子操作脱敏为 deleted；来源随 FactChange 删除。延迟检查要求原会话最终确已不存在，阻止仅清空 submission_tag 的伪删除；独立删除来源或 Fact 也不能抹去审计。

墓碑只保留 id、contract_version、key_digest、state、created_at、expires_at，所有业务关联与 HMAC 标签清空。非过期墓碑不可删除或更改；只有过期 deleted 可由将来独立受限清理流程删除。本 PR 没有清理 API/定时任务，不修改旧 MiningReceipt / IdempotencyOperation 的清理语义。live 记录过期也不能通过 DELETE 清除重复保护。

非空新表（包括 deleted 墓碑）阻止 downgrade。空表允许降至 0012 再升级。升级锁住旧关联表，失败整事务回滚；没有重置 Alembic 版本或半套 Schema 的补救逻辑。

## 权限与锁序

新表和五个触发器/检查函数对 PUBLIC 及继承自 default ACL 的非 owner 角色撤销权限；不创建角色、不授予 Web/runner 读写或任何付费权限。函数固定 `search_path=pg_catalog`，所有业务表使用迁移时可信 Schema 的限定名。删除入口仅为固定 Session 触发器；对新表的普通直接权限不能凭调用验证函数取得。

函数由迁移执行者拥有。本阶段没有部署运行写入者；**正式启用 BLOCK**：须先独立核验迁移/函数 owner 为隔离非 LOGIN 身份，Web 无其成员关系/SET ROLE 通道，以及未来最小权限命令的可调用链。隔离测试 owner 仅用于建 Schema 与构造合成事务，不是生产角色方案已部署的证据。

维护构造先锁 Session，后处理 Fact、Turn、回执与来源；延迟校验重复锁同一 Session，不触碰 Funding/Grant/Call。删除也先锁同一 Session，父子清理不再争取 Funding，未引入 Session→Funding 锁链。数据库级唯一索引解决同提交/同 parent 的竞争。新事务不触发 Provider，未解决 MiningRun（reserved/running/unknown）禁止新维护；stopped 下允许本地事实维护，ended 禁止。六轮计数和挖掘停止逻辑不变。

## 验证范围与命令

仅使用专用 PostgreSQL 测试实例（本机 15487）中的 pathwise_test 随机 Schema。专项 fixture 在运行时禁止供应商 HTTP、原生凭据 API，并校验数据库名称；没有读取日常配置或使用 pathwise_dev / pathwise_probe。

在 `apps/api`，由测试环境提供隔离 `TEST_DATABASE_URL`：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_fact_maintenance.py -q
.\.venv\Scripts\python.exe -m pytest -q -ra
.\.venv\Scripts\python.exe ..\..\scripts\check_isolated_migrations.py
.\.venv\Scripts\python.exe ..\..\scripts\check_m12c2_contracts.py
.\.venv\Scripts\python.exe ..\..\scripts\check_s03b_output_contract.py
.\.venv\Scripts\python.exe ..\..\scripts\run_offline_evaluation.py --profile 0 --output <隔离报告路径>
```

专项覆盖合法 append/correct/withdraw、Unicode 9 code points/10 UTF-16 units、来源/快照/current 不一致、缺字段和 SQL NULL、错误角色/跨会话/旧来源、效果计数、不可变历史、父子恢复、重复/并发、删除双向竞争、墓碑过期清理、权限/default ACL、旧 PATCH 与版本冲突、升级/空降级/非空拒绝/注入失败回滚。所有维护测试 Provider 调用数为零，金额和模型授权未变化。实际通过数量与 CI 链接以 PR 的执行记录为准，不把设计用例视为已测试结果。

必要的旧测试适配：迁移 preflight 和 Schema 测试的当前 head 改为 0013，0011/0012 历史升级目标不改；失败的跨版本 downgrade 仍要求完整事务回滚到当前 head。原 HTTP 和 E2E 各有一项明确断言 rejected 编辑可复活，按本轮安全授权改为 409、事实/历史零写入；E2E 额外保留正常 pending 编辑的键盘确认和失败后草稿保护。不是跳过原场景，也不修改 UI。E2E 总数保持 38。

## B2-b 前置条件

1. 独立审查并实现新 API DTO、HMAC 摘要、键证明/截止复检、GET-only 回执恢复、鉴权与版本冲突顺序。
2. 顶层事务内保存 Turn、精确原句来源和 FactChange；纠错身份/意图不明确时零写回退，不能让数据库的字符一致性冒充语义判断。
3. 跨新旧入口的重复与 rejected 再创建防护、来源 DTO/导出/03 当前版本选择；本 PR 不注册尚未完成的操作。
4. 原子 correct/withdraw/resolution 的 API 级故障测试，停止/六轮不重开，任何恢复不调用 Provider。
5. 正式非 LOGIN 函数 owner、运行角色与清理权限部署须另批；持久开发库/实验库迁移仍未获本轮授权。

本轮没有真实凭据读取、真实供应商请求或费用；未访问持久业务库、探针库和历史冻结账本，没有前端/模型/资金合同变更。

特别地，旧 reject 路径仍保留原 evidence_id 行为；新 withdraw 合同要求清空当前指针而保留历史。B2-b 必须单独实现并验证这个显式命令的 before/after 历史，不能直接把旧 reject 宣称为完整 withdraw API。

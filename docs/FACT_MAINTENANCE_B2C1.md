# B2-c1：批量原子 append（默认关闭）

基线：main `c7eb24ade43ad7fd85eecc0fdb1e4c6f01e0b03f`。本阶段采用用户明确批准的 D1 all-new、D2 S1、D3 rejected 会话临时阻断、D7 append 专用“整理”窄规则。设计依据为 `FACT_MAINTENANCE_B2C_DESIGN.md`。D4/D5/D6 与生产 D8 均未开放；不实现 c2。

## 实现合同

- 新 `POST /api/v1/experience/sessions/{sid}/conversation-appends`；独立 AppendCommand/AppendResult。只接受 contract_version=2、action=append、base_revision、完整 input.content、1–5 个精确 statement 引用。extra、bool/float 索引、typed/related_plan/classify 均拒绝。
- 新 `GET .../conversation-appends/recovery` 和 `GET .../conversation-appends/{oid}`；默认工厂始终 503 conversation_append_disabled，无环境启用开关。既有 maintenance factory 继续关闭。
- 新事务共享 facts.add_turn/add_fact/created history，按 key advisory → Session 锁序执行。先构造一个新 user Turn、N 个 pending/v1/manual Fact 及独立 created/FactSource，再构造一个 CO 与 N 个 statement/addition FCS；任一失败连 Turn 一起回滚。无 skip_guard、局部成功、no-op、Provider 或 MiningRun。
- 正文只由对应原句构造，保留 code-point 半开区间、CRLF、emoji、组合字符与 ZWJ，不 trim/NFC/改写。content 1–10000、单句 ≤500；必须覆盖全部非空白。Python 与 PostgreSQL 明确使用同一 Unicode 空白集合；PostgreSQL 无法保存的 NUL 和无效 UTF-8 被拒绝。
- append-personal-v1 是有限 positive-only 语法：我/本人 + 单个明确动作 + 了 + 对象 + 句末标点。含不确定/否定/计划/团队/假设/组合动作或嵌套引用的输入拒绝，不做一般自然语言理解。仅此策略增加“整理”，全局 atomic、Provider 和冻结 quality-v1 未改。规则可能保守拒绝合法自由叙述，不代表人工或模型质量已经验证。

## 0014 数据库安全

`0014_append_batch` 以前向迁移扩展 CO 的 identity/shape 为 v1 explicit-target-v1 与 v2 append-batch-v1 两组配对。0001–0013 不变，无历史 UPDATE/backfill，也不重算 HMAC、修改期限或重签证明。

迁移携带 0013 validator 的冻结 SQL，使用 CREATE OR REPLACE 更新同一个 maintenance_validate(uuid)，保留函数 OID、owner、ACL、SECURITY DEFINER 与 search_path=pg_catalog；没有新增 helper，没有增加原六个 maintenance 函数的调用权限。v1 分支保持原宽 append/no_new_fact、correct/withdraw/父子澄清历史和原约束。

v2 额外检查 root/applied/append/created、无 target/parent/intent/progress、效果数恰好 N；proposal 顺序与 effect_slot 一一匹配；N 个不同 Fact/created change/唯一初始来源/FCS；相同原句不能占两个槽。新事实 pending/v1、manual、无 evidence/ai_run，快照显式 null 与原文一致。顶层 XID、新 Turn、同会话、全部当前事务效果入回执、来源不可变等仍由既有校验执行。不能补挂旧 Turn/Change，不能用 SAVEPOINT 或 touch 旧历史绕开。

升级/降级均在明确 schema 内持六张相关表的 ACCESS EXCLUSIVE NOWAIT 锁，全部由迁移事务原子执行。存在任何 v2 CO（含 deleted 墓碑）就拒绝降级；纯 v1 资料允许恢复原 0013 validator/shape，但继续受 0013 非空审计降级保护。停用应关闭工厂、保留审计和恢复，不删除记录换取降级。

## 幂等、版本与读取

继续使用 conversation_maintenance_v1 / session:{sid} key proof 和原 submission HMAC。完整请求摘要包含全部已验证字段；换版本/入口/key 不创造新的提交资格。成功回执优先于旧 revision、ended、后来 rejected 门禁。

鉴权后、摘要比较前检查持久 version/decision/action/kind 与固定路由合同。v1 与 v2 GET/POST 错路由固定 409 conversation_contract_mismatch；同合同有效异正文固定 409 idempotency_payload_mismatch。v1 root/resolution 仍按不同完整 canonical request 检查。未知版本不会被当作不存在重新创建。

保留原键 available→Session/归属，以及 operation_id 的 Session/归属→available 顺序。错误 proof 401、外会话 404、到期/删除原安全错误保持。GET 使用同一个实际 REPEATABLE READ READ ONLY 连接，仅 SELECT/SHOW，无锁、deadline 注册、清理、写入、自动重发或 Provider。v2 projector 校验完整效果与来源，损坏固定 410；读取后续 fact.version 不更改原 pending/v1 历史。

## 独立权限

append 有单独 check_append_runtime 与真实独立 LOGIN 测试身份。它需要六张效果表 INSERT、Session 的 updated_at/context_revision UPDATE，以及完整来源读取；不拥有 experience_facts UPDATE、CO UPDATE、审计来源 UPDATE/DELETE/TRUNCATE、DDL、资金写入或函数直接 EXECUTE。

共享准入检查仍检查 role/session identity、无高权/继承/成员、无 DB/schema CREATE、非 owner、六个函数的 definer/search_path/owner/ACL、资金权限及列权限。append 额外要求全部 INSERT 与 0014 validator 存在；缺权限/旧 schema fail-closed。B2-b 角色不增加 INSERT，append 身份反过来被 B2-b gate 拒绝。管理员仅在随机合成测试 schema 准备资料/创建角色，绝不替代 HTTP runtime。

## 测试对应

`tests/test_append_api.py` 与 `tests/append_process_worker.py` 专项覆盖：

- A01–A04：N=1/3/5、全状态/来源数量、非法形状、第二句非法、重复/逆序/重叠/已有原文、全部零写。
- A05–A06：真实运行角色下构造错 quote、after 缺键/null/非数版本、当前正文不符、缺效果/跳槽、额外 Turn/Fact；关闭的仅为测试 projector，DB 延迟约束必须自行拒绝。另测旧 Turn/旧 Change/少于 N 项的 v2。
- A07–A09：同键完整重放、末项/顺序/区间/revision 改动、两连接与两真实进程的同键/不同键竞争；Turn、第一/最后 Fact、FCS、COMMIT 前/后六个真实 os._exit 点，独立新进程 GET-only 恢复，提交前零效果/提交后恰好一批。
- A10：append 与 edit/stop/end/delete 双向 Event 控制，实际 pg_stat_activity 证明 Session 锁等待；stop 改 context 时旧 revision 冲突，停止后显式当前 revision 请求仍可本地追加。
- A11：新 v2 审计后原来源 update/delete/insert/move 拒绝；既有 test_fact_source_maintenance.py 的首次审计、两连接与 RR 快照屏障继续完整回归，所测原始来源 guard/锁规则本阶段未改。
- A12–A13：reserved/running/unknown、stopped/ended/六轮/failed/stale；旧 Turn/Mining 已存输入、新 append 后旧 Turn/Fact/Mining 均保留保护。旧成功回执优先规则继续由原维护/HTTP 回归验证。
- V01–V07：双向两个 GET 路径、跨路由 POST、root/resolution key 冲突、真正 0013→0014 后 correct/withdraw/ambiguity/resolution/append 原型的原 key/ID 恢复与同键 POST、owner/ACL 不变、持久未知版本/decision/action/坏来源/缺权限、proof/归属优先、只读单连接及后续编辑恢复。
- R01–R05：rejected 当前/历史/改写/无关补充一律在新 append 临时阻断，提示未保存且无 operation_id；已有成功结果优先。旧精确/来源保护由原测试继续覆盖。R03 特别用普通旧入口实证一个语义改写仍能建档，作为生产 BLOCK 的回归记录，绝不把它称为安全通过。
- L01/U01：GQ03/团队/否定/假设/计划/复合/数字错配，旧 atomic 不变，emoji/组合/ZWJ/CRLF/Unicode 空白、非法 offset/NUL/代理码点。后续确认/编辑、旧技术导出保留原始来源。
- M01/M02/C03：空库、真实 v1 旧资料、迁移失败注入原子回滚、降级重升、v2/live/tombstone 危险降级拒绝、独立 LOGIN/缺 SELECT/INSERT/过权/危险 owner/PUBLIC EXECUTE fail-closed。

原测试仅更新迁移最新 head 的精确预期（含 E2E probe）；历史迁移目标和全部业务断言保留。实际运行命令、数量和 CI 以本 PR 验证记录为准，不把矩阵当作执行结果。

## 保留的生产 BLOCK 与停止点

1. rejected 会话临时整会话阻断可能拒绝真正无关工作；没有正式独立性/澄清/再主张协议，不保存假的澄清回执，不指引换 key/Turn/会话或旧入口解锁。
2. R03 等旧自由文本路径精确规则以外的语义防复活缺口仍在；本次只收紧新 append，不宣称全入口安全、普通连续补充正式可用或模型质量通过。
3. 生产运行 role、非 LOGIN function owner/ACL、调用链、旧角色 CO/FCS 读取权限、迁移与部署仍须 D8 独立审批。测试 LOGIN/离线通过不是生产许可；两个工厂均关闭。
4. 无类型/进度/计划关联/classify、新 summary/export、前端体验或正式 Provider 变更。事实没有分类，不宣称它已成为完成成果。D4/D5/D6/c2 继续关闭。
5. 未读取真实凭据/账本，不连接 5432/pathwise_dev/pathwise_probe，不产生真实供应商请求、token 或费用。

只交付 Draft PR，供独立复核；不 Ready、merge、部署或继续 c2。

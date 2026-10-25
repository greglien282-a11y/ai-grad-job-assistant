# G2.3 — CO3 数据库合同准备（未安装）

基线 `b96581175f4a2a307a7cfcfb7d60d1609d83983d`。#44/#45/#46/#49 已合并；本 PR 仅新增参考测试和本文，不修改任何 writer、迁移、ACL 或回执。0001–0015 保持原样。CO3 正式持久化、分类依据写入及生产准入均未授权。

## 1. 现状与证据分层

CO1/CO2 已有真实事务、来源、幂等及 GET-only 恢复保障，不能把版本字段改成 3 就复用旧投影。数据库 ck_co_identity 明确只允许 1/2；ck_co_shape 绑定 explicit-target-v1 / append-batch-v1。0015 已约束分类矩阵和 typed 当前/历史快照，但没有独立 classification declaration 表。FactV3 的 classification_citations 仍为空；依据状态只有 legacy_unclassified/not_recorded。

#49 的 M4 模型用内存不可变值验证 N 项图、回滚和回执转移；模拟异常不是进程崩溃，串行排列不是数据库并发，摘要符号不是 HMAC 身份。M3 真实 SELECT-only 读取、损坏历史拒绝与零效果不证明未来 writer 可提交。新增测试分别标注 REAL_EXISTING_DB_BOUNDARY 与 SIMULATED_REFERENCE；不混写为 CO3 数据库已实现。

## 2. 待批准的最小图

对于 N=1–5，建议固定一个原始输入 User Turn、N 个独立新 Fact、N 个 created FactChange、N 个原始 FactSource、N 个 statement FCS、N 个独立分类声明和一个 CO3。effect_slot 为 1..N，无遗漏、重复、多余、跨会话或跨项目边。每条 Fact 初始 pending/v1、manual、memory_state=unspecified、ai_run_id/evidence_id=NULL；任何一项失败整批回滚。正文逐 code point 来自原始 Turn，无改写或自动确认。

每个初始 FC 必须 before=NULL、action=created、actor=system、after.version=1，所有与当前状态对应的字段含分类三列、信任元数据、原始来源和引用完全匹配且保留 JSON 类型。唯一 created；同版本多个快照不得只挑一条匹配。旧合法快照缺分类键只能受控 legacy 解释，不回填、不重写、不加版本。

分类声明候选字段：id、session/project、operation_id/effect_slot、fact_id/created_change_id/fact_version、显式 kind/stage/contract、用户选择来源标识、validator_contract、不可变选择记录摘要与时间。原始建档来源、当前正文来源、分类选择来源分别表达；不得用 FS 冒充用户后来分类的依据。有限词法通过不是真实性认证。

**发现的待决差异：**M4 SimBasis.source 当前复用 statement Source；G2.1 新读取候选则要求独立完整的选择 Turn。这两者尚不构成可直接接通的同一持久化合同。建议联审两个最小方案：

- 一个正文 Turn + 独立不可变 UI 选择事件/来源表。可保持 append 一个 Turn，但 G2.1 的来源类型需另行版本化；不能把事件谎称已保存 User Turn。
- 正文 Turn + 独立选择 Turn，在同一 CO3 事务保存。可保留 G2.1 候选来源形状，但改变 M1 的恰好一个新 Turn 数量，必须明确批准、补图约束和恢复协议。

本轮不选择或安装任一方案，也不修改 M4/G2.1 来隐藏分歧。未来迁移必须以通过联审的图为准；迁移号待当时 Alembic 拓扑核验，不能预占 0016。

## 3. 身份、锁、版本和新请求

正式路由/决策合同、born-contract 和 key 格式待批准，不能由客户端协商降级。候选顺序：严格 DTO/key proof → 同碰撞域 key advisory lock → 查原回执 → 保留原合同的可用性/归属校验和重放优先级 → 对确属新请求鉴权 Session/Project → Session 行锁 → 状态/worker/版本 → 完整历史与来源/R03 → 所有 item 校验 → 一次顶层事务保存完整图和回执 → 延迟校验提交。

Fact.version 是事实历史序列，context_revision 是会话并发屏障，CO contract_version 是操作协议。三者不可替代、重置或从分类推断。跨项目/Turn 来源先鉴权，错误凭证或外会话只返回既有安全错误，不先披露 typed/rejected 详情。新请求遇到未知版本、Schema/ACL/历史损坏固定拒绝，没有旧 writer fallback。

事务内重跑 c3a 的批准版本和 c3b 所要求的来源/历史义务。只读预检不是 capability、租约或写入许可；不可用预检结果跳过 Session 锁或数据库检查。最保守 R03 当前/历史 rejected 阻断会连带拒绝无关贡献，需独立政策批准；无精确复用也不能证明语义独立。

## 4. 同键、跨合同和恢复矩阵

- 已提交 CO1 → CO1 原键/ID：按原窗口和归属恢复；不能受新 typed 准入规则误阻断。
- 已提交 CO2 → CO2：同正文合法 replay 不写；GET 只读。其他正文为 payload_mismatch。
- CO1 ↔ CO2：鉴权后 contract_mismatch；不得当新请求。现有真实参考测试覆盖 CO2 键误入 CO1 GET、原 CO2 replay 与改正文冲突。
- CO1/CO2 ↔ 未来 CO3：双向显式拒绝，旧回执不改版本、摘要、期限或来源。CO3 GET 不投影旧效果；旧 GET 不投影 CO3。
- CO3 同键同规范正文：仅返回原完整效果；后续 revision/历史变化不能重执行。same key/不同声明、区间、次序、数量、语义合同、project 或 revision：冲突。
- 不同 key/同原话或来源：新命令拒绝；数字、同义词、新 Turn 不证明独立。换 key 不能解锁 R03。
- 未知持久版本：固定合同拒绝；未找到合法原回执才可走新请求。删除/过期仍保留各旧入口原安全优先级。

未来 GET-only 恢复必须原键证明或已鉴权 operation_id、独立 SELECT-only LOGIN、一个 REPEATABLE READ READ ONLY 快照。原始 after_version 与 current_version 分开。校验全部图、来源和声明；不完整时整份失败。GET 无 advisory lock、Turn/Fact/Run/CO、key 登记、清理、修复、Provider 或账本效果。客户端网络失败只读恢复，不自动 POST/换键。

## 5. 最小权限和所有权候选

迁移 owner 与运行 LOGIN 分离；安全函数 owner 为 NOLOGIN，固定 search_path、schema-qualified 对象、REVOKE PUBLIC EXECUTE、最小显式授权。函数不得由 writer/read LOGIN 拥有。独立 append3 LOGIN 只能 SELECT 必需表、INSERT 已批准图表、UPDATE Session 的 revision/时间列；不允许任意 Fact UPDATE、历史重写、DELETE、DDL、角色成员、BYPASSRLS、SUPERUSER 或函数所有权。声明表不允许运行身份改写。

恢复 LOGIN 仅 SELECT；无 DML/DDL/危险函数执行。准入检查列 ACL、继承/成员、owner、PUBLIC/default ACL 和安全函数体，缺权限与权限过大均 fail-closed；不能用 owner 连接替代运行身份。旧 B2-b/append2 角色不扩权。工厂默认关闭，测试只用随机 Schema 和真实一次性限权 LOGIN。正式 ACL、环境开关及生产身份由 D8 单独批准。

## 6. 必须完成的真实写入验证计划

未来实现前置矩阵（本轮未通过 CO3）：

- N=1/3/5 成功；逐图节点、重复 slot、缺声明、错误来源、JSON 类型、初始快照及 before 语义失败整批零写。
- 两连接同键同体、同键异体、异键同 revision、异键同来源；at most one 完整提交，失败者不注册残缺键。Session/key 锁顺序死锁和超时需有确定性屏障测试。
- 在 Turn/Fact/FC/FS/FCS/声明/CO 前后、COMMIT 前后真实子进程终止；用另一连接查持久效果。提交前零图，提交后 GET 恢复恰好一图；不能用 Python 异常代替 kill 证据。
- 删除与写入/恢复并发：保留既有整会话删除授权。CO3 墓碑仅保留必要 digest/version/state/expiry，不留原话或声明正文；原 key 不能复活。外凭证不能探测 typed/deleted 状态。到期不自动删有效审计。
- 旧 CO1/2 合法恢复、历史 0013 append、旧 typed-history 门禁、worker stale/fail/unknown 收尾、旧客户端 fail-closed，均不能因新 writer 一刀切失败。
- 全图/source/basis 不可变、owner/ACL 缺失或过大、函数篡改、Schema 未升级、未知版本、降级 typed 非空拒绝；迁移故障完整回滚和合法旧数据字节保持。

## 7. 本轮实际参考测试

`apps/api/tests/test_co3_contract_reference.py`：8 项通过。随机 PostgreSQL Schema、现有独立 append LOGIN/SELECT-only LOGIN，全部合成数据；owner 只在请求外准备夹具。真实 SQL 尝试插入 CO0/3/4，均由 ck_co_identity 以 23514 拒绝且全表摘要不变；旧 CO2 回执仍可 GET、合法 replay，跨路由/改正文不产生额外效果；读取身份证明 RR/READ ONLY 与无高权限，不能 INSERT，且不存在分类声明表。三项 M4 图损坏测试明确只证明内存参考校验。

执行：`TEST_DATABASE_URL=<隔离合成数据库> python -B -m pytest tests/test_co3_contract_reference.py -q -ra`，目录 apps/api。完整后端和现有应用 CI 随本测试 PR 执行，实际结果另记 PR/交接，不能把计划写成通过。

## 8. 需要单独批准

分类选择事件/Turn 方案、CO3 路由/版本/key/期限、born-contract、R03 人工决议与误阻断政策、D4/D5 语义与编辑、D6 新来源读取/导出兼容、删除/墓碑最小留存及 D8 角色准入。方案 A 仅设计假设，legacy writer 未截止。没有 typed append/classify/related_plan/自动退级；没有新迁移、生产配置、Provider/付费或部署。保持 Draft，R03/D4/D5/D6 剩余/D8 继续 BLOCK。

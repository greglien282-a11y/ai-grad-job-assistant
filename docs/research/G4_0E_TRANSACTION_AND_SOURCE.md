# G4-0E：真实事务证据与来源防御回归

基线：#60 `123aaf42d2cc4e7fa1d660ec51cd7d3ee466db9b`。独立增量，不修改 #56–#60 分支、正式应用/DTO/迁移/权限/工厂。

## 产品负责人先看结论

**正式可信写入仍 BLOCK，存在 P1 准入问题。** 一次性 PG16 的真实受限 LOGIN 已证明：提前执行可延迟约束后，检查事件可以被消耗；回到 DEFERRED 不会自动产生一个新 COMMIT 钩子。因此不能把触发器名 `verify_at_commit` 当作不可绕过的最终检查保证。

本轮没有收到平台安全限制拒绝，也未使用其他账户/进程绕过限制。只在明确合成库验证已有授权的问题；本报告保留成功攻击作为风险证据，不把绿色测试说成漏洞全部修复。若后续研究被限制，应停止相应复现并保留记录。

## 实际 T1–T4 结果

随机 Schema、真实 NOSUPERUSER/NOCREATEROLE/NOCREATEDB/NOBYPASSRLS writer；无 owner 请求、无禁用触发器/约束、无时间 monkeypatch。短期 permit 由合成可信签发方真实签发，按它的实际期限等待，不是固定 sleep 掩盖竞态。

- T1，正常延迟到期检查：COMMIT 拒绝，SQLSTATE 23514，失败阶段 COMMIT；revision=1，新增 Fact/operation/permit 各0，全表零效果。
- T2，期限内提前检查再改回 DEFERRED：过期后 **COMMIT 成功**，SQLSTATE=null，revision=2，新增各1，最终 seal 仍匹配，但期限保证失败。
- T3，合法 A 及 permit 提前检查，再暂存不同 key/原话 B：**COMMIT 成功**，revision=3，新增各2；A 最终重算 seal 不匹配，B 匹配。
- T4，不提前检查的 A/B 对照：COMMIT 拒绝，23514，revision=1，新增各0，全表零效果。

每次执行可将 SQLSTATE/失败阶段、身份能力、触发器启用/延迟模式、计数、revision、seal 对比和零效果写入 `G4_0E_EVIDENCE_FILE`，不得包含密码、密钥或真实资料。CI 上传自己的记录；本机原始记录另存 `.e2e/handoff/g4_0e_transactions.jsonl`。

PostgreSQL 的 [SET CONSTRAINTS 官方说明](https://www.postgresql.org/docs/16/sql-set-constraints.html) 明确允许事务内改变约束检查时间，constraint trigger 也受其控制。这里的结论首先来自真实 COMMIT，对照文档解释机制；不是只凭静态猜测。

## 最小收敛候选与其限制

`guard.install` 只在一次性图上建立 **NOT DEFERRABLE 的 created_xid 唯一索引**：同一事务只能建立一个 operation（N 个 Fact 仍由这一 operation 承载）。普通 writer 不能指定 created_xid，不能延迟或删除该索引。早检查后第二个 operation 即使换 Session 也在 INSERT 23505，全事务回滚。

已有 `ref_revision_guard` 继续阻止无对应 operation 的额外 revision 更新，无需重复造规则。首次另加 Session trigger 的候选被原 G3 精确准入拒绝，3 项测试真实报红；没有过滤 catalog、绕过 admission 或放宽旧断言。最终改用不改变既有触发器合同的唯一索引候选，并保留原 revision 约束回归。

这收敛 T3 的多操作状态变化，不是完整最终状态证明。它**仍不能防止 T2 的期限后 COMMIT**；新增测试明确验证该成功反例仍存在。也不是已批准的正式 one-operation-per-transaction 产品政策。

在允许任意 SQL 的事务控制身份下，不能用再加一个延迟 INSERT trigger 宣称得到不可绕过的 COMMIT 实时时钟检查。本候选没有发明这种保证。备选架构需由受信执行器拥有完整短事务与 COMMIT，调用者不接触连接/SQL；它只建立可信程序保证，仍不自动证明数据库硬实时 deadline。若产品一定要求“物理 COMMIT 瞬间未过期”，需重新定义期限与准入时点/授权保留政策并独立批准；当前保持 `STRICT_COMMIT_DEADLINE_BLOCK`。

## 来源绑定与执行链

增加 selection ID、CP 起止/quote、整批替换、Project/Session/Bearer/subject 交叉、组合字符/预组字符、ZWJ/Emoji、同源同 key replay、不同 key 复用、RR 来源快照与写入 revision 变化、两连接同 key 并发的真实 PG 回归。原 #60 的到期/缺失/未知来源、错误旧 issuer 和历史反例原样复跑。

同 key 旧成功回执不需要重签来源，不创建第二份图。来源绑定成功不代表语义独立，R03/旧 CO 共享域不因它关闭。

`execution_pin.py` 增加有限批准文件清单（c3a、G3 runtime/SQL、G4 runtime/SQL、来源模块、guard/pin 自身）及当前已加载 callable 的代码指纹；检查发生在研究执行边界，不从请求动态学习批准值。防御测试显示：原 #60 hash 不包含某些执行依赖，换依赖时旧 hash 可不变；新 pin 对文件变化与已加载函数替换明确拒绝且无写入。

这是配置/运行漂移的有限防御，不是供应链认证或恶意 Python 沙箱。OS、解释器、导入路径、stdlib、psycopg/libpq、native crypto、构建/依赖分发、provisioner、校验器与密钥根仍需审批；攻击者若能同时改检查器和批准值，仍可伪造。B 的新 pin 是同进程防御，独立进程证据留给 C，不冒用旧证据。

## 验证与停止线

```powershell
$env:G3_TEST_DATABASE_URL='postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
$env:G4_0E_EVIDENCE_FILE='<本次忽略的合成 evidence.jsonl>'
python -B -m pytest research/g4_0e_hardening research/g4_source_binding research/g4_trusted_boundary -q -ra --tb=short
```

本机 **122 passed /44.43s**：本轮24 + 原来源14 + 原边界84。全部使用实际一次性PG，不是122个已修漏洞；T2/T3 等测试是特意保留的风险证据。无新增skip/xfail/timeout变化，原测试未删除/放宽。最终准确 HEAD/CI 见 PR，不能把底座 CI 冒称本 HEAD。

`STRICT_COMMIT_DEADLINE_BLOCK`、完整来源审计/执行隔离、共享 CO1/2/未来3 原子域、R03、D4/D5、D6剩余、D8、正式writer/migration/部署/付费均保留。C可做标明限制的研究演示，不能借演示关闭以上准入项。

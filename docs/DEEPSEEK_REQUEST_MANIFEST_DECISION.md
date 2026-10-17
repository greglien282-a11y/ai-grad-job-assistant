# DeepSeek Request Manifest 与崩溃恢复决策（PR29）

状态：**离线合同与合成持久原型；生产正文存储及所有付费派发均 BLOCK**。
基线 add4178b09df95a5b0648e94814af9196c2f43a8。候选 head 为 0012_request_manifest；仅测试库随机 Schema 升级。0008–0011、历史 S03/b 请求/账本、正式 Provider/页面均不改。

## 1. 当前边界及实现范围

PR28 的 PreparedMiningRequestV1 只有内存中的最终 bytes；read_snapshot 是只读时点证据，validate_prepared 不是持久权限。0011 的计划/绑定投影缺 Profile、端点、模式、输出上限及独立 artifact 摘要，也不保留原始正文。三者不能自动组成收费能力。

本 PR 分为三层：

- `app/request_manifest_models.py`、0012：正式候选**元数据**，没有 BYTEA/正文/模型响应/SecretRef/账户或 Grant 审批字段；没有运行角色授权、预算、permit 或 HTTP 函数。
- `app/request_manifest.py`：受信事务中的元数据写入和纯离线原字节验证，没有生产正文读写接口、CLI、API 或 Provider 注册。
- `tests/offline_manifest_store.py`：只允许 pathwise_test/pathwise_e2e 的 test_<随机32hex> Schema，创建 `test_synthetic_request_bodies`。它是**明文合成测试装置，不是安全生产存储**；应用目录和迁移均不创建该表。

没有读取真实凭据，没有加密算法/静态密钥，也没有以权限或 hash 冒充加密、匿名化或用户同意。

## 2. RequestManifestV1 与表结构

`mining_request_manifests`：

- manifest_version=1、Prepared contract_version=1、config/prompt/schema 版本。
- 原 run_id 主键、root_run_id UNIQUE、operation_hash UNIQUE；session_id 是可信业务关联。
- 原 receipt_hash、root_request_tag（HMAC 摘要，不是 Bearer/操作键）、context_revision。
- request_sha、context_sha、完整 system 的 prompt_sha、独立 prompt_file_sha。
- canonical schema_sha、schema_file_sha、profile_sha。
- Provider、Model、expected_version、version_policy、endpoint、region、deployment、mode、structured_mode、output_cap。
- DB clock_timestamp 创建时间；expires_at 强制取首次 Run lease_until，不由调用者延长；storage_state 固定 metadata_only。

所有字节摘要沿用 PR28 的精确定义。prompt_file_sha 不是 system SHA，canonical Schema SHA 不是原件 SHA；别名/预期版本不是权重证明。Profile 全有效快照由原 profile_sha 和 pinned artifact 验证，版本绑定 config_version；没有复制自由 blocker 文本。

0011 是计划/费用绑定；0012 是完整请求配置及摘要记录。INSERT 触发器核对同一 Session/Run、当前 revision/运行状态/lease、0011 原计划和 live 原 root receipt；相同 root 不得换 Run。跨 Run 重试沿用原操作，但不能建立第二份 Manifest。

数据库拒绝任何 UPDATE、正常 DELETE 和 TRUNCATE。只有父业务对象已经删除的 CASCADE 才允许清除元数据并建立防重放墓碑。首次写入后的重复冻结只读取并比较完全相同的元数据和 body，绝不覆盖；body 缺失时拒绝，不能用缓存或 Adapter 补写。

RequestManifestV1 是可信 DB 记录的 canonical 元数据投影及时间/存储状态。恢复另传原始查找期望 Session/Run/root/operation；不把 DTO 自报身份当作独立证明。manifest_sha 绑定这些元数据与可信时间，便于本机审核，**不是签名或许可**。数据库 Owner/恶意同进程可以绕过自身代码，均不在不可变性威胁模型之外假装被防御。

## 3. 事务、锁顺序与线性化

0011 计划必须先由独立审查的流程提交。新元数据写入按 Session UPDATE → Run KEY SHARE → Manifest 顺序；INSERT guard 同样如此。**没有接着锁 Funding，也不调用 0011 写入器或 PaidControl。** 不产生 Session→Funding 反向链。未来收费许可仍须采用 Funding→Session→Run 的既有顺序，不能在持有 Session 后请求 Funding。

迁移是停写维护候选，使用 ACCESS EXCLUSIVE NOWAIT；遇忙失败并整体事务回滚，不等待形成锁环。函数固定 search_path=pg_catalog、对象引用完全限定。guard 的 SECURITY DEFINER 仅做元数据拒绝及删除墓碑写入；PUBLIC 和所有继承的默认非 Owner grants 都被撤销。没有新的 reserve/permit/dispatch 可调用链。

合成装置把元数据和 body INSERT 放在同一事务、同一个 PostgreSQL Schema，依赖 FK CASCADE 清理。事务没有 commit 时二者都不存在；commit 后进程 os._exit，二者都保留。此证明只适用于这个同库测试装置，**不证明未来外部加密存储与数据库能天然原子提交**。

恢复只执行 SELECT，按 Session SHARE → Run SHARE → Manifest SHARE 锁定，核验凭据摘要、业务身份/状态/revision/lease、原查找条件，再取原 body。它**不是数据库强制 READ ONLY 模式**：PostgreSQL 的行锁要求可写事务，不能把 SELECT FOR SHARE 描述成 REPEATABLE READ READ ONLY。PR28 的 fresh 检查仍独立使用其真正只读事务。

- 删除先取得 Session 锁并提交：恢复等待后见不到父对象，拒绝，不返回 body。
- 恢复先取得 SHARE 锁：删除等待其事务结束；该次恢复只得到一个时点性内存副本，随后删除清除存储，再次恢复拒绝。
- 无法追溯抹除已经交给调用者的 Python 内存副本；副本没有发送权，继续业务前必须重新 admit_offline。真实 Broker 将来还必须在最终许可事务中复核删除/撤销。

原业务删除须走已有 delete_session 的回执清理流程。不能直接 DELETE Session 而跳过 ai_mining_receipts FK；并发测试调用同一个原业务函数。

## 4. 原字节恢复，不重新生成

恢复顺序：

1. 从固定业务查找条件加载受保护元数据和存储的原 body。
2. 核验存储状态、创建/过期时间、原 Session/Run/root/operation，以及 body SHA。
3. 从原 body 解析原 Context；不读取新的历史来替代它。
4. 从已审查的本地 artifacts 取得 pinned Profile/Prompt/Schema，仅核对配置和摘要，不构造新请求。
5. 重建的是 Prepared 合同包装，body 仍为存储读出的原 bytes；调用既有独立 validate_prepared 验证 wire、完整 system、Schema、原引用上下文和元数据投影。
6. 返回 recovered_and_verified=true，paid_authorized=false、dispatch_permitted=false；没有 offline_contract_valid。

恢复没有 prepare_request、Adapter、build_context、MockTransport 或模型调用。新进程恢复测试将这些构造函数显式替换为禁止入口，仍恢复相同 SHA/bytes。body 缺失、篡改、截断、配置变化、存储无权限或记录不可用时停止；不自动生成、重新签名、补写或换 key。

本轮没有生产加密存储、解密密钥或 Broker，所以“真实生产密钥不可用”的端到端测试**尚未实现**，不是用假密钥宣称通过。生产入口仍不存在，无法读真实用户正文。

## 5. 删除、过期和费用审计

无费用责任：业务删除级联清除 Manifest、测试 body 及唯一副本，留下 `mining_request_tombstones` 的 root_digest、operation_hash、request_sha、erased_at、expires_at。没有 Session/Run UUID、用户 scope、receipt、原文或完整配置。过期时间由 DB 固定为删除后24小时（候选协议，不是已批准生产留存政策）。这些摘要仍可能可关联，**不是匿名数据**。

存在未来费用责任：同样删除 body 和完整 Manifest。0011 的独立 MiningPaidBinding 墓碑与 PaidCall/中央金额保留，unknown/sent/reconciled 不变、不退款、不重授权。0012 不另复制完整费用审计，更不会为账单保留原文。测试使用明确虚构的费用责任 fixture；它不是合法付费授权或实际费用。

24小时到期只允许独立批准的元数据维护者显式执行 purge_expired_tombstones；DB 拒绝提前删除和修改期限。该维护函数不注册、不调度、不自动运行，本轮没有授予维护者角色。过期不能让 API 重新创建原业务 UUID/root/已销毁的 receipt。危险 downgrade 对任何 Manifest/墓碑记录都拒绝，不能借回滚清除防重放。

生产部署前必须批准留存政策和维护调度/监控，避免逻辑 expires_at 到期后物理记录无限滞留。0011 既有费用假名审计的期限/核账后脱敏依然是独立 BLOCK，本轮不改历史删除规则。未来若核账必须保留 Profile 等额外证据，应另设计最小审计摘要绑定与期限；不能靠无限保存 Manifest 或正文解决。

lease 过期、停止、结束、unknown/stale/completed 等不活跃状态均不能继续使用恢复路径；现存 bytes 的离线验证结果不能升级为当前请求。过期正文的生产自动擦除/备份传播尚未实现，仍 BLOCK；合成装置会随测试 Schema 一起移除。

## 6. 权限合同与上线 BLOCK

- 元数据写入者：未来受限身份，仅通过审查过的冻结过程提交，不掌握资金管理。当前只有迁移 Owner 可用，新迁移不授予运行者 INSERT。
- 只读恢复者：未来经认证的独立 Broker/存储读路径，有业务查找范围和删除锁语义，不能改 Manifest。当前合成锁测试使用测试 Owner，**不宣称生产只读 LOGIN 已实现**。
- Web 业务角色：无 Manifest/正文表权限，无钱权；已有业务 CASCADE 可触发受限 erasure，不需要授予新表写权限。
- 独立费用审计者：只查最小审计摘要，不读取请求正文；未来期限单独批准。
- 可消费 Broker：本轮不存在，不能从恢复结果取得发送许可或生产 Secret。

受限 LOGIN 测试使用真正独立的随机测试角色，验证不能读取/改写 Manifest、测试 body 或取得新资金权限，不使用管理员 SET ROLE 假装运行者。未来 SELECT FOR SHARE 的权限不能粗暴地通过给 Web UPDATE Session/Manifest 来解决，必须另审受限函数 Owner、调用参数、认证范围和锁权限。

生产存储至少还缺：独立密钥管理与撤销、AEAD/KMS 方案与 key version、认证访问控制、受保护正文恢复/删除与备份擦除、同库/跨存储原子协调、留存审批、受限 LOGIN 和 Broker。不得将 test_synthetic_request_bodies 或普通目录直接部署给真实用户。

候选最短生产设计（仅设计，未实现）：由独立 Broker 在事务外完成经审查的加密，然后在业务侧受保护 Schema 内把密文对象引用/密文与 Manifest 同事务提交，中央费用表不收正文；KMS 密钥不进入数据库。提交前失败则没有可恢复 intent，提交后只解密同一对象，不重新生成。若选择外部对象存储，必须另加不可变 provisional object 回执、durable intent 和显式 orphan/删除回执协议，不能宣称沿用本轮同库原子性。需要单独证明断钥、吊销、备份删除及每个跨存储崩溃窗口。

本候选函数当前由迁移身份拥有；测试 Owner 是隔离管理员，不冒充生产角色。生产部署必须单独审查非 LOGIN 函数 Owner、成员关系/SET ROLE、默认 ACL 和 Broker 最小调用权限；本 PR 没有创建这些角色，也没有部署授权。

## 7. 验证、失败记录与复现

在显式 TEST_DATABASE_URL（专用测试库）下：

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m pytest -q -ra tests/test_request_manifest.py
.\.venv\Scripts\python.exe -m pytest -q -ra
```

测试覆盖：首次冻结、相同冻结读取恢复、并发唯一、事务回滚、真实子进程提交前/后 os._exit、新进程禁止构造器后的恢复；字节缺失/篡改、完整配置/身份篡改、根重试、跨 Session/Run、revision/lease/停止/结束/删除；删除与恢复两个锁时序；纯 SELECT 恢复、反复恢复零 Mock 调用；独立显式 Mock 请求经原验证/complete 仅产生 pending；费用状态不变、业务删除不丢费用责任；权限/default ACL、安全迁移/回滚/危险降级拒绝。既有0009排他保护及业务/E2E断言继续保留。

首轮78通过/6失败：子进程导入/数值地址隔离、纯恢复缺独立 Run 查找期望、并发删除夹具跳过原回执清理，以及 TRUNCATE 先被 FK 拒绝而未进入 guard。分别修正测试进程环境、增加独立 lookup、调用原 delete_session、显式列出合成子表测试触发器；没有删除失败断言或放宽旧业务规则。相关38项复验通过。最终数量与完整 CI 以 PR 记录为准。

收尾的双连接测试另复现2项失败：调用者预加载 Run 到 SQLAlchemy identity map，另一个事务提交 unknown/lease 变化后，行锁查询仍可能返回缓存属性。新写入/恢复路径的锁定读取显式 populate_existing，分别覆盖 stop/end/revision/unknown/lease 的10项回归；不修改旧业务模块。这也说明“获得行锁”不等于“ORM 属性已经刷新”。

恢复装置还拒绝带 new/dirty/deleted 对象的调用者 Session，防止 SELECT 的 ORM autoflush 隐式写入。三项回归断言拒绝发生在任何 SQL 之前，原业务状态不变。生产恢复仍需独立角色与受限事务设计，不能仅依赖这个测试辅助函数。

## 8. 崩溃处理及最短后续步骤

- 提交前崩溃：合成同库事务整体回滚，无部分正文/Manifest。只能恢复已有记录；没有则停止，是否重新冻结需要用户/服务端独立决定，不能自动产生收费操作。
- 提交后崩溃：新进程按原查找身份读取原 bytes，不调用 Adapter，不建立第二个 Manifest。
- 已 sent/unknown 或业务输出失败：恢复不触碰费用状态，不推理、不退款、不补调；必须原核账流程人工处置。
- 配置/证据变化或存储损坏：固定安全错误停止，保留原元数据，不自动修复、删除、换 Run 或重新签名。
- 最短下一步：先审查生产正文存储/密钥与原子 intent 协议、删除和留存调度，再审受限恢复 Broker 与动态预算准入。真实质量探针、请求字节、账户/币种、预算和风险窗口仍需单独授权。

停用：不注册本模块，正式 Provider 继续关闭。空表可安全降级；非空保留元数据，不强行 DROP/清空。撤回代码不撤销已有费用责任。

本 PR 的真实模型请求、真实凭据访问、真实数据库访问和真实费用均为0；测试 PostgreSQL/Mock 不等于供应商行为。保持 Draft，等待独立审查。

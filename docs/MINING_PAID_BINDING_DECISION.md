# MiningRun 与中央费用账本绑定：v1 离线决策及迁移提案

状态：**原型可执行，正式上线 BLOCK，未注册 Provider / API / 真实 Transport**。
基线 `37a9632a2b0105ae1f6a39336c06215c226b91ca`。本轮没有 Alembic 新迁移，不修改0008/0009，不触碰已有实验、额度或原文。以下DDL仅由测试装入新的随机schema。

## 1. 审查发现与不可变边界

- 0006 `cost_ledger.Ledger` 是namespace内的 MOCK/CNY_SIMULATED；换namespace会另建模拟限额，不能承担真实全局预算。
- 0008 `paid_funding(id=1)` 是中央CNY总池，以ledger UUID识别部署；`paid_calls`保存USD价格经批准FX/税费余量转换的CNY预留，以及实际原币USD/折算CNY。provider/model scope、grant/call限额和并发均在同一个总池锁内检查。`PaidControl.reserve()`只接受既有固定 `SyntheticRequest` 白名单，真实动态请求仍被拒绝。人工approve/reconcile只属于独立owner角色。
- 0009 `controlled_exclusive` 对paid_calls INSERT的保护：**只要controlled_probe存在任意记录，即使已reconciled，也禁止新paid_calls**。实验记录不可删除，downgrade在非空时拒绝。已核销、冻结的S03/b不能重新授权、复用或通过更换操作键/库/namespace恢复发送名额。
- `mining.reserve/claim/complete`是独立短事务；`PaidControl._invoke()`另开事务，现有Python方法不能自动共享业务事务。若业务与账本部署在同一个PostgreSQL数据库，可在一个连接/事务内调用原paid_runtime再写绑定（本原型）；若位于不同数据库，即使同一5432实例也没有普通跨库事务，必须使用持久协调协议，不能声称本原型已证明跨库原子性。
- 当前应用只有临时Bearer会话，没有可信的跨会话真实用户账户。token或客户端user_id不是已认证用户。真实user总限额必须先解决身份发行；MVP最多能证明服务端授权的匿名会话范围。本轮用**测试服务端登记的合成用户身份**验证跨会话user子限额，不代表正式身份体系已实现。
- `DeepSeekBridge`是固定合成请求+受限账本角色的离线链路；`controlled_probe_io`是人工单次实验。二者都不能成为绕过正式mining准入的通用付费Provider。本轮不改变它们，不重新使用历史探针许可。

## 2. v1 数据合同及唯一约束

`app/mining_call_binding.py`只定义冻结的 `MiningCallBindingV1` 元数据，无ORM注册、引擎、环境读取、密钥解析或启动副作用。其余可执行代码位于tests，无法由生产配置开启。

完整DDL提案：`apps/api/tests/fixtures/mining_paid_binding_v1.sql`，不是迁移文件。只接受专用本机测试库和`test_<随机UUID>` schema的安装器执行，正常Alembic head仍为0009。

### mining_call_bindings：不可重新绑定的费用审计

- `contract_version=1`；`run_id`主键；`root_run_id UNIQUE`；`operation_hash UNIQUE`；`call_id UNIQUE FK paid_calls ON DELETE RESTRICT`；`grant_id FK paid_grants ON DELETE RESTRICT`。
- `receipt_hash`为原始root MiningReceipt的高熵幂等键摘要，不是Bearer或用户原文；操作摘要绑定版本、ledger、root receipt、actor_scope及session_scope。沿retry_of查找root，显式重整也不能取得另一笔付费调用。已对账不释放这些唯一约束。
- `actor_scope/session_scope`为服务端HMAC作用域；本原型合成身份由owner测试fixture登记，普通运行角色无法登记/修改。HMAC秘密与原始用户标识不入绑定表。正式身份密钥轮换必须保持历史映射及累计限额，不能每次换key/实例重置用户范围。
- `ledger_id/call_id/grant_id`、provider/model、`profile_version=fixed-fixture-binding-v1`、request/policy/context/prompt/schema SHA、数据库clock_timestamp创建时间。
- `binding_state=bound/tombstoned`与`tombstoned_at`只表示业务资料是否删除，**不是业务run或paid_call状态**。二者分别从原表读取，不能把reconciled当成business completed。
- UPDATE/DELETE触发器拒绝改写/删审计，只允许保持全部其他字段不变的bound→tombstoned一次转换。无FK指向business run/session，业务删除不会级联清除费用责任。call/grant的RESTRICT阻止审计悬空。
- 不保存经历、模型回复、材料、API Key、Bearer、完整DSN、客户端user_id。request/context摘要及随机run UUID仍是可关联的**假名化审计资料，不是完全匿名数据**。

### 只由可信测试服务预置的资料

- `binding_identity`：授权业务session→server actor/session scope，session删除即级联删除；禁止更新身份映射。
- `binding_plans`：run/root/session、中央ledger/grant、原receipt/operation摘要、request/policy/context/prompt/schema/account摘要、配置版本与可信创建时间；禁止更新，业务删除级联清除。stager先调用原`facts.authorize()`，核对run会话/项目/输入/revision和固定合成来源，再从服务端登记及不可变grant构造字段。客户端没有提交grant/call/user/scope的接口。
- `binding_limits`：user/session的**附加上限**（CNY ceiling、次数、未核销并发、批准证据摘要），没有held/spent余额，不可独立消费。普通角色无写权限。花费/占用唯一从中央paid_calls经binding关联求和，`coalesce(actual,reserved)`；tombstone也计入历史。次数不因核销或删除归零。

正式迁移建议：审核后新增00010（名称待定），创建上述表/约束/受限函数与业务删除触发器，空表/零权限默认，不种任何正额度或审批。先回填/人工检查是否有未归属paid_calls，无法归属则停用。非空绑定、未核销call或历史tombstone存在时downgrade必须拒绝，不允许删表重获发送资格。需要单独验证空库、0009升级、回滚拒绝、现有资料兼容和函数权限；**本PR未新增、执行此正式迁移**。

## 3. 单库事务预留与权限

测试函数 `binding_runtime(ledger,action,run_id,usage)`是唯一原型写入口。运行调用不接受PaidCall、Grant、User或Session标签；从可信plan查出。固定schema/ledger在服务端构造。

1. 校验session_user为指定独立LOGIN，拒绝owner/超级用户、INHERIT、角色成员、CREATE及任何持久表DML；也拒绝可直接EXECUTE旧paid_runtime的角色，防止绕过归属子限额。
2. 锁中央paid_funding(1)，核对唯一ledger UUID；已有binding先核对PaidCall的operation/request/policy/grant/provider/model。相同bind只返回既有call，不重派发、不重复预留。
3. 对新bind/permit检查业务run=running、session/mining active、revision/lease，服务端plan与grant账户/配置/证书对应；先锁Session FOR UPDATE，再锁Run KEY SHARE，直到事务提交；等待后重新验证锁定的Session状态/版本，防止停止/结束/版本更新被普通快照读漏掉，以及分配/删除并发留下未标记的绑定。存在未归属中央paid_call则拒绝分配。存在sent/unknown/response_received未核销时保守阻断新调用。非实验总池的held/spent与中央调用求和不一致时拒绝，不自动修账。
4. 在同一事务内调用**原0008 paid_runtime reserve**，其检查grant时效/撤销、价格/FX/完整输入证书、provider/model/单次/grant/全局次数及预算；原0009触发器继续生效。随后写唯一binding。任意插入/约束/子限额失败，整笔paid_call、held、audit及binding一起ROLLBACK。
5. 完整锁顺序是中央总池→Session FOR UPDATE→Run KEY SHARE→user→session子限额，从中央记录累计费用、次数和未核销并发；没有批准的子限额拒绝。全局锁已串行化不同进程/批次，子限额不形成第二套预算。原0008的provider/model查询在同一全局锁内，不再获取独立互相冲突的锁。业务删除只执行原级联和绑定tombstone，不反向获取资金锁；后续不要添加Session→Funding的事务路径造成反向死锁。
6. permit前重新核验撤销、配置、lease及限额，再调用原paid_runtime取得唯一一次sent许可。预算不足/审批改变不释放预留，也不回退模型或换key。
7. received/unknown允许业务删除后更新既有账单状态（不能新增call）；只接收原paid_runtime允许的规范usage。只读`read()`强制READ ONLY，不调用任何状态函数或模型。显式人工对账仍只走原PaidAdmin；核账不恢复permit。

原型最小权限：新测试LOGIN仅有schema USAGE、binding/paid_calls/funding的SELECT及新函数EXECUTE；没有底层paid_runtime EXECUTE、表DML/DDL、owner或审批权。函数固定search_path=pg_catalog并完全限定表名。全部PUBLIC EXECUTE撤销。正式部署需再验证专用非LOGIN函数owner、业务服务角色、审批角色、账单审计角色，不能把迁移者凭据交Web进程。本轮测试DDL由隔离schema owner拥有，不证明正式生产角色已配置。

## 4. 三个状态机与故障窗口

- 业务：reserved/running/completed/failed/unknown/stale。由原状态机和事实来源、lease/revision检查控制发布；候选始终pending，确认权不变。
- 费用：reserved/sent/response_received/unknown/reconciled。发送许可后任何不确定性保留全部预留；failed/stale/删除不等于退款。输出通过或收到200也不等于对账；模型可能已收费但无候选。
- 绑定：bound/tombstoned。唯一身份、字节和审批关系不可变，业务/费用状态不塞进此字段。

本轮可执行故障证据：

- 业务预留已提交、未staging/绑定：恢复可见run，费用为0，不能取得许可；不自动创建plan或发送。
- paid reserve成功、binding插入前触发器报错：真实SQL事务把两者一起回滚，held=0，无孤立call。
- binding/费用预留已提交、许可前进程`os._exit`：独立进程读取仍reserved，hold保留，旧bind只读返回；下一步不能自动派发。
- permit事务尚未提交便异常：ROLLBACK回reserved，无真实HTTP。**内存中的布尔true不是已提交许可证明**，正式Transport需独立可消耗派发令牌，当前0008布尔permit不能直接作为公网入口。
- permit已提交、HTTP前进程`os._exit`：sent+完整hold持久存在，第二次permit=false；不宣称供应商执行次数。
- HTTP Mock超时：业务unknown、费用unknown；不同key/用户/批次新绑定被保守阻断，不退款、不重发。
- received提交后、业务commit前进程`os._exit`：费用response_received+hold，业务仍running，无事实；GET只读不能重新推理/补发布。
- 业务commit后进程`os._exit`：独立连接可见pending事实与completed，费用仍未核销；claim不会再次执行。
- 输出引用错误或并发用户修改：原mining.execute/complete产生failed/stale，无候选，但费用response_received且hold保留。
- 删除业务：原DELETE HTTP真实级联删除原文、问题、事实、run及plan/identity；触发器只留下tombstone费用审计，received/unknown/人工对账仍可跟进。删除后同一服务端身份新会话仍受历史累计限制。

跨进程同run绑定只产生一个call；跨进程相同用户及不同用户共享总池竞争，不突破user/global预算。线程重放、同键恢复、retry链核账后换key、同PaidCall映射另run、错误ledger/account/policy和不一致中央行均有拒绝测试。

## 5. 重要的未证明项：固定请求与正式字节绑定

本原型使用原0008合成白名单与虚构token证书/价格/FX，仅在随机schema生效；这些**不是实际批准、真实输入上界或供应商计费证据**。没有制造新可用的付费授权。

固定SyntheticRequest含固定项目/用户回合UUID和原文，测试business fixture使用这些相同来源；stager校验其匹配，request SHA来自完整不可变bytes。原始审批请求中的合成context_revision/stop/history与原business claim的真实快照不必相同，故**同时保留独立context_sha并明确profile=fixed-fixture-binding-v1**。FakeBoundProvider只用Mock返回来源合法的夹具，再交原complete，验证的是**费用归属与事务约束**，不是证明正式多轮context已获此固定请求授权。

动态MiningContext完整bytes、prompt/schema版本、模型/区域/模式/上限与真实grant绑定仍BLOCK；不能把business context hash当作固定request SHA，也不能重写旧SyntheticRequest/历史SHA来消除差异。PR25的动态请求接线与本PR的固定授权费用原型都不能单独或合起来宣称真实Provider准入完成。

## 6. 不同数据库的持久协调协议（提案，未实现/未验证）

如果正式架构选择业务库和中央账本分离，建议先新增并审查业务侧immutable调用intent/outbox及中央allocations/回执，不使用无持久性的内存saga：

1. 业务事务中原子写run/receipt与服务端确认身份、作用域、context/request/policy摘要的intent；root操作稳定绑定，调用未知不能换key。用户内容留业务库，不进入费用outbox正文。
2. 中央分配服务凭服务端签发、时限/撤销受控的intent，按唯一(ledger,root operation)完成call+central binding+子限额预留。中央先生成的回执是持久分配事实，不是可任意消费的前端授权。
3. ACK丢失时只按原操作读取中央回执并核对全部摘要；不能新建operation/call或自动POST模型。业务侧持久写入匹配的call_id后才可申请单次派发令牌。
4. 派发服务在中央事务最终校验意图/权限/费用/撤销及回执一致性，再提交可消耗permit；broker必须自行核验并消耗令牌、绑定实际发送bytes，之后才解析SecretRef。网络层/代理层不能保证绝对一次，关闭重试并保留unknown责任。
5. 发出后无论本地ACK、业务commit、删除或结果校验如何，中央费用不得补偿性退款。未发出的孤立预留也仅可由owner核实没有任何permit后使用既有close_unsent；保留原operation防重放，禁止删除恢复额度。回执不明不能自动释放。

**未完成**：两个真实数据库的durable outbox、互认身份/撤销、ACK丢失恢复、分区/故障切换、两侧并发删除与派发、孤立预留审核和输出安全恢复。需要后续正式迁移和双库故障测试；本PR同库SQL/多进程测试不覆盖这些窗口。不得用内存Mock宣称跨库保证。

## 7. 数据删除、留存与人工核账提案

业务原文按现有删除规则即时级联删除；费用保留只包括随机run/root/call/grant/ledger、假名scope、摘要、金额与时间/状态。对账证据保存在单独受控账户审计范围，不把余额截图、账户个人资料或原始模型响应写进binding。账单读取/核销另行授权，普通应用不能审批/增额/解冻。

期限提案（未批准，代码无自动清理任务）：已核销明细建议90天后由独立审计审批按实际法律/财务需求最小化；未核销/unknown每30天人工复核一次，不能因为到期默认为0费用。最小防重放墓碑及call/grant关联需随ledger生命周期保留，不能在旧授权/操作仍可能重放时清除。身份映射、可关联HMAC密钥与账单明细是否可销毁、何时销毁需单独隐私/财务决策；不能承诺“完全删除了所有个人可关联信息”。现有immutable表不能直接执行上述归档/脱敏政策，需另审迁移及非运行角色流程。

人工核账：停止新付费调用→只读核对原call/usage/时间/账户证据→负责人确认原币实际金额、价格/FX/税费→唯一账单摘要核销→如超预留记实际超额并冻结→检查全部未知、未归属和scope超限→独立审核后才考虑解除未来准入阻断。核账/解冻不允许旧run重新获得第二次call，旧experimental记录永不复活。

## 8. 上线BLOCK与最小后续顺序

1. 审查本契约、DDL、权限和故障证据；决定正式同库或跨库部署。**现有冻结pathwise_probe不能作为新业务消费池，也不能擅自另建pool逃避它**；必须获得单独中央账本部署/历史负债迁移审计方案，现有保护继续拒绝。
2. 决定可信用户身份、scope密钥发行/轮换、隐私同意、留存期限。真实账户CNY/USD、价格/FX/税费与完整Token/风险授权合同仍未解决；旧一次S03/b风险接受不能转为一般业务许可。
3. 单独小PR审批正式迁移、中央子限额/intent/绑定函数的最小权限，含非空downgrade拒绝、角色升级攻击、deadlock/撤销/未知/跨库故障测试；不交Web管理员凭据。
4. 独立审查broker、可消耗派发许可、byte SHA与模型/提示词/Schema冻结、版本化非synthetic DTO/Provider准入。完整输入证据不足继续阻断；无已批准额度/隐私同意在凭据/DNS前拒绝。
5. 最后单独批准账户/SecretRef、固定合成请求SHA、最多次数、原币及总额/单次风险、执行窗口和核账范围，再讨论人工小额联调。不得自动切换供应商、重试或后台付费。

停用/回滚：先撤销新准入和未发送意图，保持原账本/绑定/审计；sent/unknown不重发、不退预留；只读核验与人工对账继续。不能DROP表、降级0009或重建ledger来“回滚费用”。未获审批前正式Provider、真实网络/Secret路径继续关闭。

## 9. 测试运行与范围

工作目录apps/api，显式设置专用TEST_DATABASE_URL后运行`python -m pytest -q -ra tests/test_mining_paid_binding.py`。测试role与表只创建于新的随机schema；没有生产初始化命令、数据库迁移或启用开关。复用PR25的外部网络/原生凭据拦截，MockTransport之外的HTTP拒绝。业务ORM、paid_runtime和0009均为原实现，未删除或放宽既有测试。

本地初期SQL安装器曾因psycopg把固定SQL中的百分号当占位符失败，改为SQLAlchemy明确no_parameters（DDL不含数据参数）；localhost启动曾无输出，停止后改用带连接超时的明确127.0.0.1测试URL。未改用正常数据库或放宽安全检查。最终测试数量及完整CI结果以本PR检查记录为准。

删除竞态新增用例最初因观察器错误地用pg_locks.database过滤transactionid（该字段为NULL）没有观察到锁；改用pg_stat_activity归属测试数据库后维持原等待断言。删除先行用例最初直接删ORM会话遗漏原receipt擦除，已复用完整原delete_session函数，未放宽原FK或删除语义。两种竞态都用真实事务等待验证；无真实用户库操作。


## 10. PR26 并发复审：Session 与发送许可的线性化

旧原型确有竞态，不仅是假设：在本机一次性 PostgreSQL 16（127.0.0.1:15487、pathwise_test、每项随机schema）上，用两个独立真实连接复现。新增测试在修复前得到 **3 failed / 1 passed**：stop、end、revision 的“业务提交先行必须拒绝”断言均失败，delete已由原Run锁保护。失败原因是 Session 普通SELECT能读到未提交更新之前的active/revision；Run KEY SHARE不与Session的非键更新互斥。没有保存或调用真实供应商请求。

受控时序与证据：

- **业务先行**：连接A调用原`mining_api.stop`、`experience_api.close_session`、`facts.add_turn`或`experience_api.delete_session`，通过SAVEPOINT纳入受控外层事务；再锁user子限额作为旧代码检查后的阻挡点。连接B以受限LOGIN执行permit。A用`pg_blocking_pids(B)`确认B确实被A阻塞，然后A COMMIT，最后等待B结果。旧代码在子限额处等待，恢复后错误批准；修复后B在Session行处等待，恢复后重新读取最新元组，拒绝许可。不是靠sleep推测先后或Mock身份检查。
- **许可先行**：连接B执行permit获得true但不提交；连接A调用上述原业务操作。B用`pg_blocking_pids(A)`确认A等待B的Session锁，然后B COMMIT，A才继续提交。提交后的费用仍sent、held保留；再次permit拒绝，bind重放不新建call。之后unknown记录仍可落库，不退款、不重发。内存true或回滚事务不等于已提交许可，原rollback测试保留。
- 两种时序各覆盖stop/end/revision/delete，共新增8项，原47项未删除、跳过或放宽。均检查只有一个PaidCall、完整预留不变、actual仍NULL；删除时审计绑定必须tombstoned，其余仍bound。只观察两个参与者PID，不会把无关等待误认为证明。

本机修复后绑定专项为55 passed；最终显式READ COMMITTED断言补齐后，8项双连接测试再次全部通过（原47项未重写）。完整后端与CI结果记录于PR检查，不把尚未完成的检查写成已通过。前端回归首次因沙箱临时缓存重命名EPERM而未运行用例；正常权限重跑91项与构建通过，无前端源码变更。

修复仅改变测试DDL：Funding→Session FOR UPDATE→Run KEY SHARE→user→session子限额。Session锁必须先于Run，否则与原删除的Session→子Run锁序反转。现有业务修改/删除会锁Session及其子行、绑定墓碑，但**不获取Funding或子限额锁**；binding_erasure只更新审计绑定，且permit在Session之前只普通读binding，不持其行锁。故在已审查路径内不存在Session→Funding或Run→Session的反向边。received/unknown、bind只读重放仍可不依赖已删除的业务行，只按原Funding路径处理既有责任。子限额阻挡仅用于受控测试，不新增业务路径；测试业务先持Session再持子限额，也没有等待Funding。

线性化以**持Session行锁的事务提交**为边界：停止/结束/版本更新/删除先提交，后续不得得到sent许可；permit先提交，后续停止/删除不能追溯撤销sent账单责任。锁不跨HTTP，不保证供应商绝对只执行一次，也不保证停用按钮取消已经提交的许可。

证明范围仅为本PR同库、READ COMMITTED、现有业务事务和该测试函数。正式迁移/角色部署仍未批准；跨库协调、未来任何Session→Funding事务、新的直接Run更新器、真实Transport的可消耗许可仍是上线BLOCK，必须重新审查锁图并做故障测试。不能将本轮结果称为正式Provider已经可收费运行。

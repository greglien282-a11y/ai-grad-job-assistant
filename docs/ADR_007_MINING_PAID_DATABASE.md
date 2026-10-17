# ADR-007：V0.3 业务与中央账本同库，0011 仅落元数据

状态：**推荐架构 A；Schema 候选可审查；实际部署与收费启用均 BLOCK**。
基线：aa54c0b9cf4ad61f69117d91fbdf3f9ed3ecc3bd（PR26）；原 head=0010_response_diagnostics，候选=0011_mining_paid_metadata。

## 决策与依据

A：业务和唯一中央费用账本位于同一 PostgreSQL 数据库，通过受限角色、表/Schema 权限及短事务隔离。PR26 已在随机测试 Schema 证明 Funding→Session→Run→用户/会话子限额的事务锁序；业务先提交会阻止 permit，permit先提交保留sent责任，删除不退款。A 可让计划/绑定/中央预留共同提交或回滚，无需先建设跨库协调。

B：业务库与中央账本分离，使用 durable outbox、中央回执、稳定操作键和独立 Broker。网络分区、ACK丢失、删除/撤销与派发竞争均需持久协议和双库故障测试；普通SQLAlchemy事务不能跨数据库，即使同一PostgreSQL实例。PR26仅提出协议，尚未实现证明。

V0.3 推荐A，降低工程复杂度；**不自动回退到B**。如果唯一中央账本的部署身份/历史负债条件不满足，继续BLOCK。未来需要安全边界独立或扩容时另审B。

## 静态部署现状与历史责任

- `app/db.py`：正式Web/API只从明确DATABASE_URL惰性构建引擎，未因本PR改动。业务ORM、paid_*与controlled_probe属于同一个Base/Alembic链，在指定current_schema迁移；现有函数完全限定迁移时Schema。
- 本轮没有读取真实环境配置、凭据或访问业务/实验库，**不能声称现有业务部署角色已经受限**。数据库同名不等于同ledger；同一个数据库也不能用多个Schema各自生成总预算。
- 已有pathwise_probe包含一次受控实验及费用责任，已核销不意味着可复用。0009对任何controlled_probe记录排斥新paid_calls，非空downgrade保护仍保留。旧S03/b许可、风险接受和冻结账本不迁移、不重置、不解冻。
- 0011不创建paid_funding行、不变更ledger UUID/金额，不创建真实消费池。测试每项随机Schema的虚构资金只能用于测试，不能成为正式中央池部署方案。
- 正式部署之前必须批准：唯一canonical数据库/Schema与ledger UUID、部署角色、原账本负债与防重放墓碑的审计处置。不得另建消费池或复制额度规避已有冻结/责任。现有Schema可先有惰性元数据，**有实验历史时仍拒绝新绑定**。

## 0011 的实际范围

四个独立前缀表（不与PR26测试表重名）：

- `mining_paid_identities`：session FK CASCADE、服务端actor/session假名scope、身份发行版本及数据库时间。不保存真实user_id、Bearer、Key或原文。禁止更新；仅业务会话删除可级联清除。
- `mining_paid_limits`：唯一(ledger, kind, scope)，仅CNY附加上限、次数/并发及证据摘要。金额/次数/并发默认0，不种任何行；没有第二个held/spent总池。ledger FK指向原paid_funding唯一UUID。
- `mining_paid_plans`：run FK CASCADE，session归属、root、ledger/grant、操作/receipt/request/policy/context/prompt/schema/account摘要、模型/配置/提示词/Schema版本及数据库时间。禁止改写或单独删除，业务删除才级联。root/operation唯一；验证root确为同会话retry链根、grant/账户/模型对应。
- `mining_paid_bindings`：run主键；root、operation、call各自唯一。没有指向业务Run/Session的FK；只对中央ledger/call/grant做RESTRICT。插入必须与计划、身份及PaidCall全部字段对应；不能用前端指定的ledger/call冒充服务端绑定。绑定不等于发送许可。

仅新增三个函数：

1. `mining_paid_guard()`：SECURITY INVOKER触发器；只拒绝不合法元数据，不调用paid_runtime。新plan/binding锁序Funding→Session→Run；计划验证的root和上下文摘要**不是动态请求外发审批**。有历史controlled_probe时拒绝。绑定前若还有其他未归属paid_call则拒绝，不自动认领、补写或清账。
2. `mining_paid_erasure()`：唯一SECURITY DEFINER，固定search_path=pg_catalog、表名完全限定；仅在原Run AFTER DELETE时将对应绑定标记tombstoned。guard同时要求Run确实不存在、其他字段全部不变。不锁资金、不写paid_*；不撤销sent/unknown，不退款。
3. `mining_paid_audit_ok(ledger)`：只读SECURITY INVOKER布尔检查，验证中央UUID、没有实验历史、没有未归属call。它**不是费用准入、预算证明或全账单正确性认证**；false要停止人工审查，不自动修复。迁移不调用它来抹平旧历史。

迁移不安装binding_runtime/reserve/permit/dispatch，不创建Provider、Grant、Secret、操作键或审批。ORM新增仅注册表元数据，便于Alembic check；不加入API或运行工厂。

当前候选继续使用现有迁移Schema和表级ACL；不移动0008/0009旧表或改写函数指向。未来若要拆分business/billing Schema，需要单独审查FK、函数目标、canonical账本和角色，不能在多个Schema重复初始化资金池。

## 权限边界与仍未配置的生产角色

本迁移不创建LOGIN、成员关系、角色授权或新的运行EXECUTE。对新表/函数清除PUBLIC和迁移者ALTER DEFAULT PRIVILEGES继承的**所有非Owner ACL**，不扩大原对象权限。触发器函数PUBLIC EXECUTE也撤销，不能成为直达入口。

正式最小权限目标：

- Web业务角色：仅原业务表/API职责，无新资金、限额、审批、绑定写权限；不属于迁移/审批/Broker owner角色，禁止SET ROLE升级。
- 中央费用运行角色：只读所需行和独立审查的受限函数EXECUTE，无直接paid_funding/paid_calls/limits写权；本PR**不授予这些新函数**。
- 独立审批/核账角色：明确人工审批/账单证据范围，不交给Web；不能借核销重新派发。
- 迁移管理员：只在维护窗口安装候选，绝不作为Web DATABASE_URL身份。数据库Owner/超级用户始终属于信任边界，不能用触发器声称防御管理员DDL。
- 将来Secret Broker：独立最小权限身份，验证中央ledger、字节SHA及可消耗许可后才解析Secret；本轮未实现、无网络入口。

唯一新SECURITY DEFINER暂由迁移角色拥有，零额外ACL，函数正文只能写墓碑。**生产必须独立批准非LOGIN受限函数Owner、禁止运行角色成员/SET ROLE升级及最小列级授权**。guard中的FOR UPDATE需要受信任元数据写入口，不能为使它可用给Web直接UPDATE资金权限；未来需独立受限函数设计。现有0008/0009函数Owner/权限未改变；正式角色体系、默认权限巡检和独立Broker均仍BLOCK。

## 删除、留存、锁序与回滚

身份和计划随业务删除级联；绑定保留最少随机ID、假名scope、摘要、金额关联和可信时间。无用户经历、回答或模型自由文本。费用审计假名仍可能可关联，不承诺完全匿名；期限、HMAC密钥轮换、审计最小化仍需独立隐私/财务批准。计划/绑定不能通过删除再插入刷新root/call唯一名额。

绑定写入持有Session→Run锁（前有中央Funding锁），删除持Session→子Run，墓碑不反向获取Funding。保护继承PR26已证明的同库锁序；本轮不新增生产写入口，也不声称实现了正式许可事务。

候选升级先对现有FK/触发器目标表用ACCESS EXCLUSIVE NOWAIT取得维护锁；冲突直接失败，必须回滚并停止，不自动重试。downgrade同样NOWAIT；四个新表任意非空（含0限额、身份、计划或墓碑）均拒绝。空表才明确删本轮触发器/函数/表，绝不CASCADE，不改历史版本。DDL应在PostgreSQL完整事务执行；隔离测试注入创建末尾触发器后的故障，证明表、函数、触发器和版本一起回滚，资金不变。实际部署须停写维护，不把该候选当在线无锁迁移。

停用：保持生产Provider关闭、撤销未来准入；保留账本与审计，未知费用不退款。存在审计时只能前向修复，不能DROP/降级清账重获许可。未经单独批准不向pathwise_dev/pathwise_probe应用0011。

## 隔离验收与已知限制

只在本机15487一次性PostgreSQL/pathwise_test或CI专用pathwise_test/pathwise_e2e的随机Schema运行。复用PR26外部HTTP、DNS/原生凭据拦截；虚构审批只用于构造FK/约束测试。新角色由隔离测试集群创建，权限拒绝用独立受限LOGIN实际连接验证；不使用真实管理员凭据模拟业务角色。

覆盖0010→0011、空库/往返、原业务资料与HTTP幂等重放、Schema无消费授权、Run/Call/root/操作唯一性、错误ledger/grant/账户/摘要/归属拒绝、未归属call诊断、删除墓碑、非空downgrade拒绝、不可变记录、权限与默认ACL、原0009实验排他性和核销不可重启、注入故障完整回滚。完整后端/React/Chromium E2E及离线合同结果以本PR最新CI为准，不提前声明通过。

初期失败记录：首次pytest命令从仓库根目录执行导致app导入失败，改从apps/api按既有约定运行；首轮27通过/11失败，暴露共享触发器提前绑定其他表专属字段、受限测试连接未指定随机Schema、历史实验夹具违反reserved>0。修复新代码/测试夹具，保持原安全断言，未修改0008/0009。

## 启用前必须另行批准，建议下一步

1. 先审查并合并惰性Schema候选，不部署到持久库；确认唯一canonical账本部署与历史责任审计方案。无法满足则BLOCK，不能偷偷选B或新池。
2. 独立实现可信身份及映射发行/密钥轮换、动态完整请求bytes/prompt/schema/配置审批绑定；决定真实资料外发同意与区域/留存政策。
3. 单独审查原子预留/子限额/最大调用并发、撤销/unknown冻结及恢复函数，独立非LOGIN函数Owner和受限LOGIN角色。币种/价格/Token证据或风险授权不能借用一次S03/b实验。
4. 实现独立Broker与一次性可消耗许可、发送前最终校验和崩溃恢复；不将0008布尔true直接交公网Transport，不自动重试或换模型。
5. 最后才单独授权固定合成请求的小额联调、真实质量留出评测及人工核账。模型、Key、动态用户付费、自动扣费/核账、环境开关启用全部仍禁止。

复现命令（工作目录apps/api；只允许显式专用测试URL）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -ra tests/test_mining_paid_schema.py
.\.venv\Scripts\python.exe -m pytest -q -ra tests/test_mining_paid_binding.py
.\.venv\Scripts\python.exe -m pytest -q -ra
```

本机新增专项53 passed；与原PR26专项联合阶段99 passed（当时新增44+原55），之后补齐receipt/维护窗口/可信时间等9项。原55项没有改写。React91、构建、E2E类型、隔离迁移/清理、12/48离线合同及Mock CLI通过。完整后端及Chromium CI结果在PR记录，不以估计冒充已完成。

补充兼容性：独立临时受限Web LOGIN只有原业务表的SELECT/UPDATE/DELETE，无paid_*或新元数据DML/函数权限，仍可调用原delete_session删除资料并留下费用墓碑；最终新增专项54 passed。未使用管理员身份冒充业务角色。

首轮CI的E2E启动前失败源于既有probe.py把迁移版本固定为0010；现明确更新为0011，仍做精确版本断言，未删除或放宽任何浏览器业务验收，也不动态接受任意head。该文件仅为测试环境预检，不改页面/API。

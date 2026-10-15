# M1-2C-2 C-1A：持久授权与收费预算控制（不开放 HTTP）

基线 main `951116d6349a19199308fd4cd40913d4ec864cee`；已核对合并 CI [38684948630](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/38684948630) 成功。开发分支 `codex/m1-2c-2c1a-paid-ledger`。依据 C-0、阶段 B、适配设计及 D-006；没有重定义产品或模型选择。

**真实批准预算仍为 0 元，真实请求 0 次。充值计划不是支出许可。** 迁移只创建零额度总池，不创建授权、价格、汇率、Token 证书或运行角色。测试的正金额、发票和审批人全部是随机隔离 Schema 内的合成夹具，不是负责人真实批准。

## 数据结构与信任边界

新增 `0008_paid_authority`，独立于 0006 Mock / 0007 offline_fixture。两版原约束不变。

- `paid_funding`：单例 id=1、随机 ledger_id、CNY ceiling/held/spent、冻结与总额批准证据摘要。初始额度、占用和支出均为 0。
- `paid_scopes`：provider/model 两类累计 CNY 上限及独立批准摘要；没有 namespace，也没有按批次复制的总池。
- `paid_grants`：批准人、创建/生效/到期时间、唯一批准证据摘要、撤销位、授权累计/单次/次数上限、不可变政策与 SHA。政策包含账户引用、SecretRef 摘要（不是 Key）、供应商、模型/预期版本、完整端点、区域、模式、输出硬 cap、具体合成请求 SHA 与 Token 证明。
- 政策中的不可变 USD 价格快照绑定模型/账户、来源摘要、起止、峰谷输入/缓存/输出价格、日历及缓存规则摘要。FX 快照含有效期、批准来源、CNY/USD 和税费余量因子。所有金额运算使用 Decimal/PostgreSQL numeric，无默认汇率或默认税费批准。保留完整政策快照，而不是事后引用可变配置。
- `paid_calls`：全账本唯一 operation_hash、授权/请求/政策摘要、批次、供应商/模型、五种状态、CNY 预留/实付、原币 USD（12 位小数）、全局唯一 invoice_hash、lease 与白名单用量。业务删除不能级联费用资料。
- `paid_audit`：追加式审批、scope 调整、授权/撤销、对账、确认未发送、人工解冻事件及证据摘要。数据库触发器禁止更新/删除审计和授权；授权仅允许一次 false→true 撤销，不可恢复或修改正文。

这里的 SHA 是审计索引，不是电子签名或自动验证审批真实性的系统。批准原件及来源材料须由负责人在独立受控记录中保管，并绑定全部政策字段/ledger_id；只有可信管理角色能把审查过的记录写入数据库。不能把“拿到一个摘要”当作业务进程有权审批。没有公开授权 API、环境开关、启动自动批准或正额度种子。

## 权限隔离

迁移/管理所有者与普通应用角色必须分离。`PaidAdmin` 仅供隔离的可信管理进程；它的数据库凭证不能提供给 Web/评测业务进程，也没有加入现有业务 API。owner/DBA 能修改底层数据库是明确的信任边界，本实现不声称防御恶意 DBA。

迁移撤销 PUBLIC 对收费表及函数的权限。`PaidAdmin.provision_runtime_role(schema, role)` 是显式 DBA 操作，不创建角色、密码或环境配置；验证现有角色没有 superuser/CREATEDB/CREATEROLE/BYPASSRLS、没有管理所有者成员资格、没有数据库 CREATE 或持久 Schema CREATE 权限，然后仅授予：该 schema USAGE、收费表 SELECT、`paid_runtime(text,text,jsonb)` EXECUTE。没有表 DML、对账、增额、授权或解冻权限。

`paid_runtime` 为 SECURITY DEFINER，固定 search_path=pg_catalog，表/函数完全限定 schema，无动态 SQL。输入值全部绑定，schema/角色标识符受严格白名单限制。`PaidControl` 固定 engine/schema/ledger UUID，不接受 namespace；错误位置或 UUID 直接拒绝。所有部署/批次/将来渠道必须接同一受控 PostgreSQL 账本。不能通过环境变量或请求选择另一库；配置发布仍需管理审查。不能把每个随机测试 Schema 当成生产预算池。C-1B 接线前须证明实际运行身份符合本隔离规则，而不是继续使用迁移所有者。

CI 专用服务中建立随机 NOLOGIN 受限角色，并真正以该角色连接/调用，验证允许预留、拒绝 INSERT 授权、改总额/Scope、解冻、删除账本/审计、创建另一 Schema；之后清理自己建立的角色。没有改动 Windows 服务或日常数据库角色。本机专用测试角色无 CREATEROLE：本地验证 PUBLIC 无执行权限及自身无管理能力，完整受限角色操作由 CI 执行，不能把本地分支说成已验证所有角色权限。

## 事务、状态与恢复

每次变更首先锁同一 `paid_funding(1)`；等待锁后重新读取数据库墙钟。预留在同一事务内验证授权期限/撤销/政策 SHA、价格/FX/Token 有效期、unknown/冻结、并发槽（全局2）、次数，以及全局/供应商/模型/授权/单次上限，然后插入唯一操作记录、增加 held。批次仅用于追踪，不是额度边界。不同授权可各有名义上限，但实际消耗始终扣同一总池。

预留公式：`ceil_micro_CNY((input_bound × max(all input rates) + output_cap × max(output rates)) / 1e6 × approved FX × approved tax_margin)`。不预测缓存命中、谷价或假日；即使缓存更贵也取最大值。所有参数均来自 owner 写入的不可变快照。数据库独立计算金额，普通调用者不能传一个更便宜的预留值。

状态转换：

| 原状态 | 操作与新状态 | 费用与恢复 |
| --- | --- | --- |
| 无记录 | reserve → reserved | 提交记录及全额 held；同键同请求重放同 ID |
| reserved | permit → sent | 重新核对期限/撤销/配置/未知状态；事务提交一次意图，无第二次许可 |
| sent | received → response_received | 仅保存 input/output 数值；全额 held 保留；用量超界冻结总池 |
| sent | unknown → unknown | 取消/超时/断线/远端错误等均不认定免费，不退款 |
| expired sent | GET 投影 unknown | 原记录仍 sent，GET 完全只读，不重试或补发 |
| expired sent | 显式 recover → unknown | 持久化未知，全额 held，整个总池暂停新 reserve/permit |
| expired reserved | owner close_unsent → reconciled | 只有持久证据“从未给出发送许可”才可经人工证据核对为0 |
| sent/response_received/unknown | owner reconcile → reconciled | 唯一账单+复核证据，按批准 FX 记录完整实际 USD/CNY，转 held 为 spent |

同键不同授权/请求/政策/批次返回专用 `paid_idempotency_conflict`；同键重放不重复占用/计次。permit 是账本一次意图，不是可传到 HTTP 的能力令牌，本阶段没有网络消费者。发送意图已提交但实际未出网时，也可能只能保守记 unknown，不能猜测免费。已完成对账不被迟到错误覆盖。expired reserved 不自动退款或释放并发槽，需明确 owner close_unsent；这是小批探针的保守停止选择。

`reconcile` 不调用账单接口，仅接 owner 人工确认的原币最终账单和摘要；税费余量是预留缓冲，最终 USD 发票已含适用税费时不再重复乘余量。需要补税/附加账单时不得复用原发票覆盖历史，须先停用并另审调整合同。账单重放必须金额及摘要一致；同一摘要不能在另一调用复用。实际超预留或总额时完整记超额、全局冻结，不截断账单。只有所有未核对项已解决、实付在批准总额及 provider/model scope 内，owner 才可凭追加审计显式解冻。没有到期自动释放、账单清理或自动恢复。

`totals()` 只读按 provider/model 汇总 Token、未结预留、实付 CNY 和原币 USD；缺少用量仍为 null。未知费用不是0。底层账本保留摘要/数值，不保存请求正文、系统提示、完整模型响应、简历、Bearer、操作明文或 Key。

## Token 与真实计费仍然阻断

`TokenCertificate` 绑定确切请求 SHA、完整 system/Wire/context/角色/framing 的输入上界、tokenizer/version、证据摘要、覆盖声明及有效期；缺少证据或 unverified/Mock 证据拒绝授权。没有字符数、字节数比例或默认 tokenizer 回退。正向数据库测试显式使用“TEST ONLY” owner-attestation 夹具，只证明控制算法，不证明 DeepSeek 计费 Token 真上界。

**目前没有一个已验证的真实证书，也没有实际授权/价格/FX。** `owner_attested_full_request_bound` 仅是管理方审核证明的表达格式，不能靠更改标记把 Mock 数字升级为可信证明。C-1B 必须明确可靠 tokenizer/framing 证据的验证流程；如果离线仍无法证明，请保留阻断并向负责人报告，不能因为有余额或预算而发送。

实际供应商价格/账户币种、峰谷/缓存计费、真实 Token/framing、Key 有效性、地区/别名权重、超时后的账单及数据条款仍未测量。本轮沿用已核验官方合同，不对未知条件作新承诺。`DeepSeekOfficialTransport.invoke()` 无条件拒绝，未修改任何 Transport/Key resolver/Provider 门禁。PaidControl 不能注入 C-0 exercise_offline 冒充 ProbeControl，也不能用于 MockRunner；没有真实 HTTP、账户或充值查询。

## 运行与验收

使用已有 Python3.12 虚拟环境，显式 TEST_DATABASE_URL 仅指向专用测试库；不加载真实供应商 Key。示例（在 apps/api，先在受控终端配置测试 URL，不把密码贴到报告）：

```powershell
.venv/Scripts/python.exe -m pytest -q -ra tests/test_paid_control.py
.venv/Scripts/python.exe -m pytest -q -ra
```

测试包含：无授权零出网、最坏价 Decimal、各层额度/次数、跨授权批次/进程竞争、同键一次许可、真正 os._exit(41) 后持久 sent/unknown、取消/断线不释放、期限/配置/价格/证书失效、发票全局去重、超额冻结/人工核对、不可变记录、合成清单限制、随机 Schema 0007→0008→0007→0008/空库与 alembic check/旧资料兼容。CI 保留原282后端、62 React、30 E2E 和离线合同/Mock评测。30个 E2E .spec.ts 未改，仅更新数据库启动探针 head 到0008。最终测试数及 CI 链接写入 Draft PR。

所有迁移/回滚/数据写入都在随机隔离测试 Schema。日常 pathwise_dev 未迁移；页面、PRD、prototype、Pages 未改。

## C-1B 仍需完成的工程与授权

1. 审查本账本和生产 DBA 部署流程：固定中央数据库/Schema/ledger UUID、受限运行身份、独立 owner 入口、审批原件保管、备份/保留/权限审计；所有批次及将来供应商共用总池。
2. 验证可信的完整请求 Token 上界，补充实际价格/账户币种/FX/税费批准和有效期；任一不足继续拒绝。没有默认认可的汇率或预算。
3. 单独设计一次 sent 意图与真实 HTTP 的 Bridge、有限 deadline/retries=0、受控 SecretRef 注入、取消/崩溃窗口及只读账单恢复；不可把当前布尔 permit 当作可重复使用的发送令牌。
4. 独立批准真实请求的账户、URL/模型/版本政策/地区/模式、固定合成 SHA、次数、输入/输出、总额及单次预算、时间窗、执行/核账人、Key 注入方式、外发资料及未知账单处理。10元充值计划及既往30元草案均不满足这些条件。

交付后停止，等待代码审查及后续明确授权；不自动合并。

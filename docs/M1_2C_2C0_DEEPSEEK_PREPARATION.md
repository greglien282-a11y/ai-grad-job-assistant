# M1-2C-2 C-0：DeepSeek 官方零费用接入准备

日期：2026-10-15（Asia/Shanghai）。基线 main `91039f2d355afed7b7329323636f7bf264d25b01`；先确认合并 CI 38675387829 成功，再创建 `codex/m1-2c-2c0-deepseek-preparation`。依据已批准的适配/上下文合同和 D-006，未改变产品决策。

**真实批准费用=0 元，真实模型请求=0。30 元仍只是草案。** 本 PR 实现独立官方 HTTP 协议处理和离线控制证明，另提出真正收费账本的独立审查合同；没有真实调用入口、真实 Key 解析器、付费授权发行器或正式用户页面集成。

## 官方合同与 Mock 差异

2026-10-15 只读核验[官方 Chat 文档](https://api-docs.deepseek.com/api/create-chat-completion/)。本阶段固定 `https://api.deepseek.com/chat/completions`、`deepseek-flash`、`thinking.type=disabled`、`response_format.type=json_object`、`stream=false` 和有限 `max_tokens`。不接受 `/v1`、Beta、Responses、Anthropic、自定义域名/路径/查询、工具或其他模型。JSON object 不提供 JSON Schema 约束；本地 Wire Schema 仅作提示，最终仍由 Pydantic 和既有来源/原子性/状态校验决定。

旧 Mock packet 常省略 id/object/created/fingerprint/choice index/assistant role，缓存及总用量也有默认值。新 decoder 对照文档检查这些字段、命中+未命中=输入、输入+输出=总量，拒绝缺失/矛盾用量、布尔假冒整数、模型漂移、截断、拒答、意外思考/工具调用；不把缺少缓存字段解释为免费命中。正文中的 tokens/status/确认字段仍不可信。只保存经过白名单的版本标签及 ID/fingerprint 摘要，别名与 fingerprint 都不是不可变权重证明。

[官方价目](https://api-docs.deepseek.com/quick_start/pricing/) 当前将 deepseek-flash 对应 DeepSeek-V4.1-Flash；USD/百万 token：未命中输入峰/谷 0.30/0.15，命中 0.006/0.003，输出 1.20/0.60。高峰工作日 UTC 01–04、06–10，排除中国法定假日。只按最坏价格预留，不预测命中或依赖谷价。价格与账户实际结算规则仍需批准时重新核验。

[缓存文档](https://api-docs.deepseek.com/guides/kv_cache/) 说明前缀持久缓存为 best effort，不保证命中；缓存保留与安全日志/训练留存是不同问题，不能据此宣布零留存。[限流文档](https://api-docs.deepseek.com/quick_start/rate_limit/) 网页工具超时后只读获取官方静态 HTML：非流式可能持续返回空行，十分钟尚未开始推理可断开；应用不得由这些字节无限续命。没有调用模型、余额、模型列表或账户接口。

[错误码文档](https://api-docs.deepseek.com/quick_start/error_codes/) 的重试/替代供应商建议不适用于本项目的费用授权合同。429/5xx 不自动重发，也不认定免费；401 的供应商 Key 有效性只能在获准后观测。离线只能验证本地 Key/SecretRef 绑定，不能证明真实 Key 未被撤销。

仍待授权探针：实际账户可用版本/地区、返回 model/fingerprint 的证据强度、字段可选性、JSON 输出在 cap 下的表现、计费 Token/缓存/峰谷、取消/超时后的实际账单与账户适用数据条款。Chat 不接受 json_schema 参数，不能从 tool/Responses 文档推断其 Schema 关键字支持。

## 已实现接口与阻断

`app/deepseek_contract.py`：固定 12 组合成集中的 24 个单轮输入，规范化换行后固定 dataset/Wire SHA；确定性构造 MiningContext 和官方请求。只接受 128/256/512/1200 的有限输出 cap。授权请求摘要之外，还必须命中代码内合成清单；改 synthetic 标记、构造用户资料对象或修改文件都不能变成获准输入。不访问日常会话/简历/材料数据库。

`app/deepseek_transport.py`：独立 `DeepSeekOfficialTransport`，`invoke()` 无条件报 live_dispatch_disabled_c0，发生于解析 Key、创建 Client、数据库、DNS 之前。没有可由环境变量开启的实费开关。`DeniedNetworkTransport` 再次拒绝 socket；内部 `_post_once` 也只接受**精确类型** httpx.MockTransport 和固定假密钥。`exercise_offline()` 额外要求 ProbeControl/FakeSecretResolver，不能与旧 MockTransport/Ledger 冒充。没有注册到 safe_provider 或既有用户 API。

可执行的 HTTP 协议路径是同一个非流式 POST、响应收集/解析流程，但本轮所有 transport 都是内存 fixture。连接5秒、read15秒、总45秒独立，限制≤对应默认值；asyncio 总 deadline 覆盖连接/keep-alive/body/close，解析后再次核对墙钟。body 上限256KiB。HTTPX不跟随重定向，trust_env=false，无显式 proxy/mount/hooks，无 SDK/重试循环/自动路由。真实网络调度仍不可用；未来真实 AsyncHTTPTransport 必须显式 retries=0，代理/网关的重试关闭及 egress 证明也须单独审查，不能把本地测试当作真实代理已验证。

`DisabledSecretResolver` 永远拒绝。`FakeSecretResolver` 只识别公开固定的非供应商假字符串，repr 隐藏值，不读环境/文件/真实 Key。生产 SecretRef/账户绑定、过期、撤销、最小权限和受控进程内注入的实现仍待批准；禁止在聊天、URL、命令行、Git、前端或报告中提供 Key。

HTTP错误、无效JSON、截断、拒答、漂移、超时/取消进入 unknown 并保留预留；突然进程死亡保留 sent，由只读投影/显式维护恢复。既有 MiningOutputV2 结构规则复用；**新 Transport 不向经历库发布任何事实**。未来 Bridge 仍必须调用原 mining.complete，进行同会话/项目/合法 user 引用/code-point/原子性及 revision/lease/active 最终验证；不能直接确认或核实事实。

## 0007：独立的离线预检控制，不是假冒收费账本

保留 0006 的 Mock/CNY_SIMULATED 原约束，新增 `0007_probe_preflight`：

- probe_funding：数据库固定单例 id=1；approved_real_cny 必须为0。fixture_ceiling/held/spent/frozen 只用于离线金额模拟；记录人工复核摘要。
- probe_grants：固定 pool_id=1，approved_real_cny=0；只允许 draft/offline_fixture/revoked，不存在 approved/live 模式。有效期、次数/模拟额度、完整安全政策（USD价目、FX、Token证据摘要、目标和输入摘要）。
- probe_attempts：全库唯一操作摘要，不带 namespace；绑定授权及政策快照、批次标签、五种状态、预留/对账模拟金额、lease、规范用量和安全错误。execution 只能 offline_http_fixture。

迁移不插入任何批准或额度。**数据库也拒绝30元真实批准、第二总池或 live 执行模式。** 这刻意避免 C-0 几个开关就变成实费系统。新增迁移只在随机测试 Schema 执行 upgrade/check、0006→0007→0006→0007 及旧 Mock 资料兼容。E2E启动探针仅更新到0007，30个 .spec.ts 不变；日常 pathwise_dev 未触碰。

`ProbeControl` 的所有变更先锁 funding(1)。在同一随机测试Schema中，不同授权/批次共用 held+spent，总池不能由批次/授权参数增大。不同测试Schema是彼此独立的fixture实验，不声称其模拟额度跨Schema共享；每个Schema真实批准额都为0。未来实费池必须固定数据库及全限定schema，禁止调用者切换search_path或另建库来复制同一批准额。额外检查授权期限/次数/额度、全局活跃2个、unknown/过期sent暂停，以及政策哈希/操作键冲突。发送许可在短事务中提交一次，事务外才执行 fixture；派发前再次校验政策和期限。等待数据库锁后重新取当前时间。已经预留的第二个请求也不能越过其他过期 sent。

USD预留 = 输入上界×峰谷/命中未命中的最大输入价 + 输出硬cap×最大输出价，再乘FX和税费余量，向上取整CNY微元。price/FX/token证据缺失、过期、非法或不可用均拒绝。这里的 token 证据类型**只能是 offline_fixture_not_supplier_verified**，不能冒充真实 tokenizer/framing 证明。

reserved→sent→response_received/unknown→reconciled；GET只读，对 expired sent 投影unknown，不推理；显式 recover_expired 将 sent 标unknown而不退预留。过期 reserved 有“从未发放发送许可”的持久证据，显式维护可记0。unknown跨授权暂停；相同键不重发；迟到错误不能抹掉reconciled。模拟对账独立幂等 invoice 摘要，记录全部超额并冻结。人工恢复需要所有未知已核对且 spent≤额度，记录复核摘要；不退款或自动解冻。

独立 OS 进程和真实 PostgreSQL 证明跨授权/批次预算竞争、同键一次发送和 os._exit 崩溃恢复。金额和账单全是fixture，不是实费测量。没有真实账单查询或授权发行API，没有长期实费账本清理工具。

## 真正收费账本合同：独立提案，尚未启用/实现

后续单独审查，不修改0006限制、不将0007离线金额改名：

1. 只有负责人明示授权才能由受控管理入口建立不可变 ApprovalGrant。保存批准证据摘要、审批人、UTC起止、账户/SecretRef绑定、目标/模式/版本政策、合成请求SHA、次数、单次/会话/模型/供应商限额；撤销可阻止未发送请求。配置、余额、fixture测试记录都不能充当批准。
2. 全部署单一 FundingEnvelope 管理**同一批准预算**，各批次/渠道都FK到它；新授权可分配而不能自行增额。schema/namespace是存储位置，不是预算边界。另建总预算管理角色，应用角色不能创建第二池或改批准额。多实例必须共用此库；多环境若可调用同账户也必须共同扣预算。
3. 不可变 PriceSnapshot/FXSnapshot，绑定账户币种、供应商/模型、文档/批准证据、有效期、峰谷日历/缓存/推理计费、税费/保守FX、账单币种。不自动刷新价格或推定未批准汇率。跨时段用最大价，最坏情况全未命中。
4. TokenCertificate 必须覆盖**确切完整请求**（system指令/Wire/context/角色及供应商framing）的上界，绑定可信 tokenizer/模型/版本与审查证据。字符数、平均比例和本Mock字节公式都不是已验证供应商证明。证明不成立就不派发；即使人批准预算，也不能跳过此门禁。
5. PostgreSQL funding根锁、各scope锁、次数和并发槽与 call attempt 同事务预留；提交sent意图后仅一次HTTP。未知保留全额，整个批准池暂停；GET只读，无重发/修复模型/跨渠道。供应商成功但输出被拒、stale或客户端取消也可能收费，不能自动释放。
6. 对账记录原币发票金额/证据摘要、批准FX后的CNY、用量估算和差额；同账单不可两次扣减。超过预留照实记录并冻结全部scope，不能截断为批准额。人工复核必须追加不可变事件，不以自动过期、删会话、重启或新批次清空未知。长期账本保留/权限/备份和人工对账入口需另审，不用一次性Mock CLI清理。
7. 授权、数据、价格、FX、Token、Key绑定、目标/模式、代理无重试或实际版本任一不可证明即拒绝。无已确认授权余额时先拒绝，**不解析Key也不DNS**。实际供应商撤销Key只能由获准401探针观测，不能离线承诺Key有效。具体费用授权与技术上线批准是两个条件。

上述实费表、可信审批链、生产Key解析、真实tokenizer证书、实费派发与真实对账尚未实现；C-0交付的是独立可审合同及离线数据库控制证明，不声称真实费用安全已经认证。

## 本地/CI验证

Python3.12，使用现有虚拟环境与显式 TEST_DATABASE_URL（仅已有专用测试库，不在命令/报告展示密码）。不加载真实Key、不安装供应商SDK。示例从仓库根目录：

```powershell
Push-Location apps/api
try {
  .venv/Scripts/python.exe -m pytest -q -ra tests/test_deepseek_c0.py
  .venv/Scripts/python.exe -m pytest -q -ra
} finally { Pop-Location }
```

所有数据库测试各自随机Schema。本机后端282项（原229+新增53）、最终C0专项53项、React62、构建/类型检查、迁移/清理、旧12项离线合同和Mock CLI已通过。初次Edge与后端并行时出现一项30秒限时超时，未修改断言或限时，另行串行复测；最终结果写入PR。CI保留全后端、React62、E2E30、构建、隔离迁移/清理、旧12项离线合同和12组Mock评测；最新CI及提交写入Draft PR。覆盖无授权/假密钥错误/地域/模型/到期、全URL、缓存/总量、非法JSON、截断/拒答、429/5xx/重定向、超时/keep-alive/取消、同键/政策漂移、跨进程总池/崩溃/unknown不退款、超额冻结及人工复核。

未生成真实模型质量、耗时或账单报告；这些字段无数据应为null。实际供应商请求0，费用0；数据库fixture金额不是实际消费。

## 首次真实合成探针的最小授权清单（提议，不是许可）

- 先批准真正收费合同及实现审查；具体执行窗口、执行人/账单核对人和停止条件。现有C-0 live入口仍不可用，不因为批准费用就绕过技术门禁。
- 仅官方指定账户/SecretRef、完整chat URL、deepseek-flash，接受alias非固定权重；地域/数据条款须确认。不授权百炼/其他模型/端点、工具、流式、自动重试或自动路由。
- **1次**合成请求，限定一个审核过的C0请求SHA（建议S03b），non-thinking/json_object，输出≤256；输入上界草案≤5000，必须先有真实framing/tokenizer证据。结果坏/超时后先只读恢复和对账，不补第二次。
- 单次及总预算草案**人民币0.05元**（不是批准；30元也仍未批准）。仅在USD最坏价、批准FX/税费/未知缓冲可证明覆盖时才可行；示例FX7.5×税费因子1.1的模拟上界0.014910元不可当作批准汇率或真实报价。证据不足不发。
- 单独允许指定测试SecretRef在服务器内注入，以及只外发固定合成请求，不包含用户库、真实/匿名化简历、材料或任意输入。不要现在粘贴或提供Key。
- 授权只读账单核对方式或指定人工证据流程、未知预留保留与超额冻结。额度、Key、资料和核对授权均需明确，不能从账户已有余额推定。

完成后保持Draft，等待ChatGPT审查与负责人明确授权；不自动合并、不改UI/PRD/prototype/Pages、不迁移日常库。

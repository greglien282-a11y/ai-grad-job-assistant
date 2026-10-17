# DeepSeek Mining Provider 接入决策与离线接线证明

状态：**仅供审查，正式接入 BLOCK**。基线 `37b36fb41a7cbc342c78c9726642fe1aff459a75`。
本轮没有生产 Provider、API/DTO、迁移、页面、费用或权限变更。HTTP 仅 Mock；数据库仅隔离测试库的随机 schema。离线接线成功不证明真实模型质量、计费安全或已经获得真实调用许可。

## 1. 现状与缺口

- `mining_provider.py` v1 `ScriptedProvider` 只能引用本轮完整原话，问题为字符串；v2 是最多五条原子引用、最多两条带 purpose/source_turn_ids 的问题与 stop/stop_reason。两者均不是完整自然语言回复协议。
- `mining.claim(contract_version=2)` 构建受预算约束的 `MiningContext`，传给 Provider 的 legacy content 也是遮蔽文本；正式适配器仍必须只使用 `context.payload()`，不能使用独立 raw content。
- `mining_context.build_context` 包含当前/有限历史用户原话、问题状态/版本/回答关联、当前事实/记忆状态/拒绝、停止条件；最多8回合、32事实、24问题、16000文本字符、64000序列化字节。隐私正则遮蔽不是匿名化保证；姓名、学校、独特项目等仍可能识别个人。
- `mining_validation.validate_context_v2` 检查快照中的原句引用、Python Unicode code point 位置、单句、否定/不确定性/团队边界及追问去重、来源、数字。`validate_v2` 再检查数据库真实 user turn、同一会话/项目/快照 revision。当前语义规则是保守词法启发式，不能宣称普遍防幻觉或追问有效性已得到证明。
- `mining.complete` 在短事务里重查 running、lease、会话 active/mining active、reserved_revision，写 pending，去重/防止编辑拒绝原文复活，保留历史。用户确认才进入 experience-summary。它不会接受 supplier 的确认状态。
- `model_adapter.Adapter` 可复用 Provider/Model/Profile 请求形状、JSON-object/Schema 解析；`deepseek_contract.decode_official` 更严格校验官方形状的 envelope/usage/模式，再复用 `parse_output`。JSON object 不是业务 Schema 或真实性保证。两个解码器能力不完全等价，正式接入应指定唯一经审查版本，不能失败后换较宽松解析器。
- `DeepSeekOfficialTransport._post_once` 本身只接受精确 `httpx.MockTransport` 和公开假凭据；`invoke()` 永久拒绝。`DeepSeekBridge` 还绑定固定 synthetic 请求白名单、PaidPolicy、受限运行角色、预算/permit，**不能直接接任意业务 MiningContext**。
- `controlled_probe_io` 是独立人工单次实验：固定历史 SHA、Windows 本机凭据、交互风险接受、中央实验许可与安全预览。其正式发送能力不能成为 Web 业务后门；本轮不执行其派发入口，不复用已核销 S03/b 许可。历史字节校验帮助函数的传递导入可能加载该模块，但没有调用凭据解析或派发。
- `cost_ledger` 0006 是 namespace 内的 MOCK/CNY_SIMULATED，不是跨 namespace 的真实总池。0007 保持零权限。0008 `PaidControl` 有中央总池、provider/model scope、grant/call、USD价格/FX与人工核账，但请求白名单/输入硬上界证据、scope及授权合同不适合任意用户经历，也未具备完整 user/session scope。0009 受控探针为独立单次实验合同，不能重用为正式经历挖掘权限。

## 2. 本 PR 的实际最小实现

只新增 `apps/api/tests/offline_deepseek_mining.py` 测试支持与集成测试，不新增 `app/` 生产 Provider。测试支持类不是 ScriptedProvider，也不声明自己是合成真实 Provider；`reserve_cost()` 明确拒绝现有 API 准入，不能通过 `get_provider()` 或生产配置启用。

链路：测试直接调用原 `reserve → execute → claim`；测试支持类把受约束 context 交给现有 Adapter 请求构建，复用 PR22 的 v2.1 离线提示词/原 wire Schema；以不可变 UTF-8 bytes 和新版本 `deepseek-mining-integration-v1-offline` 记录 request/prompt SHA；精确 MockTransport 经过原离线 Transport → decode_official → validate_context_v2 → 原 complete/validate_v2 → pending事实。聚合、事实确认与03文本通过现有 HTTP 接口核验，数据库由独立连接读取。

请求、响应只在合成测试进程内存在。无环境密钥解析、Windows凭据、真实HTTP、付费授权或费用落库。测试阻断原生凭据 API、Python DNS/连接和真实 HTTPTransport；libpq 只连接显式指定的本机测试数据库。场景回调仅是测试故障注入，不是外部模型输出。所有 usage 是虚构夹具，不计为实际 Token/费用/延迟。

**兼容边界刻意可见**：测试 run 仍按旧数据库默认/DTO 显示 scripted/synthetic，assistant仍是固定合成标记，prompt_version仍由 complete 写 context-v2。这是未改变生产合同的测试落点，**不可拿此 DTO 表示真实 DeepSeek**。真实 Provider 的 provider/synthetic/prompt元数据、准入和 assistant语义必须先版本化，不能用继承 ScriptedProvider 或改一个环境变量绕过。

测试失败分类使用现有业务码：本地输出/来源拒绝为 failed/provider_output_invalid；超时/断线/取消或HTTP不确定结果为 unknown；迟到的有效响应在业务层变成 stale/unknown。诊断中不保留原始供应商文本。**业务 failed 不意味着供应商未执行或费用为零**；本 PR 不证明付费账本与业务事务已联接。

## 3. 推荐正式接口（设计，未实现/未注册）

`DeepSeekMiningProviderV1.mine(context: MiningContext, binding: CallBinding) -> ValidatedMiningResult`：

- context来自服务端 claim 并经 `within_budget` 与隐私同意政策核验，只将 payload 发出；不接受任意URL/角色/原始客户端提示词。输入是非可信数据，不执行其中指令。
- CallBinding 不可变地绑定 session/project/run/user、context_revision、ledger UUID、call_id、账户/SecretRef摘要/版本、固定 endpoint/model/version-policy/region/mode、prompt/schema版本与摘要、output cap、完整请求bytes SHA、授权/价格证据摘要。
- HTTP envelope（状态、大小、唯一choice、model/finish_reason/usage）→ JSON无重复键 → wire Schema/Pydantic v2 → 快照来源/位置/原子性/问题约束 → DB complete再校验。任何失败停止，不修补UUID/引用、不改写否定、不把JSON修复后当作原始有效输出，不切换模型/解析器重试。
- 返回结构区分 `validated output`、供应商reported usage、已观测HTTP状态、固定安全诊断码、可信配置证据；supplier正文/自由错误不进入日志。别名/fingerprint不证明不可变权重。
- 验证通过仍只提出 pending；证据辅助核实继续是用户材料依据，不是平台独立认证。

```mermaid
sequenceDiagram
  participant API as Future admitted API
  participant M as Mining state machine
  participant L as Central paid ledger
  participant P as Provider/broker/transport
  API->>M: user-confirmed operation + context revision
  M->>M: reserve answer/run once; claim snapshot
  M->>L: bind frozen bytes/policy; atomic reserve
  L-->>M: call_id + bound reservation
  M->>L: final approval/revocation check + unique sent permit
  L-->>P: single consumable dispatch authority
  P->>P: resolve scoped SecretRef only now; one POST
  P-->>L: received usage OR unknown (hold remains)
  P-->>M: validated v2 output OR safe failure
  M->>M: lease/revision/ownership validation; complete pending
  Note over L,M: business stale/failed does not release supplier liability
  Note over API,P: this sequence is future design, NOT live implementation
```

未来 Provider 工厂必须使用独立准入策略（显式启用+隐私授权+费用授权+受限broker），保持 scripted安全门禁不变；新Provider的非synthetic DTO/前端必须独立升级。无预算/授权/证据/用户同意时在密钥解析与DNS前拒绝。

## 4. 调用、计费与事实三个状态机

1. 供应商调用：not_sent / dispatch_permitted / response_observed / unknown。数据库唯一permit仅保证本地许可不重复，不保证网络/代理/供应商绝对只执行一次。不得429/5xx/超时后换key、模型、账户或供应商补调。
2. 计费：reserved / sent / response_received / unknown / reconciled；完整费用占用保留至有证据的人工核账。解析失败、业务stale、用户删除或取消，不是退款理由。实际超额记入实际账单并冻结，不截断为批准数；一账单唯一摘要防重复核销。未知费用占用预算并按政策冻结新付费调用。
3. 业务：reserved / running / completed / failed / unknown / stale；只在有效lease/revision下发布pending。完成后不需要等待人工账单，但计费未核销必须明确；已收费且事实失败/过期可以没有任何候选。GET恢复只读，不调用模型、permit或业务complete。

跨两个事务/外部HTTP不存在原子提交。未来需持久 `MiningCallLink` 唯一(run_id)/唯一(call_id)，同一业务操作/重试链绑定同一付费操作和请求摘要；声明发送前确认两侧状态，sent后崩溃保留未知，不自动补发。重启只读比对账本/业务/可信验证结果摘要；不能因为内存中output丢失就重推理。是否允许人工从安全保留的已验证结果重新发布，需要单独合同，当前不保存原始响应来恢复。

## 5. 费用、密钥与隐私上线阻塞项

- **BLOCK 预算证据/币种**：真实账单USD/CNY须按实际账户与价格合同建立独立快照，不能把CNY塞USD字段或用虚构FX。当前PaidPolicy USD合同与单次CNY实验不是通用正式计费合同。完整system/schema/context/framing输入上界尚无已认可的供应商证明；估算不是硬上界。路线B风险接受仅限那次S03/b，不能升级为全用户授权。
- **BLOCK 中央原子性**：保持唯一 ledger UUID，总池不能按namespace/实例复制。固定锁序 global→provider→model→user→session→grant→call，Decimal原币+经批准FX/税费；单次上限、会话累计、用户累计及并发、全局预算/次数均在同一事务预留/拒绝。现有scope不足，未来迁移需补 user/session 累计和不可变映射；不由普通应用创建额度/解冻。
- **BLOCK Secret权限**：Web进程不能读取Windows操作者Key或获得owner/审批权。独立broker用短期受限许可绑定账户、SecretRef/revision、请求/策略摘要、调用次数、时限；撤销在预留前及最终派发前检查。仅broker能解析Key并发送固定官方TLS目标，禁止代理/重定向/自动重试/回退，Key/DSN/自由响应不出broker日志。
- **BLOCK 未知恢复**：当前business GET只投影unknown，前端保守query-only；现有后端显式 retry 能复用回答但不等于允许第二次付费。必须在新准入路径联接账本许可，禁止用户重试API绕过未知消费冻结。取消/删除也不能抹掉账单审计；金额与摘要墓碑不含用户原文。
- **BLOCK 隐私同意**：合成数据许可不能变成真实简历外发许可。逐会话说明供应商、地区、保留/训练/删除条款、字段范围和退出方式，并记录政策版本/同意范围；只发最小遮蔽context，拒绝敏感类别、材料正文和隐藏/删除内容。现有context遮蔽+裁剪仍可带姓名/学校或已编辑前的历史原话，真实外发前需专门审查历史纠正/撤回的隐私语义。不能为降低Token擅自删掉否定。
- **BLOCK 质量**：词法原子性不等于语义事实正确；停止、问题目的与缺失指标不能只看Schema。需独立留出多轮评测/人工复核，供应商条款、限流、时延与版本也需授权真实探针后验证。本 PR 没有核验新的供应商行为。

## 6. 后续数据/DTO迁移建议（本轮无迁移）

- Run增加版本化provider/model/profile/request_sha/prompt_sha/contract_version，可靠synthetic来源；定义业务call_link。profile/prompt_version现有长度/默认值不能承担完整新合同。
- Question持久化purpose、合法source_turn_ids与版本语义；stop_event记录reason/actor/run/revision，区分用户停止与模型建议。维持问题纠正/隐藏/删除和原回答不可误归属规则。
- 经验证的assistant_reply如产品确需，另设有版本/长度/来源/隐私删除语义的合同；不得从固定Synthetic marker或原始响应升级。仅可读建议不成为事实，不含额外经历/数字。前端需明确非事实文本与候选引用，用户仍逐条确认。
- 前后端Provider准入/DTO升级应协调发布，旧scripted接口继续可用；不得先放宽前端字面量让旧run冒充真实AI。

## 7. 提示词、长度与留出评测

PR22历史SHA、提示词v2.1文件和历史报告保持不变。本测试使用v2.1作为离线候选系统提示词，但其示例含S03/b和UUID，因此S03/b**不能**当无泄漏泛化样本。独立测试用“我编写了离线校验器。”及随机DB ID，验证接线而非质量；手工构造Mock响应不是模型生成，也不是盲测。

既有v2.1长度报告在 `docs/evaluation/s03b-offline-contract-report.json`：单事实+verification问题126个本地估算tokens、格式化175；两题167/230；边界长输出556/620，说明256并不适合全部合法输出，不说明首次真实失败原因。多轮最多8原话、32事实、24问题+system/wire/framing，成本随上下文增长；本地JSON tokenizer不证明供应商Token，也不能用字符/字节充当输入硬界。正式cap/裁剪/停止策略与价格、质量应一起审查；本轮不改历史256 cap或批准费用。离线动态测试profile保持已有1200 cap，与历史探针分离；1200也不保证所有最大Schema输出可完整返回。

本轮另用已固定摘要的本机tokenizer归档（`e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`）作离线敏感性检查：每回合为“我编写了离线校验器。”重复10次（100字符），无历史问题/事实，turn UUID整数1..n、project UUID整数100、revision=1、input为首回合，round_count=min(n,6)，停止标志false。使用本测试builder与raw JSON的 `count_json`，不是聊天framing：1/4/8回合分别为5212/6406/7998字节，1522/1840/2264个本地估算tokens；prompt文本SHA为`1eae5ecdd75320098c6b826dc4ef4460b005c958b69d56f643f5452c100955c1`，request SHA依次为`ff6caa5a5d1d2dbd11de345d6ddeb66ee319764e9b25840cb0fda640153deaa9`、`2486d1592c13d6f4afca1843cee73a1916fceffb2db6eed54853e5c8667cb566`、`958935e8aa4ae92780693a0beb226899fedc0dcedcb1d825b1d29a286c6f0ea2`。这些新请求不在历史发送白名单。加入问题、事实及更长原话后还会增长，不能外推为最大费用。累计费用评估应逐调用按当时批准的输入命中/未命中/输出价格统计，不能只算最后一轮；本轮未获取或批准新价格/汇率，实际模型tokens/费用/延迟均未测量。

真实质量评测：冻结12组合成集作开发回归；另行生成不含示例关键词/UUID/答案的留出集（含否定、团队、含糊技术、历史纠正、相互矛盾、重复问题、停止/取消、无新增信息、非BMP偏移），记录schema_valid/source_valid/rubric_aligned三个独立轴，分别统计正贡献与否定边界事实。人工盲评事实真实性、原子性、追问价值与重复、适时停止；记录真实模型/渠道/区域、usage/cache、延迟、拒答/截断、每段完成经历和用户确认事实成本。离线模拟质量/真实延迟/费用均不得填造为实测。

## 8. 最小实施顺序及回滚

1. 审查本决策与离线证据。保持所有live路径关闭。
2. 独立小PR设计/测试业务与中央账本绑定、币种和user/session限额、未知恢复，受限DB角色/broker；隔离迁移、崩溃/并发测试；证据不够继续BLOCK。
3. 独立小PR版本化Provider准入、run/question/stop DTO和必要前端状态；无AI回复可先不实现reply合同。默认禁用，保留scripted兼容。
4. 用户**另行**批准固定合成数据、账户/SecretRef、单次及全局预算/剩余风险、请求SHA/prompt/model/region/cap、时间窗、最多次数、账单核对范围；离线prepare，人工执行一次，无自动重试。过去已核销实验不可复活。
5. 合成质量/成本评测通过且获得真实数据隐私许可后，才讨论少量正式业务启用。

回滚先禁用新Provider准入并撤销未发送许可；已sent/unknown不重发不退预留，保留immutable账本和call links供人工核账。不得降级数据库删除消费记录或复用许可；scripted可供明确选择，但不能故障后自动代替一次收费结果。

## 9. 运行与验收

仅在显式指向专用 `pathwise_test`/`pathwise_e2e` 的 TEST_DATABASE_URL 下运行：`python -m pytest -q -ra tests/test_deepseek_mining_integration.py`（工作目录apps/api）。沿用原迁移fixture每例创建/清理随机schema，不能指向pathwise_dev/pathwise_probe。本轮不提供真实执行命令。

覆盖正常候选→pending→HTTP聚合/原文引用→用户确认→summary；空候选；JSON/Schema/usage/model/引用/Unicode/否定/团队归属/重复追问/截断拒绝；超时/断线/取消未知；revision/lease/stop/end导致迟到结果不发布；同键重放/重复execute不再调用Mock；多轮回答关联和历史context；纯快照通过但跨会话DB来源拒绝；非Mock及正式工厂拒绝。

完整既有后端、React、Chromium、离线合同、隔离迁移和Mock CLI结果以本PR CI记录为准。本地故障记录：首次临时集群启动遗漏端口参数，连接15487被拒绝；已停止该测试进程并显式绑定127.0.0.1:15487，未转用正常服务。新测试曾误用枚举.value、扫描UUID为隐私文本，修正测试实现后重跑；不修改原业务断言。

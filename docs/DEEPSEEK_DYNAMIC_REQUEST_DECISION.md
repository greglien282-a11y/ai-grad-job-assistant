# DeepSeek 动态请求冻结与离线准入决策（PR28）

状态：**仅请求准备/离线合同验证；不是付费授权或派发许可**。
基线05af9725c0ece74a64915457ce56dc5752227763；Alembic head仍0011_mining_paid_metadata。本PR不修改0008–0011、不注册Provider、不开放环境开关、不部署到持久库。

## 1. 已有三条路径不能自动拼成真实付费能力

- PR25的tests/offline_deepseek_mining.py：动态MiningContext→版本化Mock请求→原验证/complete，旧v2.1提示词含已披露的S03/b示例。证明离线衔接，不能证明授权、质量或泛化。
- PR26的fixed-fixture-binding-v1：固定SyntheticRequest的真实同库绑定/费用原型；其context revision/history不等于实际业务快照。请求SHA和业务context SHA不能互换；重试链不能另买一次调用。
- PR27/0011：惰性身份/限额/计划/绑定Schema，默认没有新增运行权限；没有binding_runtime、资金预留或公网派发函数。

本PR增加新的纯离线边界，不改这些文件或历史请求SHA。旧S03/b及已核销冻结账本永不复活。

## 2. 冻结合同与唯一字节来源

`app/prepared_mining_request.py`的PreparedMiningRequestV1使用frozen、slots dataclass；bytes和Profile规范JSON bytes均不可原地改写，repr隐藏对象内容。数据包含最小化的用户资料，仅在内存保留，不写数据库、日志或报告。Python对象不可变不是对恶意同进程代码的密码学证明。

包含contract/config版本、run/root、context_revision、稳定operation摘要、完整UTF-8 body及request SHA、context SHA、Provider/Model/expected version/version policy、固定endpoint/region/deployment/mode/JSON模式/output cap、prompt文件/完整system/Schema/Profile摘要与版本及准备检查列表。**不包含SecretRef、密钥、Grant审批、账户余额、预算或paid permit。**

唯一数据入口是服务端构建的MiningContext.payload()。从Adapter复用固定non-thinking Chat Completions结构，再嵌入新的版本化system message；最终规范JSON一次编码为bytes。测试MockTransport直接收到同一个prepared.body，不重新序列化。未来真实Transport若接入也必须只消费这些已绑定bytes，但本PR没有此入口。

固定配置：DeepSeek official / deepseek-flash / https://api.deepseek.com/chat/completions，thinking.type=disabled、json_object、stream=false、temperature=0、max_tokens=1200。1200沿用既有Profile上限，不是消费授权，也不更改旧256上限的历史探针。region=provider_managed_unverified；expected_version=DeepSeek-V4.1-Flash、alias_observed_not_immutable仅为预期配置，**不是模型权重或实际部署区域证明**。

配置不能由调用方传入URL、system、tools、模型或额外消息。Profile仍enabled=false、actually_verified=false。无配置开关可开启调用。

## 3. 精确摘要规则和原件边界

规范JSON统一复用cost_ledger.canonical：UTF-8、ensure_ascii=false、sort_keys=true、无无效空白。读取冻结JSON时额外拒绝重复键、NaN/Infinity、非规范字节、额外字段、额外消息或角色。该canonical工具复用不意味着使用模拟账本。

- request_sha = SHA256(最终body原始bytes)。不是重新序列化后另一份内容的摘要。
- context_sha = SHA256(UTF8(canonical(当前服务端最小化context.payload())))。
- prompt_file_sha = SHA256(新prompt文件精确原始bytes，含结尾LF)。新.gitattributes只固定这一新文件LF，不改变任何历史文件。
- system message = 原prompt UTF-8文本（不rstrip）+固定分隔符`\nWire Schema:\n`+canonical(wire Schema)。prompt_sha = 这一完整system message的SHA256，**不同于prompt_file_sha或request_sha**。
- schema_sha = SHA256(嵌入请求的canonical wire Schema UTF-8 bytes)。schema_file_sha另记实际读取的Schema原件bytes SHA；原件换行可能随checkout不同，不能拿canonical摘要冒充原件摘要。历史Schema文件不修改。
- profile_bytes = canonical(Profile.safe_snapshot())的UTF-8；profile_sha为其SHA256。safe_snapshot只排除不进入合同的自由blocker说明，不包含其他候选模型/预算草案；disabled等状态及全部有效Profile字段保留。

审查版本pins：

- config_version：deepseek-dynamic-request-v1-offline。
- prompt_version：dynamic-mining-prompt-v1-offline。
- prompt原件SHA：d9d7b2a4303c58004cbbf97fbc50e57ac195270182b73e760aefb575d8ee5273。
- canonical Schema SHA：a55afacc5c0e570a4c86dc6eaa723f8d8b43e58c455bef0308fe57e8834db736。
- Profile SHA：e1601192c9dbf3013c75b171f5bb7d037f639dd3c56831e31b00f290f3ce8218。
- schema_version：mining-output-v2-wire-v1。

pins写在版本化代码中，由独立验证器重新检查实际文件；不是调用方提供或构造器临时签发的哈希。有效Profile/prompt/Schema改变需新版本及独立审查，当前版本fail-closed。上下文有效字段变化会改变context/request SHA，并使已固定的0011映射不再匹配。摘要不是审批签名或外发许可。

## 4. 来源、最小化和幂等根

`app/mining_request_snapshot.py`只接受服务端依赖注入的factory，不读.env、URL、系统凭据或供应商信息。它自己开新事务，设置并核实REPEATABLE READ READ ONLY；同一连接内授权会话、核对run/session/revision/lease、构造context、追溯root及原receipt、读0011映射。

要求run=running、当前session/mining active、reserved_revision与当前版本一致；过期lease、删除/停止/结束、错会话、缺失或过期root receipt均停止。引用仍由build_context只从同项目合法user turns构造；assistant不能伪装来源。纠正/隐藏/删除问题及回答版本关联、事实修改/拒绝与memory_state继续使用现有context构建规则，不从legacy MiningInput.content、原始项目长文、FactChange旧正文或材料详情补资料。

沿用最多8个user turns、32事实、24问题、16000文本字符/64000 context JSON bytes；保留当前回答，不截断成另一个意思。重新解析Frozen模型，防止model_copy跳过字段验证；检查重复ID、隐藏/删除问题不得带正文、rejected事实不得带statement、停止条件和预算。已编辑事实的当前版本优先，但合法历史用户原话仍可能存在；不宣称所有旧文字都消失。已有输出来源抑制/complete继续阻止旧来源重新覆盖用户编辑。

已有PRIVATE遮蔽保留Unicode code-point位置；新增只拒绝已知Bearer/API-key样式，不修改用户文本。两者都是有限模式检查，**不是完整秘密检测或匿名化**；姓名/自由文本仍可能敏感。成功不意味着真实用户外发同意。

稳定operation_hash = SHA256(canonical({version:新config版本,session_id,root_run_id,root receipt_hash,root_request_tag}))。这些来源由数据库读出，不相信客户端user_id、操作键或Grant ID。相同root重试不能改变这一身份；若已有root计划指向旧Run，新Run直接拒绝，不换键创建可消费身份。该摘要**不是**PR26 fixed-fixture算法，也不是新的资金许可。缺失原receipt不能静默换键恢复。

## 5. 独立校验和四种状态

`app/mining_request_admission.py`不调用prepare_request/Adapter构造器，不接收调用方自选配置；解析最终bytes，逐字段核对严格固定wire形状、当前context全文、已审查system/Schema/Profile与独立摘要、Run/root/revision/原始幂等关系及0011投影。即使攻击者重算所有声称的SHA，或者构造器误加tools/消息，仍不能覆盖可信期望。

1. 请求已准备：纯builder只产生不可发送的冻结候选，**不声称快照现在仍有效**。
2. 快照合同匹配：纯validate_prepared返回snapshot_contract_matches/metadata_mapping_valid；重用旧快照不产生fresh数据库证明。
3. fresh离线匹配：admit_offline新开只读快照，再独立校验，才返回时点性的offline_contract_valid。
4. paid_authorized与dispatch_permitted：以上所有结果始终false，无代码路径可升级为true。

一次只读快照验证不跨越之后的业务变更，不是连接池永久证明，更不是可缓存的发送令牌。冻结后业务提交修改，再次fresh检查必须拒绝；检查期间/之后的并发最终派发仍必须在未来受限费用事务中以Funding→Session→Run锁序重新核对。没有实现或宣称这项真实派发保证。

所有错误为有限、本机固定码，不携带原异常、SQL、正文、Key或响应；无自动修补、重签、重试、账户/模型切换、自动轮询或推理。

## 6. 0011映射与不能复用的证据

复用0011的run/root/operation/receipt、request_sha/context_sha/prompt_sha/schema_sha、provider/model及config/prompt/schema版本。这里prompt_sha明确绑定**完整system message**；schema_sha绑定canonical wire bytes。与PR25裸prompt摘要、PR26原件Schema摘要的区别以新config/schema版本区分，不重写历史行。

读取计划时验证ledger、会话/身份映射、Grant关联policy/account/provider/model及已有binding的核心元数据；固定SyntheticRequest证书不包含该动态request SHA时拒绝，不能拿固定授权替换动态bytes。**这不是对该Grant的预算/价格/Token/隐私授权有效性检查。**

测试为了满足0011必需的Grant FK，只在随机Schema构造显式execution=offline_contract_fixture_v1、ceiling=0的合成行，中央总额仍0，policy不是合法PaidPolicy，不能reserve。测试断言PaidPolicy解析拒绝、无paid_call/占用/消费。写入helper只在tests目录；应用侧reader/checker全部SELECT，不签发此行，更不以它冒充审批。

0011不足以保存profile_sha/Profile完整快照、endpoint/region/deployment/mode/output cap/version policy、独立prompt_file_sha/system/schema原件证据和冻结manifest版本；也没有安全恢复原始body的机制。**本轮不改0011、不创建新迁移**。

后续迁移建议（未实现/未批准）：新增不可变request-manifest v1，明确绑定Run/root及以上完整配置/摘要和可信时间，与0011计划唯一关联；只存费用最小元数据，原始请求bytes若需恢复应由独立审查的业务侧受保护intent/短期存储保留，不能把原文放中央账本。业务已变更或证据缺失时停止，不从新context静默重造旧审批请求。保留root防重放及删除/审计分离，非空降级保护另审。

## 7. 离线集成和长度观察

测试链：真实合成业务reserve/claim → 新只读快照 → 冻结bytes → 显式零额度映射fixture → fresh独立校验 → 严格httpx.MockTransport接收同一bytes → 既有decode_official/validate_context_v2 → 原mining.complete。

仅tests/offline_prepared_mining.py提供executor测试辅助，reserve_cost始终ai_provider_unapproved，不注册到API、不冒充scripted准入。原DTO仍只能表示scripted/synthetic，该事实不改；直接executor是离线测试缝，不是正式真实Provider接入。

合法Mock结果只产生pending，确认/拒绝规则不变。团队/不确定性等不具备合法候选时可为空并澄清；非法JSON/Schema/引用/截断失败，超时/503保持unknown，重复execute或同键恢复不产生第二次Mock请求。usage只标simulated_usage，不产生或估算实际费用。

附加1/4/8个user turns长度用例只记录原始bytes，8个user turns不代表允许超过现有6轮停止阈值；finish_reason=length必须拒绝。没有下载或调用tokenizer，没有真实模型耗时/质量/费用数据，更没有Token硬上界证明。

运行（apps/api，TEST_DATABASE_URL必须显式指向专用测试库；fixture只迁移随机Schema）：

```powershell
.\.venv\Scripts\python.exe -m pytest -q -ra tests/test_prepared_mining_request.py
.\.venv\Scripts\python.exe -m pytest -q -ra
```

初轮97 passed/1 failed：跨Run夹具先把上一轮标failed后试图直接新建，正确触发原mining_retry_requires_confirmation。已改为原complete后开始下一轮，未放宽重试规则；两项跨Run/root回归随后通过。最终专项/全量CI结果记录于PR，不预先宣称通过。历史测试、Provider门禁、模型适配器、页面、预算和迁移均保留。

## 8. 上线BLOCK与下一阶段最短路径

- 先审查本合同与0011缺口，再单独审查不可变manifest/intent存储及受限写入/恢复合同；本轮没有部署权限、可信跨会话用户身份或真实资料外发同意。
- 唯一中央账本部署/历史实验责任、原币价格/预算/Token或风险授权依然独立BLOCK；旧S03/b冻结账本及一次性批准不能复用，更不能另Schema创建第二个消费池。
- 需要独立非LOGIN函数Owner/受限运行角色、可消耗发送许可与Secret Broker，发送前原子复核撤销、额度、context/lease和准确bytes；sent/unknown不自动退款、重发或回退。当前仅只读校验不替代这些条件。
- 新prompt不含S03/b目标原文/UUID，但Mock仍是oracle式管线测试，不能据此声称真实泛化质量。需要独立留出样本与单独获批的真实合成质量验证。
- 下一次真实探针必须重新批准该新版本的完整request SHA、固定合成输入、账户/币种、次数/预算/剩余风险、有效期、SecretRef读取范围和人工核账；新1200 cap与旧256探针不同，不继承任何旧许可。当前真实供应商请求/费用继续0。

停用/回滚：不注册本合同到Provider即可保持关闭；保留历史审批/账本/请求文件不动。代码撤回不清理真实费用，不能靠换键/账户/模型或静默重建请求恢复消费。完成本PR后停止，等待独立审查。

附加长度观察（完全合成、仅字节，非质量/Token/费用证明）：1/4/8个user turns的context bytes分别为508/907/1439，完整request bytes为4362/4791/5363；actual_tokens、actual_cost、real_latency均null。该观察不适用于任意用户材料，也不代表供应商硬上界。

专项阶段104 passed；补充legacy content getter拒读和固定诊断码边界后总106项。最终完整后端及CI结果以本PR记录为准；全部真实调用、密钥访问、费用继续0。

收尾追加的边界回归先失败，确认新builder曾用round_count>=6误拒原reserve已准入的第六轮。仅在新模块修正为>6；末轮可处理当前回答并由原complete停止，不生成下一轮问题，之后fresh检查拒绝。新增真实六轮正向用例及停止/结束/超限/连续空轮/负轮次拒绝，未修改旧业务规则。最终新专项112项，失败历史保留于本段及PR。

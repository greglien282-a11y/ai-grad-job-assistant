# S03/b 离线输出契约与提示词审计

基线：`f5a1499daf229c90de68d4529fb5ca84859a1ecf`。本轮不是第二次真实模型验证，未读取真实 Key、凭据、账单、审批文件或实际探针数据库。

## 1. 审计结论与证据等级

确定的提示词缺口：旧 `Adapter.build_request()` 在简短指令后附上输出 Schema，没有完整输出实例，也没有说明 Python Unicode 半开区间及停止状态的跨字段关系。

2026-10-16 核对的 [DeepSeek 官方 JSON Output 文档](https://api-docs.deepseek.com/guides/json_mode/)说明 JSON mode 面向合法 JSON，建议提供期望格式示例、合理设置输出上限，并提示可能返回空 content。这不能证明满足 Pathwise 的业务 Schema，也不能提供固定成功率。本轮仅浏览公开文档，没有访问推理、余额或账户接口。

不是代码错误：现有解析器没有把 `json_object` 当作业务 Schema 保证；它仍检查精确的五个顶层字段、Pydantic 结构、停止状态、来源和安全预览。JSON 合法但 `{}` 或缺字段的响应会安全拒绝。

确定的信息可用性：S03/b 上下文包含合法用户 UUID 和完整原句 `我实现了本地筛选。`。正确引用为 `[0,9)`；UUID 为 `1144cfca-8c37-5d49-bc83-8f4d45bc266f`。模型有必要信息，但是否能稳定照抄 UUID、计数和保留限定条件，离线测试不能证明。

确定的契约分层：wire Schema 定义字段类型/枚举/数量，但不表达 stop/questions/reason 的交叉关系。Pydantic `stopping()` 才要求：

- 继续：`stop=false`、`stop_reason=null`、1–2 个问题。
- 停止：`stop=true`、合法非空 reason、零问题。

旧提示词未解释这层约束，存在产生矛盾输出的合理风险；服务端已经会拒绝，不能为模型易错而删去约束。停止原因是否在语义上恰当、追问是否真正有帮助，仍非这些结构/词法测试所能证明。

合理风险：JSON-mode 空内容、Markdown、字段别名、缺字段、错误引用、过早停止或过长输出都可能发生。旧 happy-path 测试使用自动从句子生成的理想引用，能证明管线但不足以模拟模型偏差。

未经验证：以上任何风险是否造成第一次失败、示例能提升多少成功率、供应商 framing/tokenizer 与本地估算的差异、真实模型追问质量。首次 71 个输出 tokens 不能单独证明截断，也不能和下文的本地估算直接对号入座。

## 2. 48 个合成偏差样本及分层目标检查

完整、可复核的逐项结果见 `docs/evaluation/s03b-offline-contract-report.json`。每项列出输入条件、验证范围、预期阶段/代码、实际代码、安全拒绝与预期是否一致，并独立列出 `schema_valid`、`source_valid`、`rubric_aligned`。所有 HTTP usage 均为人工构造的自洽数字，不是模型实际用量。

固定 S03/b 完整链路覆盖：精确事实/UUID/偏移，结构合法的继续/停止及业务不符反例，空候选追问，两个问题，允许的模型标识、缓存统计及可省略的 usage 扩展；缺少五个字段中的任一个、额外字段/错误类型、自确认、错误 UUID/偏移/改写、未经提供的数字、重复追问、空 content/半截/Markdown JSON、停止状态矛盾、显式 length、非法 usage 和 fingerprint null 的保守拒绝。

补充来源样本覆盖否定、团队、假设和非 BMP 字符：

- 完整否定原句可作为边界事实通过通用来源校验，不视为正向贡献。
- 去掉否定、把团队/计划改写成个人已完成事实被拒绝。
- 团队/假设即便原文准确，也不能绕过现有原子性限制。
- 团队归属不清时可返回空候选及贡献澄清问题。
- emoji 使用 Python code point 可通过；UTF-16 单元或 UTF-8 字节偏移被拒绝。

这些补充输入明确标为 `snapshot_source_guard`：仅运行现有通用来源验证器，其 `source_guard_*` 是离线审计标签，**不是运行时 HTTP 诊断码**。固定探针预览会再次核对原始 S03/b，因此不能把外部上下文的局部通过冒充完整探针通过。所有变更上下文和新版请求都另有测试证明会被现有 HTTP 字节白名单阻断。

S03/b 金标准直接读取既有评测数据：`allow_stop=false`、`question_goals=["verification"]`，且要求完整原句的候选引用。新增正例包含该事实和 verification 追问。旧 stop=true、detail 追问、空候选等反例仍保留：它们可以通过完整 HTTP 校验，但 `rubric_aligned=false`，不能算案例目标成功。

三个轴的含义：`schema_valid` 包括严格 JSON/Pydantic 和停止跨字段约束；仅结构通过后才运行既有来源校验得到 `source_valid`；仅来源通过且适用 S03/b 金标准时才评估 `rubric_aligned`。后者只自动检查金标准引用、停止许可和问题 purpose 覆盖，不证明提问文本的语义质量，仍需人工评分。`null` 表示前置检查未通过或该补充案例没有适用金标准，不表示通过。HTTP envelope/usage 是否有效另见 `full_response_validated`；三个轴不能取代完整响应验证。

没有修改原子性、否定、数字、来源、预览或 Pydantic 校验；没有自动补字段、生成引用、修正模型 UUID、重试或写入用户事实库。

## 3. 输出长度：离线估算，不是计费上界

使用已有公开 tokenizer ZIP，SHA-256：
`e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`。
只读取固定 tokenizer.json 数据，不下载或执行远程代码。原始 JSON、add_special_tokens 的本地估算为：

- 空候选停止：紧凑 28 / 缩进 39 tokens。
- 一个完整事实并停止：75 / 108。
- 一个事实、一个 verification 追问：126 / 175。
- 一个事实、两个短追问：167 / 230。
- 一个事实、两个很长的合法结构问题：556 / 620。

停止样本和缺少 verification 的长度样本仅用于容量对照，在 S03/b 下 `rubric_aligned=false`；不能作为业务正例。最后一项只是字段长度边界，不是优质问题示例。长度样本只验证业务 Schema 与来源，不构造假 HTTP usage 来声称长文本已在 256 cap 内返回。它说明 256 并非整个 Schema 输出空间的容量保证。对本轮短 S03/b 示例，紧凑格式的估算在 256 以内；不能据此保证真实输出不会冗长或截断。也不能据此追溯第一次响应。

历史请求原始 JSON 估算输入仍为 812；v2.1 为 1476（上一版 v2 为 1412）。示例和明确规则相对历史请求增加了 664 个本地估算 tokens，**不是更省输入的实测结论**。实际供应商用量、费用、质量、延迟和严格最高 Token 数均未测量。本轮不选择新的真实输出上限或预算。

## 4. 新版提示词：独立、离线、未接线

`docs/evaluation/s03b-prompt-v2.txt` 版本为 `s03b-prompt-v2.1-offline`。S03/b 继续实例使用完整原文引用及 verification 追问，通过完整响应链路并符合案例金标准。停止实例改为不同的用户原话和 UUID，用户明确说“我记不清更多细节，先停止追问。”，上下文 `user_stopped=true`，无候选、无追问，reason=user_uncertain；它单独经过 Schema 与该场景的来源校验，不冒充固定 S03/b 探针的完整通过。

S03/b 文本和 UUID 已直接出现在提示词中。因此未来对同一输入的模型成功结果只能算**样例内契约遵循检查**，不能作为无泄漏的泛化验证。报告明确 `s03b_is_in_prompt_example=true`、`generalization_evaluated=false`；泛化需要后续独立、未入提示词的留出案例。本轮没有运行模型或建立泛化结论。

输出仍是 MiningOutputV2；wire Schema 未改变。旧 `Adapter.build_request()` 未改变，历史请求仍为：
`5cc2def4f875e43760e799678a43c1f2d2072dd4245eaf54457dfe78ee0b373e`。

新版仅通过 `offline_output_contract.prompt_v2()` 生成独立 `OfflinePrompt`，SHA 为：
`a07982bc19a7dbdbc8012f12a310035ad72d82ebcfa1cec88e689cb377e34fec`。
上一版离线 v2 的 SHA `48909005b457c51a6a1a6d50ce6545a3b40a4c12f6512ea52432697311424959` 已由本次 v2.1 替代；它也从未接入真实发送。
仅 system 内容变化；用户原话、上下文、模型、输出 cap=256、模式等保持相同，以隔离提示词变量。

它不是 Provider 或 SyntheticRequest，不注册到用户页面、真实 Transport 或授权流程；现有真实探针 `verify_bytes()` 明确拒绝该 SHA。没有更新旧允许列表、Policy、预算、许可、核销或数据库迁移。以后若要真实验证新版，必须另行审查请求版本/字节/SHA、输出 cap、费用与用户授权，不能复用已核销名额。

## 5. 本地与 CI 验证方式

不需要数据库或 tokenizer 的纯离线审计：

```powershell
& .\apps\api\.venv\Scripts\python.exe scripts/check_s03b_output_contract.py
```

复算长度并写入**新的**合成报告（不覆盖旧报告）：

```powershell
& .\apps\api\.venv\Scripts\python.exe scripts/check_s03b_output_contract.py --tokenizer-archive .e2e/controlled-probe-tokenizer.zip --output .e2e/s03b-output-review.json
```

不提供 archive 时长度字段保持 `TOKENIZER_NOT_PROVIDED`；缺失/摘要错误不会触发下载。脚本没有 DB、Credential Manager 或 HTTP 操作。

pytest 新用例覆盖逐项结果、新旧 SHA、两个提示词实例、变更请求不能进入发送门禁、报告复现、长度证据边界和 CLI。真实 PostgreSQL 测试只使用临时测试集群的随机 schema，验证原固定请求的合法/非法响应、HTTP200、资金保留/冻结及同键不重发。现有完整 API、React、合同、迁移和 30 项 Chromium E2E 保留；CI 另运行本轮纯离线 CLI。

## 6. 保留的问题

48/48 表示离线预期错误码分类被实现，不表示所有样本符合金标准，更不表示模型准确率。结构/来源合法而业务不符的样本刻意保留为负例；回归断言分别验证三个轴。新版提示词是否更好、输入开销是否值得、真实空内容/冗余/停止行为、供应商可选字段差异等，仍需未来单独授权的实验。不得宣称第二次真实模型测试成功；本轮没有发生该测试。

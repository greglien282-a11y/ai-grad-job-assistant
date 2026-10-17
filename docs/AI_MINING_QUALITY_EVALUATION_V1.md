# 应届生经历挖掘质量评测 V1（DRAFT）

基线 d7a13c778e4bb93ed519d4551496fa7987731c18，合并CI39047977330三项已确认success。
本轮建立数据与工具，**没有真实模型成绩，没有已审核人工金标准，没有真实人工评分**。

## 1. 审查结论与复用边界

- `offline_evaluation.py`：既有12组teacher-forced合成案例→Mock/原业务complete/模拟账本，证明工程管线。保留原文件、案例和报告；本轮不另造Provider、数据库、调度或费用系统，也不运行它来冒充质量评测。
- `mining_context.py`：复用受限MiningContext/问题版本/回答关联、记忆状态和停止字段。新工具仅从虚构案例构造评测快照，不读业务库，不冒充server build_context。
- `mining_provider.py`、`model_adapter.parse_output`：保留MiningOutputV2五字段wire合同及严格JSON/Pydantic校验。
- `mining_validation.validate_context_v2`：继续原样复用来源/Unicode/原子性/数字/去重规则。它是保守词法guard，不是语义裁判。
- `offline_output_contract.py`、S03/b文档：48项合同、结构/来源/草案目标三轴和历史SHA都不改；历史提示词含S03/b样例，不能当无泄漏泛化评测。
- 旧report-template是历史工具合同；其0–2追问评分设想不直接换算为本轮0–4六维Rubric。旧文件出现gold/human注释，不等于本轮核实了人工审核来源。
- `dynamic-mining-prompt-v1.txt`不改。新增案例原文/UUID不写回Prompt；没有根据答案调Prompt求通过。

## 2. 新数据：20个虚构场景、12开发/8留出

数据：`docs/evaluation/quality-v1/dataset.json`，版本grad-mining-quality-v1-draft；全部synthetic=true、label_status/review_status=DRAFT、human_reviewer=null。

开发集GQ01–GQ12依次覆盖：课设无实习、团队分工不清、基础数据整理、基础手工测试、“我们”不等于“我”、无指标、记不清规模、未完成计划、否定经历、学习不等于成果、多个步骤拆解、历史纠正。

留出集GQ13–GQ20覆盖：拒答/跳过、两题只答一题、主动停止、六轮上限、极少经历、没有材料、普通维护工作的价值、非BMP字符引用。留出集没有Oracle/反例输出示例，不进入Prompt；只运行结构/偏移等工具单元测试，不生成留出集质量成绩。

每例含背景、用户原话及UUID、显式回答关联、历史问题状态/版本、合成用户已确认与pending事实及来源、记忆状态、原文引用code-point区间、正向/边界标签、不可推断信息、推荐澄清目标及文字说明、误导问题、停止条件、备注和审核状态。

`split-manifest.json`记录canonical dataset/case SHA。代码独立pin数据SHA和12/8划分，不能改两份JSON便静默交换划分；改语料须新版本/审查。当前SHA为：
`ea46915e46784e5e729935828f044546052736479d10246460432a90faff3329`。

这是**公开、Codex起草的留出材料，不是秘密盲测集**。未来模型输入只能用context_for()的用户/问题/事实快照，不传reference、目标、误导问题或评分标签。人工审核后应另立版本保留审核来源，不把DRAFT直接改名为人工gold。禁止用留出答案继续调Prompt。

多轮案例采用最后一轮的teacher-forced快照：能检查模型是否利用历史、纠正、拒答和回答关联，**不证明模型真实促成了此前回答，也不是自由多轮rollout**。未来需要单独设计多检查点、用户回答策略和人工过程评审。

## 3. Rubric：人工0–4及N/A

完整逐分行为锚点、N/A规则及正反例在`rubric.json`，版本grad-mining-quality-rubric-v1-draft；不是自动打分规则。

- 事实忠实度：0编造/改变否定，1多处无依据扩展，2遗漏重要限定，3基本忠实有小歧义，4全部主张有据且保留边界。
- 个人贡献：0团队成果冒充个人，1默认负责核心，2职责混杂，3基本分清，4只保留本人动作、未知则澄清。
- 追问有效性：0诱导虚构，1无关/索要不存在材料，2相关但太宽，3具体可答，4优先一至两个高价值缺口且无错误预设。
- 非重复/上下文：0复活纠正/删除内容，1忽略已答/跳过，2漏重要关联，3轻微冗余，4正确处理历史、版本和两题部分回答。
- 不确定性/自主性：0强迫猜测/替用户确认，1持续施压，2暗示必须量化，3基本尊重，4允许不知道/跳过/停止且不贬低普通经历。
- 停止合理性：0违背明确停止/上限，1无休止或无依据终止，2时机明显不当，3基本适时，4按意愿/信息边界/轮数停止并保留事实核对。

没有判断机会可N/A，必须说明理由并提供依据；缺失/未评审是unreviewed/null，**不是N/A、零分或满分**。有追问不能因其质量差就标N/A。每个提交的评分都需证据原文/位置、理由和评审者状态。

编造指标、团队冒充个人、无依据确认、敏感资料泄漏、编造技术/证明、忽略停止等独立记录。没有总平均分替它们作抵销；有严重错误的评审组保持severe_errors_block_acceptance=true，即使某些维度均值4分。

## 4. 离线评分器与分母

`app/mining_quality_evaluation.py`只读取受控合成案例和预先提供的输出content JSON。没有HTTP、env/Key、DB/凭据、推理或重试接口。输出来源可标authored_oracle、authored_counterexample、mock或imported_model_unverified；Provider/模型均为**提供方声明**，generation_verified始终false。

Prompt文件SHA与canonical wire Schema SHA绑定现有版本；prompt_file_sha不是完整system/request SHA。所有运行明确记录数据版本/摘要、划分、来源、模型标签、Prompt版本和Schema摘要，不把Mock用量或本地估算写成实测。

每项比率都有numerator、denominator、unscorable、not_applicable、unit和ratio。分母包含已知但不可评分的机会，不能先丢掉失败样本再报满分。候选数未知另计citation_unscorable_outputs，不能凭空估计缺失候选数量。

- strict_schema/stop_structure：通过数/计划输出数；缺失仍在分母，不计正确。
- runtime_validation：现有完整快照guard通过数/计划输出数；结构失败标不可评分，仍不算通过。
- literal_citations：原始候选字面引用匹配数/可枚举的原始候选数，独立于结构与语义；不能抵销Schema失败。
- draft_candidate_precision/recall：与DRAFT引用元组精确匹配的唯一事实/原始候选或参考事实；重复不能刷分，结构失败不计匹配。
- draft_positive_recall与draft_boundary_recall分开，否定边界不充当简历正向贡献。
- draft_runtime_accepted_recall另记既有guard实际接受的参考事实，显式展示词法限制。
- draft_stop_alignment检查草案停止目标；结构合法但过早/过晚仍可为0。
- purpose/goal coverage仅检查枚举匹配；不叫追问质量得分。
- exact_nonduplicate仅是规范化文本/已有指纹去重，无法判断同义重复；这部分需要人工。
- supported_numeric_tokens只核对数字字符串来源，不证明单位、归因或数字语义正确。

空候选的precision是null；若预期有事实，recall为0。没有参考事实时recall为null，不是100%。缺失/非法Schema/无法枚举候选均显式保留。有限规则不能自动判断语义“真实性”：critical_rule_signals标明机械或DRAFT来源、human_confirmed=false。

## 5. 两组可复现示例，不是模型成绩

开发集`oracle.outputs.json`由Codex依据DRAFT参考编写，是有意拟合标签的管线样例；`adversarial.outputs.json`含缺字段、错误引用/偏移、篡改否定、计划/团队冒充个人、旧职责复活、虚构数字和过早停止。

Oracle结构12/12通过，现有guard为11/12：GQ03“整理缺失记录”虽有准确原文且DRAFT认为可表达价值，但现有atomic()动作词表不识别“整理”。该差异保留，**不改事实校验或Prompt求过关**。标签是否合理仍待人工，不宣称词法guard必须放宽。

反例中GQ04可结构/来源通过而过早停止；GQ12旧陈述可以原文引用准确但不符合当前纠正后的标签；GQ06 purpose匹配却预设未提供的比例。这些样例证明不能用结构、来源或purpose覆盖代替语义评价。

示例结果在`examples/*.report.json`及Markdown。人工语义评分、真实模型留出质量、实际tokens和供应商延迟均null；tool_provider_requests=0、tool_cost_cny=0只描述工具本身，不是对外部导入输出既有成本的核账。

## 6. 人工评审流程

1. 先运行CLI，取review-packet.md及绑定的review-template.json。评审材料展示原话、历史题/版本、回答关联、当前事实及输出，不显示参考答案，降低标签锚定。
2. 人工独立检查引用、个人贡献、追问、停止；逐维填0–4或N/A，写理由和原文区间证据。只用非秘密评审者标签，不放个人联系方式。
3. 提交时填写operator_submitted_unverified和submitted；工具不认证真实身份、不生成签名。示例必须demonstration=true，不能混入正式记录。
4. 用相同数据/输出bundle导入评分；dataset/output SHA、证据位置、评分范围及版本均校验，不能把评分挪到另一次响应。
5. 标记needs_second_review；第二人独立评分。工具导出逐维分歧（含分数与N/A差异）及严重错误，不捏造一致率；仲裁与实际复核由人完成。

默认模板没有评审者、分数或虚构签名。`demo-review-records.json`是两条明确DEMO的合成评分，验证严重错误和分歧导出；`examples/demo-reviews.report.json`的human_reviews为null。评审JSON与metrics.json分开，用dataset/output_bundle SHA关联，不偷偷把规则值灌入人工六维分数。

## 7. 本地运行（不需要数据库或Key）

每次使用**不存在的新输出目录**，不覆盖历史证据：

```powershell
& .\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_mining_quality.py --outputs .\docs\evaluation\quality-v1\oracle.outputs.json --split development --output-dir .\.e2e\quality-oracle-new
& .\apps\api\.venv\Scripts\python.exe .\scripts\evaluate_mining_quality.py --outputs .\docs\evaluation\quality-v1\adversarial.outputs.json --split development --reviews .\docs\evaluation\quality-v1\demo-review-records.json --output-dir .\.e2e\quality-demo-new
```

产生metrics.json/md、review-template.json、review-packet.md；提供reviews时另产生reviews.json/md。CLI只打印固定摘要；非法输入/路径只报固定错误，不回显异常。疑似敏感输出在报告/材料中脱敏，不回显正文。有限模式检测不是完整敏感信息识别；只接收已受控合成材料，不能拿它处理真实简历。

holdout需要显式--split holdout及仅含该划分的独立外部输出bundle；拒绝开发样例混入和authored_oracle/counterexample在留出集评分。无输出时仍报告全部计划案例缺失，不生成模型响应。

## 8. 工程验收和四层证据

1. 工程合同通过：严格JSON/Schema、原文、Unicode和既有guard测试；不是语义质量。
2. 合成Oracle符合预设：DRAFT引用/目标匹配及反例检查；不是泛化能力。
3. 人工语义评审：本轮只有规范/模板/DEMO；实际评分、评审者和一致率都不存在。
4. 真实模型留出质量：本轮没有调用或已认证输出；结论null，不能用前两层代替。

专项测试覆盖20例结构/偏移、划分与Prompt隔离、未审核标签、确定性报告、缺失/空值/错误分母、严重错误独立、人工N/A/绑定/分歧、来源声明、安全脱敏、零DB/HTTP/DNS/原生凭据、原事实规则保持及CLI不覆盖证据。CI追加一次纯离线质量CLI，保留完整后端/React/Chromium、迁移及旧12/48合同。

初轮74通过/1失败/2临时目录错误：编码名称拼写和本机沙箱临时目录权限；随后Unicode反例发现新语料验证只比较切片，未拒绝超长end（Python切片会截断）。已在新数据验证器加显式区间上界，未改原事实规则。77项复验通过；补充缺失/类型/评分/重现检查后，最终专项89项通过。完整回归及CI以PR记录为准。失败历史保留，不删除断言。

## 9. 后续最短顺序

先由产品负责人/独立评审者审核开发集标签与Rubric，修订须版本化记录依据；再冻结独立留出协议及真实质量成功/严重错误阈值。接着在单独批准的合成模型实验中采集固定Prompt的输出，由此工具做工程检查，再做独立人工语义评审。多轮自由对话、同义重复、用户负担和最终可用事实价值仍需真实观察与人工判断。

本轮不重做基础设施，不改0008–0012、Provider、费用、凭据或页面；不解冻旧实验、不签发预算，不把Oracle报告当收费接入许可。所有真实模型/费用仍需独立授权。保持Draft，不自动合并。

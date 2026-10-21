# B2-c3a Typed Fact Semantic Validation Spike

状态：隔离的合成输入实验、合同候选，等待独立审查。**不是 typed writer，不是事实真实性认证，不授权任何持久化。**

启动基线 `d585f150a37fabdbbd232eb0fa2dfc7a1134ca26`；remote main、fetch 后 origin/main 与基线一致，工作区干净。[基线 CI 39584012688](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39584012688) head_sha 一致，workflow、FastAPI、React、Chromium 全部 completed/success 后才建立分支。

依据 B2C_DESIGN §4、§6–9、§12 及 [c2e 截止预检](FACT_MAINTENANCE_B2C2E_CUTOFF_PREFLIGHT.md)。本轮按方案 A **讨论兼容性**，不是批准生产政策 A，不启用任何截止或工厂。

## 1. 六种责任不能混同

1. **结构校验**：字段、严格枚举/三列组合、版本、长度和整数是否合法；不是语言理解。
2. **窄语言规则**：完整句子是否属于公开、有限的句式/动作对象词表；不判断真实世界是否发生。
3. **用户声明**：调用者显式提交 fact_kind、progress_stage、classification_contract。没有默认 personal/completed，没有自动分类或模型。
4. **文本引用一致性**：quote 与调用者提供 raw_text 的 code-point 区间精确一致，完整句界与全非空白覆盖。它只证明**这两个输入相等**，不能证明 raw_text 就是保存的不可变 user Turn，更不能证明整会话上下文完整。
5. **来源证明与人工核实**：事实归属、保存的 Turn/FC/FS/FCS、分类依据、版本、用户确认或材料审核都不在函数内；不能用建档来源冒充分类依据，也不能凭空生成 classification_citations。
6. **真实事实可信度**：身份、外部证据、发生情况及效果仍未核实。通过窄词法规则不能称为平台认证、完成真实性证明或“分类准确率”。

## 2. 隔离模块与固定候选输入

[`typed_semantic_spike.py`](../apps/api/app/typed_semantic_spike.py) 仅依赖标准库 dataclasses/re；没有数据库、Session、网络、Secret、环境变量、日志、Provider、时钟或随机数访问。不导入任何现有 writer/全局 atomic，不被任何生产 app 模块导入，没有 HTTP 路由、POST/PATCH、factory 或 DTO 升级。

调用 `validate_candidate(payload)`，输入严格 JSON 形状：

```json
{
  "validation_contract": "typed-semantic-spike-v1",
  "synthetic": true,
  "raw_text": "我整理了27条缺失记录。",
  "items": [{
    "fact_kind": "personal_action",
    "progress_stage": "completed",
    "classification_contract": "explicit-typed-v1",
    "quote": "我整理了27条缺失记录。",
    "start": 0,
    "end": 12
  }]
}
```

`synthetic=true` 是实验调用者的声明和误用防护，**不能证明资料确实虚构，也不是生产安全授权标志**。未知版本/额外字段固定拒绝或 unsupported；不接受 memory_state、Session/Turn/Fact ID、related_plan、force 或历史判决参数。没有把该实验版本称为 CO3/append-typed-v1，也不支持 HTTP 协商。

raw_text 1–10000 code points；1–5 items；每 quote 1–500；start/end 必须是严格 int（不接受 bool/float），半开区间。UTF-8 不可编码的孤立 surrogate、NUL 拒绝；不做 Unicode normalization、修复、润色、数字换写或偏移转换。

每项 quote 必须与 raw_text[start:end] 完全一致，并按顺序覆盖原文每个以 `。！？!?` 结束的完整句子。仅允许句间/首尾 ASCII 空白 `空格、tab、CR、LF` 留在区间外，不改 raw_text 坐标；不可省略额外句子、逗号后限制、否定前缀、标点或不确定性。零宽字符不是可忽略空白；英文缩写/小数句界等未实现，不能自动切句修复。

重复 quote、重排、重叠、缺项、尾部未闭合句子拒绝。多项目前只支持 personal_action 的独立完整句；非 personal 的多项批次 unsupported，避免把计划/限制上下文当成已证明独立的贡献。**句子独立不等于语义独立**，后者始终要求事务审核。复合“我编写并测试了系统。”既不接受，也不自动拆两条。

## 3. 三列结构与有限语言规则

结构严格复用已经持久化的组合，但不改数据库：personal_action/completed 或 in_progress；plan/planned 或 in_progress；background、boundary/not_applicable；新类型只接受 explicit-typed-v1。legacy_unspecified/legacy_unknown 搭配 legacy-v0/unclassified-v1 在结构上可识别，但返回 unsupported/legacy_not_classified，**不根据正文重分类旧资料**。

语言候选使用八个动作的有限对象集合：编写、测试、验证、部署、实现、优化、制作、整理。不是任意宾语通配符；对象里的修饰、团队归属、否定、指标不能藏在开放尾部。具体集合固定在代码中，扩充就是合同候选变更，需新反例审查，不能自动继承全局 atomic 的所有正例。

| 用户声明 | 可候选的最小句式 | 保守边界 |
| --- | --- | --- |
| personal_action/completed | 我＋有限动作＋了＋有限对象＋。 | 不从“负责/参与/应该/可能/独立”等词猜职责或完成 |
| personal_action/in_progress | 我正在＋有限动作对象＋。 | 不作为 completed；不凭 memory_state 推进阶段 |
| plan/planned | 我计划＋有限动作对象＋。；另有 GQ08 完整原句的有限特例 | GQ08 的“还没有开始”全部保留，不去掉计划/否定 |
| plan/in_progress | 我正在准备＋有限动作对象＋。 | 仅筹备计划的显式句式；与正在实施动作的声明不能混用 |
| background/not_applicable | 我们/团队＋有限完成句式；有限课程背景句 | 不向个人授予独立职责，不能成为个人成果正文 |
| boundary/not_applicable | 我没有＋有限动作对象（可含过）＋。；有限不知道/不确定/拒答原句 | 只能保留限制，不把否定转成正向，也不把候选变成工作流停止命令 |

已知完整句式与声明冲突时 requires_clarification/declaration_conflict；未知表达默认 unsupported/language_not_supported。假设、猜测、复合动作、指标或引号等已知歧义返回 requires_clarification；不为了获得更多正例扩大语法。这里没有自动返回“正确分类”的接口。

固定冻结 GQ03 原句“我整理了27条缺失记录。”可以候选；团队同句不能声明 personal_action，假设/可能/否定/计划不能声明 completed，27 不能在 quote 中改成 28，也不能附加提升率。
如果调用者把 raw_text 本身一并谎改成 28，本函数没有保存的源可对照，两个版本都可能通过；新增反例明确断言这个边界。真正 writer 必须绑定保存的原话，不能把字符串一致性当作不可变来源证明。

## 4. 结果与后续事务边界

返回不可变 Decision：status、code、structure_valid、citations_valid、可选 item_index、已知校验版本，以及**始终** `truth_verified=false`、`persistence_authorized=false` 和 transaction_review_required。

status 仅为 eligible_candidate / rejected / requires_clarification / unsupported。没有 Fact、operation_id、已保存回执、accepted_items 部分成功列表、确认状态、来源对象或自动推断标签。某项失败则整份输入不是 eligible_candidate；这只是一致的函数结果，**不是数据库原子事务已验收**。

每个结果（包括失败）都列出后续必查：保存的 Turn 身份和完整上下文、Session/Project 归属与鉴权、rejected 当前/历史及语义再主张、来源复用与独立性、事实/关系/分类依据版本、原子性/key/回执合同、真实限权 runtime/数据库约束。函数不能虚构这些检查的通过结果。

R03 的“我测试了3个导出按钮。”、“我测试了三个导出按钮。”、“我验证了3个导出按钮。”都可能匹配有限语法；这正说明改写、近义词或新 Turn **不能由本函数证明新贡献独立**。不接收伪造的 history_safe=true，也不建议换 key/Turn/Session 绕过既有保守阻断。c2e 的反例与生产 BLOCK 原样保留。

## 5. GQ01–GQ20：公开 DRAFT 样本的有限支持矩阵

[`test_typed_semantic_spike.py`](../apps/api/tests/test_typed_semantic_spike.py) 直接读取冻结 dataset.json 的原文，新增预期只针对本 spike，不修改原 reference、Prompt、oracle、质量评测或报告。它们是已公开的 DRAFT 讨论材料，**不是盲测、人工 gold 或真实性评测**。以下选择的某回合能候选，不表示该产品案例的多轮需求已支持。

| 案例 | 本轮选取的原文与声明 | 函数结果 / 未覆盖 |
| --- | --- | --- |
| GQ01 | 第2回合“我编写了借阅状态组件。”/personal completed | 可候选；不从课程或讨论背景推独立责任 |
| GQ02 | 团队订单看板且说不清分工/background | unsupported；不删逗号后不确定性 |
| GQ03 | 整理27条缺失记录/personal completed | 可候选；数字原文保留，无提升率或真实性判断 |
| GQ04 | 登记表单空值提示测试/personal completed | 可候选；不因短小手工工作自动降格 |
| GQ05 | 我们实现了推荐系统/background | 可候选为 background；绝不能变成个人独立成果 |
| GQ06 | 第1回合优化导入页面/personal completed | 原句可候选；不造速度/访问量，第2回合限制仍需上下文审核 |
| GQ07 | 数据量记不清、不想猜/boundary | requires_clarification；不推测数字 |
| GQ08 | 完整计划句含“还没有开始”/plan planned | 可候选；冻结样本**没有后来完成回合** |
| GQ09 | 没有部署过推荐服务/boundary | 可候选限制；不作正向发生事实 |
| GQ10 | 课上学过但没有应用项目/background | unsupported；不从学习推完成 |
| GQ11 | 原文三个完整句各一项/personal completed | 可候选；不拆复合动作，不证明会话内语义独立 |
| GQ12 | 第2回合纠正归属并限制自己职责 | unsupported；不更新旧事实或从纠正中偷截一个肯定片段 |
| GQ13 | 第2回合不想回答、可以跳过/boundary | 仅可候选完整限制句；不触发提问、跳过或停止状态写入 |
| GQ14 | 第2回合编写冲突提示/personal completed | 可候选；不把参加课程自动计成果 |
| GQ15 | 第2回合要求停止核对 | unsupported；停止工作流不在函数职责内 |
| GQ16 | 第6回合制作项目讲解图/personal completed | 句子可候选；不决定轮数/继续提问/停止 |
| GQ17 | 第2回合没有其他任务或内容/boundary | unsupported；不制造新动作 |
| GQ18 | 第2回合缺截图/性能数据且不便找材料/boundary | unsupported；无虚构证据，不改旧信任状态 |
| GQ19 | 每周负责更新比赛报名名单/in_progress 声明 | unsupported；职责频率不够证明当前进行或完成 |
| GQ20 | 我制作了🧪原型图。/personal completed | 可候选，原句 [0,9) code points；额测组合字符/ZWJ/CRLF |

选取输入的结果分布为 12 可候选、7 unsupported、1 requires_clarification；**不是产品支持率或分类准确率**。
GQ08 的后来“我部署了服务。”仅为额外合成来源，分别调用验证，旧计划输入不变；没有继承“学校服务器”、旧确认、材料或关系。两段来源不能在本轮伪装成已持久关联的进展链。
GQ20 额外合成例覆盖 BMP、🧪、e+U+0301、é、👩+ZWJ+💻、CRLF 与首尾空白。错误 UTF-16 end、NFC 替换、截断标点均拒绝；保留原 code-point 偏移，不以视觉字素数代替。

## 6. D4/D5 最小范围及与来源 v3 的兼容

D4 最小可讨论子集：显式声明现有三列、有限语法候选、每项完整句引用；计划和后来动作保留两个独立来源，不支持 related_plan/FactProgressLink，不修改旧计划，不能显示“已完成原计划”。其持久化仍未获批。
D5 本轮仅实验新候选声明与文本是否匹配；不提供 classify、更正现有分类、旧 typed 编辑或 unclassified 自动退级。已确认/有材料的既有事实如何变更、是否清信任/回 pending、历史/FCS/版本如何原子记录，仍需独立批准。

三列结构与 0015 相容不等于满足其 typed 当前/历史/created/来源不变量；本函数没有 DB 行、版本或引用外键，不制造 FactChange.before/after。legacy 原行和缺键历史不推断、不重写、不回填、不增加版本。
未来保存后才能由已审查读取器构建 FactV3/summary2/export2。不能直接把 Decision 包装成 FactV3，不能用 quote 与源一致冒充 classification_citations 或已核实的分类依据；未记录依据仍应按既有 v3 合同如实标记 not_recorded。个人 completed 正文资格还需要既有审核状态，boundary/plan/background/in_progress 不会因通过函数获得正文资格。所有现有读取/前端运行行为不变。

待批准项：可接受的句式/对象覆盖与误拒绝代价、plan in_progress 的筹备定义、团队与限制资料的录入/审核体验、复杂语境澄清、跨句/历史独立性、分类依据来源、D4 关系与 D5 分类变更协议。公开正例不构成生产语义安全批准。

## 7. 真正 typed append 前的门槛与持续 BLOCK

须另行审查：R03 全入口 rejected 当前/历史/旧来源及语义再主张的保守政策；同会话/项目和真实不可变源绑定；1–5 all-new/整批原子性与 FC/FS/FCS/Turn/CO 双射；CO3 与旧版本双向隔离、跨路由 key 冲突、权限优先、GET-only 恢复、崩溃/并发/过期/墓碑；受限 LOGIN/owner/ACL/admission、来源与历史完整性、迁移失败回滚及危险 downgrade；D6 剩余前端/读取/写入/恢复链；旧 writer A/B、删除与 worker 收尾分别批准。

当前词法通过不能替代上述任一门槛。R03、D4/D5 正式批准、D6 剩余、D8、typed writer、生产角色、读写 factory、真实 Provider、付费和部署全部继续 BLOCK。0001–0015、原 writer/CO1/CO2、FactView3/summary2/export2、02/03、typed-read、frozen Prompt/MiningContext/评测均不修改。

## 8. 实际验证和未覆盖项

纯函数专项：`./.venv/Scripts/python.exe -m pytest -q tests/test_typed_semantic_spike.py`：128 passed，涵盖结构/合同、数字与指标篡改、假设否定团队不确定性、完整句/全覆盖、无拆分与部分返回、GQ08 两份源、GQ11、GQ20、R03 未解决证据、确定性/输入与结果不可变、标准库依赖及生产无导入。没有新 skip/xfail，首轮127通过后只加强 JSON key 类型、递归隔离检查与“raw 也被改写”的限制证据。

完整回归命令从 apps/api / apps/web 执行，明确使用 loopback15487 合成测试库、随机 Schema 和既有真实限权夹具，不访问生产凭据/数据库；函数专项本身不需要数据库：

- `python -m pytest -q -ra`；`npm run test -- --reporter=dot`；`npm run build`；`npm run test:e2e:types`。
- `PATHWISE_E2E_CHANNEL=msedge npm run test:e2e`（本地真实 Chromium 内核 Edge；CI 为 bundled Chromium，原 timeout、retries=0 不变）。
- `python ../../scripts/check_isolated_migrations.py`。
- `python ../../scripts/check_m12c2_contracts.py`；`python ../../scripts/check_s03b_output_contract.py`（冻结12/48）。
- `python ../../scripts/evaluate_mining_quality.py --outputs ../../docs/evaluation/quality-v1/oracle.outputs.json --output-dir ../../.e2e/c3a-quality`（DRAFT、人审未完成、真实质量 null）。
- `python ../../scripts/run_offline_evaluation.py --profile 0 --output ../../.e2e/c3a-mock.json`（无供应商请求/费用）。

完整回归的实际数量、平台 skip、环境清理、精确 HEAD 与最终 CI 记录在 Draft PR；不把尚在运行的检查写成成功。
未覆盖：任意自然语言、英文/复杂句界、嵌套引语/指代、一般数值语义/同义识别、完整多轮产品工作流、真实世界真伪、saved Turn 绑定/权限/历史/rejected/关系/回执/数据库事务与 typed writer。它们没有被算作本函数通过保障。

仅交付独立 Draft PR。停止等待独立审查，不 Ready/Merge/Deploy，不自动开始下一阶段。

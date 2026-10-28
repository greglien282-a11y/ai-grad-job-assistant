# M2.5 · 离线 AI 建议质量与用户审核候选

本候选从已核验 M2 main `6284faccb446f0d37a0c3896d80f2a30ee346c29` / tree `8891daa354971dfc21ff8541618247e651df6d8f` 建立独立分支，最终以一个 Draft PR 交付。#68 已合并的本地工作台继续使用原准入和恢复合同；不重新打开五个旧产品分支。最终 HEAD、精确 CI、测试命令和截图以该 Draft PR 及本地交接报告为准。

## 实际新增能力与责任边界

- `research/m25_quality`：60 组公开合成案例、冻结清单、严格 Python 合同、离线候选读取、分维度诊断及人工审核声明文件校验。
- `apps/web/src/features/ai-suggestions`：同版 TypeScript 合同、关键词 / Mock 适配器和 `/resume-lab` 内独立默认关闭的候选审核区。
- 路线图和产品摘要校准，以及未来 [Provider 审批包](M25_PROVIDER_APPROVAL.md) / [用户研究任务脚本](M25_USER_RESEARCH_PREPARATION.md)。

没有真实模型输出、外部 AI API、密钥读取、上传、数据库保存、正式 FactV3 / CO3 / 分类依据写入或认证。接受一条原句最多改变本地用户草稿的选择和顺序；任意变化的改写、新主张、证据或能力缺口均进入待核对区，不能通过接受按钮晋升为事实。正式业务、生产构建、迁移、ACL、冻结 Provider / MiningContext / 12/48 / quality-v1 合同均不因本候选而改变。

## H · 案例、冻结和评估维度

`cases-v1.json` 包含 60 个不同的合成案例，覆盖课程 / 无项目 / 无实习、无量化指标、团队与个人责任、计划 / 进行中 / 否定 / 未知、原文夸大、必备 / 加分 / 冲突 / 模糊 JD、视觉 / 后端 / 测试岗位迁移、同义 / 缩写 / 中英文、Unicode / Emoji / 组合字符 / ZWJ / CRLF、证据不足和双岗位优先顺序。没有真实身份、联系方式、凭证或求职者资料。

案例、参考观察和风险标注均由 Codex 草拟，`label_status=draft_unreviewed`，`human_review=null`。`cases-v1.manifest.json` 固定整库及逐案例的 canonical SHA；当前 60 案例内容 SHA 为 `78715182dbe9a6ee0fab08fbe740993d8ee190aaabe2eb5bbdfa80f8d66f2192`。这是**内容冻结**，不表示标签经人工批准，更不是金标准。修改案例必须出新版本 / 清单，不能覆盖原始失败以制造通过结果。

评估器分别输出七个维度的 `pass` / `fail` / `uncertain` 计数、规则名、候选 ID、引用及详细理由：

1. `jd_requirements`：给定 JD 引文绑定；要求是否提全、分类是否正确仍需人工判断。
2. `association`：有限词表交集的观察；没有交集也不能推导没有语义关系。
3. `source_fidelity`：来源图、全文快照、code-point 原句 / 区间及岗位绑定。
4. `fabrication_risk`：已知新增数字 / 保护词反例；未触发不代表没有编造。
5. `state_preservation`：原句保留，以及有限否定 / 计划 / 团队等限定词丢失反例。
6. `usefulness_explanation`：理由和实用性保留人工审核，不能自评为优质建议。
7. `clarification`：新主张、改写、风险上下文的未证明状态与人工澄清需要。

合同、来源错位和已知硬性反例不能被软性平均分抵销。整例有硬失败即 `fail`；图检查通过但语义 / 实用性未审，仍为 `uncertain`。`accuracy` 和 `fact_error_rate` 固定为空，`truth_verified=false`、`persistence_authorized=false`。

## 可重复执行与现有基线的区别

在仓库根执行，输出路径必须是尚不存在的文件，以免覆盖证据：

```powershell
python research/m25_quality/quality.py verify
python research/m25_quality/quality.py baseline --output .e2e/m25-baseline-new.json
python research/m25_quality/quality.py evaluate --input .e2e/m25-baseline-new.json --output .e2e/m25-baseline-report-new.json
python research/m25_quality/quality.py evaluate --input research/m25_quality/fixtures/deliberate-negative-candidates.json --output .e2e/m25-negatives-report-new.json
python -m pytest research/m25_quality/test_quality.py -q
```

`evaluate` 的退出码区分 0（诊断完成且无已检出硬失败）、1（已保存含硬失败的诊断）、2（文档合同无法处理）。退出 0 也可能全为 `uncertain`，不能当作质量通过。CI 对保留的负例应验证其预期失败及不确定项，不修改冻结答案消除它们。

标准输入为 `m25-candidate-batch-v1`，`cases` 按冻结案例 ID 绑定完整 `local-suggestion-candidates-v1` 包。可以传入独立离线候选，不需要生成器或网络。未知案例、错误快照、重复键、缺少字段和未知版本不静默修复 / 降级。报告同时保留相同案例的有限关键词基线，比较候选数和硬检查诊断，不输出模型质量排行榜。

离线基线复用现有有限关键词词表，选择完整原句、记录字面交集；不进行真实模型生成。它可以验证合同与诊断流程的自洽性，不能作为独立质量证据。UI 适配器仍复用工作台的现有 `suggestions()` 及最终准入，不用离线评估结果取代打印限制、拒绝或能力缺口校验。离线基线和 UI 的角色 / 准入目的不同，不宣称二者排序输出逐项等价。

已保存的真实离线输出位于 `research/m25_quality/reports`：基线 60 例全部为语义质量 `uncertain`；故意构造的 7 条负例中 5 条被有限规则判为 `fail`，2 条仍为 `uncertain`。后两条英文计划 / 团队反例说明窄中文词法有遗漏，不能称其安全，也不能推算为模型事实错误率。原始反例单独保留，生成器和诊断规则不能互相给出真实性背书。

## 人工审核、争议与金标准

未来审核人员可在独立 sidecar 中固定 corpus SHA、审核者声明、证据引用、理由及 `agree` / `dispute` / `uncertain`；`quality.py review --input ...` 只检查结构 / 版本。`identity_verified=false`、`gold_authorized=false`，客户端填写姓名不证明真人身份、独立性或批准。

应先隐藏候选生成来源让审核人员逐项核对，再记录不同意见；保留双方理由，不能多数投票自动删除严重反例。需独立产品负责人确认审核人员与版本、争议解决和冻结政策后，才可讨论人审金标准。当前没有已审核参考库，也没有模型准确率结论。

## I · 运行实际候选审核界面

在 `apps/web` 执行：

```powershell
npm.cmd ci --no-audit --no-fund
$env:VITE_PATHWISE_JD_LAB='synthetic-v1'
$env:VITE_PATHWISE_AI_SUGGESTIONS='offline-v1'
npm.cmd run dev -- --host 127.0.0.1
```

打开 `/resume-lab`，只使用本轮公开合成材料：导入并核对原文 → 分析合成 JD → 生成关键词对照或离线 Mock → 核对原始经历、JD 引文、候选变化与新增主张 → 接受原句顺序 / 拒绝 / 保留编辑到待核对区。风险 Mock 明确列出无来源的 Docker 部署、独立责任和 30% 数字，必须停留在澄清 / 阻断状态，不进入打印。

外层仍要求现有 DEV + JD 实验门禁，内层还须 DEV + `VITE_PATHWISE_AI_SUGGESTIONS=offline-v1`；默认值和生产构建不能启用。不是只隐藏一个付费按钮：代码只有同步本地规则、Mock 和本地 JSON 解析；未知 / 外部模式直接拒绝，没有 SDK、key、fetch、网络 fallback 或后台任务实现。

本次合同包括：岗位 ID、来源快照、JD 快照与原文条目、完整段落 / JD 引用、展示优先序、可空改写、理由、新增主张、证据缺口，以及规则 / Mock / 离线输入的来源标识和版本。展示优先序不是匹配分数，候选自报的模型 / 规则标识不证明身份。

严格 TypeScript / Python 解析器拒绝未知 / 缺失字段、未知版本、伪造来源或 JD ID、跨来源、越界、非整数或错误 Unicode 引文、重复身份 / 配对、裁剪原句及过期岗位快照。载入失败先清空旧候选，没有部分安全结果。元数据没有产生认证；JSON 中的合法字段亦不是签名。

来源快照保留导入文本的原始 code-point 范围。手工声明追加在**本地审查文本快照**，保留 `user_manual_statement` 身份与独立范围；它不成为原文件原话、数据库 User Turn 或分类选择事件。不用文件指纹替代文本真实性。候选绑定当前角色 / JD / 来源；切换角色或改变内容、选用和风险状态后需重新生成，不能串用旧建议。纯外观和复习回答不改变原始来源依据。

原句应用还要重新运行当前准入、角色绑定、JD 冲突、自评缺口、拒绝和来源一致性校验；审核时显示过的绿标不能豁免点击时检查。编辑区只在当前页面内存保存，刷新清空，不进入 v1 / v2 / v3 草稿文件或打印，不提供认证 / 正式写入按钮。相同本地候选的拒绝记录不因重新生成自动解除，但它不是不可变完整历史，不解决 R03 的同义、数字和跨入口复活。

## J · 产品状态与下一步

M2 已证明本地导入、多岗位、原文核对、打印和恢复可运行；没有证明真实 AI 或真实用户效果。本轮进一步提供可检查的候选和离线失败证据，不做正式上线声明。`ROADMAP.md` / `PRODUCT_BRIEF.md` 已按这三个层次校准；历史 G0 机器可读检查点不为本任务改写或假装启用自动恢复。

下一步先独立人工审核案例和本 Draft，再批准是否开展少量合成真实模型试验，最后才讨论真实用户研究。研究脚本定义首次价值、步骤 / 用时、第二岗位重复、依据理解、发现不真实改写和打印 / 恢复成功；当前无参与者或满意度结果。模型、地域、隐私、预算、超时和失败停止必须单独批准，既有费用硬上界 BLOCK 不因提案消失。

## 验证证据与保留 BLOCK

候选专项需覆盖合同正反、共享冻结 fixture、过期 / 跨角色绑定、严格 JSON、Mock 风险、拒绝 / 编辑、原句应用、生产关闭、零上传 / 零持久化；运行全部 React、TypeScript、构建、真实 Chromium、12 组合成旅程及受影响的正式后端 / PostgreSQL / 迁移 / 12/48 / quality / 零费用 Mock。真实执行数量、平台 skip、失败和精确最终 HEAD CI 在交接 / PR 固定记录，不把本说明中的命令当作执行结果。

未修改正式 writer、迁移、数据库权限、FactV3 / SummaryV2 / ExportV2、旧操作回执和模型冻结合同。G4、T2/T3、共享 CO 键域、R03 全入口语义防复活、D4/D5、D6 剩余和 D8 继续 BLOCK。真实 Provider 调用、正式 typed writer / CO3、生产数据库、部署、开放真实用户、Ready 和 Merge 均未授权。

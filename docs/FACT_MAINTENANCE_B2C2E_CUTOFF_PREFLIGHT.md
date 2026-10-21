# B2-c2e Legacy Writer Cutoff Preflight

状态：兼容政策、风险验证及合同冻结**候选**。只新增测试和本文；不启用截止，不启用 typed writer。等待独立审查与用户逐项授权。

基线 main：`957d66c5b18ab9f0569182372e194d64f1fe2ac2`。
实施前 remote main、fetch 后 origin/main 均与该 SHA 一致，工作区干净；[基线 CI 39542680283](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39542680283) 的 head_sha 相同，workflow、FastAPI、React、Chromium 均 completed/success。

本文复核的是此提交的实际代码，不把 [c2d 建议](FACT_MAINTENANCE_B2C2D_HANDOFF.md) 当成已启用政策。依据仍为 B2C_DESIGN §4.2、§7、§9、§10、§12 和 c2a/c2b/c2c/c2d；不改冻结合同。

## 1. 四类能力与不变量

1. **N：新业务命令**。新建 Session/Turn/Fact、修改/审核 Fact、发起新 Mining、问题处理。新命令有新效果；拒绝必须在对应业务效果前发生。创建 Session 本身不等于创建 Fact，也不等于语义分类。
2. **R：已有结果恢复**。有效原 key 的 GET recovery、POST 同键合法重放、operation GET。只返回原合同的既有结果，不改 key/有效期、不再执行。不要让未来 cutoff 提前拦截这些请求，也不能绕过原认证、过期、删除或合同版本检查。
3. **M：删除、结束与状态管理**。整会话 DELETE 是现有合法副作用，不能当成新增事实；end/stop/question 各有门禁与版本规则。不能在统一“禁写”中顺手取消删除能力，或把结束当成无效果 GET。
4. **W：已受理 worker 收尾**。claim/build_context/complete/fail 有不同阶段；stale、failed、unknown 和零候选完成可能产生 Run、问题、assistant Turn、revision 等效果。不给新 Fact，不意味着没有业务副作用；阻止后续新命令也不能抹去已发生的运行状态或费用记录。

共同边界：权限先于 typed 信息披露；当前 typed 或历史 typed 不能靠洗回当前标签重获旧合同。已有 v1/v2 key、来源、JSON、版本、revision、信任状态及恢复语义不能被迁移推断重写。运行 factory 默认关闭的接口仍关闭。

## 2. 实际入口—能力—副作用矩阵

源码链接指向本轮基线代码。L 表示 `require_legacy` 的**整个 Session**当前/历史门禁；F 表示仅目标 Fact 范围。`unclassified-v1` 也不符合旧 legacy 三元组，不是旧合同逃生口。

“零效果拒绝”不表示无锁：旧 v1 GET 常有 Session FOR UPDATE；CO recovery 则明确 REPEATABLE READ READ ONLY。下面的顺序是业务检查顺序；HTTP 的输入解析、Bearer/proof 和独立 runtime admission 还会先行拒绝无效请求。

| 入口 / 实际代码 | 能力、合同 | 新增 legacy-v0 Fact | 当前/历史 typed 门禁 | 鉴权、锁、版本、key 顺序与零效果点 | 已成功结果恢复 | 合法副作用 / R03 |
| --- | --- | --- | --- | --- | --- | --- |
| [create_session](../apps/api/app/experience_api.py#L117)、[create_experience](../apps/api/app/facts.py#L35) | N，旧创建 v1 | 不直接创建；为后续 legacy Fact 提供新 Session | 无已有目标，无 born-contract | 有 key：proof → advisory lock → 已有创建回执认证/匹配；否则创建 Session/Project/初始 Turn。现在没有 cutoff 拒绝点 | 同 key POST 201、GET 创建 recovery 200，返回旧 CreatedSession；后来 typed 不使回执失效 | 新 Session/Project/Turn/receipt；无分类。新 Session 仍是残余 legacy 路径 |
| [add_turn](../apps/api/app/experience_api.py#L150)、[facts.add_turn](../apps/api/app/facts.py#L60) | N/R，v1 | 否 | 新命令 L；旧 Turn replay 无 L | key lock → Session 认证锁 → freshness → 旧 receipt 匹配优先；新请求 L/已消费输入检查 → INSERT。L 在 Turn/revision 前拒绝 | 旧 TurnView 可在混合 Session 恢复，201 + replay header，不新增 Turn | 新 Turn/revision；新来源不能证明与 rejected 语义不同 |
| [add_fact](../apps/api/app/experience_api.py#L171)、[facts.add_fact](../apps/api/app/facts.py#L108) | N/R，v1 | **是**，pending/v1，默认 legacy 三列 | 新命令 L；旧 replay F | key lock → Project/Session 认证锁 → key/receipt；新请求 L → 输入/来源/rejected 检查 → Fact/FS/FC。typed 在新效果前拒绝 | 同 key 201 返回原 Fact 的当前合法 v1 投影；混合 Session 的 legacy 目标可恢复；目标 typed/历史 typed 时 F 拒绝 | Fact/FS/created FC/revision；精确来源保护不覆盖语义改写 |
| [Fact PATCH](../apps/api/app/experience_api.py#L196)、[change_fact](../apps/api/app/facts.py#L134) | N，edit/confirm/reject/verify_material/set_memory | 不新增 Fact；legacy 目标仍 legacy | L，包括只改旧 legacy Fact、但同会话另有 typed 的情形 | 找 Fact → Session 认证写锁 → refresh → L → expected_version/状态/正文/来源 → 修改。无 operation key，不能把重试当幂等 replay | 没有专用 PATCH receipt；不确定结果只能核对读取，不能换 expected_version 自动重发 | Fact/version/FC/evidence/revision；确认/核实不推断完成，不分类；legacy 计划仍可入确认正文 |
| [close_session/end](../apps/api/app/experience_api.py#L211)、[end_session](../apps/api/app/facts.py#L216) | M，v1 | 否 | L；已 ended 返回 SessionView 仍 L | Session 认证锁 → active 时 end 内 L → 状态写入；响应 SessionView。typed active 在写前拒绝 | 非 CO receipt；重复 end 走既有状态与投影合同 | Session ended/revision。与删除不是同一能力 |
| [DELETE Session](../apps/api/app/experience_api.py#L228) | M，v1 合法整会话删除 | 否 | **没有 L** | Session 认证锁 → legacy/Mining receipt 擦除 → DELETE/级联/CO 删除语义；须数据库 DELETE 权限 | 删除后的 legacy/CO key 返回原 410 墓碑语义，不得自动创建 | 明确有删除和回执墓碑效果；不可只因 typed 存在就擅自取消此能力 |
| [CO v1 correct](../apps/api/app/fact_maintenance.py#L135) | N/R，CO1 explicit-target-v1 | 否，修改目标旧 Fact | 新命令 L；旧 replay 无 L | 独立受限 admission/proof → key lock → 旧 CO replay 优先 → Session 认证锁/L → active/Run/revision/target version → 原子效果 | POST replay 200；GET recovery/operation 旧 v1 投影。仍认证、同版本、同 payload、未过期 | 新 Turn、编辑 FC/FCS/CO、Fact version/revision；same_atomic_claim 窄身份，不解决跨入口 R03 |
| CO v1 withdraw（同 apply） | N/R，CO1 | 否 | 同上 | 同上；原子撤回及来源保留 | 同上 | rejected、FC/FCS/CO、撤回 evidence 指针语义；不是删除或语义去重 |
| [CO v1 resolution](../apps/api/app/fact_maintenance.py#L157) | N/R，CO1 resolution | 否 | 新命令 L；旧 replay 无 L | 旧 key replay 在前；新请求 Session/L/gate 后 parent 行锁、parent 未解决/合同/冻结输入、selected target/version/revision | 原 child 回执可恢复；不可重新执行冻结父输入或生成新 child | 使用原输入，不新增假澄清输入；FC/FCS/child CO 等；不能把旧 parent 强转 typed classify |
| [CO v2 append](../apps/api/app/fact_append.py#L69) | N/R，CO2 append-batch-v1 | **是**，1–5 all-new pending/v1 legacy Fact | 新命令 L；旧 replay 无 L | proof/key lock → 旧 CO2 replay → Session 认证锁/L/gate/revision → 原句窄语法/D3/去重 → 一笔事务。拒绝时 Turn/Fact/CO 零写 | POST 200/GET-only 恢复原 v2；跨 v1/v2 key 固定合同错误，不当新请求执行 | Fact/FS/FC/FCS/Turn/CO；D3 当前/历史曾 rejected 整会话保守拒绝，有可用性代价；不是 R03 语义解决 |
| [Mining reserve](../apps/api/app/mining.py#L115) / start | N/R，旧 Mining、extractive-v1 / context-v2 | reserve 本身否；后续候选可能是 | 新请求 L；已有 receipt 先返回 | provider 安全准入/proof → key advisory lock → capacity 行锁 → Session 认证锁 → 已有 receipt/tag → L → active/revision/source/capacity/retry → reserve | replay 旧 Run，不再 execute Provider；不凭新 key 重复已保存回答 | 新 Turn/链接/Run/receipt/Session mining 状态/revision；准入内 lease cleanup 可收尾其他过期 Run。拒绝事务回滚；R03 改写仍可被 v1 提取 |
| [Mining claim](../apps/api/app/mining.py#L205) | W | 否 | build_context 有 L；状态/lease/revision 分支在其前 | get_run Session 认证锁 → reserved/lease/status/revision；过期→unknown、变化→stale；否则 running→build_context。context 拒绝使本事务 running 回滚 | 不是新 key/replay，也不授权重推理 | 状态收尾可能真实写入；与新 Fact 门禁必须分开 |
| [build_context](../apps/api/app/mining_context.py#L103) | W，只读构造冻结上下文 | 否 | L | 调用方先锁及认证；函数再 L，读边界/来源/预算裁剪。不是独立 HTTP 授权入口 | 无回执，无写入 | 不修改冻结 Prompt/MiningContext；不得绕过以续跑 typed |
| [Mining complete](../apps/api/app/mining.py#L255) | W，旧完成事务 | 候选通过 add_fact 时**是** | 候选落库 L；**没有函数级全路径 L** | 认证 Session 锁 → state/lease/status/revision（unknown/stale 可能写）→输出校验/提交期限 →候选去重/rejected guard/add_fact L →问题/assistant/Run 完成 | 不接受新 key；重复已终态调用无新效果 | 正常 typed 加入改变 revision，使在途 Run stale；匹配 revision 的 owner 合成状态下，候选被 L 阻止，但零候选可创建问题/assistant Turn 并 complete。不能把后者说成正常 typed writer 可达 |
| [Mining fail](../apps/api/app/mining.py#L245) / execute 异常收尾 | W | 否 | 无 L | get_run 认证锁 → ACTIVE 判定 → failed/unknown/error_code；Session 已删除时不重建 | 无新执行；只对原 Run 收尾 | 真实状态副作用，不写新事实/付费账本。真实 Provider 授权仍关闭 |
| [Mining receipt GET / get_run GET](../apps/api/app/mining_api.py#L75) | R，旧 MiningRunView | 否 | 无 L | recovery 认证→receipt→Run 归属；by-id get_run(lock=False)；不登记新 key、不清理期限 | 原 Run 可读；旧 POST replay 在 reserve 前部匹配；状态不确定不意味着可推理重试 | GET 无业务写入；不是新版 FactView 兼容或事实正文资格 |
| [CO recovery / operation GET](../apps/api/app/maintenance_api.py#L70)、[maintenance.recover](../apps/api/app/fact_maintenance.py#L93) | R，CO1/CO2 各自固定投影 | 否 | 无 L，保留旧合同恢复 | 独立 admission；REPEATABLE READ READ ONLY；row 查找/可用性、Session 认证/归属、合同版本、key 有效性。by-id 无 key，不凭此延长期限 | 不写、无 advisory lock/Provider；GET 与同键 POST 都不能解释为另一个 CO 版本 | 个别 availability/deleted 错误先行属于既有回执合同；不得统一改成 typed 信息响应 |
| [旧手工 UI](../apps/web/src/App.tsx)、[experience adapter](../apps/web/src/lib/experience.ts) | N/R/M，v1 消费者 | 可间接 create/add_fact | 服务端 L/F；adapter 精确升级错误锁存 | 用户显式动作；原 Session storage/操作 key 恢复；客户端不是授权边界 | 原创建/Turn/Fact 恢复合同不变 | 纯 legacy 新增/审核仍可用；不是完整 typed 工作台，也不宣称拥有 02/03 的全部交接体验 |
| [02/03](../apps/web/src/features/discovery/useDiscovery.ts)、[workbench](../apps/web/src/features/discovery/DiscoveryWorkbench.tsx) | N/R/M，旧 UI，c2d 安全交接 | 可间接 Mining 新 legacy Fact | 服务端门禁 + 收到精确 upgrade_required 后 UI/adapter 锁存 | 创建/Mining key 原证明/显式提交；GET 恢复优先；升级时清正文/来源/计数/按钮，原 key 保留，不自动重发 | 升级后本页面不再调用旧接口，原记录仍可按原合同独立恢复；这不同于服务端删除回执 | 显式无凭证 `/typed-read` 链接；不注入 storage、不 fallback；不能撤回错误前已发出的请求 |

补充边界：`offline_evaluation.py` 是合成离线测试 harness，复用旧 facts 服务；不是另一条已授权生产 writer。直接 owner SQL 是夹具/迁移能力，不能被声称受应用 Bearer 门禁覆盖。本轮不扩大任何 runtime ACL。

## 3. 可重复的实际风险与兼容证据

新增 [`test_cutoff_preflight.py`](../apps/api/tests/test_cutoff_preflight.py)，47 个真实 PostgreSQL 场景。不使用 xfail 把未实现的目标伪装成通过；当前允许的行为被明确断言允许。

| 实际证据组 | 断言 / 含义 | 不是本轮保障的内容 |
| --- | --- | --- |
| legacy 正常创建、edit、confirm、verify、恢复 | 独立受限 LOGIN 从 HTTP 创建，旧 Fact 三列仍 legacy；原 key replay 当前合法结果，全表摘要零变化 | 未分类的未来计划不会因用户确认/材料核实变成 completed；此例计划正文**仍会出现** |
| 11 类新命令 × 当前 typed / 仅历史 typed（22） | turn/fact/PATCH/close/correct/withdraw/resolution/append/reserve/stop/question：外 token 404，无 typed 信息；合法 token 409 精确升级码，所有表含账本/回执均不变，Provider=0 | 不是全局 writer 截止；不包括 DELETE 与所有 worker 分支 |
| creation/Turn/Fact 旧 key × 两种 typed 状态（6） | 同键合法 replay 仍 201，创建 GET 仍 200；结果一致，变更 payload 409，无额外业务效果 | Turn/Fact 没有被虚构出专用 GET receipt 路由；Fact 返回原目标当前投影，不保证字面冻结旧版本 |
| CO correct/withdraw/resolution/append 回执（4） | typed 加入后 POST replay 200、原 GET 投影正确；v1/v2 跨路由 GET/POST 同 key 409 conversation_contract_mismatch，全表不变 | 不重签 key、不绕过 expiry、无 CO3/typed 结果转换 |
| 已完成 Mining 回执（1） | typed 加入后 GET/POST 同键返回原 Run；payload mismatch 拒绝，Provider 总调用保持原一次 | 不增加 inference，不自动续租/重试不确定 Run |
| DELETE 当前/历史 typed（2） | 外凭证 404；撤销本测试角色 DELETE 后 503 且零效果；恢复测试 ACL 后 204，目标 Turn/Fact/FC/FS/FCS 删除、CO 与创建回执原 410 墓碑、外 Session 保留 | 没有修改生产 DELETE；这是合法例外证据，不是当前漏洞已修复 |
| worker 八种分支（8） | claim/complete stale、过期 unknown、fail/unknown 可写 Run；原 Fact/FC/FS/FCS/CO/费用表不变；context/候选 typed 拒绝事务零效果；空候选同 revision 合成状态允许 assistant/问题/完成 | 同 revision 由 owner **显式安排**，不是证明生产可通过正常 claim 到达；没有绕过 Provider 或冻结上下文 |
| R03 手工 / Mining / append（3） | 旧 rejected“我测试了3个导出按钮。”以新 Turn“我测试了三个导出按钮。”在旧 add_fact 和 v1 Scripted Mining 中可新建 pending legacy Fact，旧 rejected 保留；同句 append 合法窄语法后 D3 409 整笔零写 | 不能宣称语义去重。Scripted 成功是合成行为，不是对正式模型质量的判断 |

R03 的代码根因：`maintenance_guard.rejected_contribution` 只选**当前 rejected Fact**，比较其当前/历史正文和原始 Turn 的精确复用，不做语义等价；改写并用新 Turn 可绕开。其“历史正文保护”不等于“扫描所有历史上曾 rejected 的事实”。append D3 额外扫描 FC before/after 曾 rejected，因而会保守阻断同会话其他无关合法新增，牺牲可用性；也不使其他入口自动获得同等保护。

已有 `input_consumed` 防 CO 输入精确再使用；同样不是跨入口语义身份检测。方案 A/B 都不能单靠截止创建修复 R03；该风险继续生产 BLOCK。独立修复建议是另行审查全入口 rejected 身份、来源与保守回退协议，同时明确误阻断与用户可用性代价；本轮不改 guard/评测。

## 4. A / B 可实施方案比较与主张

| 选择 | A：向后兼容优先 | B：集中截止旧新建入口 |
| --- | --- | --- |
| 新 Session | 旧 v1 继续；未来 typed 走独立版本化创建，依赖完整 typed writer/UI/恢复链 | 用户另行批准的切换点后，**未命中合法旧创建回执**的 v1 新建零效果拒绝；不默认开放替代 writer |
| 存量 pure legacy | 原合同创建后续 Turn/Fact、编辑审核与原 key 恢复 | 默认候选同 A；若要求冻结存量，须第三项单独政策，不能藏在“停止新建”中 |
| 当前/历史 typed 新旧事实命令 | 复用已存在全会话门禁；不得允许旧 writer 新建事实/编辑 | 同 A，不依赖创建截止来保护 typed |
| 恢复 | 保留原 proof/key/expiry/版本/权限/删除语义 | 同 A，必须先认证并匹配原回执再判定“新建”；不能按请求方法把合法 POST replay 一起禁掉 |
| DELETE / end / stop / worker | 按四类能力分别保持既有合同，后续另行批准 | 同 A；集中入口开关不能冻结 drain、取消删除或伪造未知结果 |
| 可用性代价 | 旧客户端持续可用，但 legacy 风险持续，新数据不保证 typed | 旧手工/02 新用户无法新建；若 typed 链未开放就出现真实功能空档，必须明确人工交接，不循环重试 |
| 残余 legacy-v0 | 旧新建、存量 add_fact、append v2、Mining 生成；确认/核实不分类 | 存量会话的 add_fact、append v2、Mining 仍可产生新 legacy Fact；切换前已成功创建的空会话也可能稍后新增 |
| 迁移需要 | 本轮不需要；未来 born-contract/typed 创建需前向迁移候选 | 只有 v1 创建拒绝不必推断/改写旧数据；若采用持久 cohort/born-contract 或切换审计，则另加前向迁移与显式合同，不偷改 0001–0015 |
| 误阻断风险 | 把“typed session”状态推广到 legacy 目标旧回执、删除或收尾会误伤合法操作 | 在旧回执匹配前判 cutoff、把暂时网络失败/未知 key 当可新建、切换竞态/自动换键，都可能丢恢复或重复建档 |
| 回滚 | 关闭未来新 typed 准入，保留已建档的 typed 不可变含义和原恢复 | 是否重新允许 v1 新建需用户批准；不能自动回落 A，更不能将 typed Session/Fact 洗回 legacy |

**主张：采用 A 作为兼容合同冻结的推荐起点；将 B 保留为未来可独立批准的新建策略。** 这不是授权今天切换，也不声称 A 已完整实施：删除、在途收尾、旧回执的例外必须先按本文保留并验证。不要为了获得“所有新数据都 typed”的口号提前选择 B；只截新 Session 对存量新事实无此保证。

未选择生产切换日期、环境变量或 cohort。是否在 typed 完整替代链可用前选择 B、是否 grandfather 存量、是否允许重新打开 v1 新建，都需要用户单独决定。

## 5. 未来 born-contract / typed 创建协议候选（未实现）

以下是提交未来评审的最小固定协议方向，不是本 PR 新 API、Schema 或运行开关：

1. **持久 born-contract**：候选会话级不可变标识 `legacy-session-v1` / `typed-session-v1`；字段名和前向 revision 待批准。它描述**出生的 writer 合同**，不取代 Fact 分类三列，不复用 CO.progress_stage/memory_state，不因当前 Fact 标签或正文而变化。
2. **存量归属**：如果未来增加该列，已存在 Session 只可按明确旧创建合同标记 legacy-born，不能由文字推断 typed、不能改 FC JSON、补 FC、增加 Fact.version 或重置 revision。legacy-born 可能后来含 typed；因此准入必须同时看 born-contract 和不可抹去的 typed 当前/历史，不能只看出生标签。
3. **显式 typed 创建版本**：候选独立 `POST /api/v2/experience/sessions`，`creation_contract_version=2`，严格独立 DTO/响应。这里的“2”是**创建合同**，不代表 CO2 append 或 FactView3；不能把旧 v1 raw_input 客户端隐式升级。正式字段及版本须完整评审，本文不开放空壳 typed Session 作为 writer 绕行入口。
4. **原话/效果原子性**：保留用户 raw_input 原文。创建 Session、Project、首个 user Turn、born-contract 和创建 receipt 同事务；无自动 Fact 分类、确认或推理。只有整条 typed writer/来源/读取/恢复链已获批且可用，才允许启用该创建能力；现在全部关闭。
5. **证明与幂等隔离**：候选独立 key kind `create_typed_session_v1`、固定 creation version/scope 和 canonical body tag；具体编码待安全审查。不得把旧 create_session proof 在新路由重新解释。同 key 合同冲突不能新执行：无效 proof 按原认证错误，已认证且能证明的版本冲突按固定冲突码；不泄漏其他 Session 或回执是否存在。有效原回执仍按原合同/原有效期恢复，不清理/换键/延长；GET 不产生 key 或推理。
6. **首个效果前决定**：未来 cutoff 对新请求的判断与创建事务/收据匹配有明确线性化点。先验证请求、匹配合法旧 receipt；无 receipt 才在首个 Session/Turn/receipt INSERT 前检查有效政策。切换并发请求只属于一个明确政策版本，不能先创建半会话再返回“不支持”。锁方案与持久政策审计需未来真实两连接/崩溃测试证明，不在本文假称已实现。
7. **响应与旧客户端**：typed 响应须显式 creation contract、born-contract 及新版读取合同，不混用旧 CreatedSession。无 query/Accept 自动协商、无 URL Bearer，无旧 storage 自动注入新版，无旧 API fallback。未知版本/Schema/ACL/政策状态固定 fail-closed，不能悄悄建立 legacy 会话。

这项 born-contract 的前向迁移会改变持久意义与准入协议，必须先审查后实施。本文没有为 Session 加字段，没有设置 enum/DEFAULT，也不把合成 typed 夹具当成 typed 创建产品。

## 6. 旧客户端拒绝、显式切换、灰度和回滚

未来 B 的新拒绝码候选为 HTTP 409 `legacy_session_creation_closed`，与现有三个 typed 升级码、401/404、context/version conflict、503 分开；正式状态码/DTO/客户端提示须批准。仅在已认证的旧创建回执未命中、且明确属于新建时使用。无 key 旧 v1 请求仍须明确拒绝，不能因“legacy 兼容”绕过截止。

提示候选：“旧版暂不接受新建；本次没有创建资料。原操作记录保留，请先恢复既有结果，或在授权的新入口手动继续。”不得声称先前不确定 POST 没有保存；只有服务端已证明本次零效果才表述本次未创建。
既有回执返回成功并不意味旧 SessionView 可读：随后 typed 读取仍按 c2d 清旧正文、停操作、保留记录、用户点击新版只读。这个页面没有 typed 创建能力，不能把 `/typed-read` 宣传成新建替代入口。

灰度仅在未来用户指定并批准的显式政策版本/范围后设计；不自选 cohort、不加环境变量逃生开关、不以正文/URL/query/客户端 Zod 忽略字段决定版本。缺政策/Schema/权限时拒绝新命令，旧合法恢复按原合同运行；每次政策变更可审计，但不将用户正文、Bearer 或 key 放入日志/URL。

失败回滚分层：

- 关闭未来 fresh typed/new-create 准入；保留所有已提交的 typed 分类、来源、历史、版本、revision、receipt 和费用账本，不危险降级 0015。
- 旧 key 不清、不重签、不重新提交；HTTP 不确定必须 GET 恢复，失败不能自动换新 key 或改走另一版本。
- 运行侧保留获批 drain/stale/fail/unknown 和已发生费用的记账完整性；不能把失败运行写成成功，也不能为了“禁写”冻结必要审计。
- 整会话 DELETE 的保留、迁往独立能力或后续授权变更须明确批准；end/stop 与已终态幂等行为分别测试，不借回滚改规则。
- 是否重新允许 v1 新建属于政策回滚决策，不能自动 fallback；读工厂不可用仍 503，typed 不回旧读取；不将 born-contract/Fact 偷偷退回 legacy。

## 7. 待批准决定与未来实施前置条件

需逐项批准，而非“一次批准所有写入”：（1）A 或 B 的政策范围；（2）存量 legacy grandfather/冻结；（3）born-contract 的持久定义、enum/列及迁移；（4）typed 创建路由/版本/DTO/proof/恢复；（5）cutoff 的线性化、审计、日期/范围；（6）旧客户端固定拒绝和人工新建交接；（7）DELETE 独立能力及权限；（8）end/stop 管理能力；（9）在途 worker drain 与账本收尾；（10）R03 身份/来源/语义保守回退及误阻断可用性；（11）灰度关闭/政策回滚准入；（12）D8 生产身份、预算及部署。

未来实施前必须补齐 typed writer、完整前端审核/写入/恢复、分类来源、D4/D5 相关协议和 D6 剩余消费合同，并单独审查权限。不能因为本轮测试通过就解锁 typed append/CO3、classify、related_plan/FactProgressLink、自动退级、正式 Provider/MiningContext 或付费请求。

未来测试规格（**未实现，不能计作已通过保障**）：

- 新/旧创建合同 × 有/无/错误 key × 已成功/未知/过期/删除回执 × 当前/历史 typed × 外会话。合法 replay 优先、版本隔离，所有新拒绝完整零效果，无部分响应。
- 生效边界两连接并发、同 key/不同 key、前后进程崩溃；首个创建效果、born-contract 与 receipt 原子一致；不重复创建、不自动换路由。
- 纯 legacy grandfather 的新 Fact/审核/旧计划行为，以及未来若冻结其新写入时的精确能力区别，不能只测 UI 按钮。
- DELETE / end / stop 与 worker reserved/running/lease 过期/未知结果/空候选/有候选分别验证；原资料、来源、回执墓碑与费用的保留/删除范围逐项批准。
- 新建协议与 migration/ACL 缺失、未知政策版本、回滚/不可降级历史、旧客户端手动交接；正常 typed writer 全链尚未存在，不能用 owner 合成 fixture 替代正式启用验收。

## 8. 本轮隔离、安全与验证记录

本轮只新增测试文件和本文。没有生产代码、0001–0015、Session 列、角色部署配置、Prompt、MiningContext、冻结质量预期或前端变更。

合成测试在 loopback15487 的 `pathwise_test` / `pathwise_e2e`，随机 Schema。新 `c2e_legacy_<uuid>` LOGIN 非 superuser、无继承/创建角色/创建库/Schema CREATE，无对象所有权、DDL、TRUNCATE、付费表 DML；只授予旧 N/M/W 场景所需表/列，DELETE 仅 Session。CO1/CO2 使用既有独立限权 LOGIN，**不扩权原 B2-b 或 append 身份**。owner 只建夹具/注入历史故障/核查，不用于模拟 runtime。HTTP uses real LOGIN；worker 直接调用使用同一受限 factory，不调用真实 Provider。

读取 typed 历史故障夹具时，owner 恢复全部触发器后才运行 runtime 请求；这种 fault injection 不创建新的生产绕过。新拒绝/恢复比较全表摘要，包含历史、receipt、revision 与费用，避免只比较 Fact 数量。合法删除/worker 收尾则按预期副作用断言，不错误要求全表不变。

初轮新测试 6 个失败来自测试假设：5 个将 UTC 与本机 +08:00 的同一时间戳字符串当成不同结果；1 个 R03 文句不属于 append 窄正语法。测试连接固定 UTC，仍保留**整个响应相等**断言；R03 采用“3/三个”同义改写，符合窄语法，再验证 D3。未改生产时间处理或词法合同，未删除旧断言。补充删除墓碑断言后专项 47 passed。

实际命令（从 apps/api / apps/web，各自使用明确合成测试 URL；日志位于忽略目录 `.e2e/c2e-*`）：

- `./.venv/Scripts/python.exe -m pytest -q tests/test_cutoff_preflight.py`：47 passed。
- `./.venv/Scripts/python.exe -m pytest -q -ra`：完整后端；最终数量、平台 skip、CI 以本 PR 验证记录为准，不将运行中写成成功。
- `npm run test -- --reporter=dot`：158 passed；`npm run build`、`npm run test:e2e:types` 通过。
- `PATHWISE_E2E_CHANNEL=msedge npm run test:e2e`：59 passed，真实 Chromium 内核本地 Edge；CI 仍 bundled Chromium，零失败重试，原 timeout 不变。
- `python ../../scripts/check_isolated_migrations.py`：空闲随机 Schema 升级/校验/清理通过；拓扑仍 `0014_append_batch → 0015_fact_classification`，没有新迁移。
- `python ../../scripts/check_m12c2_contracts.py`、`python ../../scripts/check_s03b_output_contract.py`：12/48 离线合同；最终结果列入 PR。
- `python ../../scripts/evaluate_mining_quality.py --outputs ../../docs/evaluation/quality-v1/oracle.outputs.json --output-dir ../../.e2e/c2e-quality`：DRAFT 脚手架，真实质量仍 null，不修订冻结评测。
- `python ../../scripts/run_offline_evaluation.py --profile 0 --output ../../.e2e/c2e-mock.json`：Mock CLI，无供应商请求或费用。

本轮覆盖的是当前合同与可重复风险；**未来 cutoff/born-contract/typed 创建/生产 cohort 未实施也未覆盖**。全部后端、React、Chromium、迁移和离线检查的最终实际结果与精确 HEAD/CI 链接记录在 Draft PR；既有平台 skip 如实说明，不新增 skip/xfail、不提高 timeout 或重试失败直到通过。

R03、D4/D5、D6 剩余、D8、正式读写 factory/Provider/付费权限/生产部署继续 BLOCK。保持 Draft，不 Ready/Merge/Deploy，不自动进入 typed writer。

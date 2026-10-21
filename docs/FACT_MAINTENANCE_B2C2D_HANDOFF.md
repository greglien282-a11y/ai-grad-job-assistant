# B2-c2d：旧工作台安全交接与 legacy writer 截止策略候选

状态：独立工程候选，等待独立审查。**只有前端安全交接实现；writer 截止仅设计，未启用。**

基线 main：`761ccf947b1fb6025fc9d3a428102e6cb27f6cac`。
启动时核验 remote main、工作区干净及 [main CI 39431907538](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39431907538) workflow、FastAPI、React、Chromium 全部成功且 SHA 一致，随后建立独立分支。

依据 B2C_DESIGN §4.2、§7、§9、§10、§12，以及 B2C2A、B2C2B_READ、B2C2C_READ_UI。本文的未来策略不是生产授权。

## 1. 本轮实现的交接合同

只将带凭证请求的 HTTP 409 与三个精确错误码视为升级交接：
`fact_contract_upgrade_required`、`summary_contract_upgrade_required`、`export_contract_upgrade_required`。
401、404、普通 context/version conflict、503、未知错误码不会触发升级交接。

`createExperienceApi` 在当前实例锁存升级错误；后续任何旧 GET/POST/PATCH/DELETE 在 fetch 前拒绝。并发晚到的成功响应也不能重新填回旧状态。
`useDiscovery` 进入明确的 `upgrade_required`，清除 session、summary、选中问题及旧成功提示，不再走普通失败后的 v1 重读恢复分支。
02/03 整个旧内容树被交接提示替换，包含确认、编辑、拒绝、核实、memory、问题处理、回答、Mining、重试、导出、复制、停止、结束、删除及已打开的管理面板。
旧闭包调用另有 hook/adapter 门禁，不依靠隐藏按钮作为唯一保护。

creation/mining 原 key、证明、有效期、待恢复内容和 Session 凭证不删除、不换键、不自动重放。创建回执已恢复但随后的 SessionView 拒绝时，creation 暂存也保留；普通成功的 legacy 流程仍按原合同清理已恢复记录。
不保证撤回错误发生前已发送的请求；服务端现有锁、版本及 `require_legacy` 才是并发写入安全边界。

提示说明旧工作台无法完整展示、本次读取没有修改资料。仅提供用户点击的 `/typed-read` 链接，无 query/hash 凭证，无自动跳转、存储注入或旧接口回退。新版默认关闭时显示不可用，保留全部生产 BLOCK。

## 2. 现有 writer 覆盖清单（源代码审计，不是新权限）

以下“先拒绝”指新命令在业务写入前拒绝；不代表没有 SQL 锁或允许抹掉合法旧回执。
`require_legacy` 检查当前三列以及对应历史，当前标签改回 legacy 不会使 typed 历史获得旧合同资格。鉴权先于这个检查。

### 2.1 旧建档及事实服务：`facts.py`、`experience_api.py`

1. **create_session / create_experience**：旧 v1 创建 Session、Project、初始 user Turn，本身不创建 Fact。无 typed 目标会话可检查。新会话随后仍可通过旧入口创建 legacy-v0。这是未来创建截止需要单独批准的实际缺口。
   有 key 时先 advisory lock、证明及已有回执匹配；创建回执恢复对 Session 凭证/初始 Turn/Project 校验，不返回 FactView。已有会话后来进入 typed 后，合法创建回执仍可能恢复，零新增效果。
2. **add_turn**：v1；Session 归属鉴权与行锁后，全会话 `require_legacy`、输入复用保护，再插入 Turn。不会直接创建 Fact。key 重放优先，新请求可在 Turn/revision 写入前拒绝；旧 Turn 回执允许零效果重放。
3. **add_fact**：v1；Project 定位、Session 鉴权锁、全会话 `require_legacy`、已消费输入/来源及 rejected 保护，然后创建 pending/v1 legacy-v0 Fact、FS、created FC。没有语义类型分类。
   已有 key 的事实回执先匹配，再以 fact 范围 `fact_view` 检查；混合会话中的合法 legacy Fact 回执可能恢复，typed Fact/其 typed 历史不返回旧投影。不要将这一零效果恢复等同于允许新写入混合会话。
4. **Fact PATCH**（edit、confirm、reject、verify_material、set_memory）：v1；Session 鉴权锁、刷新 Fact、全会话 `require_legacy`，然后版本与动作验证，先拒绝 typed 写入。编辑不会生成新 Fact；确认/核实只改变信任状态，**不推断完成状态或分类**。
5. **close_session / end_session**：v1；鉴权锁后 `require_legacy`，active 会话写入前拒绝 typed；已结束响应也经过 SessionView 门禁。
6. **整会话 DELETE**：现有合法删除例外。鉴权锁后擦除对应临时回执并整会话删除，**没有 `require_legacy`**。保留历史完整性合同允许的整会话删除，本 PR 不修改该 API、权限或数据库规则。02/03 一旦收到升级错误就不再显示或提交删除；直接旧 DELETE 仍是必须单独决定如何交接的能力，不能宣称所有旧 writer 已被全局阻断。
7. **旧 SessionView / summary / export**：Session/Project 鉴权锁后分别按会话/项目 `require_legacy`，使用固定升级错误。原读取有行锁，不应被宣传为新版 REPEATABLE READ READ ONLY。v1 export 不是 v2 备份；本 PR 不修改返回合同。

### 2.2 CO v1 correct / withdraw / resolution

入口为 `maintenance_api.py`、`fact_maintenance.apply`。使用独立默认关闭的 B2-b runtime 和 CO v1 key 证明；key advisory lock、同合同已有回执优先，随后 Session 鉴权锁、全会话 legacy 门禁、状态/revision/target/parent 锁与版本校验。
新命令在 Turn、FC、FCS、CO 或 revision 效果前拒绝 typed。correct 更新原 Fact，withdraw 拒绝原 Fact，resolution 按原动作合同处理，不开放 classify。
GET recovery / 旧 POST 同 key replay 仍校验权限、版本、证明并投影已有结果，不重新执行、换合同或新增事实，不要求后来仍为全 legacy。保留这种合法恢复是兼容要求，不把它误算为新 writer 漏洞。

### 2.3 CO v2 append

入口为 `append_api.py`、`fact_append.apply`。独立默认关闭的 append 身份；CO/key 版本隔离、跨路由冲突与已有回执优先；新请求 Session 鉴权锁、全会话 legacy 门禁及 revision/状态检查。
1–5 个 all-new 原子 Fact 仍使用 legacy-v0 默认值、pending/v1；不是 typed append。
D3 临时阻断检查**当前 rejected 或 FC before/after 历史曾 rejected**，先返回未保存错误，不生成假澄清回执。typed 门禁和 D3 都不授权语义分类。
GET-only 恢复保持原 v2 投影，绝不误读成 v1 或重新执行。

### 2.4 Mining、问题及运行收尾

1. **新 reserve/start**（`mining.reserve`）：旧 Mining 合同；key advisory lock、capacity 行锁、Session 鉴权锁；已有合法 mining receipt 优先，新请求在 Turn、Run、receipt、revision 等业务写入前 `require_legacy`。重放旧 Run 元数据不意味着再次推理。
2. **claim/build_context**：`mining_context.build_context` 已有全会话 legacy 门禁，冻结 Provider/MiningContext 本 PR 不动。claim 的状态与 lease 处理不是新的事实分类合同。
3. **complete**：有 Session 锁、Run 状态/lease/revision 检查；候选经 `facts.add_fact`，继承全会话 legacy 门禁。
   **不能据此声称整个在途 worker 在 typed 会话上永远零写**：stale/unknown/fail 运行收尾本来会更新 Run；零候选完成路径不会调用 add_fact，仍可能处理问题、assistant Turn 和 Run 状态。正常并发 revision 变化通常先得到 stale，但这也有运行元数据写入。这里是源代码审计发现的后续策略差距，不是本 PR 实施或验证了全局 worker 截止。
4. **stop / question skip/correct/hide/delete**：`mining_api.py` 鉴权锁后 legacy 门禁、revision/问题版本校验，业务写入前拒绝 typed；不创建 Fact。
5. **get_run / recovery**：鉴权/归属校验后只投影旧 Run，无新 Provider 调用，无新 Fact；合法旧恢复应继续可用。cleanup、fail 和 erase_receipts 属于运行或删除合同，不应为了 writer 截止无审查地冻结、延长 key 或伪造成功。

### 2.5 UI 与恢复入口

旧手工 `App.tsx` 仍可对纯 legacy 会话显式建档、add_turn、add_fact 和 PATCH；02/03 仍按原合同显式创建及 Mining，只有观察到精确升级错误才锁存前端交接。本轮没有为旧手工入口新增全局截止或 typed 编辑器。
后端新写入的全会话 legacy 门禁独立于 UI；隐藏按钮从来不是数据库授权。各 creation、Turn/Fact receipt、Mining、CO 恢复保持已有 key、认证、版本及 GET/POST 区别，不能一律清除或禁止恢复以简化前端。

## 3. R03 与剩余差距

`maintenance_guard.rejected_contribution` 以**当前 rejected Fact** 为集合，比较其正文、历史正文和原始来源 Turn；不是扫描所有曾 rejected 后又恢复的事实，也不是语义等价检测。
旧 add_fact/自由文本/不同入口的改写仍有 R03 缺口。append 的“曾 rejected 会话阻断”比旧入口保守，不能反推旧入口都有同等历史阻断。
纯 legacy 新事实仍能包含计划并被用户确认，旧 summary 与新版 summary 的 legacy 兼容路径仍可能展示它。**不能宣称计划永远不会进入确认正文，也不能把 typed 会话门禁等同于所有新事实均已语义分类。**

剩余风险矩阵：

| 场景 | 当前保护 | 差距 / 后续批准边界 |
| --- | --- | --- |
| 旧页面已有成功正文后进入 typed | 本轮清空、锁存、无自动重读/提交 | 请求发出前后竞态仍依赖后端锁/版本 |
| 纯 legacy 新建与确认计划 | 保留原业务合同 | 无正式语义分类，不作 completed 保证 |
| typed 当前或历史的新命令 | 已有服务端全会话门禁 | 不代表整会话 DELETE/在途收尾全被截止 |
| 同 key/GET 恢复旧回执 | 版本/权限/证明，零新执行 | 不能破坏恢复，也不将其升级为 typed 结果 |
| 当前 rejected 的来源复用 | 旧来源与文字保护 | R03 语义改写、跨入口及历史恢复仍 BLOCK |
| CO v2 append 的曾 rejected | 保守零写 D3 | 不解决全入口语义防复活 |
| UI 与 typed 只读工厂 | 显式无凭证链接、默认关闭 | 无生产启用；旧 02/03 未升级成 typed 工作台 |

## 4. 推荐兼容策略候选（本 PR 不执行）

原则：纯 legacy 历史继续原合同；进入 typed 合同的会话不接受新的旧事实命令；未来新建何时停止产生 legacy-v0，另设明确且可审核的合同切换门槛。

最小候选步骤：

1. 先批准并定义“新事实命令、运行收尾、合法恢复、整会话删除”四种能力边界。删除迁往显式有鉴权的独立能力还是保留例外，必须决定；不能在全局截止中顺手取消合法整会话删除。
2. 正式 typed writer/source/classification 合同审查完成后，再提出**显式版本化新建合同与不可变的会话写入合同标识**候选。其持久字段/版本、创建 proof/receipt 隔离、旧客户端拒绝码都需单独审查；本轮不新增字段或实现通用协商器。
3. 选择明确生效 cohort/合同版本，在首个 Turn/Session 业务效果前决定。旧客户端对不支持的新建合同应零效果拒绝，不靠时间猜测、正文推断、环境变量旁路、客户端 query 强制或静默降级。
4. 已出生的 legacy 会话是否永久 grandfather、只读冻结，或提供用户发起迁移，需要产品批准。默认候选保留既有合法 legacy 工作流及原 key 恢复，因此不能给出跨旧资料的全局语义分类承诺。
5. 新 typed 合同不再允许旧 add_fact/Mining 新事实；在途 worker 的 drain、stale/failure/审计收尾与新事实落库分别设计。不得冻结账本或抹去不确定 Run，更不得为通过截止检测而重新推理。

兼容代价：旧客户端可能无法新建、旧 legacy 始终不能被推断为 typed；混合会话旧读拒绝；用户需要显式新版入口及相应权限；历史/来源不得补造；重复请求必须恢复原合同，不重新执行新合同。

灰度与回滚：未来仅按已批准的显式合同/cohort 开启，不扩大身份权限；本 PR 没有 rollout 开关。回滚关闭未来新建/新命令准入，保留 typed 历史、分类、回执及删除/运行收尾合同；不改旧 JSON、不清 key、不降级 typed 标签、不回退旧读取，不危险 downgrade 0015。新读工厂关闭仍返回 503，不自动 fallback。

需用户另行批准：新建截止时点/范围、legacy grandfather 政策、会话合同持久含义及创建协议、旧客户端拒绝体验、整会话删除能力、在途 drain/收尾、typed 来源与分类证据、D4/D5/D6 后续协议、R03 全入口策略、D8 生产身份与部署。建议本身不构成批准。

## 5. 验证矩阵与独立环境

新增 React 单测：精确错误与普通错误区分；02/03 已显示数据后清空；export 失败；所有 hook/adapter 陈旧回调阻止；creation/Mining 原记录保留；网络 POST 不确定后的 GET recovery 不能掩盖升级；并发晚成功不复填。

新增 PostgreSQL HTTP 专项两种状态：当前 typed、仅历史 typed；真实随机 Schema 与独立限权 LOGIN；先验证合法 legacy Session/summary/export，后构造 synthetic confirmed plan/background，鉴权先于三种精确拒绝，逐次比较全部业务表及账本，并核验旧 FC 原 JSON 未变。

新增 11 个真实 Chromium 场景：02/03 的 Session/summary/export 拒绝；实际成功 Session GET 与后续 summary GET 间转为 typed；当前标签恢复 legacy 但历史 typed；旧管理面板清除；保存的 key 与回执记录保留；显式进入新版且输入框为空；默认关闭 503；外会话、网络、未知错误码、context conflict。全部 API 请求为实际 HTTP，typed 合同场景由真实 PostgreSQL 校验，不使用静态成功 JSON 代替。

E2E 仅 test wrapper 按显式测试 header 注入独立 v1 读身份。旧 GET 有 `FOR UPDATE`，故该身份有 Session `updated_at/context_revision` 两列 UPDATE 锁权限及必要 SELECT；**不能称为 SELECT-only**。没有 Fact/Turn/Run/key DML、owner 或角色继承。新版仍使用独立真实 SELECT-only LOGIN，不把旧身份注入新路由。owner 仅布置合成夹具/损坏历史，在 HTTP 外运行；所有触发器复原后再读。测试 header 不进入生产 app/factory。

全表摘要比较包含 revision、所有事实历史、回执、Run 及费用表，比较结果不输出正文或凭证。未知版本/缺权限/损坏历史等继续由既有 c2a/c2b/c2c PostgreSQL、Chromium 与本轮完整回归验证。纯 legacy 审核、恢复、导出及旧 02/03 全部原断言保留，不 skip/xfail/放宽 timeout/重试失败用例。

未来截止批准前额外矩阵：新旧 born-contract × 新命令/旧回执 × 当前/历史 typed × 外会话 × in-flight worker × 结束/删除 × schema/ACL 失败 × 升级/回滚。必须验证所有新拒绝零业务效果、旧恢复恰好一次语义、无 Provider 重放、历史与账本保留；本轮不声称已完成此未来 writer 实施矩阵。

## 6. 验证记录与停止点

命令在合成 loopback `15487` 测试集群执行，随机 Schema/临时 LOGIN 清理；没有生产数据库、真实凭据或付费调用。

- `pytest -q tests/test_legacy_upgrade_handoff.py`：2 passed。
- `npm run test -- --reporter=dot`：158 passed（原 140 + 新 18）。
- `npm run build`、`npm run test:e2e:types`：通过。
- `PATHWISE_E2E_CHANNEL=msedge npm run test:e2e`：59 passed（原 48 + 新 11），真实 Chromium 内核；CI 使用 bundled Chromium。
- 完整后端、独立迁移、12/48、质量脚手架、Mock 与最终 CI 以 PR 验证记录为准，禁止把未完成项写成已通过。

D6 本轮完成的是旧 02/03 的安全失败与人工交接；新版独立只读消费已有 c2c 范围不被扩大。未完成旧页面 typed 完整升级、typed 写入/编辑/自动退级、D6 全体产品协议。R03、D4/D5、D6 剩余与 D8/生产读写工厂/Provider/预算/部署继续 BLOCK。0001–0015、writer、生产 ACL/factory、冻结评测与 Provider 合同不变。

只交付 Draft PR，等待独立复审；不 Ready、Merge、Deploy 或继续后续阶段。

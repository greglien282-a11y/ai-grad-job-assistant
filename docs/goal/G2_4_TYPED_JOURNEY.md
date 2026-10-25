# G2.4 — 独立 typed 录入旅程（合成 / 未保存）

本轮基线 main `776f257ebfcb036b718d414703567da2b4359ba1`。开工前核验 #52 已合并，指定 [main CI 40190058125](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/40190058125) 的 head_sha 精确一致，workflow/FastAPI/React/Chromium 均 completed/success；#50/#48/#51/#52 已在 main。

依据 [#53 独立审查评论](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/53#issuecomment-6397216179)，从此 main 新建 `codex/g2-typed-journey-review`。仅按显式白名单复制原 #53 相对其 aa09128 基线的 15 个 UI 文件，来源 HEAD `31094a430e156fd040d79d572818c50f8e49eb6a`；不搬入 #50 等历史提交，不 cherry-pick/merge 原 #53 分支。原 #53 的 HEAD/base/Draft/内容保持不变；新 Draft 是替代交付候选，不能据此关闭旧 PR。未修改任何 apps、正式 DTO、共享 G2.1 解析器、迁移、writer、ACL、Provider 或调度器。

## 本地查看

目录 `research/typed_journey`，Node 22：`npm ci --ignore-scripts --no-audit --no-fund`，`npm run dev`，打开 `http://127.0.0.1:5187/`。仅本机开发服务，不部署；没有数据库配置、凭证、Provider、后端 API 或 storage。刷新丢失全部演示状态。不要输入真实资料。

可演示旅程：选合成原话 → 显式选择类型/阶段 → 查看完整原话和 CP 引用 → 查看独立合成选择来源 → 待审核 → 模拟用户确认 → R03 对抗情景与追加解释 → 模拟响应中断 → 只查看内存结果。所有阶段固定说明未保存。

10 条样本原样取自既有 c3a 窄规则；Python 在测试时实际调用未修改 c3a 证明对应三列组合为 eligible_candidate。浏览器**没有重新执行 c3a**，只对完全相同样本+声明组合使用预先校验的模拟记录，之后调用 G2.1 TypeScript 严格解析器。任意自由文本或改标签不在样本组合中即拒绝，不另写宽松词法分类器。UI 的固定日期是合成夹具时间，不是可信提交时间。

原始文字、当前引用、独立分类选择来源分开；新来源只是内存 synthetic Turn，不插入真实 Turn。用户声明和用户模拟审核都不等于平台认证。缺失分类依据的旧正式读合同仍 not_recorded/legacy_unclassified，未补造记录。G2.1 的历史/未知版本/缺字段严格解析证据不等于本 UI 已连接数据库。

## R03 和恢复的真实边界

复用 #46 已审查数字/同义/责任归属/无关误阻断案例语义，展示当前已 pending 但历史曾 rejected 的事实、原拒绝和完整合成快照。浏览器状态机是 G2.2 非持久化协议的体验实现，**不调用 Python begin/explain，也不证明真实历史完整性**。来源、风险提示及解释都是合成。加载情景开始另一个虚构演示，不是清除真实 Session 历史或绕过准入。

追加解释只追加内存文本和未核实证据描述，版本不符、非法 Unicode 或空内容拒绝。不会访问链接。改原话、重新分类、用户确认、任意轮解释都保留当前情景的拒绝历史；有拒绝历史始终不能生成模拟成功结果，贡献预览也被阻断。没有 force、批准即保存、新 Turn 解锁或换 key 的控件。

无拒绝历史时也只是体验示意：pending 不自动确认；计划/进行中/背景/限制经模拟审核仍不进入个人完成贡献预览。无历史提示不证明语义独立。

原有中断分为生成模拟结果前/后；恢复按钮只读取同一页内存，既不 HTTP GET 也不调用正式恢复 API。后者保留相同 SIMULATED-RESULT-1，不重执行；前者返回无结果。刷新后不可恢复，这是明确的未实现能力。这个符号不是 CO/正式幂等键，不能证明数据库原子性、崩溃恢复或真实 GET-only 恢复。所有数据库写入、模型调用和费用均为零；浏览器验证记录实际请求仅静态 GET、无 /api/。

## 验证与操作记录

- `python -B -m unittest discover -s research/typed_journey -p "test_*.py" -v`：2 项方法含 10 样本 c3a 子项及原 M2 风险材料检查。
- 目录内 `npm test`：36 项状态测试（原16项保留，新增20项）；`npm run build` 包含严格 TypeScript 检查。
- `npm run test:browser`：真实 Chromium 21 项（原9项保留，新增12项），完整旅程/来源/Unicode、四类非贡献、R03 解释/误阻断、拒绝伪 completed、刷新无残留及 390px 无横向溢出；另外六类读取故障 × 有/无拒绝历史，验证旧成功结果/来源清除、原话与历史/解释保留、禁用动作以及零 fetch/API/重试。无 sleep/retry/timeout 放宽。
- 本机 Windows 使用 `PATHWISE_PROTOTYPE_CHANNEL=msedge`（Chromium 内核）；Linux CI 使用 bundled Chromium。截图在 test-results/evidence，CI 附件包含桌面、澄清、手机；均合成资料。
- 页面 details 内展示事件名操作记录，不打印正文、凭证或网络审计。证据说明在实际 CI 后按精确 SHA 更新 PR。

本轮另运行 `python -B -m unittest discover -s research/declaration_read -p "test_*.py" -v`：43 方法含53共享子例通过；`npm run typecheck` 和 `npm run build` 均通过。新分支原型 CI 在新 Draft 中按最终精确 HEAD 记录，未知/pending 不当成功。

当前 main 的完整应用 CI 已按启动门槛核验；本轮为15文件隔离 UI 候选，不改正式工作台，也未重新执行/冒称正式后端或 PostgreSQL writer 集成验收。原型 CI 运行 Python 样本、G2.1 共享 Python 解析回归、TS/Vitest、构建和 bundled Chromium；主分支的 G0 文档专项亦按实际结果记录。

## 本轮限定审查修正

新增六类**纯合成**读取失败：unknown_contract、missing_source、missing_basis、conflict_409、unavailable_503、offline。它们不是实际 HTTP 响应、真实断网或鉴权检查；没有 fetch/新路由/网络恢复适配器。浏览器测试还把 fetch 设置为拒绝并计数，确认失败提示完全不依赖真实 API；观察到的 HTTP 请求只用于本机静态资源 GET。

未知版本、来源缺失和依据字段缺失：复制当前合成读包后分别改为未知 read_contract、删除原话 Turn、删除 basis 字段，再调用**未修改的 G2.1 strict parse**。其拒绝码分别为 candidate_version_unsupported / candidate_source_invalid / candidate_shape_invalid；拒绝后不使用原投影、不重建一个正常本地包假装恢复、不降级 v1。有效的 `basis={status:not_recorded,declaration:null}` 依然是合法缺记录表达；测试明确将它与整个 basis 字段丢失的损坏包区分，未收紧共享合同或补造依据。

所有六类故障置 read_failed 并保留本情景失败门禁：view=null、reviewed=false，旧正文/来源/贡献预览隐藏；raw、拒绝历史、解释、revision 原样保留。已有内存模拟结果标识仅在内部保留，不换标识、不显示、不允许 recover 将它转换成成功。没有已有结果时也不生成新标识。失败对象固定 truth_verified=false、persistence_authorized=false。

故障后 prepare/review/attempt/recover 在状态机与 UI 两层阻断；修改故障选择为 none、编辑原话/分类或追加解释均不清除门禁。解释仍可追加为未核实资料，不解锁 R03。用户可显式加载另一合成情景重新开始演示，这是原有虚构夹具切换，不是修复原包、清除真实历史或为当前会话授权。

红灯证据：先加入19项故障测试，原状态机得到 **16 passed / 19 failed**，实际保留旧投影或返回 mock_recovered；实现后加上合法 not_recorded 对照，共 **36 passed**。浏览器保留原9项，再增加12项端到端对照（包括先显示旧模拟成功结果，再故障隐藏；有 rejected 的历史/解释保留）。无删测试、skip/xfail、固定 sleep、超时放宽或失败重试。

相对原15文件增量，本轮只再改5个文件：本文、src/journey.ts、src/journey.test.ts、src/main.tsx、tests/journey.spec.ts。其余10个文件保持原 #53 blob。最终新 PR Diff 应仍恰好15个新增文件；Git 历史从已验证 main 直接产生新提交，不包含 #53/#50 的旧开发提交。

## 未实现与审批

没有真实保存、分类依据写入、真实人工决定、文件证据认证、持久操作回执或 Goal 自动恢复。M4 basis 与 G2.1 选择来源模型差异由 G2.3 列待批准；本 UI 不解决。R03、D4/D5 正式政策、D6 剩余、D8、typed writer/classify/related_plan、生产角色/工厂、Provider/付费/部署全部保持 BLOCK。保持 Draft，不 Ready/Merge/Deploy。

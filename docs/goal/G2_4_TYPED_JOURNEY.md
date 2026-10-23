# G2.4 — 独立 typed 录入旅程（合成 / 未保存）

基线 main `b96581175f4a2a307a7cfcfb7d60d1609d83983d`；开发分支从 G2.1/#50 的 `fff29fefa238b1ccc738af2ba540bd4e8fab17cb` 建立，Draft PR 明确以 #50 分支为 base，仅展示 UI 增量，不能跳过 #50 独立审查。没有合并任何 PR，也未改正式 apps。

## 本地查看

目录 `research/typed_journey`，Node 22：`npm ci --ignore-scripts --no-audit --no-fund`，`npm run dev`，打开 `http://127.0.0.1:5187/`。仅本机开发服务，不部署；没有数据库配置、凭证、Provider、后端 API 或 storage。刷新丢失全部演示状态。不要输入真实资料。

可演示旅程：选合成原话 → 显式选择类型/阶段 → 查看完整原话和 CP 引用 → 查看独立合成选择来源 → 待审核 → 模拟用户确认 → R03 对抗情景与追加解释 → 模拟响应中断 → 只查看内存结果。所有阶段固定说明未保存。

10 条样本原样取自既有 c3a 窄规则；Python 在测试时实际调用未修改 c3a 证明对应三列组合为 eligible_candidate。浏览器**没有重新执行 c3a**，只对完全相同样本+声明组合使用预先校验的模拟记录，之后调用 G2.1 TypeScript 严格解析器。任意自由文本或改标签不在样本组合中即拒绝，不另写宽松词法分类器。UI 的固定日期是合成夹具时间，不是可信提交时间。

原始文字、当前引用、独立分类选择来源分开；新来源只是内存 synthetic Turn，不插入真实 Turn。用户声明和用户模拟审核都不等于平台认证。缺失分类依据的旧正式读合同仍 not_recorded/legacy_unclassified，未补造记录。G2.1 的历史/未知版本/缺字段严格解析证据不等于本 UI 已连接数据库。

## R03 和恢复的真实边界

复用 #46 已审查数字/同义/责任归属/无关误阻断案例语义，展示当前已 pending 但历史曾 rejected 的事实、原拒绝和完整合成快照。浏览器状态机是 G2.2 非持久化协议的体验实现，**不调用 Python begin/explain，也不证明真实历史完整性**。来源、风险提示及解释都是合成。加载情景开始另一个虚构演示，不是清除真实 Session 历史或绕过准入。

追加解释只追加内存文本和未核实证据描述，版本不符、非法 Unicode 或空内容拒绝。不会访问链接。改原话、重新分类、用户确认、任意轮解释都保留当前情景的拒绝历史；有拒绝历史始终不能生成模拟成功结果，贡献预览也被阻断。没有 force、批准即保存、新 Turn 解锁或换 key 的控件。

无拒绝历史时也只是体验示意：pending 不自动确认；计划/进行中/背景/限制经模拟审核仍不进入个人完成贡献预览。无历史提示不证明语义独立。

中断分为生成模拟结果前/后；恢复按钮只读取同一页内存，既不 HTTP GET 也不调用正式恢复 API。后者保留相同 SIMULATED-RESULT-1，不重执行；前者返回无结果。刷新后不可恢复，这是明确的未实现能力。这个符号不是 CO/正式幂等键，不能证明数据库原子性、崩溃恢复或真实 GET-only 恢复。所有数据库写入、模型调用和费用均为零；浏览器验证记录实际请求仅静态 GET、无 /api/。

## 验证与操作记录

- `python -B -m unittest discover -s research/typed_journey -p "test_*.py" -v`：2 项方法含 10 样本 c3a 子项及原 M2 风险材料检查。
- 目录内 `npm test`：16 项状态测试；`npm run build` 包含严格 TypeScript 检查。
- `npm run test:browser`：真实 Chromium 9 项，完整旅程/来源/Unicode、四类非贡献、R03 解释/误阻断、拒绝伪 completed、刷新无残留及 390px 无横向溢出。无 sleep/retry/timeout 放宽。
- 本机 Windows 使用 `PATHWISE_PROTOTYPE_CHANNEL=msedge`（Chromium 内核）；Linux CI 使用 bundled Chromium。截图在 test-results/evidence，CI 附件包含桌面、澄清、手机；均合成资料。
- 页面 details 内展示事件名操作记录，不打印正文、凭证或网络审计。证据说明在实际 CI 后按精确 SHA 更新 PR。

现有正式工作台未被替换或改路由。本轮综合应用回归在 G2.3/#52 的独立测试分支执行：React 158/build/E2E types、真实 HTTP+PostgreSQL Chromium 59、隔离迁移、12/48、质量脚手架和 Mock 已通过；完整后端/CI 终态单独核验。本 UI 无任何 apps 生产代码改动，不用那些测试宣称已覆盖真实 typed writer。

## 未实现与审批

没有真实保存、分类依据写入、真实人工决定、文件证据认证、持久操作回执或 Goal 自动恢复。M4 basis 与 G2.1 选择来源模型差异由 G2.3 列待批准；本 UI 不解决。R03、D4/D5 正式政策、D6 剩余、D8、typed writer/classify/related_plan、生产角色/工厂、Provider/付费/部署全部保持 BLOCK。保持 Draft，不 Ready/Merge/Deploy。

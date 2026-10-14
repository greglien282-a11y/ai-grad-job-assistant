# M1-2C-2B：零费用适配器、持久账本与隔离评测

基线 main `c2f4625e59112b8edeb74d9eca97fcc0c88b6820`，合并 CI 38582461447 成功。依据 [批准设计](M1_2C_2_ADAPTER_EVAL_DESIGN.md)、[上下文合同](M1_2C_1_CONTEXT_CONTRACT.md) 和 D-006。真实调用授权仍无，预算批准额仍为 0；30 元不是许可。

## 范围与接入结构

`app/model_adapter.py` 定义不可启用的 Profile、请求 Adapter、Envelope、唯一的 MockTransport 和 OfflineRunner。Provider 为 deepseek_official/bailian；Model 独立于渠道；Profile 保存请求模型名、预期版本/别名政策、区域/部署、端点、非思考模式、结构模式、输出 cap 和 task。CLI 显式选择 0/1/2，不自动路由或降级。

三个 Profile 复用禁用配置草案：官方 deepseek-flash，百炼 deepseek-v4.1-flash，百炼 qwen3.7-plus-2026-05-26。官方请求构建 thinking.disabled，百炼 enable_thinking=false；JSON object 或 Qwen JSON Schema 使用已有 Wire Schema；每个请求保留有限 max_tokens。构建的对象只供 Mock 检查，未证明供应商接受参数或 Schema 子集。真实 cap 尚未确认的 Profile 也只能 Mock。

**没有 HTTP Transport、供应商 SDK、Key resolver 或环境密钥读取。** enabled/actually_verified 只能是 false；OfflineRunner 严格拒绝非 MockTransport。CostCall 数据库也限定 transport=mock。既有 safe_provider、用户 API DTO、Scripted Provider 和页面均不改，不把适配器伪装为 scripted 注册。未来真实启用必须另审实现和迁移，而非翻一个变量就绕过。

请求仅使用 MiningContext.payload。Mock 请求按全部消息 UTF-8 字节数+固定开销和输出 cap 估算模拟上界，预留不足时在 dispatch 前拒绝；返回用量超出 Mock 协议上界也拒绝。此上界只属于本地 Mock 协议，不能代替未批准的真实 tokenizer。响应拒绝拒答、非 stop 完成、截断、重复 JSON key、围栏、多对象、额外状态/用量字段及非法 Schema；Pydantic 验证完整 v2 合同。usage 来自 Mock 协议 envelope，不信输出正文；缓存输入和 reasoning 是子集，不能重复计费。错误只输出白名单代码，不传播响应体或异常正文。报告 reported_model 明确为 mock_only_not_real_version。

评测通过现有 build_context、validate_v2 和 mining.complete，继续检查真实 PostgreSQL 中同会话/项目 user 原文、Unicode code-point 引用、原子性、问题去重及 revision/lease/active 最终 fence；候选统一 pending。隔离 fixture 的 MiningRun 标为 offline_mock，既不调用 safe_provider，也不修改正式 API 门禁。S07 的编辑/确认是固定数据集中明确用户事件，不能由 Provider 触发。

## 0006 数据模型与迁移

新增 `0006_cost_ledger`，父版本为 0005_answer_questions：

- cost_budgets：namespace + kind + key 主键；global/provider/model/session，Decimal(20,6) ceiling/call_limit/held/spent，frozen 和 max_active。
- cost_calls：UUID、操作键与请求摘要、固定安全 Profile 快照/摘要、provider/model/合成 session tag、Mock 状态、预留/估算/对账金额、价目/用量/版本证据、lease、错误码和唯一账单摘要。

单次限制是各预算 scope 的 call_limit；模型额度按 model family 聚合，渠道单独按 provider 聚合，跨渠道仍共用同 namespace 全局额度。namespace 是一次独立 Mock 实验的账本边界，不能通过增加 namespace 解释为扩大真实预算。当前没有真实批准/账单授权表，因此不能用于实费调度。

不保存业务原文、系统提示、完整响应、操作明文、凭证、Key 或私人账单；不关联经历记录，业务删除不级联费用。费用模块没有自动删除/到期退款功能。价目只支持显式 CNY_SIMULATED；USD、未知价格/非法用量失败关闭。当前测试配置金额和 invoice 均为模拟值，不是批准价格或真实 Token。

所有升级/回滚只在随机隔离测试 Schema 内执行。新增真实 PostgreSQL 用例验证空库 roundtrip、0005→0006→0005→0006 和原有资料兼容；alembic check 无差异。CI 原 public-schema 升级步骤改为 check_isolated_migrations.py 创建全新 test_eval_*，保留 upgrade/check/既有清理函数的验证。E2E 仅将启动探针的迁移版本从 0005 更新为 0006；30 项 .spec.ts 内容未修改。**日常 pathwise_dev 未迁移；不要为本阶段手动升级它。**

## 预留、发送和恢复合同

每次写事务先锁 namespace 的 global row，所有预算/状态变更遵守相同锁顺序；短事务完成后才能调用 Transport。不在外部调用期间持锁。这是小批量评测的明确串行协调选择，不用进程内锁冒充跨进程一致性。

预留逐一检查 global/provider/model/session 的 spent+held+new≤ceiling、call_limit、冻结与 unknown，以及 global 2/session 1 活跃槽。创建唯一 operation_hash 记录并同时增加各 scope held。相同键及请求/配置/会话/额度/价目重放同记录；任一不同返回 idempotency_payload_mismatch。同键不会取得第二次发送许可。

状态转换：

- reserved→sent：在短事务中提交一次发送意图，只有转换获准的调用者可调用一次 Mock。
- sent→response_received：记录规范用量和估算；账单未核对，预留仍全部保留。
- sent→unknown：超时、取消、协议错误、429/5xx、拒答、截断等；不假定远端免费，不自动退款。
- sent lease 过期：get 只读投影 unknown，原记录仍 sent；显式 recover_expired 才持久化 unknown。
- reserved lease 过期：发送许可从未发出，有持久证据未 dispatch；显式维护可记 0 并转 reconciled。
- sent/response_received/unknown→reconciled：显式模拟账单证据。幂等 invoice 摘要禁止重复核对或在两次调用复用。
- reconciled 不允许被迟到 unknown 擦除，账单内容变化报冲突。

unknown 或过期 sent 阻止本 namespace 后续调用，跨供应商也不能兜底；GET 不改变状态、不重新推理。释放本地过期槽不释放费用占用。实际金额超过预留时完整记录超额、所有相关 scope 冻结，不截断金额；usage 估算超过预留也冻结。费用冻结没有自动解冻入口。报告按 provider/model/session 汇总 Mock 输入/输出 Token、用量估算、已核对金额和未核对预留，各 call 可只读查看。

独立 OS 进程/连接测试验证同键一次发送、预算竞争；另有真正 os._exit 的进程死亡测试，验证 sent 已提交、读恢复只读、维护后 unknown、不会重发。没有模拟锁替代 PostgreSQL。

## 离线评测运行

使用 Python 3.12 现有 API 虚拟环境。显式在当前终端设 TEST_DATABASE_URL 为已配置的 loopback pathwise_test/pathwise_e2e；不要使用 DATABASE_URL、pathwise_dev 或管理员 postgres 角色。工具不加载 .env、不索取 Key，不在命令示例写连接密码。

```powershell
# TEST_DATABASE_URL 由负责人本地设置，不贴到 Git 或报告。
apps/api/.venv/Scripts/python.exe scripts/run_offline_evaluation.py --profile 0 --output .e2e/m12c2-mock-report.json
apps/api/.venv/Scripts/python.exe scripts/run_offline_evaluation.py --profile 1 --output .e2e/bailian-deepseek-mock.json
apps/api/.venv/Scripts/python.exe scripts/run_offline_evaluation.py --profile 2 --output .e2e/bailian-qwen-mock.json
apps/api/.venv/Scripts/python.exe scripts/run_offline_evaluation.py --fault timeout --output .e2e/timeout-mock.json
```

工具在专用测试数据库中创建新 test_eval_UUID Schema，核对数据库、迁移/check 后运行，结束清理**自己新建**的 Schema；不复用现有资料。它是一次性零费用 Mock 实验，不是实费调用/账单恢复工具，不能用它清理未来实费 unknown。账本的跨事务/进程持久恢复另由模块和 PostgreSQL 回归测试验证；真实阶段的长期账本保留/权限/对账入口仍需批准。

固定 12 组完全虚构 teacher-forced 输入；确定 UUID/context 顺序、问题回答版本、事实编辑/用户确认、跳过/隐藏/纠正、重复提交、停止和遮盖检查。每轮只用指定 golden Mock 响应，不让模型自己编用户回答。结果为 24 次 Mock，15 条 gold：11 条正向贡献、4 条否定/边界事实。正向也必须保留原文限制，不等于可以自动写正式简历。

报告输出原始/接受数量、相对人工 gold 的精度、引用字面准确率、问题目的符合率、精确重复，以及按 Profile/供应商/模型/会话费用数据。语义追问质量需人工评审；real quality、provider latency、actual model tokens 均 null。示例为 [精简 Mock 报告](evaluation/m12c2-mock-example.json)，完整报告由 CLI 生成。gold oracle 成功绝不证明真实模型质量；S02 的现词表过宽问题仍保留，未放宽 gold 或旧校验。

--fault 支持 429/5xx/refusal/truncated/schema/source/timeout/crash；只执行首个固定案例并停止，报告不冒充完成 12 组。错误引用必须拒绝发布；同键恢复不新增 Mock 调用。crash 报告在 lease 未过期时诚实保留 sent，不假装已知远端失败；逾期 read/维护在数据库测试覆盖。未知费用仍 null，已知零费用只以明确 Mock invoice 核对。

## 验证与尚未验证事项

本机完整后端 228 项、React 62 项、Edge 30 项、TypeScript/Vite 构建、迁移/check/清理 smoke、离线合同 12 项及实际 CLI 均通过；最终 CI 结果见 Draft PR。原171后端、62 React、30 E2E 不删除/跳过/放宽。新增 PostgreSQL/Provider/故障评测测试；本机迁移 smoke 和实际 CLI 也运行。既有 Starlette TestClient 弃用和 Zod 构建注释警告仍是环境限制，不影响断言。

尚未实测：官方/百炼实际可用型号/权重版本、区域/Workspace 域名、Schema 子集/UUID、有限输出 cap、真实 tokenizer/计费 Token、峰谷缓存/推理计费、拒答/超时/取消账单、留存/隐私条款适用账户、真实 latency/质量。没有 HTTP/Key/真实 ledger dispatch；不存在可启用的实际调用开关。未来也不得自动换渠道、模型、模式或修复 JSON 产生第二次费用。

首次真实探针前需单独明确批准：供应商/账号空间/地区/端点/版本政策/模式、一次合成探针的次数和输入/输出上限；人民币预算及每次/会话/模型/供应商限额、有效期、税费/FX/未知缓冲；仅指定合成集外发及对应隐私条款；服务器受控 SecretRef 注入和只读账单核对方式。真实 Transport、授权账本/价目/批准汇率、上界 tokenizer、权限/保留机制和原子 budget gate 需另审实现，不能将本 Mock 账本金额改名后直接用于实费。30 元仍仅草案。

本阶段结束后停止，等待审查。无 UI、PRD、prototype、Pages、自动路由、日常库迁移或真实消费。

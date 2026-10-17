# 02 交互生命周期适配（离线合成模式）

基线：`b132d19f450cb6a1a8bb05ce5087daf96f8286af`。本轮不接真实 AI，不改数据库、生产 API、供应商适配器、提示词或收费控制。状态卡是应用的固定说明，不是模型自然语言回复。

## 现有能力与证据

- `mining_api.py`：POST mining-runs 先原子 reserve，再执行合成 Provider；可返回 202/201/200。GET recovery 和 GET run 只读，不启动推理。当前 `get_provider()` 只允许已启用的 ScriptedProvider。
- `mining.py`：保存原回答、问题关联、base/reserved_revision、lease、运行状态和候选事实归属；GET 的有效状态可把过期 active lease 投影为 unknown，不写回。完成时校验来源并建 pending 事实，去重可导致零新增候选。连续空轮、轮数限制或合法 v2 stop 可停止会话。
- 持久化与生产 `MiningRunView`/前端 `miningRunSchema`：reserved/running/completed/failed/unknown/stale、error_code、候选 ID、问题 id/state/version/content、回答问题版本关系。前端合同仍强制 provider=scripted、synthetic=true。
- 当前问题不完整持久化/暴露 v2 的 purpose/source_turn_ids；stop_reason 未持久化/返回。不能从 stopped 推断是用户停止、信息充分、记不清或轮次上限。
- 当前 assistant turn 是固定合成流程标记，不能视为正式 AI 回复。页面不直接显示其正文，不仿写模型理由。运行 API 也不提供可信的实时进度、生成中 token 或成本字段。
- 事实、原文引用、用户编辑历史、记忆/材料核实和 experience-summary 已具备；本轮复用，不另造事实库。ContextFakeProvider 仅是离线 v2 测试工具，未接到正式用户流。

## 展示层结构和优先级

`interactionState.ts` 是纯函数，只读取现有会话快照及本页请求阶段，返回固定文案、下一步、候选计数和呈现守卫，不调用 API、计时器或 Provider。`InteractionStatus` 放在原左侧追问与 AnswerComposer 之间，保留手机“回答这题”、桌面双栏与原 03。

优先显示恢复/暂存问题，然后是实际请求阶段，再根据会话和最新运行数据投影状态。普通 busy、GET 和事实管理操作不等于模型在思考；只有原 POST 发送阶段标为“正在提交并进行合成整理”，且明确尚未确认保存结果。不会按本地时间自动猜测 lease 状态、轮询或切换可重试状态。

- `describe` / `not_started`：无会话时引导合成描述；已保存且没有 run 时等待用户明确启动。
- `reading`：启动读取、只读恢复或普通资料操作；不宣传为 AI 思考。
- `submitting`：操作键已安全暂存且用户发起的 mining POST 正在等待；按钮禁用并显示提交中，不提前声称回答已保存。
- `reserved` / `running`：已读取的服务端运行状态；只能手动只读查询，不自动轮询。
- `completed`：以本轮 candidate_fact_ids 与当前 facts 的交集计数；分别显示当前候选总数和 pending 数。不会把整个会话 pending 数当作本轮发现数。已确认或编辑过的旧候选仍按当前事实状态显示。
- `awaiting_answer`：本轮候选已审核且仍有未作答的有效问题，提示显式选题或自由补充。
- `no_new_facts`：本轮完成但实际零新增，合法追问仍可继续；没有问题时可自由补充或明确停止，不伪造提取成功或停止理由。
- `failed`：仅 provider_output_invalid 标为“输出未通过校验”；其他失败用通用说明，不把任意错误码或供应商自由文本显示给用户。新回答暂停，重整已保存回答仍需独立确认。
- `unknown`：保留原操作记录，锁定回答提交与会话管理；只有只读查询。GET 仍为 unknown 就继续保持，不自动开放推理。即使没有本地 pending，服务端 unknown 也会阻止写入。
- `stale`：本轮迟到结果过期，新回答暂停；先核对资料，重整仍需明确确认。现有事实是当前服务端资料，不能将旧 run 当成新成功输出。
- `conflict` / `recovery_required`：版本冲突、读取失败、暂存异常或候选与当前事实不对应时暂停写入；版本冲突即使自动 GET 成功，也保留暂停，直到用户手动重新读取。
- `not_found`：仅沿用已有明确 404 的原操作同键重试入口；不更换 key 或自动提交。与 unknown 严格分开。
- `stopped` / `ended` / `limit`：服务端已停止、会话结束或本次返回明确的 admission/round 限制。停止后可审核事实和阅读 03；结束保持只读。达到限制不等于经历完整。

## 数据流和草稿保护

`useDiscovery` 只增加本页 phase/failureCode 及保守守卫；原始 POST、GET、幂等键格式及恢复机制不变，没有新后台请求。保留既有启动/异常后的只读 GET，不增加自动轮询、POST 重试或推理。

unknown 不再按一般终态清空 pending。未恢复期间锁定原回答框，以免之后的终态恢复清掉新写的草稿；明确 not_found 时仍可输入完全一致的原回答显式重试。只有确知回答操作的终态才清其输入；初始整理/重整不清空另一份未提交回答。删除会话时清除本页回答和选题。

事实编辑草稿、问题纠正草稿、来源和用户确认仍在原组件内，未自动确认、补造引用或把未经校验输出写入事实库。

## 离线验证边界

- ViewModel 和 React 使用完全合成、符合现有 Zod 合同的快照，分别验证普通 GET、实际 POST、候选计数、空结果、校验失败、unknown/active 持久恢复、stale/冲突、两题关联、草稿和零后台推理。
- 保留原 34 项 E2E，新增 4 项真实 React/FastAPI/PostgreSQL 场景：空轮继续及服务端停止、失败不发布、unknown 刷新后仍 query-only、实际并发编辑造成 stale。
- 仅 `apps/web/e2e/server.py` 的隔离测试 ASGI 入口识别固定测试场景 header；生产 mining API 不识别它。原启用/ScriptedProvider 门禁仍在，测试替身仅在已验证的隔离 schema/零费用环境下制造空结果、ValueError、TimeoutError 或延迟，没有真实模型、HTTP Transport 或收费路径。
- 截图只使用合成资料，保留桌面、390px、320px 和 CSS zoom=2 检查。CSS zoom 不等同于所有原生浏览器/Windows 缩放和真实手机键盘组合的人工验收。

人工验收：在隔离预览按 [E2E 文档](M1_1B_3_E2E.md) 启动；描述合成经历，显式选择一题或两题回答，查看真实候选数、确认并进入原 03；停止后继续核对。断网时仅恢复，不要重复提交。故障场景由测试运行器注入，不给正式页面增加演示按钮。

## 未来最小契约建议（仅设计，未实施）

1. 版本化扩展 QuestionView 并持久化经校验的 purpose、source_turn_ids；纠正/隐藏/删除的版本与隐私语义一起定义，不能靠前端猜题意。
2. 服务端持久化 `stop_event`：规范 reason、actor（user/system/validated_provider）、run_id/context_revision。必须区分用户明确停止与提供者的停止建议；不得把模型判断冒充用户意愿。
3. 如确需自然语言 assistant_reply，单独定义版本、来源/输出校验、长度限制和删除策略；当前固定 assistant 标记不能直接升级成“真实 AI 回复”，也不保存原始供应商响应作为聊天正文。
4. 真 Provider 接入需单独版本化 provider/synthetic 合同及审批、费用、密钥、隐私和错误恢复；本轮不放宽 scripted 字面量。服务端还应提供经审查的 unknown 终局处置/允许重试条件，不能由客户端读一次 GET 就授予新推理许可。

已知限制：当前 UI 对服务端持续 unknown 采取保守 query-only 策略，不能在页面自行解除；停止原因、真实回复、结构化问题意图和真实模型质量均未实现。当前状态卡不能证明模型能力或供应商延迟。

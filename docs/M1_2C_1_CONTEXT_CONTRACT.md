# M1-2C-1：多轮上下文与 extractive-v2 合同

基于 main `a29fdfa72d65985a0127ab09e69181afc05ff49b`（合并 CI `38560046030` 已通过），分支 `codex/m1-2c-1-context-contract`。依据完整 V0.3 PRD、USER_JOURNEY 与现有 M1-2A/B；不改三入口、首页/01/03、HTTP 请求/响应、数据库或日常库。此阶段不是已验证的自适应 AI 能力。

## 实现与兼容

`mining_context.py` 在 claim 的父会话锁事务内构建不可变快照；`mining_validation.py` 校验 v2 来源、原子片段与追问；`mining_fake.py` 是仅用于合成测试的确定性 v2 Provider。`MiningInput(turn_id, content, context)` 保持旧字段兼容，未来适配器只允许使用 `payload()`。旧 ScriptedProvider 的 output_contract_version=1，整轮引用/固定问题维持原行为；v2 Provider 声明版本 2，不能返回 v1 绕过原子性校验。v2 输入的兼容 content 字段也已遮盖隐私。唯一保留原始 content 的路径是已批准的零费用 v1 合成实现。

普通配置依然只允许显式 AI_ENABLED=true、AI_PROVIDER=scripted；Fake 不通过新增环境开关上线，测试用依赖注入启用。AI_ENABLED 默认 false；safe_provider 仍拒绝非 synthetic、非 scripted 名称或非零费用预留。没有真实适配器、SDK、密钥读取或外部模型调用。Provider 不在事务内运行。

## 输入 Schema 与上下文裁剪

可审核的机器合同：[mining-input-v2.schema.json](contracts/mining-input-v2.schema.json)。从 Pydantic MiningContext.model_json_schema() 生成，测试逐字段比对，避免文档漂移。

快照包含 project_id、reserved context_revision、input_turn_id；当前及有限历史 user_turns（turn_id、遮盖后原话、answered question ID/作答版本）；历史 questions 当前 ID/version/state、当前正文、作答 turn/version、是否与当前问题版本匹配；当前 facts 的 ID/version/status、当前陈述、memory_state、source_kind；轮数、最多 6 轮、连续空轮及停止/结束条件。用户资料全部视为不可信数据，不是系统指令。

预算是确定性的 **16,000 文本 Unicode code points + 64,000 UTF-8 JSON bytes**，同时满足；最多 8 个 user turns、24 个问题元数据、32 个当前事实。不是 tokenizer 精确 token 上限或已批准真实费用；M1-2C-2 必须增加对应供应商 tokenizer/preflight 与总输入输出预算（含系统指令/schema），不能仅凭字符预算扣费。tokens_in/out 目前只用于合成计数，不是可信账单。

裁剪顺序：

1. 当前完整回答及其 ID/version 关联必须保留，绝不在句中截断。单独已超预算则 failed/mining_context_invalid，回答仍只存一份，可由用户明确重试。
2. 最近问题的 ID/状态/版本/作答关系优先；然后在预算内填当前正文。active/corrected/skipped 的 content=None 可表示正文因预算未包含，不能推测文字。
3. 优先最近已确认/材料辅助事实，其次最近其他事实；只发当前陈述，不发 FactChange 旧正文、原始事实副本或材料全文。过长事实整项省略，明确计入 omitted_facts。
4. 剩余预算容纳最近历史用户回合，最多 7 个；当前回答总在 user_turns[0]，其余按最近在前排列。旧回答整条省略，不能把省略解释成用户没做过。
5. 返回 omitted_turns/facts/questions；最终序列化再次计入元数据，超界失败关闭。服务端只接受快照真正包含的来源，不能引用被裁掉的旧回合。

数据最小化：不发送 assistant 回合、完整系统提示/模型响应、Bearer、幂等键、receipt、材料引用/全文或完整变更历史。邮箱、URL、中国手机号/身份证样式以同长度 █ 遮盖，保持 code-point offsets；被遮盖区域不能成为候选原文。它不是完整匿名化：姓名、自由描述隐私、其他电话格式仍可能存在；外发前还需要负责人批准数据范围、用户同意及供应商条款，不能宣称可安全发送真实简历。

问题语义：skip 保留当前文字/状态，不能重新绑定；hidden 不发送文字，仅 ID/状态及瞬时去重指纹；deleted 文字和指纹均为空，不创建旧问题缓存。correct 只发送当前措辞和版本，原回答保存旧作答版本；answer_matches_current_version=false 时绝不能当作已回答修订后的措辞。指纹仅对仍存在的当前问题文本计算，不持久保存；删除后不会留旧文字的指纹副本。精确/规范化重复对 hidden/skipped/active/corrected 均拦截。

已拒绝事实只发送状态/版本/记忆等元数据、不发正文。用户编辑以当前 statement 与 user_edit 表示，旧 quote 只留原事实历史，不能继续支持新正文。v2 来源区间与任何旧事实来源重叠时不重新建档，含被编辑/拒绝的 v1 整轮引用；手工来源无可靠区间时保守阻止整轮再提取。相同陈述/quote 跨回合也沿用旧去重检查。

## 输出 Schema 与严格验证

机器合同：[mining-output-v2.schema.json](contracts/mining-output-v2.schema.json)。这是一份通用服务端 JSON Schema；未来供应商严格模式子集（defaults、必填/nullable 等）需要独立适配和合同测试，不宣称直接适用于所有 SDK。

```json
{
  "schema_version": 2,
  "candidates": [{"citation": {"turn_id": "00000000-0000-4000-8000-000000000001", "quote": "我实现了列表筛选。", "start": 0, "end": 9}}],
  "questions": [{"text": "你还记得这一步采用的技术或操作吗？不记得可以跳过。", "purpose": "detail", "source_turn_ids": ["00000000-0000-4000-8000-000000000001"]}],
  "stop": false,
  "stop_reason": null,
  "tokens_in": 0,
  "tokens_out": 0
}
```

示例 quote 长度 9 是 Python/Unicode code points，区间 [start,end)，不是 UTF-16 units。最多 5 个候选，每个 quote 最多 500 字符；只能从同项目同会话、快照已包含的合法 user turn 中提取，原 DB 原话与遮盖后快照切片必须同时逐字相符。Schema 不允许 statement、status、evidence、确认或记忆状态字段。发布只调用既有 add_fact，统一 pending/ai_extracted/unspecified；用户单独审核后才能进摘要。

保守原子性范围：完整连续的简单句，保留人称、否定、限定词和数字；不允许只截“部署”来丢掉“没有”。明确个人主语、一个受支持动作词，拒绝逗号/分号/并列连接及多个动作、团队归属不明、假设、猜测、记不清等片段；应改为无预设的澄清问题。例如“我实现了筛选。\n我没有负责部署。”可成为两个 pending 事实；“团队大概完成了 2 页；我没负责部署”整体不自动成事实。缺少指标不能补百分比；缺少技术细节不能猜技术栈。明确的单个操作可按原文保存，不要求每件事都有指标。

这不是通用语义原子性证明：词表会保守拒绝合法长句，也无法覆盖所有隐含复合语义；真实模型上线前需扩展评测和专业审查，而非改几个词就宣称质量达标。v1 整轮复合候选是明确的兼容路径，不冒充 v2 原子提取。

追问包含 text、purpose（contribution/detail/uncertainty/verification/correction）、1–2 个合法来源 turn ID；每轮 1–2 题，不写事实或猜测答案。规范化 NFKC/大小写/空白/标点后，重复历史问题或本轮重复均使整轮失败，不发布部分事实。问句中的数字必须已出现在指定来源原话里，防止诱导出虚假指标。真正的高价值/同义语义去重、无预设措辞仍需真实合成评测，不能由字符串规则保证。

提前结束为 stop=true + 白名单 stop_reason（enough_information/user_uncertain/no_new_information），此时 questions=[]。继续必须有 1–2 题。已有用户停止、连续两轮零新增候选和 6 轮上限仍优先；停止不确认事实、不改用户资料。问题 purpose/source_turn_ids 是 Provider 输出验证信息，当前持久化仍只存问题正文一次；后续回答 ID/version 持久化不变。若未来需要跨轮保存 purpose，须另审最小迁移，不能在 assistant 历史偷偷复制整个输出。

## 状态、幂等与恢复

base_revision→原回答/绑定原子保存→reserved_revision→claim 锁内构建快照/转 running→事务外调用→重新取父锁核对 active/running/lease/reserved_revision→验证/原子发布。发布使用同一份不可变 claim 快照核对允许来源；若资料已变则先 stale，不发布旧结果。快照只在内存，不落库/日志；崩溃后 GET 仍只读投影为 unknown，不重新推理。

合法转换沿用 M1-2A：reserved→running/completed（仅经 running）/failed/unknown/stale；running→completed/failed/unknown/stale；终态不可复写。快照构建失败可将 reserved→failed/mining_context_invalid；输出失败 running→failed/provider_output_invalid；取消/超时 unknown；进程死亡由 lease 投影 unknown，显式重试才回收。retry 是新 run、复用原已存回答/绑定，在当前 revision 重建快照；不承诺重跑旧快照或保存完整上下文恢复缓存。

同键同正文/关联仅保存一次，重放不调用 Provider、不再加 revision；不同正文/关联仍 idempotency_payload_mismatch。未找到不能自动换键；过期/删除墓碑及旧键不能复活。旧业务写入仍由现有 DB 触发器递增 context_revision；一会话一项目约束不变。没有新迁移，head 仍 0005_answer_questions，日常 pathwise_dev 不操作。

## 合成评测与验收

[多轮样本](../apps/api/tests/fixtures/mining_multiturn.json) 为合成资料：模糊课程、团队贡献、遗忘技术、否定、Unicode、假设。数据库测试还覆盖用户纠正/拒绝/记忆、跳过/隐藏/删除/纠正与旧作答版本、重复回答、同键并发/恢复、精确问句重复、非法数字/跨会话/assistant/UTF-16/截断否定/私密内容、原子失败、裁剪来源禁止、合法历史来源、取消/明确重试及管理/写入后的迟到结果。

ContextFakeProvider 是少量固定句式/词表的测试工具，不是模型效果样本：删除题后保守结束，已忘记细节则给跳过/结束选项；两轮无新增事实仍触发旧停止规则。它能验证合同和 SQL 结果，不能用于比较供应商中文质量。旧 ScriptedProvider/UI 原 30 项 E2E 完全不改。

本机 PostgreSQL 171 项、React 62 项、E2E 类型检查和 TypeScript/Vite 构建通过；Edge 首次启动因专用端口被人工预览占用，启动器拒绝复用，待正常关闭后再补跑。最新提交、最终 CI 与后续 Edge 结果记录在 Draft PR；所有数据库测试使用独立迁移 schema，禁止日常库回退。本轮未安装依赖、系统软件，也未迁移日常库。

## M1-2C-2 前置选择项

供应商/API/区域/固定模型版本、单次/会话/每日费用上限与真实 tokenizer、允许外发字段与数据条款、中文质量评测阈值、语义原子性/同义追问判定及失败人工降级需审查。先只用这些合成用例；评审与单独授权后才读取受控密钥和开展付费测试。参见[供应商官方资料比较](M1_2C_2_PROVIDER_RESEARCH.md)。

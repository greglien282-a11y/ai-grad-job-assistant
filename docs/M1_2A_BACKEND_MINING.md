# M1-2A：合成经历挖掘后端合同

基于 main `3d8ca2f`（M1-1B-3 已合并），分支 `codex/m1-2a-backend-mining`。依据完整 V0.3 PRD 文档 v0.2 的 F01/F02/F08、USER_JOURNEY 和已审查的 M1-2 技术方案。这里只实现后端合成状态机，不代表真实模型质量、完整简历或 M1-2B UI 已交付；三入口、PRD、prototype/Pages 不变。

## 数据归属与迁移 0004

- `experience_projects.session_id` 数据库唯一约束强制 MVP **一会话一项目**。ConversationTurn 仍只有 session_id，但该会话不可能有第二个项目。迁移遇到旧多项目资料直接失败并回滚，不合并、不删除。将来多项目需独立迁移 project_id/FK，而非放松本约束。
- FactSource 同会话 FK + 用户角色触发器；原始回合的角色/正文/归属数据库不可变。AI 提取仅接受当前 run.input_turn_id 的同会话 user turn。项目和输入回合的同会话 FK 共同约束 MiningRun。
- Session 增加 `context_revision` 和独立的 `mining_status`；Fact 增加 `origin`、`memory_state`、`ai_run_id`；FactSource 增加 citations。旧事实回填 manual/unspecified，原确认状态、版本、引用、编辑历史不变。
- `ai_mining_runs` 仅保存状态、输入/输出资源 ID、revision、lease、重试链、合成提供者/模板版本及用量；不保存完整模型响应、系统提示或思维链。一个有效 reserved/running run/会话，由部分唯一索引约束；一个 retry parent 只能有一个后继 run。
- `ai_mining_questions` 是问题正文唯一存储位置。assistant 回合只保存固定合成状态提示，不复制问题；run/FactChange/receipt 不保存问题历史正文。
- `ai_mining_receipts` 采用现有 Bearer 绑定的签名键、HMAC 请求标签和 24h 操作窗口；删除转成仅 key_digest/state/expires_at 的墓碑。`ai_mining_capacity` 单行锁协调跨进程准入：全局最多 2 个有效 run、每会话最多 6 个不同回答轮次/12 个尝试。它是合成调用容量控制，不是已批准的真实模型预算。
- 新表随会话删除级联；HTTP 删除先擦除 receipt 关联和请求标签。清理命令同时清理过期 AI receipts，不删除业务资料。过期签名键在墓碑清除后仍不允许新建。现有每日开发库 `pathwise_dev` 未迁移。

## 上下文版本：三个检查点

1. `base_revision`：调用者 GET 聚合所得版本。预留事务中取得操作键锁、全局准入行锁、父会话锁；优先识别同键重放及不同正文冲突，然后检查 active/mining 状态与 base_revision。错版 `409 context_conflict`，没有保存新回答。
2. `reserved_revision`：本次回答保存后（或复用初始回合/显式重试旧回答），初次 mining_status 切为 active 后的 revision。与原始回答、reserved run、receipt 在同一短事务提交。后续推理不持事务/行锁。
3. claim 再核对 revision、会话及 lease，才 reserved→running；模型返回后重新取父锁，核对 running、lease、active/mining active 和 reserved_revision。不同则 stale/unknown，不发布任何候选。结果与来源/历史/问题/assistant/completed 原子提交；提交前再次检查 lease。

context_revision 由数据库触发器维护：项目、回合、事实、材料、问题的每次业务行写入递增；status/mining_status 的真实变化也递增。**是行变更计数，不是每 HTTP 请求固定 +1**：保存回答 + 首次开始挖掘通常 +2；材料插入 + 更新事实通常 +2。Fact.version 仍用于单条事实并发控制。run/receipt/lease 状态本身不改语义上下文。GET 和幂等重放不写业务行，不递增；旧业务 API、合成编排共用同一触发器。

## 运行状态转换

| 起点 | 终点 | 条件与作用 |
|---|---|---|
| 无记录 | reserved | 键/权限/正文/revision/准入有效，回答与 receipt 原子提交 |
| reserved | running | 当前上下文匹配且 lease 未到期，事务提交后调用 provider |
| reserved | stale | claim 前上下文变化或已停止/结束，零推理 |
| reserved/running | unknown | lease 到期的写操作回收，或取消/超时/不确定存储结果 |
| running | completed | 校验及最终版本检查通过，整组输出原子提交 |
| running | failed | schema/引用/字段不合法，回答保留，无输出发布 |
| running | stale | 期间编辑/确认/新回合/问题操作/停止/结束改变上下文 |
| failed/unknown/stale | 原记录保持终态，新 run reserved | 新稳定键 + retry_of + confirm_retry=true，复用原回答，不再保存一份 |
| 任意 | 删除 | 删除会话及运行资料，receipt 墓碑不可复活 |

completed 不转回 running；同键 POST 不做第二次推理。lease 默认 60 秒且不超过操作键期限；合成调用总超时 45 秒。GET 对过期 reserved/running **只投影 unknown**，数据库行保持原样；新的预留 POST 在短事务中将过期活行回收为 unknown，释放部分唯一索引和容量。故进程被强杀也不永久阻塞会话。旧 worker 即使返回，因状态/lease 检查无法发布。

重新推理始终是一个新的显式操作，不能直接重置旧 run。相同 retry parent 的后继成功后，换新键再重试该 parent 返回 `mining_retry_superseded`；若后继也失败，应明确重试该后继。第三方调用将来是否已计费无法由数据库事务保证，此阶段不作“外部推理恰好一次”承诺。

## HTTP 合同

统一前缀 `/api/v1/experience`。使用原 Authorization: Bearer、no-store、64KiB 请求限制及安全错误映射；不允许 URL 查询携带凭证。签名键复用现有格式，kind=`mining_run`、scope=`session:<UUID>`。GET recovery 同样带 Bearer/Idempotency-Key，不带请求正文。

| 方法/路径 | 输入/行为 |
|---|---|
| POST `/sessions/{id}/mining-runs` | project_id、base_revision；content / input_turn_id / retry_of 三选一；retry_of 必须 confirm_retry=true；必需稳定键 |
| GET `/sessions/{id}/mining-runs/recovery` | 通过已暂存的键只读找回 run ID/状态；未找到 404，绝不触发 provider 或保存回答 |
| GET `/sessions/{id}/mining-runs/{run_id}` | 权限校验后只读状态、revision、问题和候选资源 ID |
| POST `/sessions/{id}/mining-stop` | base_revision；停止挖掘，事实仍可审核；不结束整个会话 |
| PATCH `/sessions/{id}/mining-questions/{qid}` | base_revision、expected_version、action=skip/correct/hide/delete；仅 correct 接受 content |
| GET `/projects/{id}/experience-summary` | 确定性返回 confirmed/pending、text、incomplete 与 context_revision；text 仅拼接已确认/有材料事实 |
| PATCH 既有 `/facts/{id}` | 增加 set_memory + expected_version；用户记忆状态与事实确认分开 |

POST 完成新操作 201，重放终态 200，重放仍运行 202 + Idempotency-Replayed。业务失败运行保留为资源（state=failed/unknown），不是伪造成功候选。读响应包含 synthetic=true；新增问题和事实经旧聚合/导出也可追溯，不能漏删。

同键不同正文 `409 idempotency_payload_mismatch`；事实冲突 `409 version_conflict`；上下文冲突 `409 context_conflict`；忙碌 `409 mining_busy`；未知结果需明确重试 `409 mining_retry_requires_confirmation`。即使换新键，已经提交过的输入回合或相同回答正文仍 `409 mining_input_already_submitted`，不静默保存第二份。旧 receipt 未找到不是换键理由，调用方先只读核对会话；过期 410，越权统一不可用。限额 429 + Retry-After；这些错误不能被前端统一当作自动重发许可。

## 问题操作的真实语义

- skip：标 skipped，保留文字作为已跳过记录，不自动保存答案。
- hide：标 hidden，保留文字但消费方不应在当前问题区显示；它**不是删除**，导出仍可查看。
- correct：替换唯一问题正文、version+1；旧正文不复制到历史 blob 或 assistant。不改已有回答或事实。
- delete：content=NULL、state=deleted、version+1；run GET/重放/导出都仅返回无正文标记，不存在另一份助手历史文字。已删除问题不可再纠正。用户回答即使引用该问题文字仍是独立资料，不误删；本机备份/WAL 的物理保留不由此宣称清除。

## 来源与事实边界

提取协议只接受 citation={turn_id,quote,start,end}，不允许 provider 传 statement/status/evidence/用户记忆状态。start/end 为 Unicode code-point 整数，区间 [start,end)；服务端逐字核验。**extractive-v1 进一步要求完整当前 user turn：start=0、end=len(content)、quote=content**。这是有意保守的 M1-2A 取舍：片段可能丢失否定、假设、团队归属或模糊程度。不能将“没有部署/如果部署/团队大概完成 2 页”变成“独立部署提升 80%”。复合回答可能形成较长候选，未来若需自动拆句/改写必须另审语义合同；本轮不声称已解决通用自然语言真实性。

候选统一 pending，origin=ai_extracted；数字、限定词保持原文。模型无法自动确认/材料核实；用户单独 PATCH 审核。memory_state 仅用户主动设置，原文含“大概”也不会被模型标 certain。同原文引用/陈述重复（含已拒绝及被编辑的原文）不创建第二条；语义不同的相似说法仍需要用户检查，不声称语义去重完整。

编辑后当前来源仍是最新 FactChange；旧 quote 只作历史，当前 citations 为空，用户再确认不会将旧回合恢复成 B 的依据。专业表达尚未生成；summary 对当前 confirmed/evidence 行确定性拼接，pending/rejected 不进入 text。JSON 导出仍是包含全部状态的档案，不是正式简历。停止支持主动停止、连续两轮没有新增候选、6 轮保护上限；没有强迫用户补指标。Scripted Provider 仅输出两条固定开放问题，不代表真实自适应追问质量。

## 安全、成本与运行

AI_ENABLED 默认 false；显式 AI_ENABLED=true 且 AI_PROVIDER=scripted 才可在合成开发环境调用。没有任何真实适配器、密钥读取或外部 HTTP；未提供/未知供应商拒绝执行。Provider 协议含可测试 CostReservation，当前只接受 scripted + synthetic + maximum_cost=0；未知价格/非零费用一律 ai_provider_unapproved。它不是批准的真实预算账本，未来真实计费/日月总额/费率与密钥管理另需审查。

错误不输出正文/凭证/完整 SDK/SQL 异常；未保存 raw output/system prompt。现有临时凭证窗口仍不是长期账号恢复。Scripted Provider 启用方式只用于合成后端测试，此 PR 不提供 AI UI 或用户生产入口。

数据库操作：选定非日常隔离环境后执行 alembic upgrade head / alembic check；python -m app.cleanup_idempotency 清除过期操作元数据。不要自动升级 pathwise_dev；日常库升级必须先检查、备份、独立授权。已有 16 项 E2E spec 原样保留，仅 probe 的预期迁移改 0004、重置先清 AI receipts。

## 验证与限制

真实 PostgreSQL 测试覆盖空库往返、0003 旧确认资料升级/check/回滚、旧多项目拒绝无数据丢失；独立连接 HTTP 并发、旧写入 revision、响应丢失恢复、租约投影/回收、取消、同键/换键、原子部分失败、问题正文删除、越权、停止/结束/删除迟到结果、保留编辑历史及 Unicode/语义防改写。

本机验证（2026-10-14）：PostgreSQL 后端 105 项通过（新增 39 项挖掘/安全测试），React 35 项通过，TypeScript/Vite 构建及 E2E 类型检查通过；原 16 项真实 Edge E2E 全部通过（44.8s），断言文件与 main 一致。迁移空库/0003 升级/回滚/check 均在隔离 schema 通过。现有 TestClient/httpx 弃用及 Zod 注释警告保留；初次沙箱运行的数据库/Node EPERM 限制在所需权限下重跑后通过。CI Chromium 最终结果及链接记录在 Draft PR。真实模型、专业改写、语义拆分、自适应问答、永久账号恢复、真实费用账本和前端改版均未实现；不把 Scripted 测试当作模型质量验收。

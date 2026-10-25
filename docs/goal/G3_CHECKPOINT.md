# G3 连续交接检查点（2026-10-26）

本轮用户明确授权启动 G3。启动时 get_goal=null，随后通过支持的 create_goal 注册了本轮研究目标，实际返回 active；不是假装 Goal 已启用，也没有解除暂停或预算。未指定 token budget，没有额度重置、其他账户/密钥、自动执行器或 scheduler。本轮不得自动合并或开始正式 writer。

G0 `docs/goal/GOAL_STATE.md` 是旧 G2 封存的恢复预检锚点，其历史 null/Draft/CLI socket 记录不代表当下状态。本轮不修改它的锚点或安全判断。自动恢复依旧 enabled=false/scheduler NOT_APPROVED；共享运行时失败没有改写成成功。当前 G3 记录不被 G0 解析为恢复许可。

```json
{
  "contract": "g3-research-manual-checkpoint-v1",
  "baseline_main": "034c192828f5b5152b950300223f5282af4aa191",
  "branch": "codex/g3-choice-protocol-reference",
  "state": "CANDIDATE_DELIVERED_PENDING_CI_AND_INDEPENDENT_REVIEW",
  "native_goal_observed": "active",
  "automatic_recovery_enabled": false,
  "scheduler_approval": "NOT_APPROVED",
  "production_protocol_approved": false,
  "persistence_authorized": false,
  "next_instruction": "Read the current native Goal and exact Draft PR HEAD/CI. Complete reference and unchanged application regression, report exact evidence, then stop for independent review. Do not start a formal writer or treat this checkpoint as execution permission.",
  "blocks": ["R03", "D4_D5", "D6_REMAINDER", "D8", "A_B_PROTOCOL_APPROVAL", "FORMAL_CO3_WRITER", "CLASSIFY_RELATED_PLAN", "PROVIDER_PAID_DEPLOY", "AUTOMATIC_RECOVERY"]
}
```

## 当前实现

- G3.1：A/B 精确图、认证/选择责任边界、版本与删除候选；设计见 G3_CLASSIFICATION_BASIS_PROTOCOL.md。
- G3.2：一次性 PostgreSQL Schema、随机真实限权 LOGIN、延迟图约束、受信认证上下文、不可变图、事务/并发/真实进程 kill/整会话删除测试。
- G3.3：新版本独立 Python/TS 读取解析；从真实 SELECT-only PG 图投影五事实，供 TS bridge 消费。未改正式 DTO 或重做 G2 演示。
- G3.4：版本/同键碰撞、原结果优先、GET-only 恢复、墓碑和已知非保障。旧 1/2 参考 marker 不冒充正式回执。
- G3.5：产品解释、A/B 比较与推荐、未证明性质及逐项审批清单。

所有新增业务实验在 research/g3_choice_protocol，无 apps 代码、0001–0015、旧测试、生产配置/角色、正式合同改动。新 workflow 只运行隔离测试及原回归，没有部署。原 #53、旧 worktree 和其他 Draft 未被修改。

## 执行命令与本地证据

工作目录为当前 worktree。仅使用本轮自行启动的 loopback 专用测试集群和显式测试 URL；不读取 .env/生产凭据。DATABASE_URL 示例不能换成生产库。

```powershell
$env:G3_TEST_DATABASE_URL = 'postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
$env:G3_PG_CANDIDATE_FILE = '<本机临时目录>/g3-db-candidate.json'
python -B -m pytest research/g3_choice_protocol -q -ra
cd research/g3_choice_protocol/web
npm ci --ignore-scripts --no-audit --no-fund
npm run typecheck
npm test
```

最终本地专项数量/耗时及 CI 由 PR 更新；不将尚未运行的 workflow 写成成功。增量调试已实际得到 85、97、190、197、202、222 项绿色结果；增加覆盖后以最新结果替代旧数量，不累加为独立测试数。TS 最初 89/90，布尔版本校验顺序的跨语言错误码不一致；两端先检查整数再比较身份后通过。又加入 UUID/时间尾换行严格拒绝。

交付前本机最终专项：Python 224 passed（37.71s，其中 133 项使用真实 PostgreSQL、91 项纯结构验证），TypeScript 93 passed（其中 1 项消费真实 PG 投影产物），tsc --noEmit 通过。最终代码/CI 若继续修正，以 PR 最新精确 HEAD 证据为准。CI 在本检查点提交时尚待创建和执行，最终结果记录在 PR，不将 pending 写成 success。

真实红灯：B 的后续独立事实重复相同标签时触发 ref_turns_session_id_purpose_content_key。补测先得到 A 通过/B 失败；仅修改新参考 SQL 为正文专用唯一索引后 A/B 都通过。未放宽事件 ID、selection ID、slot 或原话重复限制。

提交后自审新增 B 选择区间尾部越界负例，N=1/3/5 均先红灯：substring 截短越界导致错误区间可以提交。新参考 SQL 补充 end<=保存正文长度、区间长度等于 quote code-point 长度；未修改正式来源约束。最终专项数量以修正后的 PR HEAD 为准，不复用前一 HEAD 的 CI。

另一真实两连接红灯：同键 POST 缓存原回执后，删除能在图读取前提交，导致 effects=[]。修正为鉴权后通过新私有 definer 锁函数读取 operation，保护整份 replay；不授予 writer UPDATE、不允许 reader 执行、不改变 GET 只读合同。直接 SELECT FOR UPDATE 因原最小权限被拒绝的证据保留在回归中，未以扩大表权限解决。

上述修正后完整 G3 本机重新执行：228 passed / 39.15s（137 真实 PostgreSQL、91 纯解析），TS 93/typecheck 通过。最初 88a315d 的 CI 40215280792/40215280494 是修正前源 HEAD 的证据，不能替代最终修正 HEAD 的新 CI。21 文件边界保持不变。

版本矩阵再补布尔/浮点/字符串/NULL/未知整数：真实红灯显示 Python True==1、3.0==3 会使参考 GET 接受非整数版本。仅新研究 _view 强制 type(version) is int，旧正式恢复合同不改；跨三种存储版本补 15 项反例。最终数量与 CI 仍按最新 HEAD 报告。

最终版本矩阵修正后本机 G3：243 passed / 50.82s（152 真实 PostgreSQL、91 纯解析）；TypeScript/bridge 93 项不变。原生账户只读观测 ordinaryUsageAllowed=true、五小时已用4%、周已用7%，只是该时刻快照；未消费任何重置额度或更改预算，自动恢复仍关闭。

真实非保障反例：正常适配器拒绝计划当 completed；受限 SQL 身份直接构造完整图并填写 validator label 可 COMMIT。测试以“数据库没有证明语言校验执行”为预期风险证据，未绕过 owner/ACL 伪造语义安全。

已重新执行未改动的 G2/G0 Python：declaration_read 43、clarification 9、typed_journey fixtures 2、goal_recovery 33，均通过，无新增 skip/xfail。G3 workflow 还执行完整 FastAPI、隔离迁移、12/48、质量/Mock、React build、真实 Chromium/PG 与原 G2 Chromium；结果必须等到终态。

## 恢复与停止

准确 commit/PR/CI 在 Git 和 Draft PR 说明保存，避免把文档自己的 SHA 循环写进自身。恢复先核对实际远端 main、工作树、PR head 和 native Goal；不要重做已合并 G0/G2。普通测试错误可以修复，生产合同不能自行升级。

若额度拒绝：另存 RATE_LIMITED、最新成功 commit/PR/test/CI 和真实原因；不得标 COMPLETE，不购买重置、不切账户/密钥或启动新模型进程绕过控制。没有安装/启用调度器。正常测试 kill 的子进程是一次性 PostgreSQL 测试 worker，不是新的 Codex/model 实例。

完成本轮候选和精确 HEAD CI 后停止等待独立审查；推荐 A 仍需用户批准。未证明的认证/语义、正式键证明、函数体指纹/默认 ACL、删除反向竞争/快照撤销、TTL/密钥轮换和生产迁移见主报告，不得以参考测试全绿代替它们。

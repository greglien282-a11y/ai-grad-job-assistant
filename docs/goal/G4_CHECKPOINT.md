# G4 连续研究检查点

本文件只保存手工交接，不被 G0 解析成恢复许可，不改旧 GOAL_STATE.md 的安全判断。

```json
{
  "contract": "g4-research-manual-checkpoint-v1",
  "baseline_main": "e1eff78fd43e424ab22996b182e0e5f4d6bd609c",
  "native_goal_observed_at_start": "null",
  "native_goal_after_explicit_start": "active",
  "phase": "G4-0A_B_C_D",
  "state": "CANDIDATES_IMPLEMENTED_PENDING_EXACT_HEAD_CI_AND_REVIEW",
  "automatic_recovery_enabled": false,
  "scheduler_approval": "NOT_APPROVED",
  "production_protocol_approved": false,
  "persistence_authorized": false,
  "next": "Finish exact HEAD CI and final handoff for Draft PRs, then stop for independent review. No further stage or production permission is implied.",
  "blocks": ["R03", "D4_D5", "D6_REMAINDER", "D8", "FORMAL_CO3", "CLASSIFY_RELATED_PLAN", "PRODUCTION_MIGRATION", "PAID_DEPLOY", "AUTOMATIC_RECOVERY"]
}
```

G4-0A：两个信任边界已在真实限权 PostgreSQL 执行，最终专项74项；#56 HEAD 01f38f93097f8958a1c506859cdb7bedc9ed560c。G4-0B：真实旧合同17项，保留future-first碰撞反例，#57 HEAD 686636e28ec0dca440afaad77c64f88ecb6bca4f。G4-0C：新增真实24项、原M2 42项，#58 HEAD affefb384f9496bc8b0a920b3f5504b1745efd84。按56→57→58→D的分支依赖分别Draft，不重写历史或强推。

G4-0D：独立React/HTTP/签发进程/真实PG闭环，Python4项，真实Chromium7项和TypeScript/Vite build通过。全链真实执行409 passed/145.54s（A/B/C/D、原G3与原M2），1既有依赖警告，无skip。完整本地后端2340 passed/1595.66s，无skip；隔离迁移upgrade/check/cleanup成功。前一次未给显式测试URL的迁移命令如实拒绝，补显式专用合成URL后通过，未改脚本。精确D Commit/PR/CI在最终外部handoff记录，避免SHA循环。

CI仍需按各PR最终HEAD核验。早期源SHA的成功不替代最终源。Windows缺管理headless浏览器的首轮失败保留；本机改用已安装Chrome，CI安装匹配Chromium。共享运行时历史失败没有改写成成功。

真实信任根反例保持绿色的意思是“攻击确实能提交”，不是安全已解决：A Broker 被篡改、B 签名根失陷仍可造假。正常调用者的直接 SQL 和标签攻击必须拒绝。只修改研究代码、新文档与研究 workflow；正式 apps/、迁移、权限、旧合同均无差异。

恢复前重新查询实际原生 Goal、远端 main、PR HEAD/CI 和工作树，不按此快照推断 active。额度拒绝时写 RATE_LIMITED／最新已确认 Commit/PR/测试，不标 COMPLETE，不重置预算或新进程绕过模型限制。测试 kill 的 worker 是合成数据库测试子进程，不是新的模型进程。没有 scheduler。

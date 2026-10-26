# G4 连续研究检查点

本文件只保存手工交接，不被 G0 解析成恢复许可，不改旧 GOAL_STATE.md 的安全判断。

```json
{
  "contract": "g4-research-manual-checkpoint-v1",
  "baseline_main": "e1eff78fd43e424ab22996b182e0e5f4d6bd609c",
  "native_goal_observed_at_start": "null",
  "native_goal_after_explicit_start": "active",
  "phase": "G4-0A",
  "state": "IMPLEMENTED_PENDING_EXACT_HEAD_CI",
  "automatic_recovery_enabled": false,
  "scheduler_approval": "NOT_APPROVED",
  "production_protocol_approved": false,
  "persistence_authorized": false,
  "next": "Verify exact PR HEAD/CI, then autonomously continue separately reviewable G4-0B/C and conditional D within user authorization. Never promote research into production approval.",
  "blocks": ["R03", "D4_D5", "D6_REMAINDER", "D8", "FORMAL_CO3", "CLASSIFY_RELATED_PLAN", "PRODUCTION_MIGRATION", "PAID_DEPLOY", "AUTOMATIC_RECOVERY"]
}
```

G4-0A：两个信任边界已在真实限权 PostgreSQL 执行；前三轮增量 48、61、67 passed，不累计测试数。扩展独立签发进程后，与原 G3 全套一起重新执行。最终数量/Commit/PR/CI 由 PR 和外部 handoff 补充，避免文档 SHA 循环。

真实信任根反例保持绿色的意思是“攻击确实能提交”，不是安全已解决：A Broker 被篡改、B 签名根失陷仍可造假。正常调用者的直接 SQL 和标签攻击必须拒绝。只修改研究代码、新文档与研究 workflow；正式 apps/、迁移、权限、旧合同均无差异。

恢复前重新查询实际原生 Goal、远端 main、PR HEAD/CI 和工作树，不按此快照推断 active。额度拒绝时写 RATE_LIMITED／最新已确认 Commit/PR/测试，不标 COMPLETE，不重置预算或新进程绕过模型限制。测试 kill 的 worker 是合成数据库测试子进程，不是新的模型进程。没有 scheduler。

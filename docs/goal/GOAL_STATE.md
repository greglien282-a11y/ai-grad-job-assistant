# Pathwise 下一轮持续开发检查点

最后环境核验：2026-10-22 UTC。这是人工可审计、Git 版本化的检查点，**不是恢复授权、进程存活证明或额度凭证**。整个 Goal 保持 active；G0 原型处于默认禁用候选，G1 等待 #46 合并和新的 main CI，G2 尚未实施。

## 机器可读状态

此文档只允许一个 JSON 块。`enabled=false`、`scheduler_approval=NOT_APPROVED` 是本版固定合同，改为 true/APPROVED 会拒绝解析，没有启用开关。下一版执行器必须另行审查和审批。

```json
{
  "contract": "goal-recovery-preflight-v1",
  "state": "ACTIVE",
  "enabled": false,
  "thread_id": "01a1542e-e712-7f21-b0ae-831becbeec32",
  "branch": "codex/goal-recovery-preflight",
  "checkpoint_parent_head": "698b8aed005d826af7a0767def3559637cff32fb",
  "last_successful_commit": "2dc0c6158072438f16eeca181be1d882c77b20a0",
  "current_subtask": "G0 environment evidence and disabled recovery preflight",
  "next_instruction": "Read this checkpoint and RECOVERY_PREFLIGHT.md; recheck authoritative PR46/main CI and current Goal/runtime. Keep scheduler disabled. Finish G0 dry-run/CI evidence before G1 or G2.",
  "blockers": [
    "PR46_NOT_MERGED",
    "POST_PR46_MAIN_CI_NOT_AVAILABLE",
    "SHARED_CLI_RUNTIME_UNAVAILABLE",
    "ATOMIC_IDLE_TO_RESUME_NOT_PROVEN",
    "SCHEDULER_NOT_APPROVED"
  ],
  "scheduler_approval": "NOT_APPROVED",
  "not_before_utc": 0,
  "last_attempt_id": "none-no-model-turn-launched"
}
```

检查点提交自身的 SHA 不在自己的内容中循环引用。解析器用 `git log -1 --format=%H -- docs/goal/GOAL_STATE.md` 求提交锚点，要求 HEAD 等于锚点、锚点父提交等于 `checkpoint_parent_head`、分支匹配、工作区干净，并对照 Git 中的原始检查点。每个新的成功检查点提交更新 parent 和记录；独立提交后忘记更新检查点会停止，不能自动 stash/reset/clean。`last_successful_commit` 表示已有完整测试及 CI 的上一交付，不是当前 HEAD 的替代品。

## 已核验基线与 PR

- main：`698b8aed005d826af7a0767def3559637cff32fb`，远端 API 与 fetch 一致。
- [#44](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/44) 已合并，merge `09d221232ab3cbf0bd6d8c810744b6555476144d`。对应 [main CI 39791415411](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39791415411) 的 workflow、FastAPI、React、Chromium 全部 completed/success。
- [#45](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45) 已合并为当前 main。09d→698 仅三份 overnight 文档；当前 main 没有同 SHA 的应用 CI，不能把 09d 的结果说成 698 的同 SHA 结果。
- [#46](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46) 仍 open/Draft，HEAD `fc9286e8f1b8e0e62f6d59d2821584391d03fd88`，未合并。
- [#47](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/47) 仍 open/Draft，HEAD `2dc0c6158072438f16eeca181be1d882c77b20a0`，base 仍为 #46 分支。该 HEAD 的 [CI 39784611827](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39784611827) 全绿；旧交付本地 2261 后端/158 React/59 E2E，CI 后端 2260+1 既有 Windows 专用 skip。这不是当前 G0 分支的验证结果。

本轮隔离 worktree：仓库根目录下 `.e2e/worktrees/goal-recovery-preflight`；分支 `codex/goal-recovery-preflight`；从 main 698 建立。根工作区仍保留 #47，未重整、强推、删除或改基线。

## 当前结果与未完成项

G0 本机 CLI `0.162.0-alpha.17.2`、goals stable/true、ChatGPT 登录已核验。桌面版本 `26.1007.71326` build `20398`，更新检查返回 restart_required；本轮未重启或更新。宿主当前账户未提权；Task Scheduler Running/Automatic；名称含 Pathwise/Codex 的现存计划任务查询为空。

额度快照：Plus，五小时已用 16%、周已用 45%；仅为当时观测，不能重用作后续准入。没有消费重置额度或购买额度。桌面读取额度成功不能证明 CLI 的共享 runtime 连接正常；CLI `app-server daemon version` 实测控制 socket 失败（Windows 10050）。不启动新 daemon 伪造 idle。

原型：`scripts/goal_recovery/preflight.py`，默认禁用且没有执行/安装入口；可选 `--inspect-local` 仅尝试连接已运行 daemon 的白名单读取。它没有模型、业务数据库、Git 写入、Provider 或 scheduler API。检查通过也返回 `DISABLED_ATOMIC_RESUME_UNPROVEN`，不启动工作轮次。

本地专项命令：`python -B -m unittest discover -s scripts/goal_recovery -p "test_*.py" -v`，33 passed，3.546s。首次工具沙箱中 29 passed/4 临时 Git 初始化权限错误；原断言不变，获准宿主测试权限后 33 passed。没有 skip/xfail。真实只读演练和本 HEAD CI 尚待后续记录；不得提前报告成功。

## 恢复记录

1. 2026-10-22：读取实际 active Goal；核验 PR/main/CI；#46 未合并，因此 G1 停止，未改正式产品代码。
2. 2026-10-22：完成 CLI/桌面/认证/额度/任务计划服务核验；发现共享 daemon 连接限制；未调用 turn/start、exec/resume、Goal set/clear 或额度重置接口。
3. 2026-10-22：建立独立 G0 worktree、默认禁用原型、33 项隔离测试和双平台 CI 候选。下一步：提交检查点，真实只读演练，Draft PR、精确 HEAD CI，然后再次核验 G1 门槛。

每次后续记录必须区分实际执行与合成测试。若真正遇到额度拒绝，记录 RATE_LIMITED、原 attempt ID、准确停止原因与可用的 reset 提示；不得将限额停止记成完成。过期 reset 提示不是恢复许可，必须重新读实时额度和 Goal/runtime。无法记录时不自动再执行，交人工核对。

## 下一轮执行顺序

1. 先检查 active Goal、当前用户暂停/审批状态、Git 锚点和工作区，再读本文证据的新鲜度。
2. 完成 G0 只读演练、CI 和独立审查；自动恢复启动能力仍缺证据，保持禁用。
3. #46 合并后重新 fetch，确认 merge 在最新 main 的祖先链；该 main HEAD 的 workflow 及三个应用作业全部成功才解锁 G1。若其间 main 漂移重新核验，不沿用旧 SHA。
4. G1 仅移植 NEXT_STAGE_PLAN.md 固定的五文件；新分支/新 Draft PR 为首选。保留原 #47，禁止 force push/删除；新增结果必须是包含已合并 c3b 的真实回归，不能沿用旧 2261 数量。
5. G2 按四个独立候选交付逐步推进；正式 writer/classify/related_plan/迁移/生产工厂/Provider/部署全部关闭。

所有 Ready、Merge、Deploy，以及调度器安装/启用均等待用户单独审批。Goal 未完成；不会因为 G0 测试通过而将 G1/G2 删减出目标。

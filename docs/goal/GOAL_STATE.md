# Pathwise 下一轮持续开发检查点

最后核验：2026-10-23 UTC。这是人工可审计、Git 版本化的检查点，**不是恢复授权、进程存活证明或额度凭证**。原生 `get_goal` 实际返回 null，不能沿用旧记录的 active。用户已授权本轮普通工程工作；原生 Goal 注册/恢复由用户通过受支持控制确认，本预检不得代为设置。G1 已由合并的 #49 完成，#47 已关闭。G2 尚无已交付原型；G2.1 仅保留未提交隔离候选。

## 机器可读状态

此文档只允许一个 JSON 块。`enabled=false`、`scheduler_approval=NOT_APPROVED` 是本版固定合同，改为 true/APPROVED 会拒绝解析，没有启用开关。下一版执行器必须另行审查和审批。

```json
{
  "contract": "goal-recovery-preflight-v1",
  "state": "APPROVAL_BLOCKED",
  "enabled": false,
  "thread_id": "01a1542e-e712-7f21-b0ae-831becbeec32",
  "branch": "codex/goal-recovery-preflight",
  "checkpoint_parent_head": "f28da72740aefaf5b792ed898e2ff54bd2c7bc37",
  "last_successful_commit": "f28da72740aefaf5b792ed898e2ff54bd2c7bc37",
  "current_subtask": "G0 status refresh; G1 complete; G2 candidate engineering authorized",
  "next_instruction": "Recheck native Goal: last get_goal was null, not active. Do not create/clear/resume it or bypass any budget. User must confirm native Goal via supported controls. Ordinary authorized G2 engineering can proceed; do not redo merged PR49 or closed PR47. Deliver separate G2.1-G2.4 candidates with exact-HEAD tests/CI and update this checkpoint. Scheduler remains disabled.",
  "blockers": [
    "NATIVE_GOAL_NOT_REGISTERED",
    "SHARED_CLI_RUNTIME_UNAVAILABLE",
    "ATOMIC_IDLE_TO_RESUME_NOT_PROVEN",
    "SCHEDULER_NOT_APPROVED"
  ],
  "scheduler_approval": "NOT_APPROVED",
  "not_before_utc": 0,
  "last_attempt_id": "g2-g0-status-refresh-20261023"
}
```

检查点提交自身的 SHA 不在自己的内容中循环引用。解析器用 `git log -1 --format=%H -- docs/goal/GOAL_STATE.md` 求提交锚点，要求 HEAD 等于锚点、锚点父提交等于 `checkpoint_parent_head`、分支匹配、工作区干净，并对照 Git 中的原始检查点。每个新的成功检查点提交更新 parent 和记录；独立提交后忘记更新检查点会停止，不能自动 stash/reset/clean。`last_successful_commit` 表示已有完整测试及 CI 的上一交付，不是当前 HEAD 的替代品。

## 已核验基线与 PR

- main：`b96581175f4a2a307a7cfcfb7d60d1609d83983d`，远端 API 与 fetch 一致。[main CI 39963621888](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39963621888) 精确匹配该 HEAD，workflow、FastAPI、React、Chromium 全部 completed/success。
- [#44](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/44) 已合并，merge `09d221232ab3cbf0bd6d8c810744b6555476144d`。对应 [main CI 39791415411](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39791415411) 的 workflow、FastAPI、React、Chromium 全部 completed/success。
- [#45](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45) 已合并为 `698b8aed005d826af7a0767def3559637cff32fb`，是当前 main 的祖先。
- [#46](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46) 已合并为 `a1c448dd837fc4036e3e4faf0c025b82e980508c`，源 HEAD `fc9286e8f1b8e0e62f6d59d2821584391d03fd88`。旧 PR46_NOT_MERGED / POST_PR46_MAIN_CI_NOT_AVAILABLE 门槛已移除。
- [#49](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/49) 已合并为当前 main，完成原 G1。其源 HEAD `ca056063c66ca94ec6e8c73744897d149e77ac6a` 的 CI 39953860759 全绿，真实本地后端 2332、React 158、E2E 59；Linux 2331+1 既有 Windows 平台 skip。仅五文件，三 Python blob 保留 M3 typed fid 补测，#46 文件未重复引入。
- [#47](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/47) 已作为被 #49 替代的重复交付关闭，未合并；HEAD 仍为 `2dc0c6158072438f16eeca181be1d882c77b20a0`。不用重做、重新打开或强推。

G0 worktree：`.e2e/worktrees/goal-recovery-preflight`，分支 `codex/goal-recovery-preflight`，原分支基线仍是 main 698。本轮只刷新文档，不 rebase/merge main，不因基线变动更改脚本安全判断。仓库根仍保留 #47 历史 checkout；它不是本轮开发基线。

本轮 [Draft PR #48](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/48) 包含 G0 和 G1/G2 计划；首个提交 `66c7d2e88a9dc9d6ab0676a33313c77a502bf2e0`，本检查点为其演练证据后继。最终 HEAD 用 Git 锚点及 PR API 核验；CI 结果按 SHA 在 PR 说明更新，不将 pending 当成功。

上一已验证交付为 `f28da72740aefaf5b792ed898e2ff54bd2c7bc37`，[CI 39803535806](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39803535806) 的 Windows/Linux 33 项预检全绿。last_successful_commit 指向它。当前后继检查点自己的专项/CI 需按新 HEAD 单独记录，不沿用旧 CI。

## 当前结果与未完成项

2026-10-23 本轮重新执行：CLI `0.162.0-alpha.17.2`；`login status` 显示 ChatGPT；`app-server daemon version` 仍因 Windows 10050 无法连接既有共享 socket。原生 Goal 当前为 null。此前 goals stable/true、桌面版本 `26.1007.71326` build `20398`、restart_required、Task Scheduler Running/Automatic、计划任务查询为空均为 2026-10-22 历史观测，本轮未重启、更新或安装调度器。

额度快照：Plus，五小时已用 16%、周已用 45%；仅为当时观测，不能重用作后续准入。没有消费重置额度或购买额度。桌面读取额度成功不能证明 CLI 的共享 runtime 连接正常；CLI `app-server daemon version` 实测控制 socket 失败（Windows 10050）。不启动新 daemon 伪造 idle。

原型：`scripts/goal_recovery/preflight.py`，默认禁用且没有执行/安装入口；可选 `--inspect-local` 仅尝试连接已运行 daemon 的白名单读取。它没有模型、业务数据库、Git 写入、Provider 或 scheduler API。检查通过也返回 `DISABLED_ATOMIC_RESUME_UNPROVEN`，不启动工作轮次。

本地专项命令：`python -B -m unittest discover -s scripts/goal_recovery -p "test_*.py" -v`，33 passed，3.546s。首次工具沙箱中 29 passed/4 临时 Git 初始化权限错误；原断言不变，获准宿主测试权限后 33 passed。没有 skip/xfail。真实只读演练已完成，见 [RECOVERY_REHEARSAL.md](RECOVERY_REHEARSAL.md)；结果为安全拒绝，自动恢复未验证。本 HEAD CI 以 PR 的精确 SHA 结果为准，未核验前不得报告成功。

## 恢复记录

1. 2026-10-22：读取实际 active Goal；核验 PR/main/CI；#46 未合并，因此 G1 停止，未改正式产品代码。
2. 2026-10-22：完成 CLI/桌面/认证/额度/任务计划服务核验；发现共享 daemon 连接限制；未调用 turn/start、exec/resume、Goal set/clear 或额度重置接口。
3. 2026-10-22：建立独立 G0 worktree、默认禁用原型、33 项隔离测试和双平台 CI 候选。下一步：提交检查点，真实只读演练，Draft PR、精确 HEAD CI，然后再次核验 G1 门槛。
4. 2026-10-22：66c7d2e 上真实默认/本机只读演练：Git 匹配，runtime 不可用，安全停止；HEAD/status/检查点 SHA256 不变，scheduler=0、测试 DB listeners=0。创建 Draft #48；没有启动任何恢复工作轮次。
5. 2026-10-22：66c7d2e Windows/Linux CI 成功；再次查询 #46 仍未合并。G1 门槛未解除。
6. 2026-10-22：f28da727 的 [CI 39803535806](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39803535806) 已核验同 HEAD、Windows/Linux 全绿；last_successful_commit 更新为此提交。
7. 上一 Goal 轮次发生 **RATE_LIMITED**：创建 G2.1 worktree 的命令被自动审批服务因使用限额拒绝执行；不是安全判定失败。没有创建分支/worktree，没有绕过审批或启动模型恢复程序。工具当时提示可在 2026-10-23 02:02（客户端本地时间提示）后重试；该提示不代表额度恢复许可。
8. 2026-10-22 17:16 UTC（北京时间 2026-10-23 01:16），新的 Goal continuation 读取实时账户状态：ordinaryUsageAllowed=true、五小时已用 8%、周已用 1%。这只证明当前普通额度观测，不能证明审批服务已恢复。实际 worktree 列表确认 G2.1 目标不存在；main/#46/#48 状态未变化。当前 Goal 仍 active；恢复创建操作必须通过当下正常审批，不根据旧 reset 时间、锁文件或本检查点自行放行。恢复调度器始终未启用。

每次后续记录必须区分实际执行与合成测试。若真正遇到额度拒绝，记录 RATE_LIMITED、原 attempt ID、准确停止原因与可用的 reset 提示；不得将限额停止记成完成。过期 reset 提示不是恢复许可，必须重新读实时额度和 Goal/runtime。无法记录时不自动再执行，交人工核对。

### 2026-10-23 最新恢复记录（覆盖上方历史门槛状态）

9. G2.1 worktree 已通过正常审批创建在 `.e2e/worktrees/typed-declaration-read-candidate`，候选 39 项合成测试通过。第一次提交因作者标识缺失失败，随后命令等待审批期间被用户中断；没有已核验的 G2.1 提交、推送或 PR。保留 staged 文件，不擅自清理。恢复程序始终默认禁用；该正常 continuation 不是自动恢复能力证明。
10. 用户明确授权开始 G1。再次独立核验 #46 已合并为 main `a1c448dd837fc4036e3e4faf0c025b82e980508c`；指定 main CI `39889913523` 精确匹配，workflow、FastAPI、React、Chromium 全部 completed/success。上次中断没有创建 G1 worktree。沙箱执行器报 setup refresh 错误，正常宿主审批后只读核验成功；Git 直连 TLS 失败，通过现有本机代理且保留 TLS 验证获取成功。
11. 建立 `.e2e/worktrees/pr47-independent-model` / `codex/pr47-independent-model`，直接父提交为上述 main。仅移植固定五文件；三个 Python 文件与原 #47 的 blob 完全相同，保留 typed fid 补测；两份文档只修正基线并解释保留的补测。#46 的五文件与 main 逐项 blob 一致。没有 cherry-pick/merge #46 历史。
12. 新建 [Draft PR #49](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/49)，HEAD `ca056063c66ca94ec6e8c73744897d149e77ac6a`，一个新提交、五个新增文件、991 additions/0 deletions。原 #47 保持原 HEAD/base/分支、open/Draft，不强推、关闭或删除。专项 132 passed；React 158 passed、build/types 通过；真实本机 Chromium/PostgreSQL E2E 59 passed；隔离迁移/12/48/质量脚手架/Mock 通过，Provider/cost=0。完整后端尚在运行，CI `39953860759` 尚待完整终态，不能记为已通过。G1 完成后按本次用户要求停止等待独立审查。
13. G1 最终验证：本机完整后端 **2332 passed**，1160.04s，无平台 skip；[CI 39953860759](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39953860759) 精确 head_sha 匹配 `ca056063c66ca94ec6e8c73744897d149e77ac6a`，workflow 与三项作业全部 completed/success。Linux 后端 **2331 passed + 1 既有 Windows 平台 skip**，1765.41s；React 158、bundled Chromium 59，以及迁移/12/48/质量/Mock 均通过。原 #47 与最新 main 再查未变。两个合成库临时 Schema/角色为零，专用集群已停止，端口释放。#49 PR 说明已更新最终证据；本检查点尚为本地修改，不声称已提交或通过新的 #48 CI。按用户要求停止等待复审，G2 未交付项仍保留；整体 Goal 未完成。

## 下一轮执行顺序

本轮状态刷新证据：2026-10-23 再次核验 main/#44/#45/#46/#47/#48/#49；main CI 39963621888 同 SHA 全绿。原生 Goal=null；未 set/clear/resume。CLI 仍为 0.162.0-alpha.17.2、ChatGPT 登录，共享 daemon 仍为 Windows 10050。G0 原专项 **33 passed，3.595s**；本提交只改三份文档，脚本、测试与 workflow 无 Diff。检查点 JSON 字段/状态枚举未变，APPROVAL_BLOCKED 只阻止自动预检放行，不撤销用户的普通工程授权。新提交与双平台 CI 将在 #48 说明中按精确 SHA 记录；未知或 pending 不作成功证据。

1. 先读原生 Goal 和预算状态，不根据文档恢复；null 不是 idle 或 active。APPROVAL_BLOCKED 是本预检的保守 veto，不是代理设置了原生 Goal 暂停。等待用户通过支持控制确认原生目标，普通已授权工程工作可继续。
2. 完成 #48 文档更新、33 项专项及新 HEAD 双平台 CI；脚本与测试保持原 blob。自动恢复启动能力仍缺证据，保持禁用。
3. G1 已完成并合并；#47 已关闭。保留历史记录，禁止重复移植或重开旧 PR。
4. 从已核验 main 开始 G2.1 Python/TS 隔离读取合同，再推进 G2.2 澄清、G2.3 数据库约束设计/隔离参考测试、G2.4 合成 React 旅程。现有未提交 G2.1 候选先审计再复用，不当作交付成果。
5. 每个里程碑用独立 Draft PR、真实专项与 CI 更新检查点。下一项在用户授权内继续，不再沿用上一轮“交付 #49 后等待”的过期工程停止点；原生 Goal/预算控制始终由实际状态约束。

所有 Ready、Merge、Deploy，以及调度器安装/启用均等待用户单独审批。Goal 未完成；不会因为 G0 测试通过而将 G1/G2 删减出目标。

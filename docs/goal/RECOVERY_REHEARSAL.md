# G0 实际演练记录

执行日期：2026-10-22 UTC。代码/检查点 HEAD：`66c7d2e88a9dc9d6ab0676a33313c77a502bf2e0`，branch `codex/goal-recovery-preflight`，base main `698b8aed005d826af7a0767def3559637cff32fb`。本记录是后一检查点提交，不声称先前演练覆盖尚未存在的代码改动；本记录之后如修改脚本须重新演练。

## 本机命令与结果

在独立 G0 worktree，使用仓库已有 Python 3.12 环境：

```powershell
& 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\apps\api\.venv\Scripts\python.exe' -B -m unittest discover -s scripts/goal_recovery -p 'test_*.py' -v
& 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\apps\api\.venv\Scripts\python.exe' -B scripts/goal_recovery/preflight.py --repo .
& 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\apps\api\.venv\Scripts\python.exe' -B scripts/goal_recovery/preflight.py --repo . --inspect-local
```

- 单元/临时 Git 测试：33 passed，3.546s，无 skip/xfail。包含合成额度/429/状态场景；没有真实模型调用。
- 默认模式：mode=DISABLED，Git clean=true、matches=true，checkpoint_commit=head=66c7d2e，decision=SHARED_RUNTIME_UNAVAILABLE（默认不探测 runtime，因此没有存活证据）。
- 真实本机探针：mode=READ_ONLY_INSPECTION，Git clean=true、matches=true；probe_code 和 decision 均为 SHARED_RUNTIME_UNAVAILABLE。只尝试既有共享 daemon，未启动新 app-server。此前 `codex app-server daemon version` 同样返回默认 control socket 无法连接 / Windows 10050。
- 两种输出均为 execution_enabled=false、model_turn_started=false、automatic_resume_proven=false；没有调度器变更或 Git/业务写入。
- 宿主只读复核：HeadUnchanged=true、WorktreeUnchanged=true、CheckpointUnchanged=true（前后 SHA256 相同）；名称含 Pathwise/Codex 的 SchedulerTaskCount=0，合成 DB 15487 端口 TestDatabaseListeners=0。

此演练没有通过访问 owner 数据库、付费 Provider、修改认证或沙箱来绕过失败。测试命令使用宿主权限只为临时 Git 初始化/清理；未修改模型沙箱设置。真实探针不请求账号重置/切换/购买或 Goal 状态更改。

## 失败与不能推导的结论

最初在当前工具沙箱执行同一测试，29 项通过，4 项临时 Git 初始化被文件权限拒绝，临时目录清理也受限；使用获准宿主测试权限运行原测试后全部通过。没有将失败改为 skip/xfail，也没有扩宽时间或改断言。

已证明：本机可识别 CLI/Goal 支持与当前 Plus 登录；默认禁用预检在已有 Git 检查点上一致；实际 runtime 探针失败时不启动任务；纯政策函数对合成错误保守停止。

未证明：CLI 可可靠读当前桌面线程的 live 状态、CLI 在线认证/额度全链、真实五小时/周限额后的调度唤醒、单次原子派发、模型进程崩溃后的 journal 恢复、用户暂停与调度竞争。没有进行真实 exec/resume 或 scheduler 安装，所以不能报告自动恢复已经可用。

## 审查与后续

[Draft PR #48](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/48) 的 Goal recovery preflight checks 在 Windows/Linux 跑相同的 33 项无账号测试。CI 证明跨平台原型逻辑，不证明宿主认证/daemon/调度器能力。每个 head_sha 的真实 CI 地址与终态在 PR 说明记录。

首个提交 66c7d2e 的 [CI 39802741779](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39802741779) 已核验 workflow、Windows 与 Linux 均 completed/success。

后续只有在共享 runtime 与原子单次派发边界得到支持接口及实测证据后，才能提交执行器候选。任何安装/启用调度器必须重新列出实际命令、账户权限、日志与安全影响，再等待用户审批。当前保留人工检查和受支持的 Goal 恢复方式，绝不替换为付费密钥或绕过限额。

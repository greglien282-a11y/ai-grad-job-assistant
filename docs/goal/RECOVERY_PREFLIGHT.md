# G0：默认禁用的恢复预检候选

证据范围：本机环境核验、受控只读探针、纯政策函数及临时 Git 测试。**自动重启工作轮次尚不可用**。本版没有 `--run`、`--enable`、定时任务安装器或外部新密钥入口。

## 支持接口与实际限制

本机此前 `codex exec --help`、`codex exec resume --help` 确认非交互执行及显式 session ID 恢复接口；2026-10-23 CLI 复查仍是 `0.162.0-alpha.17.2`，`login status` 仍为 ChatGPT。历史 features list 显示 goals stable/true，但本轮原生 `get_goal` 返回 null；此前 active 不能沿用。认证方式、历史 quota 或文档 ACTIVE 均不能替代未来在线认证/额度/原生 Goal 检查。没有调用 Goal set/clear/resume。

官方依据（2026-10-22 已打开正文核对）：

- [非交互运行](https://learn.chatgpt.com/docs/non-interactive-mode)：支持 exec、JSONL 事件及显式 ID 的 exec resume；并不承诺限额到点后自动重启。
- [认证](https://learn.chatgpt.com/docs/auth)：本地 ChatGPT 订阅认证与 API key 计费是不同路径。此目标只保留既有 Plus 认证，不导出凭据，也不创建 Enterprise token/API key。
- [Goals 生命周期](https://developers.openai.com/cookbook/examples/codex/using_goals_in_codex)：Goal 是线程持久状态，继续受空闲、暂停、预算等条件约束；没有从“有 Goal”推导出掉线后必然恢复。
- [App Server](https://learn.chatgpt.com/docs/app-server)：官方提供 thread/read、thread/goal/get、account/read、account/rateLimits/read；本机生成 Schema 也存在这些方法。thread/read 的 notLoaded 不能当作 idle。
- [内置定时任务](https://learn.chatgpt.com/docs/automations?surface=app)：支持在原聊天调度，依赖机器和应用运行及可用权限。它是优先评估的候选，但没有验证 Plus 限额后自动唤醒/只执行一次的实测证据。

本机 CLI `app-server daemon version` 连接默认控制 socket 返回 Windows 10050。进程列表有 codex 进程，不能据此认定目标任务空闲，也不能根据 socket 失败认定任务死亡。禁止启动一个新的独立 app-server 再利用它的 notLoaded 判定原线程已停。桌面工具当前能读额度/Goal，但其可用性不等于独立 Windows 脚本也有同样接口。

## 原型实际做什么

默认调用只读 Git 与检查点，输出一份固定字段 JSON 到 stdout。`--inspect-local` 增加一次现有 daemon 的 metadata 探针；没有无限循环、进程自动重启或网络重试。探针版本不匹配即拒绝；stdin/stdout JSON-RPC 仅白名单五种方法，通知 initialized 只完成握手。不会请求正文历史、刷新/导出认证、清理回执、触发模型或读取项目 .env。

程序检查 `GOAL_STATE.md` 的唯一严格 JSON 块、提交锚点/parent、HEAD、分支、remote 和工作区（包括未跟踪文件）。不自动修复 Git 漂移；忽略的 `.e2e` 合成证据不作为恢复授权。计划执行程序、环境、依赖和本机 hooks 的完整固定仍需下一次执行器审查，当前不把 Git clean 当成完整环境证明。

限额判断优先多 bucket 中的 codex；缺 bucket 不回落为“无使用量”。五小时/周窗口均必须有合法百分比与 reset 时间；未知窗口形态停止。任一达到限额或服务端阻断则 RATE_LIMITED；最早后查时机取受限窗口 reset 最大值与一小时冷却的较晚值。即便 reset 已经过期仍停止，下一次必须读新快照。快照超过 30 秒、未来时间、身份未知、Goal 暂停/完成/blocked/usageLimited/budgetLimited 都不能执行。

`stopped_attempt` 仅演练未来 journal 的停止策略：429→RATE_LIMITED；鉴权/审批错误→APPROVAL_BLOCKED；失败/传输结果未知→BLOCKED；成功一轮也只保留 ACTIVE。所有情况本进程不重试。**这些合成输出不是一次真实模型执行或持久恢复日志。**

## 八项恢复要求的证据边界

1. 防重入：合成用例证明 active/unknown/notLoaded 会阻止候选。真实共享 runtime 尚不可读，且 CLI read→exec 无已验证原子空闲租约；未实现可宣称的实际防重入执行器。单独 PID/锁文件不足，不能据此重启。
2. 检查点和 Git：实际临时 Git 仓库验证正确锚点、未跟踪文件、错误分支/parent、未更新检查点的提交都会按合同处理。正式 worktree 另做只读演练。
3. 认证：已核验桌面 Plus 登录与实时额度；原型候选要求 live account 与 live quota 同时成功。不读取凭据内容；CLI 端全链尚未完成。
4. 429/限额：纯函数测试已覆盖；没有制造真实账户限额或消费一次模型请求来碰运气。实际 exec 事件处理器尚未接入。
5. 调度：Windows 服务可用、内置工具存在；尚未注册任何调度。仅提出下节候选，不因等待时间经过而擅自开始。
6. 一次受限工作轮次：**未实测且本版不提供**。缺共享 live-state、安全原子准入以及“单轮结束后 active Goal 不继续扩张”的验证。只读探针成功也不能授权启动。
7. 日志与退避：真实 stdout 可由操作者保存到本地 ignored 证据目录；原型不写凭据、正文、原始异常。未来写前 attempt journal、崩溃后不确定结果核对、持续限额退避及进程树回收仍待实现。
8. 停止状态：检查点和 live Goal 任一 veto 都停止；不会 set Goal active、清理审批或替换旧 attempt ID。手动恢复遵守实际客户端 `/goal resume` 生命周期，不把 slash 字符串当 exec 的控制 API。

## 可执行的无工作副作用演练

在本 G0 worktree，使用已安装 Python：

```powershell
& 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\apps\api\.venv\Scripts\python.exe' -B scripts/goal_recovery/preflight.py --repo .
& 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\apps\api\.venv\Scripts\python.exe' -B scripts/goal_recovery/preflight.py --repo . --inspect-local
```

第一条不启动 CLI。第二条只启动自己的 stdio proxy 连接现有 daemon，超时只终止该 proxy，不操作 daemon/其他工作进程。标准 CLI 可能产生自己的临时运行文件；这里“无副作用”准确指零业务/模型/调度/Git 写入，不声称宿主操作系统完全无 I/O。不得把进程退出码 0 当成恢复成功，应读取固定 decision；mode=DISABLED 或 READ_ONLY_INSPECTION 均不是工作轮次成功。

检查前后记录 Git HEAD/status 与检查点 SHA256；核对没有新任务、模型轮次或数据库操作。测试 `python -B -m unittest discover -s scripts/goal_recovery -p "test_*.py" -v` 在 33 项中包含真实临时 Git 演练、代理失败只尝试一次以及修改接口白名单的反例。Linux/Windows CI 只运行这些无账号测试，不接触宿主账号或真实 daemon。

## 调度候选与审批清单（未安装）

优先在当前聊天内使用官方 heartbeat，而不是另建不相关线程。用户审批前不创建 automation（即使 PAUSED 也不创建）。需先证明：限额发生时不会丢失 checkpoint，重新调度能读取有效额度，当前任务仍在执行时不会重复派发，用户暂停/审批阻塞不会被定时器恢复。当前不能承诺这一链路。

Windows Task Scheduler 可作为后续受控**只读巡检**候选。实际 action 将是上述 Python `-B ... --inspect-local`，WorkingDirectory 固定本 G0 worktree；它不会恢复开发。建议当前登录用户 InteractiveToken、RunLevel Limited、不保存密码、MultipleInstances IgnoreNew、不使用 SYSTEM 或 Highest、不唤醒机器、不在错过时间后补跑、不配置失败自动重试。具体触发时间/周期须用户批准后填写，不能自行选择。公开仓库不保存主机账户标识或任务凭据。

注册模板（不是可运行安装脚本，`$approvedTrigger` 必须来自用户批准的时间；本轮未执行）：

```powershell
$goalRoot = 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\.e2e\worktrees\goal-recovery-preflight'
$goalPython = 'D:\AI Graduate Job Search Assistant\ai-grad-job-assistant\apps\api\.venv\Scripts\python.exe'
$goalAction = New-ScheduledTaskAction -Execute $goalPython -Argument '-B scripts/goal_recovery/preflight.py --repo . --inspect-local' -WorkingDirectory $goalRoot
$goalPrincipal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$goalSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 2)
# Only after separate approval and an explicitly approved trigger:
# Register-ScheduledTask -TaskName 'Pathwise-Goal-Preflight' -Action $goalAction -Principal $goalPrincipal -Settings $goalSettings -Trigger $approvedTrigger
```

安全影响：只读巡检仍可访问该用户已有 Codex 认证上下文和 Git 元数据；不会复制认证，但应审查 CLI 路径、脚本/工作区完整性和日志 ACL。任务只能防自身重入，不能解决桌面 Goal 同时启动的竞争。它不是自动恢复能力的替代证明。当前未申请安装；先保留人工检查/恢复路径。

真正允许未来执行时，官方候选命令形状是 `codex --ask-for-approval never --sandbox workspace-write -C <approved-worktree> exec --json resume <explicit-session-id> <bounded-instruction>`；不得使用 --last、full access、bypass、ignore-rules、API key 或不同账号。仅列出接口形状，**没有运行过且不保证其与当前 active Goal 的单轮上限兼容**；正式 runner 必须解决上述未完成项、审查 JSONL 终态、预算/超时/子进程与人工审批退出语义后才可提交启用审批。

## 持续 BLOCK

自动重启与 scheduler 启用、R03、D4/D5 正式批准、D6 剩余、D8、typed writer、classify、related_plan、born-contract/新迁移、生产工厂/角色、真实 Provider、付费调用和部署均未开放。G1 #46/main gate 已解除且 #49 已合并，不再作为当前阻塞。原生 Goal 当前为空需要用户通过支持控制确认；不替它创建或解除预算/暂停。单元测试和可用 Plus 额度不能解除安全或生产 BLOCK。

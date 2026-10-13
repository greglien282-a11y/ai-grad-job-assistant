# M1-1B 幂等修复（独立 Draft PR）

基于 main `f52df79`，分支 `codex/m1-1b-idempotency-fix`。按 [批准的合同 v2](https://github.com/greglien282-a11y/ai-grad-job-assistant/blob/21fca42cf7dfa123020f9f5c6a794a3297c6e5d5/docs/M1_1B_3_IDEMPOTENCY_PROPOSAL.md) 与 [设计批准 Review](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/5#pullrequestreview-5505636662) 实现，不合并 PR #5、不关闭 Issue #1。

## 业务行为

- 三个创建 POST 可选 Idempotency-Key；无键旧客户端行为兼容。幂等创建前使用 Web Crypto 生成候选 Bearer和带时间戳/作用域校验码的随机键；活会话只存 token hash。
- POST 发送前写入并回读验证 sessionStorage pendingCreate，仅含版本、键、token、带密钥请求标签和期限，不含经历正文。存储或加密能力不可用时零创建请求。
- 创建结果不确定时仅自动执行一次只读 `GET /api/v1/experience/session-creations/recovery`；成功恢复后先验证并保存正式会话 ID/token，再移除 pending。提示用户核对，不伪装原 POST 正常返回。刷新只读恢复；未找到结果时需要重新输入完全一致的原正文并明确同键重试，不自动 POST/换键。
- 24 小时仅是当前标签页的临时恢复窗口，不是账号恢复。到期、关闭标签页或清空存储后，实际已创建的匿名会话可能无法找回；不自动删除未知业务数据。正式 sessionStorage 凭证不因操作键到期而失效。
- 新增回合与事实分别保留稳定键。当前页丢响应后手动同键重试，只返回原回合或当前事实；刷新先读聚合，孤立补充回合可明确选用，不自动补发。选用已有回合时不允许改变陈述后仍借旧回合作当前来源。
- `409 idempotency_payload_mismatch` 不触发旧事实版本冲突自动读取；保留输入/键，提示恢复核对。PATCH version/state 冲突仍沿用原流程。429/带 Retry-After 的 503 暂停客户端网络请求，不能提前或自动重试写入；410 停止原操作，明确新操作前不会重建。

## 数据库与原子性

新增迁移 `0003_idempotency`，从 `0002_fact_version` 升级；不改既有业务表和数据。新增 idempotency_operations：256 位 key_digest 主键、state、expires_at索引；活行附加操作、session_id索引、target_id、request_tag及结果 ID。没有请求/响应全文、明文 token 或额外 token hash。

完整键摘要唯一约束 + PostgreSQL 事务级 advisory lock + 父行锁，共用现有 function-scope 事务。恢复 GET与同键 POST共用锁，等待上限 5 秒；锁后/父锁后/提交前重核期限。同键并发只写一次，正文不一致返回专用 409，失败全部回滚，锁超时安全 503。成功重放为 201 + Idempotency-Replayed，GET 为 200；事实返回当前版本/来源，不能把后续 B 编辑回 A。结束后旧成功结果可读，新写仍拒绝。

删除父会话同事务清空全部活操作的关联 ID和请求标签、转为墓碑，再删除经历、回合、事实、来源、材料、历史及会话 token hash。墓碑只剩 key_digest/state/expires_at；无正文摘要、凭证摘要或归属 ID。旧原创建键必须持合法 Bearer/proof才能识别删除并得到无内容 410；其他写接口仍先授权。

键按 issued_at + 24h 截止，不因重放或删除延长；允许客户端最多提前 5 分钟。墓碑物理清理后，原过期键仍被时间守卫拒绝，不能复活数据。

## 迁移及清理运行

在选定环境的 `apps/api`，先设置其私有 DATABASE_URL。不要将密码/URL粘贴到公开日志。项目已有 `.env` 启动器会读取该文件；Alembic CLI 本身需要显式环境变量。

```powershell
# 确认目标环境和私有 DATABASE_URL 后
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m app.cleanup_idempotency
.venv/Scripts/python.exe -m app
```

开发启动执行一次清理，失败则停止启动，不静默忽略。部署方必须按小时执行 `python -m app.cleanup_idempotency`，监测非零退出码并告警；本轮提供命令及失败测试，不安装 Windows 定时任务、修改系统服务或部署生产调度。正常每小时调度时，过期行在到期后 1 小时内物理清除；任务未运行/失败不能声称达成该期限。清理仅删除过期操作元数据，不删除活会话或用户资料；输出只有删除条数和最老过期时间，失败信息不带连接/正文。

本轮空 schema upgrade/check/downgrade/upgrade和已有已确认事实升级均在真实 PostgreSQL 测试中通过；未对日常 pathwise_dev 执行迁移或数据清理。CI 保留 upgrade/check并增加清理命令烟雾检查。

## 回归与 PR #5 组合验证

- 后端真实 PostgreSQL：56 项通过，保留 main 原 40 项。新增重复/不同正文、错凭证/键/时钟、只读恢复、多连接并发、真实等待及 5 秒锁超时、部分写入回滚、提交前过期、删除竞争、墓碑约束/清理/失败监测、当前来源及共享签名向量。
- 前端：35 项通过，保留原 21 项目标。覆盖发送前暂存、丢201只读恢复、刷新零POST、原正文标签门禁、存储/随机数失败、迁移失败保留pending、回合/事实稳定重试、专用409、过期/删除、显式孤立回合选择、Retry-After；TypeScript/Vite构建通过。
- Windows Edge真实组合验证：16项通过，包含 PR #5原11项及本PR新增5项。只用合成数据，真实React/FastAPI/PostgreSQL、独立端口与新测试schema。原两项失败断言原样变绿，不使用skip/expected failure。

新 Chromium CI作业在 `.e2e/harness` 检出 PR #5已审查的固定提交 `21fca42`，再运行 `scripts/prepare-idempotency-e2e.py` 叠加本修复代码与新增测试。脚本验证原两个 spec文件的 Git对象/文件哈希，不能改变原11项断言。仅调整组合检出的迁移 head和测试schema重置（先删除操作元数据再清合成会话，避免FK阻止测试清理），不提交/推送该检出，不改PR #5。专用数据库的普通角色与随机密码由原隔离引导生成，默认无trace/视频，仅上传合成截图。

本修复不把 PR #5基础设施整包提交到 main。新增 E2E spec单独保留在本分支，其执行入口为上述组合检出；等修复被人审查合并后，再更新/rebase PR #5进行正式验收。

本机复现可创建固定提交的独立检出，再运行 prepare 脚本，进入该检出的 apps/web安装锁定依赖，配置原Python3.12虚拟环境路径、专用测试连接和显式 msedge 通道后运行原 `npm run test:e2e`。不要直接在日常服务或数据库执行 Playwright；缺少隔离配置时启动器应停止。最终 CI状态及提交号记录在 Draft PR，人工体验仍待反馈。

构建保留 Zod依赖注释移除提示；Pytest保留现有 TestClient/httpx弃用提示。没有接入 AI、变更原产品PRD或静态prototype/Pages。

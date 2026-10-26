# G4-0D：真实一次性数据库体验与 G4 结论

main 基线 `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`。本候选依赖 #56（可信边界）→#57（真实旧 CO）→#58（R03 观察），只交付独立研究演示，不接入正式业务。每个 PR 精确 HEAD/CI 在说明与最终 handoff 核验，不将别的 SHA 的成功当成当前成功。

## 可以演示的真实路径

公开合成经历 → 核对完整原话 → 明确选择类型／阶段 → 独立进程有限校验 → 真正受限 LOGIN 暂存 → 数据库验签／完整图／COMMIT → 读取不可变选择事件 → 展示 pending 用户声明 → 模拟 COMMIT 后响应丢失 → 用户点击 GET-only 只读恢复同一结果。

这次不是 G2 的内存保存。每次启动创建随机 PostgreSQL Schema、随机 owner/LOGIN 和合成签名密钥，实际图进入该测试库；关闭演示清理本次数据与角色。浏览器不持有数据库密码、Bearer 或签名密钥；没有正式账户、CO3、Provider 或真实招聘数据。

页面在启动时就明确上述范围；plan/planned、in_progress、background、boundary 始终显示原分类和 pending，不冒充完成贡献或平台认证。只有公开列出的合成样例可进入演示，不做自由经历表单。UI 没有批准 R03、confirm、force、classify、related_plan 或正式导出按钮。

## 启动（本机测试库已准备时）

Python 依赖沿用 `apps/api/requirements.txt`，前端在 `research/g4_disposable_demo/web` 独立安装/build。原正式工作台和旧研究页面未改动。

```powershell
# 仅专用 loopback 合成库，绝不能替换为生产连接。
$env:G4_DEMO_TEST_DATABASE_URL='postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
cd research/g4_disposable_demo/web
npm ci --ignore-scripts --no-audit --no-fund
npm run build
cd ../../..
python -B -m research.g4_disposable_demo.server --synthetic-disposable --port 18174
# 打开 stdout 给出的 http://127.0.0.1:18174
# 在启动终端输入 STOP，或 Ctrl+C，等待完成清理。
```

没有 URL／确认参数就拒绝启动。数据库名/地址复用未放宽的 G3 测试 fixture 检查，只能是 loopback pathwise_test/pathwise_g3；这是测试 provisioner，不是生产 factory 开关。测试生命周期复用 pytest fixture 的底层 generator，不另造可能漏清理的角色安装器。owner 仅在 HTTP 启动前 provision、退出后 teardown；正常提交/恢复由真实限权 LOGIN 执行。

服务器只绑定127.0.0.1；校验精确 Host，POST 校验精确 Origin 和 HttpOnly/SameSite=Strict 的临时研究 cookie；无 CORS、凭证 URL、第三方脚本或日志正文。页面 CSP 限同源，body 限长，只服务自身 build 目录。不是公网安全认证或真实账户身份。部署、TLS、多用户隔离、进程沙箱、密钥托管均未授权或验证。

## 恢复和失败语义

每次 demo 生命周期只支持一个已提交操作。浏览器先在内存中产生 key，服务端保留同 key 的原 body/selection IDs；失败且确认未写入可以由用户修改声明后再提交。成功或未知时禁用新写按钮，不能自动换 key、重放或重试写入。页面内存和服务端进程在演示关闭后不可恢复；没有伪装成跨重启的正式恢复系统。

“模拟响应丢失”确实先 COMMIT，再关闭 HTTP 连接而不发成功结果；UI 显示 unknown，只开放 GET 恢复。它不调用 POST 或重新签名。恢复沿用 G4 admission / G3 recover/project，一次 SELECT-only RR/READ ONLY，复用严格 G3 batch 解析。新 envelope 只属 demo，必须是 `g4-disposable-read-v1`、研究 scope、pending/v1、explicit typed、有明确事件且与 operation 一致；没有改变正式 FactV3/SummaryV2/ExportV2。

未知合同、缺少当前来源或网络断开清空待展示结果，不混拼旧响应或 fallback v1。独立服务已拒绝且事务回滚时明确“本次未保存”；数据库连接或已提交后读取异常只叫未知／待只读核对，不能谎报未保存。提交 API 的实验路径 `/candidate` 不是 Pathwise 路由，没有被 apps/main 导入。

测试控制管道 EVIDENCE 在请求完成后由测试 provisioner 读取全表摘要／计数；不是 HTTP 端点，也没有给 reader 增加额外权限。浏览器通过它核对真实 Fact/permit 存在及 GET 前后全表相同。正常提交绝不使用 owner。

## 真实验证与平台差异

- Python HTTP 专项4项：真实计划→completed 拒绝、用户明确 plan/planned 后提交；真正响应丢失后恢复；跨 Origin/正式路由拒绝；杀死独立 signer 后503和全表回滚。
- React/TypeScript/Vite build 实际通过。复用已审查 G3 来源解析器，没有另造宽松 typed DTO。
- 真实 Chromium7项：PG提交/事件/Unicode来源/GET零效果、丢响应不二次写、计划安全、未知合同、真实断网、缺来源、模拟503。最后两类响应污染明确是前端故障注入；独立进程不可用的真实503另由 Python HTTP 测试证明。
- 本机 Playwright 管理的 headless shell 未安装，首轮5项在启动前失败，不记成功；改用已安装的 Chrome（Chromium）channel，完整7项通过，无 retry/timeout/skip 改动。CI 另安装匹配的 Chromium headless shell重新验证。
- 全链 Python：G4 A/B/C/D + 原G3 + 原M2，实际结果由 PR 更新。原完整后端本机2340 passed/1595.66s，无skip，1既有Starlette/httpx警告；它验证未改动 apps，不替代最终新候选的精确HEAD CI。

新增 workflow 将全链真实 PG、build 与 Chromium一并运行；继承研究链完整后端、隔离迁移、12/48、质量/Mock、React/正式Chromium和旧G2回归。G0默认禁用、共享运行时历史失败没有改写成成功。

## G4 综合建议与仍然 BLOCK 的事项

**可信边界**：私有 Broker 能保护普通无写权限调用者；独立签发凭证还能阻止篡改普通适配器后伪造 verdict，值得继续审查。两者都在实际 PG 有正负例和真实进程测试；签名根/owner/OS 失陷、自然人明确选择、事实真实仍无法由图约束证明。正式代码签名、验签协议、密钥轮换／撤销／服务超时与审计需独立批准。

**真实旧 CO**：已证明真实 HMAC/跨1、2版本/旧回执GET/旧JSON升级/原删除墓碑；未证明未来独立存储的双向全局碰撞域。future-first 后旧 writer仍能提交，是保留的真实反例。必须先批准统一原子 key 域、版本分发、期限、删除和迁移，不能直接把演示接进旧API。

**R03**：可以绑定原话，完整呈现拒绝历史和可审查的无关来源论据；不能凭词表未命中、新 Turn、换key或用户声明判定语义独立。现存 PATCH/CO1/Mining 缺口、append 无关误阻断如实保留。正式独立审核人、证据标准、决议版本及不可伪造许可尚未批准。本 demo 从全新空研究 Session 开始，没有历史导入，因此不声称演示 writer已解决 R03。

**产品体验**：可在本机一次性数据库演示真正提交和恢复；不是可部署的 Pathwise typed 产品。正式数据库模型、用户明确选择事件、CO3/身份/幂等、分类修改、旧客户端和备份协议、R03决议、D6剩余及D8需要分别审批。没有正式migration、writer、classify、related_plan、生产登录/ACL、付费或部署。所有PR保持Draft，最终CI核验后停止等待独立复审。

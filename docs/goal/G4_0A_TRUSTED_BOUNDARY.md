# G4-0A：隔离可信写入边界候选

基线 main `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`，即 #55 的 squash merge。开工核验远端一致、开放 PR 列表为空、原工作树干净。该 main SHA 没有直接 workflow run；#55 源 HEAD 的成功 CI 是另一 SHA 的证据，不冒充 main 同 SHA。新候选由本 PR 精确 HEAD 的 workflow 验证。

本轮 get_goal 返回 null，用户明确要求启动后，通过支持的 create_goal 建立真实 active G4 研究 Goal。没有清除旧目标、解除暂停、设置额外预算、安装自动恢复或调度器。旧 G0 封存锚点不被当成运行许可。

## 给产品负责人的结论

G3 已证明：关系完整不等于分类声明可靠。写入身份能直接插入表时，它可以把“我计划部署服务。”保存为已完成，并谎报校验通过。

本候选把“谁能说校验通过”变成一道实际边界，而不是一列文字：

- **私有 Broker（A）**：普通调用者没有 INSERT 和受信写函数权限。只有持私有数据库身份的服务运行原窄校验器后写入。服务代码／凭据被攻破仍可造假。
- **独立校验凭证（B）**：写入身份可以暂存图，但不能提交未经独立签名的图。独立服务重跑原规则，签名绑定实际图。数据库自行重建图、校验签名、期限、版本和图约束。修改普通适配器不足以伪造签名；独立签发服务／密钥失陷仍可造假。

优先继续审核 B 的纵深隔离价值；A 更简单，但安全责任集中在一个服务。两者均不是已批准的生产协议，也不证明自然人点击、自然语言真实性或语义独立。方案 A/B 在此指**信任边界比较**，原 G3 的“事件／Turn 模型 A/B”仍保留；本实现只使用原 G3 事件图。

## 实际代码与数据库保证

`research/g4_trusted_boundary/` 复用未改动的 G3 `schema.sql`、`runtime.apply/recover`、原 c3a 验证器和随机 Schema/LOGIN 夹具。不复制语言模板，不修改 apps/ 或正式 0001–0015。

每项测试另建随机 `g4_gate_<uuid>` Schema，所有权归临时 NOLOGIN owner。额外对象仅包括 policy、permits 和四个私有函数。**不是 Alembic migration**，没有生产函数或 ACL 变更。

图中 operation 到 permit 的循环 deferred FK 强制每次 COMMIT 都有一个授权 permit。permit 的反向 FK、主键、nonce UNIQUE 防止悬空、多凭证和已提交重放。既有 G3 延迟约束继续验证 N=1/3/5 的 Fact/FC/FS/FCS/选择事件和服务端认证上下文，没有绕开它们。permit 不可 UPDATE/DELETE/TRUNCATE。

数据库 seal 从实际九表、Session 和完整 operation 重建，不采用请求传来的“成功”标志。包含 schema/domain、原话、全部 CP 引用、独立 Fact/事件/selection ID、版本、标签、key/request 摘要、认证主体和 server txid/time。存储 permit 只保留 seal 的 SHA256，不额外留下正文副本。B 签名消息为明确域、批准 validator 文件 SHA256、整数到期时间、nonce、seal hash。跨 Schema、会话、Fact、版本、原话或分类都会改变绑定。

HMAC-SHA256 采用 PostgreSQL 内置 sha256(bytea) 实现 RFC2104，没有安装 pgcrypto 或其他扩展。私钥表／HMAC 函数均不授予 writer/reader；签名比较遍历全部 32 字节。算法对照独立 Python hmac 和 RFC 样例；不是新密码算法的安全认证。合成 32 字节密钥由夹具生成，只传给独立服务和私有 policy。真实正式密钥托管、轮换、撤销和多实例一致性尚未设计。

permit BEFORE INSERT 与 deferred COMMIT 再检查受信身份、模式、批准 validator hash、期限（未来不超过 300 秒）、完整图 hash、签名；伪造 finite_rule_match 不能替代凭证。旧操作 replay 不重新签名、不依赖签发服务在线。新请求服务不可用则整个事务回滚。

G4 admission 额外校验预先配置的四个函数体指纹、owner、安全 search_path、PUBLIC/角色 EXECUTE、密钥表与permit的逐列ACL、private Schema CREATE、必须存在且精确绑定列的 validated deferred FK，以及permit全部触发器定义/启用状态。原 G3 的全部角色、列权限、触发器、TEMP 污染检查仍执行；没有为了新表绕过原检查，新对象在独立 Schema。所有 SQL 函数限定真实对象和 pg_catalog，普通身份不能替换函数或读取 policy。

## 身份与信任假设

A 普通调用身份使用无写权限 reader LOGIN；私有 Broker 才持原随机 writer LOGIN。测试明确区分这两种能力，**不声称 Broker 自身没有 INSERT**。Broker 是 Python 服务边界，不是数据库内部自然语言验证函数。

B writer 可以直接 INSERT 暂存完整图，但缺有效凭证会在 COMMIT 失败。签发方是独立 Python 服务，另有真实子进程/私有 pipe 的执行测试：子进程持合成密钥，调用端 handle 不存密钥；停止该进程后新请求零效果失败。没有公网服务、HTTP 路由或后台任务。部分参数化测试为速度用同一可信 Issuer 类直接调用，它们证明逻辑与数据库约束，不证明 OS 服务隔离。

操作系统、provisioner、NOLOGIN owner、批准代码／manifest 和密钥托管均受信。持超级权限或签发密钥的人可以改变边界；数据库不能证明可信程序真的由未被篡改的二进制执行。文件 hash 拒绝未经批准的版本，但不能防御一个同时修改校验器、版本判断与部署权限的内部攻击者。单独篡改普通适配器不会骗过未被修改的独立签发方，测试保留这个差异。

数据库运行角色是受信服务角色，不是向不可信终端用户发放的账户，底层 SELECT 不是多租户 RLS。Session Bearer／主体仍为合成数据。不能将客户端 actor=user、知道 Bearer、事件存在或 finite_rule_match 当作自然人明确选择的证明。

## 正反例与可重复证据

- 正常 1/3/5 条明确动作，及 plan/planned，实际 COMMIT；保存的是 pending/v1，无 evidence，truth_verified=false、persistence_authorized=false。
- G3 计划→completed 直接 SQL 反例在新边界下缺 permit 时真实 COMMIT 失败；无 owner 篡改数据或关闭约束。
- A 普通身份 INSERT、私有函数、SET ROLE 均被 PostgreSQL ACL 拒绝。
- B 伪造标签／MAC、漏 MAC、伪装 broker 模式、错误正文/分类/session/fact/version/schema、nonce、到期、未知 validator 均零效果拒绝。回滚后旧证明不能绑定新生成的图身份。
- 验证服务不可用、签发后注入异常、真实进程在提交前被 kill：全表不变；提交后 kill：SELECT-only RR/READ ONLY 恢复同一完整结果。
- 两连接同 key 同请求：一份图、一份 permit，另一个只 replay。正常同键 replay 在签发服务停止时仍可用。
- TEMP 同名表、错误角色／版本、部署函数改变、PUBLIC EXECUTE、FK 缺失：正常服务 fail-closed。owner 故障注入均在请求外执行，不冒充限权身份。
- **仍会 COMMIT 的攻击边界**：攻破 A 的 Broker，或攻破 B 的签名根，均能给计划贴 completed。这是保留的反例，不计作“全部伪造已经解决”。

实际命令：

```powershell
$env:G3_TEST_DATABASE_URL='postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
python -B -m pytest research/g4_trusted_boundary research/g3_choice_protocol -q -ra
```

这里只能用显式 loopback `pathwise_test/pathwise_g3` 合成库。随机 Schema、角色和私钥在 finally 清理；没有 .env/生产凭据读取。完整应用、迁移、12/48、质量、Mock、React、真实 Chromium 及旧 G2 的命令复用新增 workflow；精确 HEAD、最终数量和 CI 终态更新在 PR／交接，不把 pending 当 success。

## 未证明与下一步

没有正式 CO3、真实 CO1/CO2 互操作、全入口 R03、账户身份、人工点击可信通路、完整 typed 审核／修改／导出、生产迁移、秘密轮换、PostgreSQL 主机崩溃、服务超时撤销、删除并发和正式保留政策。原 G3 eraser 删除图时 permit 仅剩 hash/nonce/版本，不代表已批准正式墓碑协议。

G4-0B 将另用真实旧合同，不以 opaque marker 冒充。G4-0C 不能以整会话永久阻断解决无关合法补充；G4-0D 仅在本边界的明确假设下做一次性真实数据库演示，不接正式业务。R03、D4/D5、D6 剩余、D8、正式 typed writer／classify／related_plan、付费与部署继续 BLOCK。需要独立批准生产信任根、凭证协议、旧合同碰撞域、分类选择来源、R03 决议、权限和迁移之后，才能讨论正式实施。

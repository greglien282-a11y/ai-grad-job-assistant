# G4-0A 补充：不窃取密钥也能替换整段来源

基线 main `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`，依赖 #56 最终 `a75a8bc754ff7b5eb4a14c92dcbc4451740d93ac`，与 #57–#59 是独立增量。没有修改前四个 PR、正式协议、生产代码、旧测试或迁移。此处是新增威胁证据及来源边界候选，不是正式准入。

## 更具体的原反例

受信入口收到“我计划部署服务。”/plan/planned。writer 把整个 proposed User Turn、quote、区间和标签替换成“我部署了服务。”/personal_action/completed。#56 的独立校验服务对后者词法相符，因此签发凭证，实际 PostgreSQL COMMIT。

测试没有 owner 改数据、没有关闭约束、没有偷密钥或修改独立 validator。真正的缺口是：**签名绑定了数据库中 writer 提供的正文，却还没有证明它等于最初收到的正文。** 独立签名可以防止谎报有限规则结果，不能独自防止伪造那段规则所读的来源。旧 #56 对“修改普通适配器”的结论必须限于不替换整个来源的情形。

这是来源完整性问题，区别于“无法证明经历真实”或“无法证明人类点击”。需要单列 SOURCE_ORIGIN_BINDING_BLOCK。不能用 #59 正常演示可保存、CI全绿或新增测试数量掩盖它。

## 新候选边界

`research/g4_source_binding/binding.py` 将可信来源入口和普通 writer 分离：

1. 可信 Ingress 在把请求交给 writer **之前**，使用实际 SELECT-only/RR/READ ONLY 连接验证 Session Bearer、Project、subject、revision、严格请求和完整 CP 来源。没有 INSERT。允许记录无效的用户分类声明，不宣称语言已经通过。
2. 它用另一把合成服务密钥签名精确 body（含原文、CP、分类、selection IDs）、原 key digest、Bearer digest、数据库 subject、固定合同、nonce 和期限。密钥不是 Bearer，不交给普通 writer。
3. 独立 BoundIssuer 先验来源凭证，再从实际 staged 图重建请求，与入口记录精确比较；换全文、标签、key、会话、主体均不能匹配。然后才重跑未修改的 c3a。
4. 最终图凭证使用不同的批准 validator hash，绑定本模块和原语义模块代码版本；旧 signer 合同即使持同一合成签名key，也不能用它原有接口降级通过新policy。没有按请求切换批准版本或新增 bypass 参数。
5. 最终凭证期限不超过来源凭证期限，数据库沿用原 G4 permit/图约束在 COMMIT 检查。返回 staged 不冒充已保存。旧已提交结果仍可 GET-only 恢复，同键合法 replay 不需要重新签来源或重开服务。

这不是只给 caller 增加一个 history_safe/source_valid 字段。writer 没有来源签名密钥，也没有权利改私有 policy；数据库只信批准的最终 signer MAC。管理员/签名根修改程序或泄密仍能破坏保证，不能排除在信任假设之外。

## 实际证明与未证明

**实际 PostgreSQL：**原来源替换攻击可以 COMMIT；新候选 N=1/3/5 合法请求能 COMMIT；原计划被改成完成句时整批零效果拒绝；原计划按 plan/planned 可提交。直接 SQL 伪报有限校验、旧 issuer 降级、跨 Session/Bearer、换原话/分类/key、缺失/篡改/过期/未知来源凭证拒绝。读取与拒绝前后全表相同，来源签发本身只读。COMMIT 和现有 FK/ACL/触发器确实由受限 LOGIN 执行。

**受信应用逻辑：**可信入口收到的请求不能在签名前被替换；BoundIssuer 必须运行批准代码。HMAC 来源验证key由入口与验证器共享，两者都是信任根。若入口本身撒谎、验证器持key造假或同一进程内的恶意代码能读取秘密，仍可伪造。

**合成/进程假设：**本补充的 Ingress/BoundIssuer 是同进程能力模拟，密钥由请求外的合成夹具持有，不是已部署的两个隔离服务。#56 原独立 signer 另有真实分进程验证，但不能把那项证明直接移植给新的 source-bound signer。正常读写仍用真实最小权限 LOGIN，owner只在新图建立前 provision 批准hash，不处理请求。

**仍未完成：**来源凭证当前只在内存传递，没有持久化、正式审计/备份/导出/删除合同；没有真实HTTP可信入口、认证账号、人类明确选择证明、独立进程密钥托管、撤销/轮换、完整源凭证并发/崩溃矩阵。正式CO1/2共享域和R03不因来源凭证解决。

本候选的真实写入可运行，但不能冒充完整可信产品。正式持久化原话/选择/认证来源的图、事务及恢复设计仍需批准。

## 对 #59 的影响

#59 仍可展示未篡改受信演示程序下的真实PG提交、pending和GET恢复；它**没有集成本候选来源凭证**，不能作为抵抗来源替换的端到端可信路径验收。保持Draft及该项BLOCK，不继续开发保存体验来掩盖边界。将来源入口、独立进程和不可变审计连成同一条经过攻击验证的链，是正式实施前置条件。

## 命令与证据

```powershell
$env:G3_TEST_DATABASE_URL='postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
python -B -m pytest research/g4_source_binding research/g4_trusted_boundary -q -ra
```

本机98 passed/29.16s（新增14 + 原84），均实际使用一次性PG。首次直接SQL测试helper生成了新selection IDs，来源校验正确地先拒绝；仅让该攻击fixture保留原请求IDs后才单独测试语言层，未改validator或放宽拒绝。新专项CI按精确HEAD执行。

未改 apps、旧研究器或Schema文件；完整正式应用已由#56同一生产代码的精确HEAD CI验证。本补充CI重跑所有84边界及14新源绑定；不谎称新增同进程候选已有完整应用/浏览器或进程隔离验收。五个PR均Draft，R03/D4/D5/D6剩余/D8、正式CO3/writer、生产迁移/权限/付费/部署全部BLOCK，等待独立复审。

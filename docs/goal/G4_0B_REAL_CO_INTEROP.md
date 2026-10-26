# G4-0B：真实旧 CO 互操作与一项未关闭的碰撞域

main 基线 `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`。本候选依赖 Draft #56 的隔离可信边界（`c85a31f3a033ed040fa5171c2e4890e3010f0d1d`），以其分支为 base 单独评审增量。没有复制 G3 的 opaque 1/2 marker。

## 实际执行对象

直接复用正式 `0013_fact_maintenance`、`0014_append_batch`、`0015_fact_classification`，真实 `fact_maintenance.apply/recover`、`fact_append.apply/view`、`idempotency.parse/request_tag/lock`、权限校验和 HTTP 路由。通过旧测试夹具注入随机 Schema、真实 B2-b/append LOGIN、NOLOGIN 函数 owner；正常 CO 命令与 GET 不用 owner。整个测试只能访问显式 loopback 合成数据库，offline_guard 禁外部网络/凭据/Provider。

旧 CO1 真实执行 correct、withdraw、disambiguate/resolution；CO2 真实 append 1–5 规则中的三事实默认例。每个回执都带真实 Turn/FC/FCS、实际版本/revision、签名 key 和 request_tag，并经过原数据库约束提交，不用手填近似回执替代。

未来侧仍是 #56 的**独立参考图**，不是正式 CO3。在请求外把合成 Session/Project UUID、Bearer hash 和 revision 绑定到参考会话，之后用真实受限 LOGIN 完整提交 G4 凭证图。没有改变正式旧 Session、历史、权限或合同。

## key / 身份 / 请求绑定

正式 raw key 为 `v1.issued.nonce.proof`，proof 是 Bearer 对 domain/kind/scope/issued/nonce 的 HMAC-SHA256；数据库 key_digest 为整个 raw key 的 SHA256。CO1/CO2 共用 `conversation_maintenance_v1` 和 `session:<sid>`，所以同 key 跨路由落在同一正式唯一域。

`request_tag` 是 Bearer 对 kind/scope/严格 canonical JSON 的 HMAC；合同版本、原文、选择、目标、revision 都必须进入请求。未来预检直接调用真实 parse/request_tag，不拿 G3 的普通 SHA256 冒充这个证明。客户端 possession-of-Bearer 不等于自然人明确选择，也不等于服务器独立签发的 G4 语义凭证，两类 proof 不可互换。

`preflight.prepare` 只做协议准备：真实 key proof → 会话鉴权 → 读取真实旧回执 → 旧合同碰撞固定拒绝 → 严格未来版本 → HMAC 请求摘要。**不写入、不注册 key、不取得未来正式写入许可**；下一步实际 reference submit 另用 G4 边界。这里两库快照之间没有原子锁，不能被当作正式冲突仲裁器。

## 数据库实际证明的兼容性质

- CO1/CO2 先提交后，未来预检对同 key／不同原话拒绝，旧图全表不变。
- 相同真实 key 改正文得到 payload mismatch；跨 CO1/CO2 得到 contract mismatch，不能重执行为新操作。
- 错 Bearer、跨 Session/scope 不能生成合法 proof；未来选择改变会改变真实 HMAC request_tag；布尔/未知版本安全拒绝。
- 未来参考图真实提交之后，旧 GET recovery 仍用其原版本投影。SQL 捕获仅 SELECT/SHOW，真实 RR/READ ONLY，无 advisory/FOR UPDATE。全表摘要与 reference 图均不变；原 POST 同 key replay 不重建。
- 旧路由拒绝 version3 请求（422），旧 Fact/回执 schema 仍有 `contract_version IN (1,2)`。限权 INSERT 版本3实际失败，未为演示改变 CHECK。
- 0013 合法 correct/withdraw/resolution 回执经原 migration 升到0015，旧 Turn/FC/FS/FCS/CO 的 JSON 保持字面相同，GET 和 POST 同 key 保持原结果。新函数 owner 的恢复只发生于测试 provisioner，不绕过运行准入。
- 整会话 DELETE 按原 API 执行，CO1/CO2 留原墓碑。旧 key 的 GET/POST 返回410，不产生新业务；request_tag 清空，不改正式删除规则。

## 必须保留的实际失败证据

**未来参考图先提交、旧 writer 后用同一合法 key，旧 CO1 或 CO2 仍能提交。** 两个参数化反例用真实旧 HTTP、真实权限和完整回执证明了这一点，没有 owner 改写正式数据或伪造绿色 marker。

原因是未来图在独立研究存储，正式旧 writer 根本不查询它。因此当前候选**没有**证明 CO1/CO2/CO3 全局 at-most-once；future-first 方向仍 BLOCK。不能用“未来侧会检查旧表”宣称双向隔离完成，也不能把 HMAC 有效性当作唯一键全局仲裁。

在保持现有正式合同不变的限制内，无法让未修改的旧 writer 识别新图。正式解决需要独立批准：扩展共享 CO 碰撞域及严格版本分发，或者先建立所有入口都强制遵守的统一注册协议／受信边界，并规定兼容窗口。共享注册若与旧操作分两事务同样有竞态；不能靠 shadow table、异步检查、换 kind/key 或应用预检伪装解决。

本轮不选择正式路线，不加正式迁移、不改 CO1/CO2 约束、不扩大角色、不安装运行服务。跨 formal/reference 双库的删除联动、墓碑和版本升级也没有原子保证；正式旧墓碑只保护正式旧存储，本候选从未声称删除会自动清理别处的实验图。

## 命令与后续审批

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://pathwise_test@127.0.0.1:15487/pathwise_test'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
$env:G3_TEST_DATABASE_URL='postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
python -B -m pytest research/g4_real_co_interop -q -ra
```

精确数量、HEAD、CI 和失败修正更新在 Draft PR；不把预期的“现存反例可提交”称为安全保障。G4-0A 的完整应用 workflow 继续运行，专项 workflow 独立执行本候选的真实正式合同测试。新模块不被 apps/ 导入。

批准清单：正式共享 key 域／HMAC domain、版本身份和路由、旧回执保留期限、删除/墓碑跨版本、身份／权限与函数 owner、迁移失败回滚、并发原子性、R03 决议和 D6 来源表达。R03、D4/D5、D6 剩余、D8、正式 CO3/writer/classify/related_plan、生产迁移、付费和部署继续 BLOCK。

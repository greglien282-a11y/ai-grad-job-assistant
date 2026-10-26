# G4-0F：来源绑定与真实一次性 PostgreSQL 演示整合

**研究演示，不是完整可信写入准入。** 严格 COMMIT 期限、R03、旧 CO 共享域、正式身份/权限与来源保留政策仍 BLOCK；界面常驻提示，不能因可以保存就开放正式 writer。

## 基线与移植边界

从 #59 `ec282916c08e1b31c9c209538b1559b88493d4e7` 建立独立分支。先比较 #56@a75a8bc→#60@123aaf42 的精确差异：仅5个新增文件。只移植其中3个必要 Python 实现/回归文件 `research/g4_source_binding/{binding,conftest,test_binding}.py`，未复制共同祖先、合并整个 #60 历史或改写 #56–#60。

另移植 #62@67cc061 的 `guard.py/execution_pin.py` 两个必要研究模块，不将 #62 的CI自动算作本分支证据。它的一事务一operation索引是临时实验约束，不是批准的正式业务政策。新增集成模块位于 `research/g4_0f_demo`；复用并更新原研究 React 页面与测试启动器，原7项浏览器断言保留。正式 apps/、旧读写接口、DTO、0001–0015、生产角色/工厂/部署配置零修改。

## 真正接通的关系

1. loopback HTTP严格解析公开合成样例，拒绝重复JSON键/未知合同/额外字段。沿旧研究 Host/Origin/临时cookie保护，无凭据URL、无日志正文、无正式CO3路径。
2. 受信HTTP程序将**解码后的正文、明确选择和服务端生成的稳定selection IDs**转换成候选命令，交给单独来源进程。绑定的是规范候选请求，不宣称保存原始HTTP字节编码或自然人点击。
3. 来源子进程持独立合成来源key和真实SELECT-only LOGIN，在 RR READ ONLY 快照中鉴权/校验归属、revision、完整CP引用，签名精确请求。它没有writer或owner凭据。
4. 普通研究writer LOGIN在一个事务内建立原G3图和不可变来源receipt。另一实际签名子进程核对来源MAC、请求/身份/版本、图与receipt相等，再运行未改c3a。它不持数据库身份。
5. 最终MAC覆盖原完整图**以及实际来源receipt**。不是未经签名的旁挂记录：临时seal包装原seal，加上receipt；operation与receipt的双向FK要求存在且同事务，receipt的server xid与operation对应。旧signer版本不能直接降级通过新policy。
6. 临时PG检查permit、图约束和来源关系，正常程序自己拥有事务并立即COMMIT，不向HTTP暴露SQL/约束时序控制。
7. 一个RR READ ONLY快照恢复原operation、Fact/选择事件和来源receipt；服务失效、来源签名过期后已提交回执仍可只读恢复。新POST同键合法replay优先读取数据库中的原body/selection IDs，不依赖临时请求缓存、不重新签发或创建第二份资料。研究key为UUID，不冒充正式CO1/2的签名key或未来CO3共享域。

两个子进程使用不同PID和私有JSON管道，启动/响应有有限等待、EOF/死亡安全拒绝。测试确实创建进程并执行真实SQL，不用同进程两个类冒充进程隔离。独立进程不等于不同OS账户/沙箱/HSM：provisioner/受信HTTP宿主仍持测试生命周期和bootstrap能力（包括fixture中的合成秘密），同用户恶意代码/主机管理员不在已证明防御范围。未证明密钥安全擦除、托管、轮换或部署供应链。

## 来源审计候选

随机独立Schema中的receipt记录operation/session、来源nonce、完整合成来源凭证（含候选正文、选择、身份/请求摘要、MAC、期限）及服务端时间/xid。普通writer仅有必要INSERT列；reader SELECT-only；UPDATE/DELETE/TRUNCATE不授予。不可变trigger、精确ACL/FK/函数/触发器manifest在请求前由provisioner固定，运行时漂移拒绝。未放宽原G3精确准入，原图的9表/函数/角色合同保持不变。

新的 `g4-source-bound-disposable-read-v1` 与 `g4-source-audit-read-ref-v1` 只服务本研究UI，保留事实pending/v1、原话/CP/选择事件及分类；严格TypeScript解析与G3 parseBatch绑定operation、selection IDs、固定BLOCK集。缺失/未知/损坏来源清空整个结果，不退回旧DTO。

**保留/删除/撤销尚未批准：**候选receipt在一次演示生命周期内持久，关闭测试环境时整Schema销毁。没有正式备份/导出服务，也没有撤销HTTP或DELETE接口。真实研究测试显示调用原reference eraser后Fact删除但receipt仍保留，GET恢复拒绝；这是一项明确的保留政策缺口，不叫删除已完成。正式CO1/CO2整会话DELETE行为原样回归，未修改。未来需审批含原文/认证摘要的保留期限、加密/导出、授权删除、墓碑、撤销及旧回执可恢复边界。

## 已验证及没有验证

实际PG/HTTP/PID验证：N1/3/5提交与完整来源；整体换正文被真实bound signer拒绝；两服务死亡/pipe失联零效果503；来源实际过期拒绝；同键并发/合法replay；响应实际丢失后两服务都死亡仍GET恢复；跨cookie、旧正式路由、未知合同、JSON重复键；audit不可写/读取权限丢失无部分响应；reference erase的保留缺口。

本机初轮新增Python14项；随后先用“临时请求缓存丢失且双服务关闭”的同键重放得到真实红灯（误报503未保存），再改为数据库回执优先/核对原body，最终新增 **15项/19.98s**。缓存仅为辅助，不能作为已保存依据；仍不提供关闭整套演示后的自动重启恢复。新严格TS17项；TypeScript/Vite构建成功；真实Chromium9项（原7项完整保留+新2项来源UI/坏receipt）。新源TTL测试由可信子进程启动配置合法短TTL，HTTP无TTL/bypass参数。

原共同研究全链+来源14+初轮集成14曾实际运行447 passed/152.89s。缓存修正后的最终集成为 **448项（327实际PG、121纯函数/结构）**，最终执行结果/精确HEAD/CI见PR和统一报告，不把旧447证据代替新版本。它保留 #57 future-first 旧CO同key仍能实际提交、#58旧入口语义复活和无关贡献保守阻断的反例，绝不称全部安全已解决。

首次TS正例用了带未引用前缀的旧单条fixture，parseBatch完整覆盖检查正确拒绝。仅将新fixture改为完整原句及一致CP区间，未削弱parser或旧断言；红灯记录不掩盖。实际浏览器仍从真实HTTP/PG取完整图，不以静态JSON替代。

严格COMMIT期限在允许任意SQL的writer模型下仍不成立；受信程序拥有短事务是额外信任假设，不是PostgreSQL不可绕过的硬时钟。T2成功反例见 #62，界面固定BLOCK。receipt持久不证明自然人操作、独立职责、语义独立或事情真实性。

## 启动 / 回归

```powershell
# 明确的一次性PG16合成库；不得读取真实凭据或更换为生产URL。
$env:G4_DEMO_TEST_DATABASE_URL='postgresql://pathwise_test@127.0.0.1:15487/pathwise_test'
cd research/g4_disposable_demo/web
npm ci --ignore-scripts --no-audit --no-fund
npm run build
npx vitest run src/source-contract.test.ts
cd ../../..
python -B -m research.g4_0f_demo.server --synthetic-disposable --port 18175
# stdout给出127.0.0.1端口；仅公开合成样例；终端STOP结束并清理。
```

浏览器：`G4_DEMO_PYTHON=<现有测试venv>`、`G4_DEMO_MODULE=research.g4_0f_demo.server`，本机显式`PATHWISE_PROTOTYPE_CHANNEL=chrome`后在web目录`npm run test:browser`。CI安装匹配Chromium，不沿用本机channel。

Python根目录：显式合成`G3_TEST_DATABASE_URL/TEST_DATABASE_URL/DATABASE_URL`，`python -B -m pytest research/g4_trusted_boundary research/g4_real_co_interop research/g4_r03_admission research/g4_disposable_demo research/g4_source_binding research/g4_0f_demo research/g3_choice_protocol apps/api/tests/test_overnight_r03.py -q -ra --tb=short`。原完整正式应用、迁移、12/48、DRAFT质量、Mock及旧前端/E2E由对应HEAD的继承CI回归。

## 审批停止线

SOURCE_ORIGIN_BINDING的参考接线/真实PID/临时审计得到增量证据，但正式可信入口/认证/不可篡改部署/完整持久依据合同未获批准。`STRICT_COMMIT_DEADLINE_BLOCK`、跨旧CO全局原子key域、R03、来源保留/撤销、D4/D5/D6剩余/D8继续BLOCK。没有正式writer/CO3/migration/classify/related_plan、生产权限/工厂/部署、真实Provider或付费。保持Draft等待独立复审。

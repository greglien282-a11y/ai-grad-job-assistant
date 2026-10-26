# G4-0C：全入口差异与可审查的独立性依据

main 基线 `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`，按 Draft #56→#57→本候选顺序评审。只新增隔离研究，不修改共享 guard、任何 writer、工厂、正式权限或历史。

## 先说能与不能支持的产品行为

以前拒绝过“测试导出按钮”，现在补充“部署服务”，不能仅因会话存在拒绝记录而宣称这两件事相同。新研究可以从已保存原话、完整 FC 历史、FS/FCS 和明确引用生成一个**只读审查包**，指出是哪条历史产生冲突，哪些只是已知表述变体，哪些没有发现字面或已知模板冲突。

对于无关部署样例，审查包真实展示新 User Turn、完整引用和旧测试拒绝历史，reason=`distinct_literal_source_argument_only`。这是可供审查的“不同原话／未命中已知家族”的论据，**不是语义独立证明**，仍返回 requires_review。新 Turn、不同 ID、没命中词表都不足以放行。

此阶段没有受信任务身份、不可伪造的独立活动记录或批准的人工决议协议，因而**没有一条含拒绝历史的候选可以被本模块授权持久化**。这也不是建议整会话永久封锁；它把合法补充转成有具体证据的待决案件，待产品批准独立审核人的权限、证据标准、有效期和审计后再讨论正式准入。用户单击“是”、解释、附件描述或换 key 不产生许可。

G2 已有非持久化澄清体验，继续复用其完整拒绝历史、解释追加与 request_save 固定 not_saved；不重做 UI，不把 research packet 接成批准按钮。

## 以实际代码核查入口

- `facts.add_fact`：鉴权/Session 锁、require_legacy、input_consumed、rejected_contribution。当前 rejected 的精确正文（含其历史文本）或复用原始来源 Turn 拒绝；新 Turn 下数字／同义／主体改写不构成可靠语义防线。手工 add_turn 是独立已保存请求，后续 add_fact 拒绝不会撤销前一个 Turn。
- `facts.change_fact`（手工 PATCH）：拒绝编辑当前 rejected 本体，编辑其他事实时调用 shared guard，排除当前目标。它检查拟新文本，不证明与别的 rejected 经历语义无关。新增实际限权 HTTP 测试证明数字写法、同义、数量、团队／否定／计划表述转个人动作可进入另一个 pending legacy 事实。
- CO1 correct/resolution：真实 key/旧结果优先、鉴权、require_legacy、Session/target/version、same_atomic_claim，再 shared rejected guard；完整回执和 FCS 原子。数字计数规则是严格 ASCII cardinal，中文“三个”被 identity 422 拒绝，**不是 R03 独立性识别**。其他可通过该身份规则的跨事实 reassertion 仍能提交。
- CO1 withdraw：更严格保留 rejected 本体、不可变原始来源、before/after 和 intent FCS；不生成新的正向声明。旧回执恢复不能因后来 rejected 或 typed 而变成新写入。
- CO2 append：原 key replay 优先；新请求检查当前以及所有 before/after 曾 rejected，整批409／零效果。这保住保守子集，但真实无关部署也会被阻断，不能叫 R03 解决。
- Mining reserve/complete：reserve 并不证明语义独立；complete 在 Session 锁、版本、上下文和既有 shared guard 后用原输出合同创建 pending legacy。脚本 Provider 的三个／验证／无关部署实际完成路径仍有缺口，不能把运行 completed 当作事实真实性或分类 completed。没有修改 worker 状态收尾语义。
- 手工新建、手工编辑、CO1、CO2、Mining 的 typed/current-history require_legacy 门禁仍按既有合同；它解决版本兼容，不等于对所有 legacy 计划语义分类。没有全局 cutoff。

原 #46 的 `test_overnight_r03.py`、24 案例与观察保持原样，在本候选重新执行。不是复制旧四十多个语义等价断言；新增部分集中此前未细测的 PATCH/CO1 和从真实完整投影产生审查材料。

## 新只读审查包

`research/g4_r03_admission/packet.py` 无路由、key、凭证签发或 writer 导入。独立 `g4-r03-review-packet-v1`，一个真实 SELECT-only LOGIN / RR READ ONLY 快照：

1. Session 鉴权在 request/version/history 披露之前；check_reader 沿用正式角色与 Schema 校验。
2. 复用 `experience_read.Projection` 完整校验事实/历史/来源/CO 关系，不复制第二套不完整投影器。
3. 原话仅从保存的 User Turn 读取，Project、角色、CP 全句、顺序和声明规则复用原 c3a。
4. 对当前或历史 rejected，保留真实 fact/version、所有 FC before/after、原始 FS 与 FCS；M2 assess 仅附加既有六种研究提示，不扩词表、不归一化数字或推断完成。
5. 任何未知版本、额外 force 字段、revision 冲突、缺 SELECT、损坏历史、来源异常返回整份 unavailable，不泄露部分原话/历史。外 Bearer 不返回冲突。

即使没有命中冲突，结果仍 requires_review / semantic_independence=NOT_PROVEN / truth_verified=false / persistence_authorized=false。本包不是可转移的校验凭证；G4-0A 的 gate 不接收或信任它。

## 实际测试与可用性代价

新增真实限权测试：六种变体×PATCH/CO1 两入口；当前／恢复 pending／恢复 confirmed 的历史×三个候选；实际 withdraw 的 FCS；缺权限和损坏历史。完整业务表摘要在所有只读/拒绝请求前后相同，成功旧命令则如实保留其副作用，paid_calls=0。

恢复历史夹具在请求外追加合法旧格式 snapshots，模拟历史 writer 的 rejected→pending/confirmed；不是允许当前 API 进行该转换。没有改写既有 JSON 或让 owner 伪装 reader。首次历史用例使用另一固定旧清单夹具，与数字家族不相符，断言正确报红；改为明确数字历史夹具。新 edited snapshot 起初漏预分配 change UUID，完整读取器拒绝，补齐真实来源身份后才通过，没有放宽 projector。

无关场景的可用性：本研究三种历史状态下的无关部署全部保留为 requires_review（3/3 合成样例），不能自动保存。这是尚未获得正式独立性证明的代价，不是总体误判率。原 M2 的五个带拒绝历史的无关例也仍保守阻断。不得把有限家族未命中等同于“安全独立”。

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://pathwise_test@127.0.0.1:15487/pathwise_test'
$env:DATABASE_URL=$env:TEST_DATABASE_URL
python -B -m pytest research/g4_r03_admission apps/api/tests/test_overnight_r03.py -q -ra
```

真实数量、HEAD、CI 随 PR 更新。完整回归由本研究链的原应用 workflow 执行；不修改冻结评测、timeout、skip、xfail 或现有断言。

## 待批准的最小决议协议方向

需要独立批准审核主体的服务器身份、被审核事实／历史版本／Session revision、不可变原话及关系、独立活动证据、具体拒绝理由、无关性论证、决议版本/签发期限、失效与撤销、操作键和签名凭证之间的绑定。任何变化都必须重新审查，不得将旧允许决定移到新的文字/主体/数字/版本。批准前只有待澄清，不产生 force、换 key 或新 source ID 的逃生通道。

即使批准这个方向，也不能让当前旧 writer 自动获得新权限，需要所有入口一致边界与真实 CO 碰撞域。R03、D4/D5、D6 剩余、D8、正式 typed writer/CO3/classify/related_plan、生产部署/付费继续 BLOCK。

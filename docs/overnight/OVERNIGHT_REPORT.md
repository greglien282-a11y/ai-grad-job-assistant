# Pathwise Overnight Development Report

报告状态：**M1–M5 研究交付完成，最终精确HEAD CI成功，测试资源已清理**。开始时间2026-10-22 00:46（Asia/Shanghai）；最终CI于当日01:56完成。本次只交付设计、证据和隔离原型，不批准任何产品/生产政策，所有 PR 保持 Draft。

## 1. 基线、范围与 B2-c3b

起始及最终实际核验的远程 main 均为：`17a35e9cf23d4d9f11b757a426793e575f861223`。没有直接改动或推送 main。

B2-c3b 已完成：[Draft #44](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/44)，HEAD `2020eaa9d3e2852671519f08894870cead7f3108`，[CI39633793288](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39633793288) completed/success。本地后端2158；Linux2157+1既有平台skip；React158；Chromium59及迁移/12/48/质量/Mock通过。其来源绑定与保守历史审核不授权保存，也未解决 R03。

夜间后续代码没有偷偷混入 #44：#46 独立基于稳定 main，#47 明确堆叠于 #46。没有把两个尚未合并分支的结果伪称为完整生产 typed 链路。

## 2. M1–M5 工程增量

- **M1 COMPLETE / NOT_IMPLEMENTED 候选合同**：定义请求、完整原话、分类/进度/信任、原子图、CO3版本/key/恢复、鉴权/版本/历史、失败/删除/worker及政策A关系。发现并明确阻断：现有 FactV3 只接受空 classification_citations，正式依据记录需要新的来源/读取/Schema审批。
- **M2 COMPLETE / SIMULATED + OBSERVED_EXISTING_BEHAVIOR**：24条合成对抗语料、六类诊断、42项测试；12项真实限权PG/HTTP观察复现旧手工/Mining与append保护差异。5/5有rejected历史的无关贡献被保守阻断；不是总体误拒率或 R03 已解决。
- **M3 COMPLETE / future specification + EXECUTABLE_ISOLATED_TEST**：17类失败义务明确未实现CO3与既有CO1/CO2证据边界；30项真实只读测试验证三种投影、安全错误、权限、整表零效果和实际两连接快照。
- **M4 COMPLETE / SIMULATED**：纯内存不可变状态模型，最终102项测试；模拟1–5图关系、重放/恢复、八个故障点、串行调度、历史风险、墓碑与分立能力。没有真实事务、HMAC、来源认证或权限保障。
- **M5 COMPLETE / 已核验证据交付**：范围/依赖/隔离/旧合同审计；发现并修复参考模型的bool版本混淆、恢复时未引用尾句及摘要漂移。最终本地后端2261通过，最终CI全部成功，资源已清理。此完成状态不解除任何正式writer或生产BLOCK。

## 3. Draft PR、HEAD、依赖和提交

- [#45 合同及总交接](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45)：BASE_BRANCH=main，BASE_SHA=`17a35e9cf23d4d9f11b757a426793e575f861223`，DEPENDS_ON_PR=无代码依赖。HEAD为报告所在文档分支的提交，精确最终值见PR与最终答复；文档不能预先发明自身提交hash。DIFF_SCOPE=3个新文档。
- [#46 R03研究](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46)：同main基线；HEAD=`fc9286e8f1b8e0e62f6d59d2821584391d03fd88`；无#44代码依赖，#45只作为候选设计引用。DIFF_SCOPE=5个新文件。
- [#47失败模型及参考原型](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/47)：BASE_BRANCH=codex/overnight-r03-research，BASE_SHA=`fc9286e8f1b8e0e62f6d59d2821584391d03fd88`，DEPENDS_ON_PR=#46，HEAD=`afe82bb10c3dff0eaacfba22406675d1d31b66c3`。真实导入父PR测试专用评估器；DIFF_SCOPE=5个增量文件，另5个父文件不算独立增量。

固定内容与检查点提交：

- M1：[05264ab](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/05264aba90cf3795f0e9510a87e61972a27576d9)。
- M1/M2日志：[c8dc4d2](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/c8dc4d254ff01facea7487f143bbfb54935a8d5b)。
- M2：[fc9286e](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/fc9286e8f1b8e0e62f6d59d2821584391d03fd88)。
- M3：[23d6e12](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/23d6e1295a64971c4eae9e117f06ae58ce07d5d9)；日志：[e2b9205](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/e2b9205285d66749f1956f5c7a7193fdf3ea7cfe)。
- M4：[3b27a96](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/3b27a96c72ea903a4984e85ac5d654d6ed7bcec8)、[ec0c961](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/ec0c961b5cb6944472cf60f5b0298c7642bcff3f)；日志：[53ac569](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/53ac5696b89649d58470919a6afafe797273a648)。
- M5模型修复：[afe82bb](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/afe82bb10c3dff0eaacfba22406675d1d31b66c3)；本地最终验证/清理检查点：[1337af0](https://github.com/greglien282-a11y/ai-grad-job-assistant/commit/1337af09060d70bb34097aa186a0067158925771)。包括本报告最终提交在内的完整列表：[45 commits](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45/commits)、[46 commits](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46/commits)、[47 commits](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/47/commits)。

## 4. 精确变更文件清单

#45，全部新文档：

- `docs/overnight/TYPED_WRITER_CONTRACT_CANDIDATE.md`
- `docs/overnight/OVERNIGHT_HANDOFF.md`
- `docs/overnight/OVERNIGHT_REPORT.md`

#46，全部新文件：

- `apps/api/tests/overnight_research/__init__.py`
- `apps/api/tests/overnight_research/r03.py`
- `apps/api/tests/overnight_research/r03_cases.json`
- `apps/api/tests/test_overnight_r03.py`
- `docs/overnight/R03_ADVERSARIAL_REVIEW.md`

#47，排除父PR后的新文件：

- `apps/api/tests/overnight_research/typed_model.py`
- `apps/api/tests/test_overnight_failures.py`
- `apps/api/tests/test_overnight_typed_model.py`
- `docs/overnight/TYPED_FAILURE_MODEL.md`
- `docs/overnight/TYPED_REFERENCE_MODEL.md`

夜间合计13个新文件。现有生产代码、旧测试、0001–0015、前端、工作流、脚本及冻结评测未修改；无删除、skip/xfail或放宽旧断言。

## 5. 实际验证与 CI

精确命令、工作目录、日志路径及每轮失败原因详见 [OVERNIGHT_HANDOFF.md](OVERNIGHT_HANDOFF.md)。仅使用专用15487合成库、随机Schema与现有临时限权身份。

- M2专项42；M3专项30；M4最终102，合计174项新增pytest case。单个矩阵内部75种分类组合不是75个额外pytest case。
- #47最终本地全后端 **2261 passed / 906.99s**；原ec0c961集合2259通过是被替代记录，不能代表新增修复通过。
- React **158 passed**，构建、E2E类型检查通过；真实本地Edge Chromium/HTTP/PG **59 passed**。
- 隔离Alembic升级/check/清理通过，无新增迁移，head仍0015_fact_classification。
- 冻结离线合同 **12/12、48/48**；S02诊断及TOKENIZER_NOT_PROVIDED保留。质量脚手架通过但仍DRAFT/人审未完成/真实质量null；Mock真实请求和费用0。
- #46 [CI39639366346](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39639366346) 精确fc9286e，workflow和三job全部completed/success：后端2128+1既有Windows-only skip，React158/build，Chromium59/types及迁移/离线检查通过。
- #47 [最终CI39644769165](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39644769165) 精确afe82bb，workflow及三job均completed/success：Linux后端 **2260 passed、1既有平台skip / 1371.16s**，React158/build、Chromium59/types和迁移/离线检查全部通过。skip是`test_probe_secret_safety.py:195`的Windows PowerShell5.1 Fake Native harness，本地Windows同用例通过。旧CI39643557810对应ec0，已被替代，不作为最终证据。
- #45仅文档，不匹配应用CI paths；状态是NOT_TRIGGERED，不是假称跑过全量；精确最终文档HEAD以PR和最终答复为准。

本地非后端组件运行后仅有测试模型修复；对应生产/前端/脚本/frozen树经git diff证实相同。最终CI已在afe精确HEAD重新运行所有组件，避免把不同HEAD的模型结果混用。曾发生短暂TLS/连接器错误，已恢复并核验推送与CI；没有修改网络安全配置或重跑workflow掩盖结果。

## 6. 复现问题、限制与审批

**已复现的既有风险**：旧手工/Mining可接受拒绝主张的数字/近义新Turn；共享guard只扫描当前rejected，历史拒绝后pending/confirmed仍有入口缺口；旧legacy confirmed可包含计划。旧手工Turn成功、后续Fact拒绝也可能保留Turn，这是跨HTTP请求的现存兼容行为，不是新原子writer已实现。

**已修复的研究模型缺口**：True/1类型混淆；原文未引用尾句；回执摘要漂移。均在测试专用模型内以实证红灯修复，未修改旧断言或生产guard。

**仍不能证明**：词法匹配/有限风险family不提供一般语义身份或真实事实认证；模型允许“部署服务/部署推荐服务”两个候选值，仍无法判定是否同一服务。所有Outcome保持NOT_PROVEN/需要后续事务审核/无真实性与持久化授权。串行模拟和异常注入不是真实进程并发/数据库崩溃证明；真实CO1/CO2测试不是CO3证据。

必须单独批准，均标为 **REQUIRES_USER_APPROVAL**：

1. R03全入口的历史身份、独立性/人工澄清及无关贡献被拒绝的可用性政策。
2. D4有限语法、个人归属、计划/进行中语义及关系协议；本轮没有related_plan/FactProgressLink。
3. D5分类声明/依据、classify、旧typed编辑/退级、确认与材料信任的版本化协议。
4. D6分类依据的新读/source/UI合同及完整新旧writer/恢复链；当前读-only闭环不能解锁writer。
5. A/B政策、存量grandfather、born-contract、typed创建合同、截止/灰度日期/cohort和回滚界限。
6. CO3正式DTO/路由/key证明域/期限/墓碑、前向数据库约束与最小权限设计。
7. D8生产身份/owner/ACL/工厂、预算/真实Provider/外发及部署；全部继续关闭。

没有为等待上述批准而伪造绿色功能；未来typed持久化、事务/幂等/来源审计和生产权限均明确NOT_IMPLEMENTED。

## 7. 清理与第二天建议

两个合成库临时Schema/测试角色均0；专用PG集群已停止，15487/15173/18000无监听。完整原始日志只在忽略的`.e2e/overnight-*`；提交文档无Bearer、真实key、密码、生产DSN或私人原文。无用户未提交修改被覆盖、reset、stash或清理。

建议审查顺序：先独立复审#44；审#45候选边界与审批清单；审#46可复现风险证据；最后审依赖#46的#47模型与M5修复。**不建议无条件合并**；#46若Squash合并，#47需要按真实父链重新核对/更新基线并重跑CI，不能沿用旧HEAD的绿色结论。今晚不执行任何合并或Retarget。

下一阶段候选：先审分类依据/来源投影候选与R03可用性政策，再决定正式CO3事务/幂等/限权Schema和完整读取/审核/恢复链的实现许可。没有上述审批，不进入typed writer、classify、关系、截止或生产阶段。

最终边界：**生产部署否；真实付费Provider否；生产数据库修改否；Merge/直接修改main否；正式typed writer开放否。** 所有PR保持Draft；完成最终文档提交和只读状态审计后停止，等待用户及ChatGPT独立审查。

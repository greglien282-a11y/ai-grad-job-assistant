# B2-c3b Source-Bound Typed Candidate Preflight

状态：隔离的只读实验候选，等待独立审查。不是 typed writer、分类命令、保存回执或真实性认证；不开放生产准入。

启动基线 `17a35e9cf23d4d9f11b757a426793e575f861223`。首次检查时 workflow/FastAPI 尚未完成，因此停止，没有创建分支或修改代码。用户要求继续后重新核验 remote main、干净工作区及 [39609072947](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39609072947)：head_sha 一致，workflow、FastAPI、React、Chromium 均 completed/success，才建立 `codex/c3b-source-preflight`。

依据 B2C_DESIGN §4、§6–9、§12、[c3a](FACT_MAINTENANCE_B2C3A_TYPED_VALIDATION_SPIKE.md)、[c2e](FACT_MAINTENANCE_B2C2E_CUTOFF_PREFLIGHT.md) 及现有只读投影/权限实现。方案 A 仅作为兼容设计假设，不是生产政策批准。

## 1. 固定接口与真实来源

[`typed_source_preflight.py`](../apps/api/app/typed_source_preflight.py) 提供独立 `preflight(factory, *, session_id, project_id, turn_id, token, request)`。三个 ID 使用 UUID 对象；token 按现有 `facts.authorize` 校验 Session 凭证。factory 必须显式由隔离测试提供，没有默认工厂、环境开关、HTTP 路由、后台任务或生产调用者。

request 是严格字典，仅四个键：

```json
{
  "preflight_contract": "typed-source-preflight-v1",
  "synthetic": true,
  "context_revision": 4,
  "items": [{
    "fact_kind": "personal_action",
    "progress_stage": "completed",
    "classification_contract": "explicit-typed-v1",
    "quote": "我整理了27条缺失记录。",
    "start": 0,
    "end": 12
  }]
}
```

版本号 4 只是示意，必须与同一读取快照内真实 context_revision 完全相同；bool/float 不作整数接受。未知预检合同拒绝，不协商、不回退。`raw_text`、force、ignore_duplicate、history_safe 及其他额外字段全部拒绝。

`synthetic=true` 是隔离实验调用声明，不是识别真实/虚构数据的能力或生产许可。凭证不进入结果、URL、日志或异常文本。

执行顺序：

1. 在真实连接设置 REPEATABLE READ、READ ONLY，SHOW 两项核验；无行锁、advisory lock 或 TTL 清理。
2. Session 凭证鉴权，不存在/外凭证统一 session_unavailable；此前不检查调用者版本、类型、来源或历史。
3. 原样复用 `check_reader` 的 Schema/列/触发器、LOGIN/owner、成员关系、ACL、函数 owner/search_path/EXECUTE 和 paid 权限检查。缺权限不当作空数据，缺 Schema 不推断 legacy。
4. 校验固定预检合同和 context_revision；构造现有 `experience_read.Projection`，验证**整个会话**的历史、状态、分类版本、FS/FCS/CO 及来源关系。不复制第二套事实投影器，也不把内部 FactV3 输出给调用者。
5. Project 必须属于已鉴权 Session，Turn 也必须属于该 Session；一会话一 Project 仍由现有合同约束。不匹配统一 source_unavailable，不查询或展示外会话分类。assistant Turn 固定拒绝。
6. 只将数据库保存的 `turn.content` 传给 c3a `validate_candidate`，语言合同固定 typed-semantic-spike-v1。调用者无法提供另一个 raw_text。保存 27 而 quote 写 28、NFC 替换、UTF-16 偏移、裁切否定或漏句都不能通过精确引用校验。

这是读取快照时刻的绑定，不是持久化时的不可变来源承诺。并发提交可以发生；旧快照结果既不锁定未来版本，也不签发可消费的 admission token。未来 writer 必须在自己的事务内重查归属、版本、历史和来源，不能复用本结果跳过审核。

## 2. 与 c3a 的关系及责任划分

不修改 c3a 规则、动作/对象词表、纯函数或冻结材料。1–5 项、严格类型/阶段三列、完整句界、全非空白覆盖、code-point 半开区间、原文顺序、不重叠、不自动拆分等均由原函数处理。unknown/unsupported 和声明冲突原样分列报告，不推断 memory_state 或改写正文。

原 c3a 的“没有任何 app 消费者”隔离测试仅增加一个明确例外：本次获准的 `typed_source_preflight.py`。所有其他 app 文件仍禁止导入 c3a，且额外禁止导入 c3b；新测试递归验证 c3b 没有生产调用者。没有将例外推广到路由、writer、Provider 或通用模块。

必须分别理解：结构合法、原文切片一致、有限语言模板、用户分类声明、保存的来源绑定、历史风险、人工核实和真实世界真伪。前六项也不能代替后两项；引用绑定不能生成 classification_citations 或证明分类已核实。

## 3. R03：可证明的历史风险与不可证明的独立性

在通过现有完整性验证的同一快照内，结果给出排序稳定的 history_flags：

- current_rejected：当前 Fact 为 rejected。
- historical_rejected：任意 FactChange.before/after 曾记录 rejected；当前已变 pending/confirmed 也不忽略。
- exact_text_reuse：候选完整原文或完整句 quote 与当前/历史 statement 字面相等；不做 trim、数字替换、同义归一化。
- original_source_reuse：复用既有 FactSource 的 Turn。即使没有可信精确 citation，也保守按整个 Turn 识别，不声称另一片段已经独立。
- historical_source_reuse：复用 FCS Turn 或历史快照记录的当前/原始 source_turn_ids。原始建档和后来纠错/撤回来源分开检查，不把分类依据补成已有引用。

没有 flag **不等于没有风险**。例如无 rejected 时，“我测试了3个导出按钮。”之后的新 Turn“我测试了三个导出按钮。”可能仍为 candidate_only；history_status 明确为 independence_unproven，semantic_independence 永远 unproven。这是未实现语义身份识别的反例，不是成功防复活的证据。

只要当前或任何历史曾 rejected，即便新候选无精确文本/来源重合，也转 requires_review。新 Turn、3/三个、测试/验证均不作为独立性证明。没有 force、换 Turn/key 解锁、自动撤销、已保存澄清回执或后台任务。

专项包含 3 种历史形态 × 3 条候选：当前 rejected、历史 rejected 后 pending、历史 rejected 后 confirmed；两种疑似再主张及一条无关“我部署了服务。”。9/9 转人工审核，其中 **3/3 无关新贡献也被阻断**。这个合成小矩阵仅量化保守策略的可用性代价，不是总体误拒率、分类准确率或真实用户统计。不能以此声称连续补充已正式可用。

当前/历史精确文本、FS/FCS 与可信快照来源重复是可证明关系；语义近似、跨轮归属和一般贡献独立性尚不可证明。没有修改共享 rejected guard、旧 writer 或 append D3；R03 全入口保障继续生产 BLOCK。

## 4. 输出合同与安全失败

不可变 Result 不含正文、凭证、审计记录、FactV3、操作键、operation_id 或 accepted_items，不存在“已保存成功”状态。结果统一含 `truth_verified=false`、`persistence_authorized=false`、`transaction_review_required=true`、`semantic_independence=unproven`。

- source_binding：not_checked / not_bound / bound。只有 c3a 完整精确引用验证通过才 bound；未知语言仍可绑定原文，但不会变成可候选。
- language_status/language_code：原 c3a 判决；未检查明确 not_checked。
- history_status：not_checked / requires_review / independence_unproven；有风险时列固定 flags。
- status：authorization_denied、permission_rejected、version_rejected、integrity_unavailable、source_rejected、rejected、candidate_rejected、requires_review 或 candidate_only。
- candidate_only 只表示保存原文与有限模板相符、未发现这几种精确风险，**不能保存、确认、作为贡献正文或声称通过 R03**。

Schema/历史/来源损坏、未知持久化版本、SQL/严格 DTO 错误固定 integrity_unavailable，无部分投影、不修复、不返回异常原文；运行身份或 SELECT 不足固定权限拒绝。连鉴权表都无 SELECT 时不能认证，返回权限不可用，不猜测凭证或 Session 是否存在。外凭证与正常可访问的鉴权表组合下，鉴权先于全部候选和分类披露。

同一候选同时有语言问题和历史风险时，status 为 candidate_rejected，language 与 history 两个维度均保留真实结果；不会因发现一个风险伪称另一项已通过。

## 5. 权限和零效果证据

随机 PostgreSQL Schema 内使用既有 reader 夹具新建的独立 LOGIN，与 B2-b/append writer 身份不同；只授 READ_TABLES 的 SELECT 和 Schema USAGE。准入函数不授任何权限；不扩展角色、paid 读取或写入能力。owner 仅在请求外准备合成资料及注入故障；另有 owner 被拒绝的负例，不能把它作为正常运行身份。

Projection 验证器原样复用，测试注入损坏后先恢复触发器，再以真实 reader 调用。没有为方便测试放宽校验。对 CO 99 的负例，现有 `ck_co_identity` 在数据库立即拒绝并回滚；专项断言具体约束名和全表不变，不重复实现新规则，也不拆除 CHECK 制造成功提交。

正常/拒绝调用均比较随机 Schema **全部表**的排序 JSON SHA-256：覆盖 Turn/Fact/FC/FS/FCS、版本/revision、操作回执、Run 与费用账本。不输出摘要原数据或凭证。SQL trace 证明无 DML/DDL/锁/SET CONSTRAINTS；SHOW 两个属性及不合格返回值的负例均覆盖。Provider mine/reserve_cost 设失败哨兵，Run/paid_calls/paid_audit/CO 初始零且全表不变。

真实两连接测试在授权建立快照后，由第二连接提交 rejected 和 revision 更新：第一次结果只看旧快照，下一次旧 revision 拒绝，刷新 revision 后转历史审核。外部有意提交的这一项不是预检写入，测试不把它记作“全表零变化”；其他请求与并发两 reader 均全表不变。结果不可作为未来写入的 TOCTOU 安全证明。

## 6. 验证命令与结果记录

数据库测试显式使用 loopback:15487 的 pathwise_test/pathwise_e2e 合成库、随机 Schema 和真实临时限权角色。没有读取真实凭据、生产连接或付费请求。无新增 skip/xfail、重试、sleep 或 timeout 调整。

- `python -m pytest -q -ra tests/test_typed_source_preflight.py tests/test_typed_semantic_spike.py`：最终 **199 passed（71 新预检 + 128 c3a）**。初版 196 passed 后增加 3 项事务属性/并发读取验证。开发中的失败是夹具提交后 revision 尚未刷新及尝试注入被原 CHECK 拒绝的未知 CO，不修改业务规则规避它们。
- `python -m pytest -q -ra`：全后端，实际最终数量、平台 skip 和日志摘要记录在 Draft PR。
- `npm run test -- --reporter=dot`：**158 passed**；`npm run build`；`npm run test:e2e:types`：均通过。
- `PATHWISE_E2E_CHANNEL=msedge npm run test:e2e`：**59 passed**，本地 Edge 的真实 Chromium 内核；CI 使用 bundled Chromium，原断言、timeout 和 retries=0 保持不变。
- `python ../../scripts/check_isolated_migrations.py`：通过，静态单头仍为 0015_fact_classification，无新增迁移。
- `python ../../scripts/check_m12c2_contracts.py`；`python ../../scripts/check_s03b_output_contract.py`：冻结 **12/12、48/48** 通过，原 S02 词法/人工 gold 差异诊断保留，48 项仍标 TOKENIZER_NOT_PROVIDED。
- `python ../../scripts/evaluate_mining_quality.py --outputs ../../docs/evaluation/quality-v1/oracle.outputs.json --output-dir ../../.e2e/c3b-quality`：通过，DRAFT、人审未完成、真实质量 null。
- `python ../../scripts/run_offline_evaluation.py --profile 0 --output ../../.e2e/c3b-mock.json`：通过，离线 Mock，真实 Provider 请求/费用零。

完整 CI 必须核对本 PR 精确 HEAD；在运行中的检查不记作成功。原 Linux PowerShell Fake Native 平台 skip 如实记录，不增加平台豁免。日志保留在忽略的 .e2e，不上传临时角色或诊断原始数据。

## 7. 后续前置条件和持续 BLOCK

尚未证明任意语义独立性、全会话语境理解、一般数字/同义身份、多语言及无限句式、真实事实真伪、生产角色/部署、持久化原子性、CO3 幂等/恢复/崩溃、来源写入审计或关系版本。本实验的真实 Chromium 回归是既有页面兼容证据；预检本身无 HTTP/UI，不能宣称 typed writer 用户闭环已实现。

未来事务 writer 仍须独立审查：Session/Fact/关系锁与版本重验、来源不可变性、all-new 批次原子性、Turn/Fact/FC/FS/FCS/CO 双射、跨合同 key 冲突和 GET-only 恢复、进程崩溃/并发、rejected 全入口规则和安全澄清、受限 LOGIN/owner/ACL、迁移回滚及危险 downgrade。不能用本次预检结果替代任何一项。

D4：关系、计划与后续完成仍需独立来源和待批协议，未实现 related_plan/FactProgressLink。D5：显式声明校验不等于 classify；旧 typed 编辑和自动退级未开放。D6 剩余新旧写入/恢复及完整客户端协议继续 BLOCK。D8 生产权限、全部生产工厂、真实 Provider、付费和部署继续 BLOCK。政策 A/B、born-contract、旧客户端截止、删除和 worker 收尾必须分别审批。

0001–0015、历史 JSON、现有 writer/CO1/CO2、FactV3/summary2/export2、02/03/typed-read、MiningContext、Prompt、Provider 和 frozen 评测均不修改。交付仅独立 Draft PR，停止等待复审；不 Ready、Merge、Deploy 或进入下一阶段。

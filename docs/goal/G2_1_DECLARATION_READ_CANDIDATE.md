# G2.1 分类声明与来源依据：隔离读取合同候选

状态：**SYNTHETIC_CONTRACT_ONLY / 待独立审查**。基线 main `b96581175f4a2a307a7cfcfb7d60d1609d83983d`；#44/#45/#46/#49 已合并，#47 被 #49 替代并关闭。main CI 39963621888 在同一 HEAD 全绿；G0 #48 的状态整理 CI 39979217045 在 `1e1fc3ebd4de8d0c9119c853c09d85015dbe0bb4` Windows/Linux 全绿，自动恢复仍未启用。本 PR 只在 `research/declaration_read` 准备 Python/TypeScript 隔离解析器及合成测试，不改变正式产品代码。源依据为 B2C_DESIGN §4/§9、c2a/c2b/c2c、c3a/c3b 和已合并 M1 候选。

## 1. 现状与本候选的责任

当前 Python `read_contract.FactV3` 与 React `experience-read-contract.ts` 都规定 classification_citations 最多 0 条，classification_basis_status 仅 legacy_unclassified/not_recorded。`experience_read.Projection` 总是按此合同返回；数据库 0015 没有本候选的独立分类声明记录。**本次没有把这些空字段改成非空，也没有实现分类依据写入。**

本候选增加一个独立、尚未注册的读合同名 `classification-declaration-read-candidate-v1`，仅供合成资料解析。暂不分配 FactView v4、summary v3、export v3 或 HTTP 路由；不做 Accept/查询参数协商，不让旧客户端忽略新增字段后继续消费。正式路由、版本号、权限及完整历史策略须联审。

它回答“候选读包中的标签、声明记录引用和文字切片是否内部一致”，不回答：声明是否真实存储、用户是否真实登录、历史是否完整、文本语言是否支持该标签、事情是否发生、能否写入。`synthetic=true` 是实验范围声明，不是识别真实资料的安全机制。

## 2. 固定根字段与三种状态

根字段严格为 read_contract、synthetic、subject、turns、text_provenance、basis，额外键拒绝。解析失败 view=null，无部分投影；不会把失败降级解释为旧 FactV3。

subject：fact_id/session_id/project_id、正整数 fact_version、完整原文 statement、原 status，以及三列 fact_kind/progress_stage/classification_contract。保留 0015 的八种合法组合；pending/user_confirmed/evidence_supported/rejected 原样表达，不由分类改写状态，不推断真实性或贡献资格。没有 memory_state 或可由调用者传入的 truth_verified。

basis 的唯一字段是 status 与 declaration：

- `legacy_unclassified`：只适用于 legacy-v0；declaration 必须为 null。“旧资料未分类”，不能显示为明确完成。
- `not_recorded`：适用于 unclassified-v1 或 explicit-typed-v1；declaration 必须为 null。即使原始和当前正文都有精确来源，也显示“暂无分类声明依据记录”。
- `user_declaration_recorded`：仅 explicit-typed-v1，必须带完整的合成声明记录。含义仅为“读包包含用户明确分类选择的记录”；不使用 verified、platform_verified 或独立认证措辞。

recorded 的声明合同固定 `explicit-user-classification-declaration-candidate-v1`。字段全部必填：declaration_id、declaration_contract、record_type=explicit_user_choice、actor=user、fact/session/project ID、fact_version、classification 三列、statement_citations、declaration_source、recorded_validation、UTC recorded_at。

声明绑定同一 Fact 当前版本、Session/Project 和相同分类三列。旧版本声明不能直接投影为当前依据；缺少当前声明时不得继承或自动修补。recorded_at 只验证日期格式/日历值，不推断持久性、可信时间或版本排序。

`recorded_validation` 固定记录 c3a 已存在的 contract=typed-semantic-spike-v1、status=eligible_candidate、code=finite_rule_match；这是**包中声称的提交时结果**。本读取解析器不调用 c3a，不扩大语言模板，也不认证该结果确曾发生。结果明确 language_validation_replayed=false。未来受信任服务端必须依据真实不可变记录，并在写事务中执行正式版本的完整校验。

## 3. 正文来源与声明依据分别表达

turns 包含本包所需的合成 User Turn ID、session_id、role、完整 content。它们不能来自数据库读取替代品，因为本模块根本没有数据库；任何未来服务端适配器必须自行证明保存的原文与身份。外 Session、assistant 引用、重复 Turn、无引用的额外 Turn 都拒绝。

text_provenance 固定 original/current 两组，每组包含 availability、turn_ids、citations。精确引用为 turn_id/start/end/quote；区间是严格 code-point 半开区间，bool/float/string 不当整数；不做 Unicode 正规化、数字改写或 UTF-16 转换。同一 Turn 内顺序递增、不重叠、不重复，组内 Turn 清单与引用一致。

`unquoted_source` 保留确有源 Turn 但没有精确切片的资料，citations 必须为空；不得凭正文相似自动造切片。`exact_quotes` 必须有引用。当前 exact quote 必须是完整 statement，而非拼接或删去限制语后的片段；完整 Turn 原文仍保留供核对。此候选不支持只由多个片段拼装的旧正文，遇到这种数据需要单独扩展审查，不能宣称已覆盖全部旧读取合同。

声明的 statement_citations 必须显式记录，并对应当前文字引用及同一版本；不存在声明时不会从 current/original 自动填充。原始建档 Turn 中相同原文不能替代后来用户选择记录的引用。该引用只证明声明“针对哪段文字”，**不是**一段能够独立证明类型、完成情况或成果可信度的外部证据。

独立 `declaration_source` 必须引用另一个完整合成 User Turn，不能复用 original/current Turn。该 Turn 原文固定为 UI 选择编码 `我选择事实类型为 {fact_kind}，进度为 {progress_stage}。`，区间必须覆盖全文；遗漏或替换声明来源时拒绝。这是合成界面显式选择的编码，不是 c3a 语言模板扩张，也没有真实创建 Turn。三种来源分别回答“最初说了什么”“当前文字来自哪里”“在哪里作出当前分类选择”；它们都不证明事情真实发生。

当前版本候选不包含全量 FactChange/FS/FCS，也不是技术备份。历史导出将需要明确独立扩展：每条不可变声明对应自己的历史版本；缺字段 legacy 用受控解释但不写回原 JSON；当前标签被改回 legacy 仍必须通过既有整会话 typed-history 门禁。单纯把本解析器接到 DB 后不能满足这些义务。

## 4. 信任边界和保留的反例

每个 Result，无论 parsed_candidate 或 rejected，固定：evidence_class=synthetic_contract_only，authentication_verified=false，database_history_verified=false，language_validation_replayed=false，truth_verified=false，persistence_authorized=false。

测试明确保留了一个非安全保障的观察：调用者可以同时伪造 subject、原文和 recorded_validation，使“我计划部署服务。”与 personal_action/completed 在结构上自洽，解析器会返回 parsed_candidate。测试同时调用**未修改的 c3a**，确认它不会把这个 completed 声明判为 eligible_candidate。该差异证明 DTO 解析不能替代语义校验/真实来源/写事务；不将它隐瞒为“分类准确”。

真实未来入口需要先鉴权，随后 SELECT-only 身份、同一 RR/READ ONLY 快照、Schema/ACL/整会话历史及来源验证，再生成新投影。当前包里的 Session ID 相等仅是结构检查，不是跨会话鉴权证明。缺权限或历史时不能拼出假的完整备份。不会把本候选接入旧 reader 形成第二套未经审查的来源投影器。

## 5. 可执行证据与兼容边界

命令：`python -B -m unittest discover -s research/declaration_read -p "test_*.py" -v`。测试包括记录缺失/显式声明、八种三列组合、四种审核状态、版本/ID/枚举严格拒绝、原始/当前引用替换、未知校验合同、日期、27→28、emoji/组合字符/ZWJ/CRLF、UTF-16 错位、重叠/重复/遗漏引用、JSON 重复键、无部分响应、输入不变、生产隔离，以及上述结构自洽但语义不成立的反例。

本地 Python 43 项（含 53 个共享用例子项）、TypeScript Vitest 57 项及 `tsc --noEmit` 通过。共享 JSON 覆盖八种分类组合 × 四种审核状态，两个实现按显式预期解析同一材料。命令：`npm ci --ignore-scripts --no-audit --no-fund`、`npm run typecheck`、`npm test`，目录 `research/declaration_read/web`。独立 Windows/Linux CI 重复这些检查。Node 22；JSON 文本入口拒绝重复键、非有限数、非整数词法，直接 JS 对象无法区分数字 1 与 1.0，因此跨语言文本边界使用 parseJson。

现有 FastAPI/React/Chromium/迁移/12/48/质量/Mock 均未修改；本 PR 不声称做过正式产品集成验收，也没有数据库身份或持久化证明。后续原型里程碑的综合回归另记实际执行证据。

未实现：真实声明持久化、FactView/summary/export 新路由、完整历史适配、正式前端真实消费、R03 独立性证明或人工决议、正式 typed writer、classify、related_plan、自动退级、新迁移和角色、生产工厂/Provider/部署。没有回填老快照或把新声明当作旧依据。

## 6. 后续联审决定

1. 用户选择记录的正式数据模型、不可变审计与与 Fact/FC/Turn/未来 CO 的原子关联，由 G2.3 给出设计，不能靠本 DTO 自证。
2. 新版本读取是否使用独立 FactView v4，如何将声明历史纳入完整 export，以及审核状态与分类依据的展示，由 D5/D6 联审决定。
3. 旧标签缺记录、typed 编辑后当前声明失效、关系进展另建事实的产品语义仍未批准；本候选不实现 classify 或 typed 编辑。
4. G2.4 合成界面可试用本合同，但必须直写“合成演示，未保存”和“用户声明不是平台认证”。真实前端和正式 writer 继续关闭。
5. 所有 R03、D4/D5 正式批准、D6 剩余、D8 及生产 BLOCK 保留。保持 Draft，等待独立审查，不 Ready/Merge/Deploy。

收尾跨语言红灯：全角年份的 recorded_at 原 Python 以 \d 接受、TS 以 ASCII 拒绝；共享用例先实测失败（parsed_candidate），再将 Python 日期格式限定 ASCII 数字。修复不改变正式 DTO、语言规则或时间可信性边界。

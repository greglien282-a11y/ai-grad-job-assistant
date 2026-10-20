# B2-c2b-read 固定只读合同候选

基线 main `8113c59a9e07bf544d92ee1e07a3f66085918819`。开工前核验
workflow `39385700781`、FastAPI、React、Chromium 均 completed/success，HEAD 一致。
本 PR 不修改 0001–0015，不增加 writer、生产授权或部署配置。

## 显式协议与停止边界

仅实现两个候选 GET：

- `/api/v2/experience/projects/{pid}/experience-summary`，固定 `summary_contract_version=2`。
- `/api/v2/experience/sessions/{sid}/export`，固定 `format_version=2`。

两者显式嵌入 `fact_contract_version=3`、`provenance_version=3` 的 FactView。
本轮不提供独立 Fact GET/会话聚合 v3 路由，也不提供 Accept/查询参数/客户端能力猜测
或通用版本协商器；这些路由选择继续留待独立审查。v1 不自动升级或省略 typed。
新只读 factory 默认关闭，无环境开关；测试注入独立受限、仅 SELECT 的真实 LOGIN。

同一实际连接先设置并核验 REPEATABLE READ READ ONLY，随后定位资源、鉴权，
再核验身份、权限、Schema 和完整来源/历史。无 FOR UPDATE、advisory lock、回执、
期限登记、修复、清理、Provider。整个响应完成校验后才返回，无流式部分备份。

身份准入拒绝角色成员关系、owner、CREATE、业务 DML、额外表 SELECT（含 paid 表）、
可执行的受保护函数和不安全函数 owner/ACL；来源表有 RLS 也拒绝，避免过滤后冒充完整。
只接受唯一的已知分类 Schema 标记，已知/未知标记混存也失败。不增加 Alembic 表读取权限。
错误统一安全输出：外会话/不存在资源 404；默认关闭 `experience_read_disabled`、
权限/身份 `experience_read_runtime_unapproved`、Schema 不支持、损坏或不完整
`experience_read_integrity_unavailable`、实际隔离级别不符 `experience_readonly_required`
均为 503，无 SQL/正文/原始异常。全部响应沿用 no-store，不做错误后的旧路由 fallback。

## 正文资格与排序

所有列表按事实 `(created_at,id)` 升序，不按类型偷偷重排。
confirmed 仅含确认/材料支持的 legacy-v0，或 explicit-typed-v1 personal_action/completed。
legacy 仍明确标记未分类，不能解释为已完成。pending 全部列入 pending；rejected
不入当前正文、pending 或 reviewed_non_contributions。text 为 eligible 原文逐条以 LF
连接；incomplete 只表示 eligible 为空，不润色或推断。

reviewed_non_contributions 只含当前确认/材料支持而不 eligible 的事实，固定 reason：
unclassified-v1 → classification_unreviewed；personal_action/in_progress → action_in_progress；
plan → plan_not_contribution；background → background_context；boundary → boundary_limitation。

## 来源及技术备份

v3 分开 original_source_turn_ids、current_statement_source_turn_ids、
current_statement_citations、classification_citations、classification_basis_status。
当前正文来源为最新 edited（若有）对应的 statement FCS，否则是 created 的原始来源。
无对话引用的旧手工编辑如实返回空来源，不能恢复建档引用。记忆/确认不换正文来源。
没有精确引用的合法旧 FactSource 可保留其 Turn ID，不能据此编造 quote/区间。
typed 原始来源的精确 quote 必须与 created 初始正文逐字相等，不能仅证明坐标有效；
没有精确引用的 typed 合成旧形状仅接受整 Turn 原话与初始正文完全相等，不猜区间。
该检查不拿后来编辑的正文对比旧建档引用，也不改变 legacy 原合同。

0015 没有持久分类依据表或 classified 写入合同，因此 classification_citations 固定为空，
basis_status 对 legacy 为 legacy_unclassified，对 synthetic typed 为 not_recorded。
建档引用不充当分类证据；枚举合法不代表分类语义已获证明。遇到未支持的 classified
动作/新版本拒绝读取，不猜测未来分类协议。

export v2 保留所有状态的当前 Fact、原始 before/after JSON、解释注记、FactSource、
FCS、关联 CO 的非凭据元数据、项目/Turn/材料、原始挖掘状态/问题/回答关联。
不导出 Bearer 哈希、操作键摘要/证明摘要或 paid_*；它是业务技术备份，不是可重放的
授权/凭据备份。历史缺全部分类键仅在额外注记中解释为 legacy，原 JSON 不添加键。
未知枚举/部分键、当前与历史冲突、版本缺口、悬空/跨会话来源、错误 Unicode 引用、
不支持 CO 版本及缺 SELECT 固定失败，不返回过滤后的假完整数据。

CO/FCS 按 effect_slot 核对事实/历史/前后版本及角色；v1 clarification/resolution
继续保留原始输入 Turn，不造新的来源。过期但仍属当前会话的审计原样备份，不调用回执
恢复的期限处理或清理。当前标签恶意改回 legacy 而历史仍 typed 时，新读取也固定失败。
新合同要求可以证明的完整历史；旧资料不能满足时拒绝新投影，不能用默认值修补。
这不改变合法 legacy 的 v1 读取、回执恢复或原始数据。
历史核心 statement/status/version 必须完整，已记录的 origin/memory/source_kind 必须
为已知枚举；相邻快照同样损坏不代表有效。只有 edited 可以改变正文，确认/记忆记录
不能偷偷替换正文后继续引用旧来源。这些仅是新读取校验，不修写旧历史。
每个历史版本按该版本最新 edited 复核来源向量，历史材料/Run 指针也须在完整备份图中。
相邻 before/after 同样缺失来源字段或引用不存在的材料，仍固定失败。FactSource 行无顺序
合同，引用以保留重复数量和 JSON 类型的集合比较，返回的历史数组不重排、不改写。

## 保留 BLOCK

TS 提供独立严格 DTO 解析与语义反例，不接入旧 React 工作台；旧 Zod 吞 extra 不算验收。
02/03 真实 typed 消费及完整入口升级仍未验证，D6 未关闭。typed append/classify/
related_plan/自动退级、Provider/MiningContext 新版、R03 全入口语义防复活、生产
owner/ACL/运行角色/工厂启用和 D8 授权全部继续 BLOCK。仅交付 Draft PR，等待复审。

# M1-1B-3 幂等修复合同提案 v2（待批准，尚未实施）

2026-10-13，根据 [PR #5 第一轮完整 Review](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/5#pullrequestreview-5505112934) 修订。本文件是拟议合同，不代表批准或已实现；PR #5 继续 Draft，Issue #1 保持 open。

## 1. 已复现问题与设计取舍

真实 React → FastAPI → PostgreSQL，提交到真实服务后丢弃响应，不伪造成功。

- 创建返回 201、数据库已有 1 个会话，但浏览器没有凭证，不能读取、导出或删除该会话。
- 新增事实返回 201、数据库已有 1 条事实，界面保留输入。手动重试后数据库出现 2 条事实。
- 两项验收测试保留原始成功条件，正常失败；不得用 skip、预期失败、放宽断言或 continue-on-error 隐藏。

保留三个分步 POST、现有事实来源和 PATCH 整数 version/409 规则，仅扩展创建类请求的可选幂等合同，不增加原子事实 API。无键旧客户端行为兼容，但不承诺它具有新的响应丢失恢复能力。

相较 v1，提出两项明确增加，需负责人批准：只读创建恢复 GET，使刷新后不必持久化经历正文也能找回已提交会话；带时间戳及 Bearer 绑定校验码的请求键，采用 **24 小时硬有效期**，使墓碑到期清理后旧键仍不能新建。使用内置 HMAC/Web Crypto，无须额外服务端加密密钥或加密依赖。

## 2. 请求键、权限与正文一致性

三个写接口：`POST /api/v1/experience/sessions`、`POST /api/v1/experience/sessions/{session_id}/turns`、`POST /api/v1/experience/projects/{project_id}/facts`。

### 键和凭证

- `Idempotency-Key` 为 `v1.<issued_at>.<nonce>.<proof>`，最多 128 个 ASCII 字符。issued_at 为规范十进制 Unix 秒；nonce 为 32 字节 CSPRNG 随机数的无 padding base64url（43 字符）；proof 为 HMAC-SHA256 的相同编码。服务端拒绝重复 header、超长、非规范编码及解码长度不符，返回 `422 idempotency_key_invalid`。
- proof 密钥是 Bearer 字符串的 UTF-8 字节；消息为以换行分隔、无尾随换行的 `pathwise-idempotency-v1`、操作种类、作用域、issued_at、nonce。绑定固定为 `create_session/global`、`add_turn/session:<规范 UUID>`、`add_fact/project:<规范 UUID>`。恢复 GET 使用同一创建绑定。键不能跨操作/项目/会话挪用。
- 创建前浏览器用 Web Crypto 独立生成 32 字节随机 Bearer（规范 base64url 43 字符）及 nonce，不使用 Math.random。创建成功后该 Bearer 成为正式会话凭证，活会话只存现有 token hash；不换凭证，不在操作表保存凭证。服务端能验证格式，不能证明客户端随机数的实际熵，正式身份和限流仍是后续边界。
- 时间由服务器 UTC 判定：issued_at 不得超过 now + 300 秒，且 now 必须小于 issued_at + 24 小时。过于超前为 `422 idempotency_clock_skew`，过期为 `410 idempotency_key_expired`；未知/从未使用/已删除/已清理的旧键同样拒绝。锁等待后、父行锁后及提交前重核期限，不能用事务开始时的固定 now() 放行已经到期的请求。成功或重放都不延长有效期。浏览器可按响应 Date 校准时间，但不能改正在恢复的键的时间戳。
- 完整签名键的 SHA-256 摘要是全局唯一操作标识。创建重放先检查 Bearer/proof，活记录再校验对应会话 token hash；比较 proof、request_tag、token hash 使用常量时间比较。只有键、错误 Bearer或不匹配 proof 得到 `401 idempotency_credential_invalid`，不获得会话信息。已有回合/事实先检查原会话归属，再查操作表；无权限仍为现有 404，不能凭键越权。
- 无键创建严格兼容现有行为：服务端生成凭证，不把额外 Authorization 当成候选新凭证。带键缺 Bearer不能退回旧路径。新前端必须在请求构造层拒绝缺键/凭证的幂等创建，成功响应也核验其 token 与 pending 一致，不能将候选凭证误当作无键创建的正式凭证。其他无键请求沿用既有授权。

### 同一请求的定义

经 Pydantic 校验后，计算 `HMAC-SHA256(UTF8(Bearer), UTF8(操作 + 换行 + 作用域 + 换行 + 规范 JSON))` 作为 request_tag。规范 JSON：键名排序、无额外空格、UTF-8、非 ASCII 不转义；UUID 为规范小写，source_turn_ids 顺序保留。文本不 trim、不 Unicode 归一化。属性顺序/JSON 外层空白可不同，实际正文字符变化就是不同请求。Python/TypeScript 必须共享中文、emoji、换行、UUID 的校验向量。

活操作仅存带密钥 request_tag，禁止存完整正文/响应或无密钥正文 SHA-256；删除时连此标签也清空。同键、合法同 Bearer、不同正文返回 `409 idempotency_payload_mismatch`，零写入、不回显原正文。键摘要及带密钥标签不能替代授权。

## 3. 创建响应丢失、临时存储与刷新

### 发送前及当前页恢复

1. 点击创建后锁住重复提交，将校验后的 raw_input 冻结在组件内存中。在**任何 POST 之前**写入并回读验证 `pathwise.development.pendingCreate={schemaVersion:1,key,token,bodyTag,expiresAt}`。bodyTag 是第 2 节的请求标签；expiresAt 从键时间推导。禁止保存经历正文、事实、材料或完整响应。
2. Web Crypto/storage 不可用或写入失败时，阻止创建请求、保留内存输入，提示开启当前标签页暂存或更换浏览器。不能悄悄退回不可恢复的无键 POST，不能使用 localStorage。
3. 发送同一 Bearer/键和冻结正文的 POST。等待中禁用重复创建/修改原输入，不自动重试写请求。
4. 收到 201；或网络/响应格式错误后**一次自动只读恢复 GET** 得到 200：先写入并回读验证正式 `pathwise.development.session={sessionId,token}`，再删除 pending，随后读取会话聚合。两个 storage 操作不是原子事务，顺序必须避免中途刷新丢失两份凭证；两份匹配时优先正式记录，矛盾时停止并提示核对。
5. 原 POST 响应丢失、只读恢复成功时，明确以 alert 提示“创建响应未收到，已恢复刚才的会话，请核对资料”，不模拟原请求正常成功。正式凭证迁移完成后才展示恢复结果，使原 E2E 的“错误提示后存在可恢复凭证”断言真实成立。已收到 201 但聚合 GET 失败则说明“创建已保存，资料读取失败”，禁新建、允许重新读取。
6. 自动 GET 也失败时显示“创建结果暂不确定”及**恢复刚才的创建操作**按钮；键/凭证不变。按钮先 GET，只有专用未找到结果且仍有内存原正文时，才允许用户明确选择“用原输入重试创建”，使用同键/凭证/正文。输入改动先比较 bodyTag，不暗中换键。
7. 正式存储迁移失败不删除 pending；本页仍可用内存凭证读取/导出/删除，明确提示暂存失败。刷新尝试 pending 恢复；浏览器彻底丢失存储时不能承诺恢复。

### 只读恢复 GET 与刷新

新增 `GET /api/v1/experience/session-creations/recovery`：无 query、无请求正文；只用 Authorization / Idempotency-Key，验证原创建绑定/期限，不隐式新建。

- 已提交且会话可访问：200，返回第 4 节创建收据，再迁移正式凭证并读取会话。
- 未找到已提交记录：`404 idempotency_creation_not_found`。与同键 POST 取得相同事务锁，等待正在提交的请求。若 GET 比迟到的 POST 更早取得锁，404 只说明检查时未提交，不证明以后永远不会成功，因此后续只能同键重试。
- 错凭证、删除、过期、锁超时分别为下文 401/410/503；GET 不插入会话、操作记录或历史。

刷新时有正式凭证就读取已有会话；只有 pending 时自动尝试一次只读 GET，并显示同名恢复按钮。**不自动 POST，不自动生成新键。** 未找到且内存正文已丢失时，提示重新输入原经历；仅在内存中重算 bodyTag，一致后才能显式同键 POST，不一致则停止。用户无法重建原输入时，不承诺恢复未提交操作；仍可只读查询可能迟到的提交。

pending 只保留键的剩余 24 小时；运行及刷新检查并清除过期暂存，明确说明恢复窗口结束。正式凭证不随操作键到期，仍只限当前标签页。24 小时后尚未恢复、关闭标签页或清空 storage 造成凭证遗失是明确限制；不自动删除未知会话，不声称无限期找回。此有限窗口需要负责人批准。

### 新增回合/事实

一次新增冻结 statement，在内存保留独立回合键；回合 ID 返回后生成/冻结事实键及其请求标签。回合 201 丢失则同键重试得到同一回合；事实 201 丢失则同键重试原事实。内容不同不能换键覆盖，不重复来源/历史。

刷新后只读聚合，内存草稿/未完成新增键不持久化、不自动补发 POST。存在孤立补充回合时允许用户核对后显式选择该回合继续建档，不能自行把文本相同的数据认作重复。本修复增加必要恢复入口，不改产品方向。

## 4. 并发原子性、重放响应与状态变化

### 事务和锁顺序

沿用现有 function-scope 事务。校验输入/header/proof 后，以完整键摘要派生 64 位标识取得 PostgreSQL **事务级 advisory lock**；同键 POST/恢复 GET 使用同一锁，锁等待上限 5 秒。64 位碰撞只增加串行，唯一性由完整 256 位 key_digest 的数据库唯一约束保证，不能使用进程内锁替代。

统一写路径：操作 advisory lock → 父会话行锁 → 活操作行核对/写入。新创建在同一事务写会话、项目、初始回合及收据。创建重放先无锁读 session_id 仅作定位，父锁后必须重读操作状态和授权，不能父锁前持有操作行写锁。删除/结束沿用父锁，删除不获取 advisory lock，避免反向锁顺序。

业务与操作同一次提交，仅持久化 completed/deleted，不留下跨提交 processing 半记录。同键并发只提交一次；不同正文并发首个成功提交占键，另一个 409 零副作用。失败/未提交则全部回滚，等待者可同键执行；唯一冲突用 savepoint/冲突处理或整体回滚，不在失败事务中继续查询。响应须在成功序列化及事务提交后发送。锁超时安全 503，不能降级或换键。

重放与删除在父锁后重核：重放先完成可返回当时结果；删除先提交就不能返回被删资料。机制依据 [PostgreSQL 16 事务级 advisory/行锁](https://www.postgresql.org/docs/16/explicit-locking.html) 及 [INSERT 唯一冲突处理](https://www.postgresql.org/docs/16/sql-insert.html)，必须由真实多连接并发测试验证。

### 状态码与响应内容

- 首次三个 POST 为 201，成功重放也为 201，增加 `Idempotency-Replayed: true`；恢复 GET 为 200并带此标记。不保证响应字节相同，明确返回当前资源视图，不存全文快照。
- 创建收据：`session_id,project_id,initial_turn_id,status,access_token`。ID 是原结果，status 是当前 active/ended，access_token 仅由本次已核验 Bearer回填，不从数据库保存明文恢复。幂等客户端 schema 需接受 ended，无键首次创建仍为原 active 合同。
- 回合返回原 TurnView；事实返回**当前 FactView**及最新 statement/status/version/来源/材料指针。A 已编辑为 B 后旧创建 POST 重放只读返回 B，不能写回 A、重新 pending、恢复旧来源或新增 FactChange/FactSource；前端再读聚合核对。
- 会话 ended 时，已成功操作可授权只读重放；不同正文仍 409，无原成功记录的新回合/事实仍按原状态规则拒绝，不能重新开启会话。
- 会话 deleted 时，有效原创建键及正确 Bearer proof 的 POST/恢复 GET 为 `410 idempotency_resource_deleted`，不含收据。回合/事实先授权失败，仍为 404，不以墓碑泄漏归属。到期键统一 410 expired，不能重新执行。
- 结果意外缺失、父会话仍在：`410 idempotency_result_unavailable`，不重建；当前没有单独删除项目/回合/事实接口，未来需另定义合同。

## 5. 操作表、墓碑、删除与保留期限

一张 `idempotency_operations` 表、一版迁移：`key_digest` 全局主键、`state`（completed/deleted）、`expires_at` 索引；活行附加 operation、session_id、target_id、request_tag、按操作需要的结果 ID（project_id/initial_turn_id/turn_id/fact_id）。约束保证 completed 收据足够定位，deleted 附加字段全 NULL。不存响应 JSON、Bearer、独立凭证摘要、业务全文或 IP。

删除授权后在父锁内，把会话的全部活操作变 deleted，并清空关联、request_tag、结果 ID；再删除会话及级联项目、回合、事实、来源、材料和历史，包括现有会话 token hash。全部同事务，失败全部回滚。操作表不能 ON DELETE CASCADE 导致未过期防重放记录消失；迁移允许墓碑解除关联，不留下 dangling FK。

墓碑**只剩 key_digest、state=deleted、expires_at**。不得保留任何正文/正文摘要（即便 HMAC）、Bearer/proof 原文、凭证摘要、会话/用户/资源 ID或删除原因。proof 随原键由客户端持有，服务端用传入的 Bearer校验绑定，无须在墓碑留下认证材料。只知键不能认证；持合法原请求者只能得到无个人内容的 410。

保留至**原 issued_at + 24 小时**，不是删除后再延长一天；最多因允许的客户端时钟偏差额外 5 分钟。活操作也到期清理，正式会话数据/凭证不因此到期。墓碑清理后旧键仍被时间守卫拒绝；改变 nonce/时间/proof 是一个明确新操作，不是旧请求重放。

拟交付可重复受限清理命令，开发启动执行一次，部署每小时一次，不在业务响应中扫描全表、不自行安装系统定时服务。正常记录到期后 1 小时内物理清除；清理失败需报告条数/最老过期时间，不能无期限保留又声称已删除。不读取/打印正文，也不删除仍存活的会话或其他用户数据。部署清理安排是批准与交付条件。

## 6. 前端错误映射与安全边界

- `409 idempotency_payload_mismatch`：保留草稿/键，提示先恢复核对；不能走原事实版本冲突自动 GET/覆盖分支，不能悄悄换键。原 version/state 冲突仍沿用重新读取、needsReload 禁写、显式复核规则。
- 410 deleted/expired/result_unavailable：说明删除/窗口结束/结果不可用，停止旧写；只有用户核对并明确新操作才生成新键，不自动重建。确认当前会话删除成功时清除其正式/残留 pending 暂存及内存正文、标签和操作键；跨标签页已删除会话在重新读取后清除失效显示，不声称服务端能直接抹除其他标签页内存。
- `429 rate_limited`：若网关/后续限流返回，保留键与正文、遵守 Retry-After，不自动补发写入；本小修复不新增完整限流系统。
- `503 idempotency_busy`（锁超时，Retry-After: 1）、网络/其他 5xx：结果未知，保留操作；创建先只读恢复，其他先读资料再决定同键重试。422 安全文案，不因曾发送请求的校验错误而自动换键。
- Authorization、键、请求标签不进 URL、console、日志、导出、HAR/trace/GitHub 报告。CORS 对允许来源增加 Idempotency-Key 请求头及 Idempotency-Replayed 响应头访问，全部响应 no-store。现有输入/正文长度限制保留。

## 7. 后端、数据库、React 与 E2E 回归

### 后端及数据库（真实 PostgreSQL）

- 无键兼容（包括创建时多余 Authorization仍不改变原服务端生成凭证行为）；键格式/重复 header/长度/缺凭证/跨操作/时间超前/到期；Python/TypeScript proof和请求标签共用向量；仅键、错误凭证、跨会话/项目均不能获信息。
- 同键同正文同 ID；等价 JSON一致、不同正文精确 409且零副作用；恢复 404 与业务 404 区分；no-store/CORS/日志与导出无凭证。
- 独立连接+同步屏障：同键创建仅一会话/项目/初始回合，回合/事实仅一次来源/历史；不同正文一个成功一个 409；提交后丢响应、事务中途失败全回滚、GET 等待正在提交、锁超时、删除竞争。
- 确认/编辑/材料核实/结束后重放创建，返回当前状态/版本/来源，无新增历史或覆盖；新写 ended 仍拒绝。
- 删除后实际表查询：业务数据和 request_tag/凭证摘要/所有归属 ID清除，墓碑三字段及 NULL 约束；正确原请求 410、错误 Bearer不能认证、回合/事实先授权；到期/清理前后旧键不复活且其他会话不受影响。
- 空库 upgrade、已有数据 upgrade、Alembic check；原 49 项后端测试保留。

### React

- pending 写入/回读发生在 POST 前，CSPRNG/storage 不可用、构造请求缺键/凭证时零请求，快速点击稳定键；返回凭证与 pending不一致时停止并恢复核对；正式存储先写后清 pending及中途崩溃/双记录冲突/迁移失败。
- 创建响应丢失 → 只读恢复 → 正式凭证 → 读聚合，真实恢复 alert；刷新 pending只读、不自动 POST；404后重输 bodyTag门禁、不一致/删除/过期不重建；正文不进任何存储。
- 回合/事实丢响应稳定键恢复、刷新只读和显式孤立回合选择；幂等 409 与事实冲突分流，429/503不自动写；原 21 项交互测试、TypeScript/Vite 构建保留。

### Playwright 真实 E2E

PR #5 原 11 项不删、不改验收目标。原创建丢响应仍断言数据库一会话、真实提示后有可用正式凭证；原事实丢响应仍断言手动重试数据库仅一事实。修复应让这两项真实变绿。

追加创建已提交丢响应后刷新并能导出/删除；未提交刷新只读 404、重输/改输入门禁；恢复 GET也断网；回合 201丢响应且来源唯一；真实多客户端并发/改正文/换凭证；删除和墓碑清理后旧键不复活；A编辑为 B后旧 POST重放不覆盖。继续独立端口/专用库新 schema、合成数据与数据库审计、Chromium CI/Windows Edge，不上传凭证或 trace。

## 8. 交付与批准边界

本轮只更新此提案，不修改接口、迁移、React或既有 E2E。负责人批准只读恢复 GET、签名键/24小时窗口、当前资源重放及清理安排后，再从**届时最新 main** 创建 `codex/m1-1b-idempotency-fix` 独立小型 Draft PR。

修复影响：三个 POST + 一个只读 GET、一个 SQLAlchemy 模型/迁移/清理命令、前端恢复/键生命周期/错误映射、必要回归测试。不把 E2E基础设施整包复制到 main。修复 PR先通过前后端/数据库测试，由人审查与合并；之后更新/rebase PR #5并跑全量真实 E2E全绿，再等待人工体验。任何 PR不自动合并，不关闭 Issue #1，不改原 PRD、prototype或 Pages。

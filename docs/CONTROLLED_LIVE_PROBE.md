# 路线 B：DeepSeek 单次真实合成探针（待审查、未执行）

基线 `c90586bdb61747f6374025ae862bab3abc6880c2`，合并CI `38729265573` 成功。本PR只交付工程，**真实调用0次、支出0元，未读取或配置真实Key**。0.10元是待确认的内部计划，不是当前批准金额。下文所有本机设置/审批/执行命令都是未来经审查和负责人明确授权后手动运行的步骤，本轮没有执行。

## 1. 独立实验合同

模式 `controlled_live_probe` 与原硬保证路径分离。C-0/C-1B `invoke()`、C-1C边界评估器、TokenCertificate、PaidPolicy和既有Mock门禁保持原样；不把估算写成证书，不修改12000限制或绕过为scripted。没有Web入口、后台任务、自动路由、开机授权、`.env`启用开关或余额客户端。

唯一候选：S03/b，原始UTF-8请求2521bytes，SHA `5cc2def4f875e43760e799678a43c1f2d2072dd4245eaf54457dfe78ee0b373e`。官方 `https://api.deepseek.com/chat/completions`，deepseek-flash，预期DeepSeek-V4.1-Flash（别名不是不可变权重），provider_managed_unverified区域，thinking.disabled、json_object、stream=false、max_tokens=256。原始字节逐次核对SHA及固定fixture，直接作为HTTP content发送，不重编码、修补或替换。

风险接受原文必须记录为：

> I accept uncertain supplier charges; this is an internal plan, not a guaranteed loss cap.

这明确允许讨论没有供应商硬计费上界的实验；**并不代表无限调用或无限支出**。技术上固定一次本地发送许可、一次POST尝试和明确金额/时间窗，无法声称供应商绝对只执行一次或实际损失绝不超过计划。费用异常/未知一律停止、占用计划额度并冻结总池，不能用新操作键补调。

## 2. 人民币估算及币种核验

[机器估算记录](evaluation/controlled-probe-estimate.json)来自2026-10-15本机实际离线计算：官方[Token文档](https://api-docs.deepseek.com/quick_start/token_usage/)链接的[V4归档](https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip)，SHA `e7310d1dafe0a86d8a5629fe78a7c763760f651db9b8682718a1781dcd6fe495`；只读取tokenizer.json，以固定 `tokenizers==0.22.2` 编码完整原始请求JSON，得到 **812**。不运行归档Python、trust_remote_code、Jinja模板或from_pretrained；不联网加载任何模型。

按[中文官方价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)观察的输入未命中高峰 **2元/百万**、输出高峰 **8元/百万**：`(812×2+256×8)/1,000,000 = 0.003672元`。不依赖缓存命中、谷价或赠金。这不是服务端framing计数，也未证明线上版本一致；未知开销、价格变化、异常收费和网络重复执行风险仍可能使账单高于估算甚至高于计划。256内也可能产出截断/非法JSON，不能因失败而再发一次。

本阶段原币只实现CNY。必须由负责人先核实**实际官方账户的结算币种及适用单价**，保留私有核验原件，并在授权中记录非秘密账户引用、currency_evidence_sha、price_evidence_sha及有效窗口。不能从中文界面、所在地区、计划充值或本报价推断账户币种；若实际USD或存在币种歧义，停止，不设置FX=1，不把CNY存入USD字段，另审相应支持。程序不宣称可以离线证明Key真实属于该账户，账户与Key的正确对应仍由本机配置负责人负责。

峰/谷和缓存规则见C-1C；本策略固定已审查的峰值2/8，价格变化需更新设计和快照。授权最多一小时，price_expires_at覆盖授权窗口，是内部风险限制，**不是供应商锁价承诺**。0.10元仅为建议软目标，审批模板planned_cny=null；需要负责人明确填写并批准。代码最多接受0.10元内部计划，超过需另审，不自动增加额度。

## 3. 数据与权限（0009）

新增一张 `controlled_probe`，复用0008的 **同一个 paid_funding(1) 及ledger UUID**，无新预算池/namespace。0009不种授权、额度、价格或角色。新表单例id=1，终身保留，即使撤销、核账完成或未发送关闭，也不能新建第二份实验。

记录不可变审批policy/SHA、grant UUID、固定操作键摘要、账户/SecretRef/revision、币种/价格/估算/剩余风险、计划金额、窗口；可变状态、lease、白名单诊断及原币actual_cny/发票摘要。PR17审查修复新增dispatch_token_hash、dispatch_claimed_at；原文令牌只在permit成功时返回一次，之后不能从数据库SELECT重建。没有Key、完整请求/响应、原始错误、用户资料或系统提示。state变更和管理动作追加到既有paid_audit。

单池锁顺序 `paid_funding → controlled_probe`，同事务检查DB墙钟、吊销、policy/ledger/请求/操作摘要、剩余额度。预留使用**批准计划金额**，不是伪造的最坏收费上界。一次发送许可提交后立即冻结中央池；未知和成功未核账均保留held。新实验一旦授权，DB触发器阻止原paid_calls插入，使这个首次探针独占已批准中央池；不能与旧路径并行复制额度。授权只允许空、未使用的中央池，已有其他额度时不覆盖或叠加，需独立审查。

状态语义：

- `approved → reserved`：一次占用全部计划；同键不重复占用。缺少/到期/撤销授权、额度不足或绑定不符立即拒绝。
- `reserved → sent`：一次原子许可并冻结；只有刚完成本次reserve的执行者能沿流程申请，后续执行看到reserved也停止，不自动续跑。
- `sent → dispatch claim`：实际HTTP入口独立检查角色、政策、字节、授权/预算，并向SQL交回permit签发的随机令牌；数据库仅存其SHA，原子消费一次、记录时间并审计。消费后才可解析真实Key和构造实际网络Transport；发送前再次检查吊销/有效期。裸`_post_once(..., mock=None)`无许可立即拒绝。即使内部代码保留旧令牌也不能再次派发；崩溃后不重建或重新签发。
- `sent → response_received / unknown`：严格业务Schema/引用有效才算received；HTTP错误、截断、超时、取消、无效响应、密钥变化和解析失败均unknown。两者都不自动结算或释放。
- 进程在sent之后、HTTP之前或期间退出：保留sent/held/frozen。60秒后report仅投影unknown，不写库、不解析Key、不重发；账单可由管理员核账。
- `sent / received / unknown → reconciled`：独立管理员凭最终账单和复核摘要手工记录CNY，发票幂等，不允许覆盖不同金额。实际原币保留12位小数，中央CNY spent向上取整到微元；完整记录超计划，不截断，不自动解冻。
- `approved / reserved → reconciled`：管理员可凭证据close-unsent，确认从未取得发送许可才按0关闭；不产生新调用名额。sent禁止走此入口。

运行LOGIN仅SELECT和受限 `controlled_runtime`（以及复用配置所授的旧受限函数），无owner角色成员资格、DML/DDL/增额/审批/对账权限；拒绝superuser、CREATEROLE/CREATEDB/BYPASSRLS、SET ROLE掩饰身份及持久schema CREATE。DB函数固定search_path、限定schema，校验绑定和诊断白名单；运行角色不能修改审批或解冻。owner/DBA及同一Windows账户的恶意代码是明确的信任边界，本实现不是防DBA或本机恶意程序的沙箱。

**0009回滚保护**：先按相同顺序锁中央paid_funding及controlled_probe；只要存在任意行，无论approved/reserved/sent/unknown/response_received/reconciled，downgrade均在删除任何触发器/函数/表之前拒绝。事务回滚后记录、审批、冻结和Alembic版本不变，重新upgrade不能获得第二名额。仅空表允许0009↔0008往返。DBA恶意直接DROP/重建属于现有信任边界，正常Alembic不提供绕过或force选项。本PR未合并，继续完善0009，不增加新版本，不迁移日常库。

生产CLI只接受本机5432的专用 `pathwise_probe/public`、固定ledger UUID，不读取日常DATABASE_URL或环境Key。不建立或修改pathwise_dev。管理员凭证与运行JSON配置分离；普通业务进程不得取得owner配置。配置发布及中央ledger身份由负责人控制，不通过换数据库/端口/配置复制审批。测试只允许pathwise_test/e2e的随机schema，用独立offline_mock模式；Mock记录禁止作为真实发票结算。

## 4. 一次性本机配置（未来人工操作）

先取得代码审查通过及明确的账户/Key本机配置授权。无需新增系统软件；使用已有PostgreSQL16和Python3.12。下述DB/角色/凭据配置均须负责人另行确认后手动执行，本PR没有执行。

1. 在受控本机目录（例如 `%LOCALAPPDATA%\PathwiseProbe`）保存私有DB配置/审批原件。移除目录继承权限，仅当前操作者可读写；不在仓库、同步共享目录、命令行URL或前端保存秘密。不把管理配置交给运行进程。API Key不进入任何JSON配置。
2. DBA显式创建**全新**数据库及两个LOGIN。密码通过psql `\password`交互设置，不写命令行或Git：

```sql
CREATE ROLE pathwise_probe_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
\password pathwise_probe_owner
CREATE ROLE pathwise_probe_runner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
\password pathwise_probe_runner
CREATE DATABASE pathwise_probe OWNER pathwise_probe_owner;
REVOKE ALL ON DATABASE pathwise_probe FROM PUBLIC;
GRANT CONNECT ON DATABASE pathwise_probe TO pathwise_probe_owner, pathwise_probe_runner;
\connect pathwise_probe
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

3. owner-setup.json只含 `database_url`，连接127.0.0.1:5432/pathwise_probe及owner。未来运行一次：

```powershell
apps/api/.venv/Scripts/python.exe scripts/setup_probe_ledger.py --owner-config "$env:LOCALAPPDATA/PathwiseProbe/owner-setup.json" --runtime-role pathwise_probe_runner
```

输入明确 `SETUP pathwise_probe` 才迁移空专库并授最少权限。已存在表则停止，不自动升级未知资料库。输出ledger UUID，额度0。将UUID加入单独owner.json与runtime.json，格式均为 `{"database_url":"本机对应角色的私有连接串","ledger_id":"本次固定UUID"}`，运行进程只用runtime.json。设置完成后不因失败删库重建或生成第二个池。

4. 获准本机配置Key后，负责人亲自在**未开转录/调试记录**的Windows PowerShell执行：

```powershell
./scripts/set-probe-secret.ps1 -AccountRef '<已确认的非秘密账户引用>'
```

仅SecureString交互输入，不回显、无Key命令行参数或环境变量，不粘贴到聊天。通过Windows Credential Manager保存当前用户的Generic Credential，目标固定 `Pathwise/DeepSeek/<account_ref>`，不写明文Key文件。脚本只输出secret_ref、account_ref及非秘密secret_revision（LastWritten）。轮换/删除凭据、账户标签或revision改变均须停止并重新审查；当前单次授权不静默沿用新Key。

Python仅在人工execute取得完整审批/预算/sent许可并消费dispatch令牌后CredReadW；核对target/UserName/revision，失败不发网。只把Key短暂用于Authorization，最终CredFree并清理原生buffer；Python字符串/OS副本不能承诺完全清零。同一Windows用户的其他恶意进程仍可能读取凭据，这不是企业级独立出网broker；正式Web账户不能复用该配置。审查修复已用随机native_test条目及公开假值验证真实Windows写读/轮换/删除，见下方证据；没有配置或读取真实Key。

5. 官方公开tokenizer归档由负责人预先离线放到本机路径。估算器必须匹配上述归档SHA，只读其中JSON，不下载或执行远程代码。复制[无效审批模板](evaluation/controlled-probe-approval.template.json)到私有目录，填写并核对：账户/实际CNY证据、SecretRef/revision、ledger UUID、一次固定operation_hash、审批人/证据SHA、最多一小时窗口、适用价格证据、明确planned_cny及风险接受原文。所有null必须有实际依据；库内模板没有批准金额或风险接受记录。

独立管理员用owner配置登记明确的负责人审批（不会发网或读Key），并核对打印政策摘要：

```powershell
apps/api/.venv/Scripts/python.exe scripts/controlled_live_probe.py authorize --config "$env:LOCALAPPDATA/PathwiseProbe/owner.json" --approval-json "$env:LOCALAPPDATA/PathwiseProbe/approved.json" --tokenizer-archive '<本机官方归档路径>'
```

只有交互输入打印的 `AUTHORIZE <policy SHA前12位>` 才写入授权/计划。不能用此命令替负责人决定预算；需要先有明确的审查、账户/币种核实、风险接受和单次支出授权。不得在CI运行。没有默认正金额、自动有效期、默认审批人或自动risk_acceptance。

## 5. 三步人工执行

上述一次性配置和授权完成后，用**运行角色**配置：

```powershell
# 1. prepare：只访问本机专库和本地tokenizer，不访问供应商、不解析Key、不reserve
apps/api/.venv/Scripts/python.exe scripts/controlled_live_probe.py prepare --config "$env:LOCALAPPDATA/PathwiseProbe/runtime.json" --tokenizer-archive '<本机官方归档路径>'

# 2. execute：仅在负责人批准本次执行后手动运行；必须有Windows交互终端
apps/api/.venv/Scripts/python.exe scripts/controlled_live_probe.py execute --config "$env:LOCALAPPDATA/PathwiseProbe/runtime.json" --tokenizer-archive '<本机官方归档路径>'

# 3. report：只读，不补发、不调用余额、不解冻
apps/api/.venv/Scripts/python.exe scripts/controlled_live_probe.py report --config "$env:LOCALAPPDATA/PathwiseProbe/runtime.json"
```

prepare核验角色、中央UUID、固定请求/模型/币种/价格/时间、tokenizer估算、账户/SecretRef元数据和剩余额度；不验证Key有效性或查询实际余额。未有授权直接拒绝，不默认创建。execute重新执行检查，显示风险/账户/金额/SHA，必须输入 `EXECUTE <grant UUID> <policy SHA前12位>`；无TTY、非Windows、取消或不匹配均停止。没有`--yes`、批量参数、自动重试或后备模型。一次许可已使用，第二次execute拒绝，即便账单已核清。

HTTP固定CA证书验证、禁止重定向和环境代理，AsyncHTTPTransport retries=0，无SDK；connect5秒/read15秒/write5秒/HTTP总墙钟45秒，响应256KiB上限，显式Content-Type/Accept。HTTP路径记录关闭，不打印原始异常/头/正文/响应。响应经过严格envelope/用量一致性、Pydantic和既有引用/原子性校验；仅输出安全诊断及usage，不写正式经历库，也不自动确认事实。数据库sent意图并非供应商exactly-once保证。

report区分初始估算、按返回usage计算的峰值未命中估算及人工actual_cny；**前两项永远不是实际账单**。响应成功但未核账仍held/frozen；超时等结果不明也保留全部计划。错误后只运行report及人工核对，不换操作键、不重复执行。失败命令退出2且不输出traceback或连接串；成功执行只有state=response_received才退出0。

### 校验后的模型结果预览（PR17修复）

execute现在返回并显示`validated_preview`：候选事实及其quote/start/end/turn_id、下一轮问题及来源ID、停止理由。只来自经过envelope、usage、Pydantic、固定合成user原话/原子性及隐私检查的MiningOutputV2，明确标为“未经用户确认、未写入经历库”。不打印API原始JSON、headers、system prompt或未校验内容，不产生正式简历导出。

真实execute在发送前准备固定本机 `%LOCALAPPDATA%\PathwiseProbe\results`，只允许当前Windows用户拥有、受保护且唯一FullControl ACE；拒绝UNC、符号链接/junction和不安全权限。文件在写入首字节前同样收紧ACL，不能覆盖已有grant文件。POSIX测试采用目录0700/文件0600。同一Windows用户/管理员仍在既有信任边界内；这是私有明文合成预览，不是假称加密存储。

仅保存`<grant UUID>.json`的最小校验输出及ledger/grant/policy/request/execution绑定；不保存完整供应商响应、Key、usage以外的任意envelope字段或真实用户输入。保存前拒绝Key原文、凭据形态和PII；真实HTTP边界在Key尚在受限作用域时也检查JSON转义后的Key回显。账本diagnostic只增加文件SHA，不存模型正文。写入刷新/fsync后才记录received。

后续report无需读取Key或发网：校验owner/DACL、摘要、grant/ledger/policy/合成SHA，重新跑Pydantic及来源校验后才展示预览。丢失、被改动或权限过宽时隐藏内容并返回安全preview_error，仍显示费用/状态，不重新调用。模型有效但留存失败时保留本次execute内存预览供操作人审看，状态保守unknown、held/frozen不释放，并提示不可重试；若ledger更新失败但文件已写，只能人工检查受限文件，不自动相信未在账本提交摘要的文件。

文件不上传GitHub/CI artifact，不通过URL或前端传输，不当作事实确认。可在完成审查后由操作人手工删除具体grant文件；只影响本地预览，不能重置账本身份或发送名额。首次旧HEAD曾丢弃的结果无法凭空恢复，不会为恢复结果补发请求。

## 6. 恢复、核账与停止条件

真实账户余额、实际扣款和最终账单核对须**另行明确授权**。本PR不实现 `/user/balance` 或任何自动余额查询；execute许可不含余额访问。负责人获准后手工取得对应账户/币种的最终账单/扣减证据，排除其他账户活动，不把余额暂未变化当免费或退款。

管理员用owner配置、明确原币金额和证据摘要手动核账：

```powershell
apps/api/.venv/Scripts/python.exe scripts/controlled_live_probe.py reconcile --config "$env:LOCALAPPDATA/PathwiseProbe/owner.json" --actual-cny '<最终人民币金额>' --invoice-sha '<账单证据SHA>' --review-sha '<复核证据SHA>'
```

需要交互确认 `RECONCILE <ledger UUID> CNY <金额>`，相同账单同金额重放不重复扣账，不同金额拒绝。超计划完整登记，保持冻结；未核清不得假定0、退款或重发。未知调用长期保留占用，report可在授权过期/撤销后读取。撤销命令 `revoke --config owner.json --review-sha ...` 阻止尚未sent的调用；sent与实际出网间存在不可消除的小窗口，吊销不能撤回已交接的远端请求。

reserved但确定从未取得许可时，管理员可 `close-unsent --config owner.json --review-sha ...`，经交互确认后关闭，仍无第二名额。sent/unknown禁止走此关闭路径。对账/关闭不自动解冻、不自动再试；下一次实验须负责人重新讨论并审查新方案，不删除本行或重建中央库。

任一账户/币种/价格、请求字节、Key revision、模型/区域/模式/上限或policy不符，过期/撤销、预算不足、重复执行、运行角色不合格，立即停止。HTTP401/429/5xx、超时、取消、崩溃、非法JSON/来源或超限均不补发。Key解析失败也消耗本次本地许可并保守unknown，需要人工处理。

## 7. 测试、实际实现范围与已知限制

实现：0009单表/受限函数/审计触发器、CNY计划/核账、独立policy/owner管理/运行控制、实际固定HTTPS IO结构、Windows本机凭据接口与脚本、prepare/execute/report、tokenizer离线估算及安全诊断。原444项后端、62项React、30项E2E及12合同不修改。新测试只使用HTTP Mock、假密钥/假native内存和随机PostgreSQL schema，覆盖权限、同键并发、发送前/HTTP期间进程退出、故障、不可变授权、原币核账及迁移0008往返。

唯一既有E2E基础设施调整：`e2e/probe.py`迁移预检从精确0008更新到精确0009；旧值导致启动按设计拒绝。30项spec业务断言未改动、跳过或放宽，正式页面不改。

旧offline_mock记录禁止核成真实发票。原币核账正向测试在随机测试schema内使用明确虚构的SQL合同夹具，不连接生产/专用真实池；报告没有将模拟账单作为真实消费。

尚未实测：真实Key/账户对应、实际币种和价格、HTTP可达性/服务端行为/账单、真实模型质量及延迟；这些需要用户本机配置与首次执行的独立授权。实际HTTP Transport虽已接线，但本轮所有HTTP均Mock，不自动调用。新安装依赖仅在Python3.12项目虚拟环境，不改变系统Python/Windows服务。日常库不访问或迁移，无首页/01/02/03、PRD、prototype、Pages或自动路由改动。

完整本机及CI结果见本PR。完成后保持Draft停止，交由独立审查；本文件不构成第一次真实执行许可。

首轮HEAD daac01b的历史验证：原444项后端全部通过；新增53项完整补跑通过（含真实受限LOGIN、多进程及os._exit）。首次全套的新增CLI子进程测试遇Windows GBK/UTF-8解码不一致，已显式指定UTF-8修复并复核，未放宽安全断言。React62、构建、E2E类型、原30项Edge E2E（2.7分钟）、随机schema迁移/check/清理、12项合同和Mock CLI通过。当时PowerShell凭据配置脚本仅做语法解析，没有执行。首轮CI497项后端及Chromium30项通过；最新原生验证与回归见下文。

### 第一轮审查修复验证

上述497项为首轮基线。修复新增21项后端回归，涵盖非空候选+追问的真实DB/MockHTTP/私有文件/只读report链路、错误无预览或Key、留存失败仍可审看有效内存结果、Windows真实ACL拒绝过宽文件、文件损坏/重解析点拒绝、裸发送拒绝、伪造/过期/吊销/错误policy令牌、不可重放、所有六种非空状态阻止回滚；空表原往返仍保留。原TLS配置测试改为纯options+内存工厂验证，保留证书/重试/代理/字节全部断言，并额外测试裸真实入口不得构造客户端。UTF-8 BOM配置测试现在明确断言到达日常库拒绝检查，防止通用错误掩盖读取失败。

Windows本机执行 `apps/api/.venv/Scripts/python.exe scripts/check_windows_fake_credential.py`，无参数、不枚举凭据，只处理不可预测的`Pathwise/DeepSeek/native_test_<UUID>`。以公开假值调用实际PowerShell writer和Python CredReadW，验证账户/revision、轮换拒绝旧revision、删除及finally清理。网络/DNS陷阱开启；没有真实Key、DB授权或HTTP调用。该脚本在Linux CI不冒充原生测试；原有假native单测继续运行。结果与源码摘要见[本机原生假凭据证据](evaluation/pr17-windows-native-fake-verification.json)。所有失败尝试也逐项确认cleanup_verified。

原生检查发现5.1子进程不能继承PowerShell7模块路径；新增最小已知环境白名单和固定5.1系统模块路径，不继承供应商Key。另修正operator的无效`utf8-sig`为`utf-8-sig`。预览DACL用.NET仅修改owner/access，不申请SeSecurityPrivilege或改SACL。没有扩大Windows权限、修改系统环境或服务。完整最新518项后端、62React、30Chromium及迁移/合同/Mock结果附同一PR，未新开PR或合并。

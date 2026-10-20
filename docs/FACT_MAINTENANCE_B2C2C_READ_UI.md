# B2-c2c 独立事实读取与 typed 只读消费候选

基线 main `0f9d9d479d48276e4d609438d2b09838334d4939`；启动时核验
workflow `39417011626` 及 FastAPI、React、Chromium 均 completed/success，HEAD 一致。
仅独立 Draft PR，等待复审，不部署、不启用生产 factory 或 typed writer。

## 固定路由及读取边界

新增 `GET /api/v2/experience/sessions/{sid}/facts/{fid}`，直接返回已审查的
FactV3（fact_contract_version=3、provenance_version=3）。无新 DTO、迁移、协议协商、
查询参数、Accept 版本选择或 v1 fallback。缺凭证 401；Session 鉴权与 Fact 归属先于
分类/历史披露，不存在或外会话事实固定 404。权限不足不能借 404 推断存在性，固定安全失败。

复用 `experience_read_api.read()`、唯一的 `Projection` 与同一个默认关闭的
SELECT-only factory；它独立于全部 writer。每次请求在同一真实连接 SHOW 核验
REPEATABLE READ READ ONLY。独立事实仍校验完整会话历史/来源，不以单条 GET 绕过
其他事实的损坏，代价是整个会话有不完整历史时本条也 503。没有新锁、写入、CO、Run、
幂等登记、修复、Provider 或费用。0001–0015 及原始历史 JSON 不变。

## 独立 React 页面

新入口 `/typed-read`，不替换或自动跳转 `/discovery`、`/discovery/summary`。
用户手动提供 Session ID、Project ID、Bearer，仅保存在当前组件内存。地址、浏览器
storage、错误消息不保存凭证/审计信息；不自动读旧 storage、v1 SessionView 或 URL 参数。
访问页面/填写字段不会调用业务 API。明确点击读取才 GET summary v2；点击来源才
GET 独立 Fact v3；明确点击“下载技术备份 v2”才 GET export v2 并创建本地下载。
无写 API、自动重试、操作键、推理或 Provider。请求拒绝重定向，防止凭证随跳转传递。

客户端复用独立严格 Zod DTO；再核对请求资源归属。独立事实若与已显示的 summary
不一致，拒绝混合显示并要求重新读取；备份必须与已有 summary revision 及相关事实一致。
后续 GET 各有自己的数据库快照，不能宣称多个 HTTP 请求是一笔跨请求事务。
切换凭证/资源清空资料、取消请求，并用 generation 丢弃迟到响应；任一读取失败清掉
当前展示，不保留“成功外观”的陈旧或部分正文。仅提供手动重新读取。

可贡献正文、pending、已审核非成果三组完全采用 summary 服务端结果，固定原因不另行
推断分类。legacy 明示未分类/进度未知；计划、进行中、背景、边界不会显示成个人完成。
user_confirmed 与 evidence_supported 分别标记用户确认/用户提供材料支持，均不等于
平台独立认证。rejected 不在摘要三组，已知 ID 可经独立 GET 核对，备份完整保留。

Fact 详情区分当前文字来源、建档 Turn 与分类依据；保留原文换行、组合字符、emoji 和
code-point 半开区间，不按 UTF-16 改写引用。原始建档引用恰为当前来源时可直接显示；
后来已编辑事实的独立 FactV3 不含旧建档 quote 正文，本页只显示其原始 Turn ID 并明确
说明完整历史在技术备份中，不拿当前文字冒充旧 quote，也不自动下载整份备份补齐。
所有 classification_citations 仍为空，basis_status=not_recorded/legacy_unclassified
如实显示“暂无分类依据记录”，文字引用不充当分类证据。

默认关闭、401、404、409、503、网络中断、不支持的顶层版本和数据校验失败提供固定
中文提示，不显示服务端原始 message、SQL、URL、正文或审计详情，不回退旧路由。
技术备份明确可能含私人资料，且不是正式简历。

## 隔离验收接线

新后端测试复用既有随机 Schema/真实受限 LOGIN 夹具，覆盖全部合法分类组合及四状态、
三种投影字面一致、外会话/不存在、完整会话损坏、每张读取表缺 SELECT、默认关闭、
Accept 不协商、query 拒绝、真实只读隔离和无业务写入。

E2E 仅在测试编排器内用 owner 创建随机 `c2c_read_*` LOGIN 与 `c2c_owner_*` NOLOGIN，
复用已审查 owner/ACL 结构。HTTP 测试 wrapper 仅注入前者的 sessionmaker，不以 owner
或旧 writer 替代读身份。owner 凭证不进入 HTTP/Vite 子进程环境；生产模块无任何开关。
CI owner 来源仅为一次性 PostgreSQL service 的合成凭证，本地须显式提供同 host/port/
测试 DB 的 `PATHWISE_E2E_PROVISION_URL`；拒绝远端、非测试库、URL options 或不同库。
不读取本地真实凭据文件。运行结束恢复本 Schema 函数 owner、RESTRICT 清理仅本轮两个
随机角色，再删除仅本轮随机 Schema。

`typed_probe.py` 只作私有合成夹具/故障注入，不是 HTTP 写入 API。复用既有 owner-only
synthetic 夹具，通过真实延迟约束后提供 legacy/typed、四状态、CRLF/emoji/组合字符资料。
Chromium 页面确实请求三条 v2 路径，并严格解析真实 HTTP 响应。权限/未知 Schema/
损坏历史由真实 PostgreSQL 注入；网络、未知响应版本和 409 为明确的浏览器故障注入，
不是声称生产后端自然会生成这些错误。default-disabled 调用原始默认关闭依赖。
每个场景前后对随机 Schema 的所有表（包括 ledger、keys、revision、Run）计算完整行
摘要，断言逐表状态总摘要相等；不输出其中原文、凭证或审计内容。
现有 38 个旧 E2E 原断言保留。最终命令、数量与 CI 写入 Draft PR。

## D6 验证范围与继续 BLOCK

本轮只证明新增独立只读入口的 summary/Fact/export 严格消费闭环。旧 02/03 的真实 typed
升级、所有旧客户端/入口策略、旧 writer legacy-v0 截止、跨请求版本协同仍未整体解决，
**D6 未关闭**。独立 FactV3 也没有新增完整原始 Turn 正文或分类证据协议。

R03 全入口语义防复活、D4 typed 语义/related_plan、D5 classify/编辑退级、完整 GQ08、
Provider/MiningContext 新版、D8 生产角色/owner/ACL/工厂/部署授权仍 BLOCK。typed append/
CO v3、FactProgressLink、分类修改、自动退级、正式模型与付费请求全部关闭。新页面可到达
不表示数据工厂已启用；生产请求仍默认 503 experience_read_disabled。

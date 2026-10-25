# Pathwise G2 持续交接报告

时间：2026-10-23 UTC / 北京时间 2026-10-24。状态：四项工程候选已提交 Draft，G2.1–G2.4 最终远端 CI 均已核验成功；G0 后继检查点 CI 另按自身 HEAD 核验；不是生产准入或 native Goal COMPLETE。

## 基线与保留成果

开工及交付前远端 main 均为 `b96581175f4a2a307a7cfcfb7d60d1609d83983d`，main CI 39963621888 精确同 SHA、workflow/FastAPI/React/Chromium completed/success。#44/#45/#46/#49 已合并，#47 被 #49 替代并关闭。本轮不重做 G1，不修改或强推原 #47。仓库根保留旧 checkout；本轮代码均在独立 worktree。

原生 get_goal 在本轮多次实际返回 null；用户已被提示通过支持的 /goal 控制注册/恢复，尚未收到确认。本轮普通工程按用户明确消息授权执行，未 create/set/clear/resume 原生目标，未解除任何暂停或预算。GOAL_STATE 中 APPROVAL_BLOCKED 只是默认禁用预检的 veto，不是将 native Goal 改成暂停。

## 独立 Draft 和精确提交

- [G0 #48](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/48)：原分支 codex/goal-recovery-preflight；文档状态刷新 `1e1fc3ebd4de8d0c9119c853c09d85015dbe0bb4`，CI 39979217045 双平台成功；阶段检查点 `1995bcec9266b70280af720ae2989197d9bdee60`，CI 39985839254 双平台成功。后继交接 HEAD 由 Git/PR 精确核验，不在自身内容循环填自身 SHA。
- [G2.1 #50](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/50)：`aa09128f4ce16c7446e65ccd2acdf2cb0ba0a6b9`，base main b965；[CI 39988619663](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39988619663) Windows/Linux completed/success。前一 HEAD fff29fe 的 CI 39983033157 同样成功，但不替代新 HEAD 证据。
- [G2.2 #51](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/51)：`203bd690afad84ad96c5e6927319aed2272c1cfd`，base main b965，独立于 #50；[CI 39983508241](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39983508241) Windows/Linux completed/success。
- [G2.3 #52](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/52)：`157e5589a3971608c8d80447e9ed6a38fafa70e8`，base main b965；[应用 CI 39984420088](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39984420088) 精确匹配本 HEAD，workflow/FastAPI/React/Chromium 全部 completed/success。
- [G2.4 #53](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/53)：`31094a430e156fd040d79d572818c50f8e49eb6a`，通过普通追加依赖同步纳入 #50 修正，明确以 #50 新 HEAD aa09128 为 base，15 文件独立 UI 增量；旧 HEAD 981c6c2 的 [CI 39987332637](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39987332637) 成功；[新 HEAD CI 39988750337](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39988750337) 精确匹配 31094a4，completed/success，bundled Chromium 9 项通过；不沿用旧结果。不能跳过 #50 审查或直接改为 main 基线。#51 是体验协议参考，UI 不调用其 Python 状态机。

## 实际代码与能力

G2.1 增加纯 Python 和 TypeScript 版本化解析器，三种来源分开：原始原话、当前文字、独立合成用户选择。严格 0015 八组合、四审核状态、身份/版本字段绑定、CP 引用、JSON 键/枚举和未知版本拒绝。缺失 basis 不补造；结果固定 truth_verified=false、persistence_authorized=false，且身份/数据库历史/重跑语言校验均 false。解析器可接受内部自洽的假声明，测试明确记录这一反例，不能拿 DTO 解析当真实性或语义认证。正式 FactV3/SummaryV2/ExportV2 未改。

G2.2 增加不可变的非持久化澄清协议，复用 #46 风险诊断和 24 对抗材料。保留完整合成拒绝历史，逐事实显示 ID/版本/原拒绝、数字/同义/责任归属风险与无关误阻断。解释/证据描述只追加，版本冲突拒绝；所有状态仍 NOT_PROVEN，request_save 永远 not_saved。无附件抓取、证据认证、人工批准即解锁或新 Turn/key 绕过。6 条标注无关的原例中，5 条带拒绝历史的案例全部被保守阻断，是合成可用性代价，不是线上指标。

G2.3 交付 CO3 图/事务/锁/身份/版本/键域/GET-only 恢复/ACL/删除墓碑和并发崩溃验证计划，以及 8 项可执行参考测试。真实 PostgreSQL 测试证明**现有数据库仍拒绝 CO3**，不是能保存 CO3：ck_co_identity 拒绝 0/3/4，独立 reader 无 INSERT，旧 CO2 合法 replay/recovery 继续成立。三项 M4 图损坏检查只属内存模型。

G2.4 为独立 React/TS 原型，不改旧 02/03、/typed-read 或正式路由。10 条样本在 Python 测试中调用未改 c3a 预先核验；浏览器只允许同一原话+显式三列组合，不执行新的通用分类器。展示原话、CP 引用、分类选择、待审核、模拟用户确认、R03、解释和中断/恢复。没有数据库、凭证、storage、Provider、真实 API 或 typed POST；请求证据只有本机静态 GET（开发服务另有本机 HMR WebSocket）。内存模拟结果不是 CO，刷新后无法恢复，未伪装成持久 GET 恢复。

## 可演示与证据

worktree `.e2e/worktrees/g2-typed-journey-prototype`，目录 research/typed_journey，Node 22：`npm ci --ignore-scripts --no-audit --no-fund` → `npm run dev` → `http://127.0.0.1:5187/`。本轮已启动本机开发预览，Codex 面板打开请求返回 queued；用户可直接访问 URL。这是本地预览，没有生产部署。

实际截图在该目录 test-results/evidence：journey-desktop.png、clarification.png、journey-mobile.png；均合成资料，已人工查看桌面与 390px。CI 附件保留浏览器证据。操作名列表在页面 details 中可看，不输出凭证或正文日志。

## 本轮实际验证命令与数量

Python 统一使用根目录已有 apps/api/.venv/Scripts/python.exe；未读取 .env 或真实凭据。

- G0：`python -B -m unittest discover -s scripts/goal_recovery -p "test_*.py" -v`，33 passed；后续阶段检查点 33 passed。脚本/测试/workflow blob 不变。
- G0：`python -B scripts/goal_recovery/preflight.py --repo . --inspect-local`，新 HEAD/clean 检查成立；共享运行时不可用/预检阻断，execution_enabled=false、model_turn_started=false、scheduler_changes=0、repository_writes=0。此结果是安全拒绝，非自动恢复成功。
- G2.1：`python -B -m unittest discover -s research/declaration_read -p "test_*.py" -v`，43 方法通过，含 53 共享 JSON 子例；目录 research/declaration_read/web 下 `npm test` 57 passed，`npm run typecheck` passed；双平台 CI 相同。
- G2.2：`python -B -m unittest discover -s research/clarification -p "test_*.py" -v`，9 方法通过，含 24 原对抗子例；双平台 CI 相同。
- G2.3，apps/api：`python -B -m pytest tests/test_co3_contract_reference.py -q -ra`，8 passed，随机 PG Schema/真实 append/read LOGIN，现有约束启用。
- G2.3，apps/api：`python -B -m pytest -q -ra`，**2340 passed**，1453.88 秒，无本地 skip；1 条既有 Starlette httpx 弃用警告。Linux CI 实测 **2339 passed + 1 既有 skip**，1622.76 秒；skip 为 test_probe_secret_safety.py:195 的 Windows PowerShell 5.1 Fake Native harness，不新增 skip/xfail。
- G2.3，apps/web：`npm test`，**158 passed**；`npm run build`、`npm run test:e2e:types` passed。build 的既有 Zod pure annotation 警告未修改。
- G2.3，apps/web：`npm run test:e2e`，**59 passed**，3.1 分钟；真实 HTTP/FastAPI/PostgreSQL，Windows 本机 msedge Chromium。隔离预检及专用非管理员身份通过。
- G2.3，apps/api：`python -B ../../scripts/check_isolated_migrations.py` passed；`check_m12c2_contracts.py` **12/12**；`check_s03b_output_contract.py` **48/48**。
- G2.3：`python -B ../../scripts/evaluate_mining_quality.py --outputs ../../docs/evaluation/quality-v1/oracle.outputs.json --output-dir ../../.e2e/g2-quality` passed；DRAFT/human unreviewed/real quality=null。`run_offline_evaluation.py --profile 0 --output ../../.e2e/g2-mock-report.json` passed；real requests/cost=0。首次 Mock 命令未设置隔离 DB URL 因而拒绝，补齐同一合成配置后通过；没有改实现或断言。
- G2.4：`python -B -m unittest discover -s research/typed_journey -p "test_*.py" -v`，2 方法含 10 c3a 样本子项通过。项目内 `npm test` **16 passed**，`npm run build` passed；`PATHWISE_PROTOTYPE_CHANNEL=msedge npm run test:browser` **9 passed**，7.4 秒，无 retries/固定 sleep/放宽 timeout。

数据库仅既有专用合成集群，loopback 15487，pathwise_test/pathwise_e2e；owner 只用于夹具/故障准备，测试请求用真实限权身份。结束后两个 DB 的临时 Schema、随机角色检查为 0，集群已停止、15487 释放。仅本机 UI 5187 仍运行供查看。

跨语言增量红灯：全角年份 recorded_at 原 Python 允许、TS 拒绝，先运行共享测试得到 parsed_candidate != rejected，随后仅将候选 Python 日期格式限定 ASCII。43 方法/53 共享例、TS57 和新双平台 CI 通过，不修改正式读取合同。

依赖安装遇到本机 npm10 edgesOut，使用现有 CI 同类 npm11 正常安装；最初链接依赖导致锁文件包含外部路径，已在提交前移除链接并重新独立安装生成锁，双平台 #50 npm ci 通过。未弱化 TLS 或写全局配置。Git 单次使用现有 loopback 代理和 OpenSSL TLS 后端成功，未强推或变更认证。

## 文件范围

G0 仅 docs/goal 的 GOAL_STATE.md、NEXT_STAGE_PLAN.md、RECOVERY_PREFLIGHT.md 与本报告；恢复脚本与 CI 未更改。

G2.1 共 11 文件：.github/workflows/declaration-read-candidate.yml；docs/goal/G2_1_DECLARATION_READ_CANDIDATE.md；research/declaration_read 下 contract.py、corpus.json、test_contract.py、test_shared.py，以及 web/contract.ts、contract.test.ts、package.json、package-lock.json、tsconfig.json。

G2.2 共 4 文件：.github/workflows/clarification-candidate.yml；docs/goal/G2_2_R03_CLARIFICATION.md；research/clarification/flow.py、test_flow.py。

G2.3 共 2 文件：docs/goal/G2_3_CO3_DATABASE_CONTRACT.md；apps/api/tests/test_co3_contract_reference.py。

G2.4 相对 #50 共 15 文件：.github/workflows/typed-journey-candidate.yml；docs/goal/G2_4_TYPED_JOURNEY.md；research/typed_journey 下 index.html、package.json、package-lock.json、tsconfig.json、vite.config.ts、playwright.config.ts、test_fixtures.py、src/journey.ts、src/journey.test.ts、src/main.tsx、src/scenarios.json、src/style.css、tests/journey.spec.ts。

所有候选相对 main 的 apps/api/app、apps/api/alembic、apps/web/src 与冻结 docs/evaluation Diff 均为空。旧 G2.1 staged 候选保留，不 reset/clean；根工作区干净，原 #47 历史未改。

## 阻塞、审批与恢复结论

最具体的协议差异：M4 SimBasis 复用正文来源，G2.1 要独立选择 Turn。一个正文 Turn + 新选择事件表，或同事务两个 Turn，需要 D5/D6/CO3 图联审。当前任何一个模拟通过都不能被当作已经选定的持久化语义；没有新表/迁移或 typed writer。

仍未实现：真实分类依据存储、正式 CO3、真实人工澄清决定/证据认证、完整持久 typed 录入/恢复、classify/related_plan/退级、born-contract/legacy cutoff、生产工厂/LOGIN/权限、Provider/付费/部署。R03、D4/D5 正式批准、D6 剩余、D8 全部继续 BLOCK。正式旧功能、真实 PG 已验证边界、内存模拟和待批准协议分别见上文，不统称正式产品能力。

额度观测 ordinaryUsageAllowed=true，Plus 五小时已用 21%、周已用 17%（阶段快照，不是后续准入凭证）。本轮没有触发真实额度阻断，不记录 RATE_LIMITED 或消费重置。原生 Goal=null；共享 CLI daemon 仍 Windows10050，安全原子 idle→单轮调度没有证明。官方 exec resume 与 thread/goal/get 的存在不能填补这些证据；本轮未启动任何模型子进程、自动恢复器或计划任务。手工继续须用实际客户端支持的 Goal 控制确认，不能依据检查点自启。

所有 PR 保持 Draft；未 Ready/Merge/Deploy。四项候选交付后等待独立审查，不自动开始正式 writer 或扩大未批准产品政策。

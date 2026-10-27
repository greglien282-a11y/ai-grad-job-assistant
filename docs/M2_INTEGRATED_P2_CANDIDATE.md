# M2 单一集成候选与 P2 收敛（待独立审查）

本候选面向 main；不是五个原 PR 的合并操作。原 #61/#64/#65/#66/#67 保持原样。所有功能仍只在显式开启的开发预览中运行，生产构建关闭。

## 来源与树证明

启动时远端 main：`e1eff78fd43e424ab22996b182e0e5f4d6bd609c`。五个 open Draft 的 base/HEAD 未漂移：

- #61 base main；HEAD `e36499c5d9e01aacb4754c62d520ee02b28d91e4`。
- #64 base codex/m2-jd-resume-lab；HEAD `f52126ddcd88b07d542bb11fdfed044e19a12419`。
- #65 base codex/m2-local-resume-import；HEAD `667a4279b6d733b934e97fde63adf085d6863897`。
- #66 base codex/m2-local-resume-studio；HEAD `99b95886e4a22b3cb536f6090ce26d4f38555c8c`。
- #67 base codex/m2-f-pdf-docx-local-import；HEAD `0674123d35ce358d24023b1659dde8f78dcd0b1f`。

旧集成预演 `f374c90bd08a8a68b9a09ec89ba6aca0cd3a302c` 与 #67 完整 tree 均为 `82ffed84dba83e56f589d1a6d65aa038ed3d29fe`。旧研究证据提交为 `016f54cc83945e3f7922fbfbfacab47d1bc2ea75`，未移植其历史。新分支从已核验 main 建立，以 `git restore --source=0674123 --staged --worktree .` 重建产品树；第一条提交 `ed7045a` 的 tree 仍精确相等，然后才增加本轮 P2。

PowerShell 可重现检查（必须引用 tree 表达式）：

```powershell
git rev-parse 'f374c90bd08a8a68b9a09ec89ba6aca0cd3a302c^{tree}' '0674123d35ce358d24023b1659dde8f78dcd0b1f^{tree}' 'ed7045a^{tree}'
git diff --exit-code f374c90bd08a8a68b9a09ec89ba6aca0cd3a302c 0674123d35ce358d24023b1659dde8f78dcd0b1f
git diff --exit-code ed7045a 0674123d35ce358d24023b1659dde8f78dcd0b1f
git merge-base HEAD main
git diff --name-status 0674123d35ce358d24023b1659dde8f78dcd0b1f HEAD
git diff --name-status e1eff78fd43e424ab22996b182e0e5f4d6bd609c HEAD
git diff --exit-code e1eff78fd43e424ab22996b182e0e5f4d6bd609c HEAD -- apps/api scripts compose.yaml .github/workflows/ci.yml research/g4_trusted_boundary
```

前两项差异命令输出为空；三项树输出相同。新历史仅 main → 重建产品树 → 本轮 P2，不重复引入五个 PR 的祖先提交。最终 HEAD、tree、逐文件完整 diff 与远端 CI 在 PR 描述及本地交接证据固定记录，不能用旧 PR CI 代替。

## 四项修正

### P2-A 简历输出与来源审查

默认展示简历输出，保留用户编辑的可准入正文、必要的用户自述标签及计划/团队限制分区。来源审查单独展示完整原句、当前文字、用户修改、来源区间、JD 原句和阻断原因；包含被阻断条目供核对，但它们永不进入输出。切换是页面状态，不改 v1/v2/v3 文件或条目准入。即使从来源审查点击打印，print media 也只展示相同准入的简历。移除打印中的来源偏移、重复原句及 G4 等内部提示，仍明确未经平台核实。

### P2-B 来源绑定优先的状态保留

source-transition.ts 严格解析提议：比较合同、完整 source（ID、原文快照、文件/文本指纹、解析信息等，单独处理用户文本核对标志）、每条 citation 的 ID/kind/source_id/start/end/quote，以及每条手工声明的 ID/kind/text/trust。只忽略段落 label/section/顺序，且不改变实际来源；匹配时保留全部岗位、条目、顺序、回答和撤销，并让撤销使用更新后的同一工作台元数据。

引用、原文或声明集合变化时列明受影响段落；暂不展示旧岗位，不允许下载旧状态；旧内存尚未删除。用户可取消并恢复原岗位，或显式确认后重建岗位、清空依赖草稿与复习。本地拒绝仍保留。新增手工声明也属于需确认的集合变更；本候选不实现复杂的局部来源迁移。

PDF/DOCX 初次核对仍须用户明确确认；仅元数据编辑不撤销已经完成的同一文本核对。新引用不能借用旧文本核对绕过重置。损坏提议保持原数据并明确错误。

### P2-C 外观与内容依据分离

密度、模板、分页目标及视图切换均保留三题回答。JD、选用内容、编辑、条目顺序、用户自评、拒绝等仍走原内容失效规则。实际来源变更在确认后清除旧回答，不以外观规则豁免来源变更。

### P2-D 可解释且批量的原句建议

优先显示有依据的可用建议。展示原句与 JD 原句共同出现的有限词表词，以及各自来源；用户改写 JD 条件不能凭新增词捏造原 JD 引文关联。标明导入片段/手工声明、字面关联、需要证据、用户明确自评缺口；词汇不证明语义、熟练度或事实真伪。明确缺口不会被自动选用建议覆盖。新增用户主动的批量选用，只恢复并选择已存在且通过原准入的精确原句，保留顺序；原来的冲突、拒绝、责任/计划边界仍阻断。没有关键词得分、自动润色或新增技能/数字。

## #67 → 本候选逐文件增量

- .github/workflows/jd-lab.yml：push main（不加 path 过滤）及手动触发；保留 PR 检查。
- .github/workflows/resume-lab.yml：同上，增加 12 组合成旅程及原生 PDF/审查截图证据；无数据库/外部服务。
- apps/web/src/features/resume-lab/source-transition.ts：严格来源变化比较。
- apps/web/src/features/resume-lab/LocalResumeLab.tsx：保留合法岗位、确认重置、暂停陈旧展示。
- apps/web/src/features/resume-lab/ResumeWorkbench.tsx：准确说明新的元数据/引用变更行为。
- apps/web/src/features/resume-lab/DraftStudio.tsx：两种视图、密度调整保留回答。
- apps/web/src/features/resume-lab/ResumePaper.tsx：简洁输出，原准入与边界分区不变。
- apps/web/src/features/resume-lab/resume.css：审查屏幕隐藏输出，打印反向隐藏审查，中文长段落分页。
- apps/web/src/features/resume-lab/workspace.ts：建议词、来源、缺口、排序与主动批量原句选择。
- apps/web/src/features/resume-lab/RoleSuggestions.tsx：呈现上述解释与批量按钮。
- apps/web/src/features/resume-lab/convergence.test.tsx：P2 正反与不可变输入测试。
- apps/web/src/features/resume-lab/DraftStudio.test.tsx：原比较断言迁至审查视图；替换原文加入明确确认后仍验证拒绝不复活。
- apps/web/resume-lab/convergence.spec.ts：真实 Chromium、下载状态对比、两视图打印及失效反例。
- apps/web/resume-lab/journey.spec.ts：原完整旅程适配视图与确认，保留全部排除/恢复/零请求断言。
- research/m2_acceptance/scenarios.mjs：复用原 12 组公开合成材料，不用真实身份。
- research/m2_acceptance/run.mjs：复用完整旅程，新增视图/元数据/回答保留检查，记录 dirty 状态，输出截图、JSON、原生 PDF。
- research/m2_acceptance/README.md：可重现命令与证据界限。
- docs/M2_INTEGRATED_P2_CANDIDATE.md：本说明与仅供批准后执行的清单。

## 验证与证据约定

实际命令与原始日志保存在本机 `.e2e/handoff/m2_integrated_p2_20261027`；旧证据不覆盖。各轮失败、定位问题与后续通过结果分开保留。新增 6 个 React 正反测试、3 个真实浏览器测试；原 302/18/5 基线保留。

```powershell
# apps/web
npm.cmd ci --no-audit --no-fund
npm.cmd test -- --reporter=dot
npx.cmd tsc -p tsconfig.resume-lab.json --noEmit
npx.cmd tsc -p tsconfig.jd-lab.json --noEmit
npm.cmd run build
$env:PATHWISE_PROTOTYPE_CHANNEL='chrome'
npx.cmd playwright test --config resume-lab/playwright.config.ts
npx.cmd playwright test --config jd-lab/playwright.config.ts
# repo root; CI uses installed Chromium, Windows defaults to Chrome
node research/m2_acceptance/run.mjs
```

另执行现有正式 Node E2E launcher（preflight/types/59 项）、完整 API pytest、隔离迁移、12/48、quality oracle 脚手架、Mock profile0 与 research/jd_lab。仅新建 loopback:15489 的一次性合成 PostgreSQL 集群，owner 用于夹具/迁移，真实运行路径仍采用受限 LOGIN；未读取生产凭据或启动既有 PostgreSQL 服务。质量脚手架仍为 human unreviewed / real_quality null，Mock 不代表真实模型质量。

本地 API 与正式 E2E 路径与 main 字节相同；日志固定说明运行时产品源码及最终差异。前端最终 commit 后再执行精确 HEAD 的浏览器旅程并以新 PR CI 独立确认。Windows 全后端预期平台条件与 Linux 不同，必须以真实输出计数，不复制旧 CI 数字。

## 待用户批准后的最小合并清单（现在不执行）

1. 独立审查本集成 PR 的精确最终 SHA、main 基线、#67 树来源及全部增量。若 main 漂移，停止套用旧证明，先比较新 main；不自动扩大权限。
2. 确认此单一 PR 取代五个 PR 的未来产品集成路径，避免同时再合并旧堆叠 PR。旧分支保留；关闭原 PR 也需用户另行授权。
3. 仅在用户明确授权后，将新 PR squash 到已核验 main；其 diff 是 main → 完整产品树 + P2，无祖先重复提交问题。不要逐个 retarget/squash 旧链同时引入同一功能。
4. 合并后先 `git diff --exit-code <已批准候选> <新main>` 验证完整树等价。若 GitHub 因 main 变化生成不同树，停止宣告等价并人工审核差异。
5. 核对新 main 精确 SHA 上完整应用 workflow（API、React、正式 PostgreSQL/Chromium）以及 JD、resume workflows 均 completed/success；resume 含 12 组与原生打印。PR 的旧绿灯不是 main 的新证据。若触发缺失，显式对新 main dispatch 并核对 head_sha，不部署作为替代。
6. 保持开发门禁和所有生产 BLOCK，保存 CI artifact 与精确 merge SHA，才讨论后续产品迭代。

## 剩余限制

仍为本地用户可控、未认证草稿。PDF 双栏/表格提取需人工核对，扫描件/OCR/旧 DOC 不支持；不保证一页容纳任意长正文、不自动截断。字面建议没有真实模型语义能力，手工声明不能变成认证事实。来源身份变化采用全岗位显式重置；尚未做逐条迁移。页面刷新仍不自动恢复，必须主动下载/导入严格版本文件。

G4、T2/T3、共享 CO 键域、R03 全入口语义防复活、D4/D5、D6 剩余与 D8 均继续 BLOCK。没有 API、上传、自动浏览器持久化、付费 Provider、正式 writer/CO3、迁移/ACL、生产开关、Ready、Merge 或 Deploy 变更。新 PR 通过只证明本地产品修正，不构成安全准入。

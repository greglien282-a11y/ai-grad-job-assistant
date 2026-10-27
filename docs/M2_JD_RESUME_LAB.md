# M2：JD → 岗位策略 → 简历预览 → 三题复习

基线 main `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`。独立于未合并 #56–#60。

## 能操作什么

显式开启的开发首页第三入口进入 `/jd-lab`，粘贴 JD 或使用公开合成 JD。有限确定性词汇/分句规则保留完整原文和 Unicode code-point 半开区间，输出技术、学历、经验和其他要求，以及必备/加分/待人工判断。矛盾条件不自动断言；用户可手动调整本地策略而保留原引文。

按现有 FactV3 严格解析公开合成事实，再通过未修改 G2.1 声明读取解析器核对独立声明、当前版本、原始和当前来源。FactV3 的 `classification_citations=[]` / `not_recorded` 保持原样，绝不补造分类依据。独立 synthetic 声明仅供研究预览，不将它注入正式 DTO 或提升真实资料资格。

仅合成已审核的 personal_action/completed 且有完整可核对来源/声明的样本可选入本地预览。pending、计划/进行中、团队背景、限制、rejected、legacy 未分类、缺声明/损坏来源分别分流；用户确认/用户材料支持不代表平台独立认证。词法相关不是岗位条件完全满足，也不输出匹配百分比。没有 Python 经历就显示证据缺口，不能从“脚本”推断 Python。

独立复审 P2 修正：精确相同正文先整体核对状态、分类和来源准入结果，再去重。不同 ID 的 pending/confirmed、rejected/confirmed 或缺声明/完整声明冲突均整组排除；同 ID 当前记录不一致继续整组排除，并传播到相关正文重复组。合法重复只保留字典序最小 Fact ID 的一条，不以输入先后顺序决定准入。保留原数组和原始引用；不合并不同记录的来源，不推断语义独立，也不解决 R03。

用户可以选择、重排、编辑草稿及恢复原句。**任何不等于原句的本地编辑都标为未核实，不进入可打印正文或复习事实**；这不保证新增主张真实，不提供自动审核。打印使用浏览器原生功能，仅打印原句预览，并明确合成资料/非正式简历。没有 PDF 服务或外部依赖。

三道离线复习问题绑定实际使用的原句及岗位要求，没有个人标准答案。支持跳过、提前结束、重新开始和简单复盘；回答只留内存，不变成事实或审核依据。

## 本地启动 / 演示

```powershell
cd apps/web
npm ci --ignore-scripts --no-audit --no-fund
$env:VITE_PATHWISE_JD_LAB='synthetic-v1'
npm run dev
# http://127.0.0.1:5173 → 首页第三入口，或 /jd-lab
```

必须同时满足 `import.meta.env.DEV` 和明确的合成 flag。生产 build 即使被传同名变量也关闭；没有自动开启 `/typed-read`、凭据注入、旧 API fallback、后端写入或网络分析。无 localStorage/sessionStorage，刷新清除所有输入。请勿输入真实用户/招聘资料。

点击“使用合成 JD 样例”→“分析岗位要求”→核对 Python 的证据缺口与各事实分流→重排两条原句→编辑 99% 等新增指标并查看打印排除→恢复原句→三题复习/跳过/结束。改 JD 会清空旧下游结果。

## 实际本机验证

```text
# worktree 根，根 venv Python
python -B -m pytest research/jd_lab -q -ra
# apps/web
npm test -- --reporter=dot
npm run build
npx tsc -p tsconfig.jd-lab.json --noEmit
# 本机显式 PATHWISE_PROTOTYPE_CHANNEL=chrome；CI 安装匹配 Chromium
npx playwright test --config jd-lab/playwright.config.ts
```

Python 1 项（9 个 typed 样本逐一重跑原 c3a，另有 legacy 样本不推断）；初轮 React/Vitest 196 项（旧158 + 新38），后续发现同ID冲突状态/不同ID的精确拒绝正文按输入顺序可能保留前项，先新增2项得到真实红灯，再对整组输入保守拒绝，最终 **198项（旧158+新40）**。这仅保护本地候选的精确冲突，不是R03语义解决。TypeScript/build成功；真实Chromium5项，含实际开发HTTP、生产静态预览、无API/非GET、无外站、无storage、移动宽度、打印媒体和故障草稿验证。截图位于 `apps/web/test-results/jd-lab`，专项CI上传合成界面证据。

这些测试不证明真实资料真实性、真实账户身份、历史 R03 独立性、服务端语义判定或正式保存。没有修改冻结规则/评测/旧测试。最终精确 HEAD、完整正式应用回归和 CI 见 Draft PR 与统一交付报告；未完成不能称成功。

P2 增量新增 9 项（6 项策略、3 项实际 React 打印区域测试）。修复前专项真实出现 4 failed / 36 passed：pending/confirmed 放行、缺声明重复被隐藏、合法重复代表随顺序变化，以及实际打印按钮被错误启用。修复后 `/jd-lab` 专项 49 项通过；既有测试和断言不变。各故障组合均核验两种排列，合法重复仍可打印一次，冲突组无可打印条目。完整回归与本次精确 HEAD 的 CI 见 PR #61 更新。

## 未实现 / 审批边界

不接真实用户数据库，没有通用 JD 语义理解、模型生成、简历导入、可信个人身份、正式经历修改、typed writer、CO3、正式 PDF 引擎或生产发布。学历/经验等缺证据不自动判人不合格。有限关键词、句界与冲突策略需人工复核，不能用于自动筛人。

R03、D4/D5、D6 剩余、D8 和既有生产 BLOCK 不变。新增功能是默认关闭的本地产品预览；候选 PR 保持 Draft，不 Ready/Merge/Deploy。

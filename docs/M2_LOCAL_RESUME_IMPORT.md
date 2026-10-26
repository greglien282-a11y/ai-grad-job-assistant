# M2 工作包 D：本地简历导入与来源工作台

基线 #61 `e36499c5d9e01aacb4754c62d520ee02b28d91e4`，核验时 main 为 `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`，#61 未合并且两条精确 HEAD CI 成功。此 PR 堆叠于 #61，不修改 #61/#62/#63，不自动 Ready/Merge/Deploy。

## 可以操作

在显式开发门禁下，首页路径 A → `/resume-lab`。粘贴文字或选择本地 `.txt/.md`，逐段查看完整原文、教育/项目/技能/实习/其他候选、Unicode code-point 半开区间。用户能改候选标题、类型和区间，跨段引用保留换行和原文，错误引用拒绝。手工补充声明单独标记 `user_manual_statement/local_unverified`。

这些不是正式事实分类。`local-resume-workbench-v1` 只含本地来源、候选片段、手工声明，不含 Fact 状态、认证 actor 或分类依据。没有 FactV3 自动确认/合成声明注入。原 `/jd-lab` 的严格合成 FactV3/G2.1、去重、可信打印保持独立不变；正式数据库未接入，不展示假的数据库认证结果。

原文不归一化，UTF-8 BOM、CRLF、组合字符、Emoji/ZWJ原样保留。文本最大20,000 code points和128 KiB，文件先验大小/类型再读，UTF-8严格解码；空白、UTF-16/损坏字节、孤立代理、隐藏方向/控制字符、疑似Bearer/私钥/密钥拒绝。联系方式仅提示人工检查，**这不是完备DLP**，不能保证识别所有敏感资料。HTML/Markdown只作React转义文字，无HTML渲染、链接预取或图片加载。文件名只是本地标签，不证明真实身份/原始文件真实性。

文件异步读取有generation保护，新粘贴/新文件/卸载使旧结果失效。更换材料立即清空旧候选。候选结构变化会在后续 E 中使下游草稿失效，不复用旧引用。所有输入仅在组件内存；无上传、遥测、storage、Provider、后台保存或正式writer。刷新清空。用户自主草稿/保存恢复属于后续工作包E，此PR不虚构已完成。

## 运行

```powershell
cd apps/web
npm ci --ignore-scripts --no-audit --no-fund
$env:VITE_PATHWISE_JD_LAB='synthetic-v1'
npm run dev
# http://127.0.0.1:5173 → 我已经有简历，或 /resume-lab
```

使用公开合成简历或合成UTF-8文件；不要用真实凭证测试。生产build即便设置同名flag仍关闭。未新增环境开关绕过后端权限。

## 验证

```text
npm test -- --reporter=dot
npm run build
npx tsc -p tsconfig.resume-lab.json --noEmit
PATHWISE_PROTOTYPE_CHANNEL=chrome npx playwright test --config resume-lab/playwright.config.ts
PATHWISE_PROTOTYPE_CHANNEL=chrome npx playwright test --config jd-lab/playwright.config.ts
```

本机React237（原207+新30）、build/严格类型成功；新增真实Chromium5及原JD5通过。新增测试覆盖实际本地文件、精确Unicode/CRLF、候选/手工声明、无请求/无storage、刷新清空、无效文件/编码/超限、恶意文本惰性显示、隐私提示、跨段/错误引用、移动端、生产关闭。首次浏览器两项失败来自新测试的label模糊匹配，改为精确角色/名称后保留所有业务断言通过；无skip/retry/timeout变更。初轮UUID默认参数推断过窄导致TypeScript红灯，明确字符串参数类型修复，没有弱化解析。

专项CI上传公开合成截图 `resume_import_sources.png` / `resume_import_mobile.png`。正式应用、迁移、12/48、质量/Mock、旧E2E由继承的完整CI核验，以PR精确HEAD为准，不借底座成功冒充本PR。

不支持PDF/DOCX/OCR、真实AI匹配、正式经历库/认证、数据库保存或生产发布。R03、G4期限/共享CO域、D4/D5、D6剩余及D8继续BLOCK。

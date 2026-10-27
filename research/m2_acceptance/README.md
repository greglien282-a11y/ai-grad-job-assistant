# M2 12 组合成产品回归

复用 2026-10-27 已交付的合成场景，原历史失败证据不覆盖。Node22；先在 apps/web 执行 npm ci、严格类型检查及 npm run build，再从仓库根执行 `node research/m2_acceptance/run.mjs`。脚本仅在 loopback15201/15202 启动本地 Vite 与生产预览，Windows 用 Chrome，Linux 用 Playwright 安装的 Chromium。`M2_ACCEPTANCE_OUTPUT` 可指定隔离证据目录（默认 .e2e/m2-acceptance）；`M2_ACCEPTANCE_CHANNEL` 可选本机已有浏览器。

完整旅程：真实粘贴/TXT/MD/PDF/DOCX → 警告/原文/引用核对 → JD/用户自评 → 选择排序/用户草稿 → 两视图核对 → 下载/刷新/严格恢复 → 原生 A4 PDF → 三题 → 元数据和外观不丢失状态；S09 同源两岗位再次下载恢复。S11 改变跨段引用时必须显式确认重置。生产构建即使传开发环境标记仍关闭。每组检查请求、storage/indexedDB/cache 均零副作用。

输出是自动化合成旅程，不是真实用户研究、OCR 保真、语义准确率或 G4 安全认证。actions / manual_checkpoints 只是脚本计数，不是人类时间。JSON 同时记录 commit 和 dirty，只有干净 HEAD 的最终运行/CI 才可作为精确版本证据。全部输入均公开合成，无真实联系方式，不能把真实简历放进测试或 CI artifact。

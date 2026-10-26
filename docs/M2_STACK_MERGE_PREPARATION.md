# #61 → #64 → #65 合并准备（未执行合并）

2026-10-26核验 main：`e1eff78fd43e424ab22996b182e0e5f4d6bd609c`。三项仍为未合并Draft。

- #61 `e36499c5d9e01aacb4754c62d520ee02b28d91e4`：base main；19文件/+636/-2。默认关闭JD实验室、严格FactV3/G2.1与可信打印、三题复习、P2保守去重修复。精确CI40317379211/40317379241成功。
- #64 `f52126ddcd88b07d542bb11fdfed044e19a12419`：base #61分支codex/m2-jd-resume-lab；增量15文件/+372/-1。TXT/MD/粘贴、原文区间与候选、未审核声明、隐私与错误保护、浏览器证据。增量提交6108ddc、f52126d。精确CI40331366915/40331367053/40331366895成功。
- #65 `667a4279b6d733b934e97fde63adf085d6863897`：base #64分支codex/m2-local-resume-import；增量9文件/+507/-5。岗位策略、用户草稿编辑与打印、v1严格保存恢复、复习。含功能提交1abcdf9及合入更新D的merge提交，因此不能把其提交区间盲目当成纯E逐条cherry-pick。精确CI40331624317/40331624327/40331624409成功。

## 将来经单独批准后的非强推方案

按61→64→65顺序。Squash合并61后，旧64仍含61的祖先提交；直接改base可能重复显示历史或产生误导diff。保留原分支/PR，从实际新main另建集成分支，仅移植已经审阅的二进制树增量：D用旧61..旧64，E用旧64..旧65。可用 `git diff --binary old_base old_head` 产生精确patch，经检查路径/基线后apply/index并正常Commit，再建替代Draft并说明关系；冲突必须明确核对，不能盲目覆盖新main安全规则。不要重放65的merge。原PR不强推、不擅自关闭/删除/Ready，本次不执行任何集成。

每步先重新核验原精确HEAD、前项合并状态、新main及增量文件；比较实际文件树差异而非只数提交。每次Squash后的main是新SHA，必须在该SHA重新跑全套适用CI；旧分支绿灯不能代替。之后F#66与G也需按各自旧base→head增量重新集成，不能重复引入D/E。

## 新main必须重验

完整React、lab严格TS、生产构建、JD5、简历浏览器D5/E11/F14/G18、正式FastAPI/PostgreSQL/Chromium59、隔离迁移与权限/降级、12/48离线合同、冻结质量脚手架及零付费Mock CLI。核验workflow精确head和每个必需job；path-filter未触发不等于成功。保留Linux原PowerShell harness平台skip的准确说明。

生产仍由DEV且VITE_PATHWISE_JD_LAB=synthetic-v1门禁关闭；无正式typed writer、真实模型、迁移、ACL或部署授权。R03、G4/T2/T3/shared CO键域、D4/D5、D6剩余、D8继续BLOCK。#62/#63不变。本地JSON非认证历史，用户草稿非平台事实，字面关联非语义AI。F解析依赖production audit0、既有dev audit3；复杂排版仍须人工核对。D/E没有新发现必须放宽安全规则的阻断；F/G仍须独立复审与精确CI，不宣称已具合并授权。

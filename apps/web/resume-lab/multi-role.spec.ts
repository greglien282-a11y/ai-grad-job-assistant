import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { importText } from '../src/features/resume-lab/import'
import { newDraft, saveDraft } from '../src/features/resume-lab/draft'
const raw = '教育经历\r\n合成大学计算机课程，应届生。\r\n\r\n项目经历\r\n我编写了Python图像读取脚本。👩‍💻 é\r\n\r\n技能\r\nPython课程基础，无量化指标。\r\n\r\n团队负责部署，我没有参与。'
test('two roles retain independent sources, edits, templates and review through explicit download/refresh/restore', async ({ page }, info) => {
  const effects: string[] = []; page.on('request', r => { if (r.method() !== 'GET' || r.url().includes('/api/') || !r.url().startsWith('http://127.0.0.1:15191/')) effects.push(r.url()) })
  await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/resume-lab')
  await page.getByLabel('选择本地文本文件').setInputFiles({ name: 'public-synthetic.md', mimeType: 'text/markdown', buffer: Buffer.from(raw) })
  await page.getByRole('textbox', { name: '岗位草稿名称', exact: true }).fill('视觉岗位A')
  await page.getByLabel('姓名', { exact: true }).fill('公开合成同学'); await page.getByLabel('联系信息', { exact: true }).fill('synthetic@example.invalid')
  await page.getByRole('button', { name: '填入视觉算法实习 JD' }).click(); await page.getByRole('button', { name: '分析本地岗位' }).click()
  await page.getByRole('button', { name: '选用原句并前移 · 2', exact: true }).click()
  await expect(page.getByRole('textbox', { name: '岗位草稿 1', exact: true })).toHaveValue('我编写了Python图像读取脚本。👩‍💻 é')
  await page.getByRole('textbox', { name: '岗位草稿 1', exact: true }).fill('我编写了Python图像读取脚本，并整理课程说明。')
  await page.getByLabel('排版密度').selectOption('compact'); await page.getByRole('button', { name: '开始岗位三题' }).click(); await page.getByLabel('我的复习回答').fill('A：课程练习，不是生产部署。')
  await page.getByRole('button', { name: '新增Python后端实习生草稿' }).click()
  await expect(page.getByLabel('完整简历原文')).toHaveText(raw); await expect(page.getByLabel('我的复习回答')).toHaveCount(0)
  await expect(page.getByRole('region', { name: '岗位策略', exact: true })).toContainText('Python后端实习生')
  await page.getByLabel('选用条目 3', { exact: true }).check()
  await page.getByRole('textbox', { name: '岗位草稿 3', exact: true }).fill('Python课程基础；我会逐项核对。')
  await page.getByLabel('简历版式').selectOption('minimal'); await page.getByLabel('分页目标').selectOption('multiple')
  await page.getByRole('button', { name: '开始岗位三题' }).click(); await page.getByLabel('我的复习回答').fill('B：仅有课程基础，部署是学习准备。')
  const paper = page.getByRole('article', { name: '用户自述简历草稿' }); await expect(paper).toHaveAttribute('data-template', 'minimal'); await expect(paper).toContainText('synthetic@example.invalid'); await expect(paper).not.toContainText('整理课程说明')
  const event = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click(); const download = await event, bytes = await readFile((await download.path())!), saved = JSON.parse(bytes.toString('utf8'))
  expect(saved.contract).toBe('local-job-resume-draft-v3'); expect(saved.roles).toHaveLength(2); expect(saved.workbench.source.text).toBe(raw)
  expect(saved.roles[0].content.review.answers[0]).toContain('A：'); expect(saved.roles[1].content.review.answers[0]).toContain('B：'); expect(saved.roles[0]).not.toHaveProperty('workbench')
  await page.getByRole('region', { name: '多岗位与基本信息' }).screenshot({ path: info.outputPath('resume_multi_role_controls.png') })
  await page.reload(); await expect(page.getByLabel('当前岗位')).toHaveCount(0); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
  await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: 'two-roles.json', mimeType: 'application/json', buffer: bytes })
  await expect(page.getByLabel('当前岗位')).toHaveValue(saved.active_role_id); await expect(page.getByLabel('我的复习回答')).toHaveValue('B：仅有课程基础，部署是学习准备。'); await expect(page.getByLabel('简历版式')).toHaveValue('minimal')
  await page.getByLabel('当前岗位').selectOption(saved.roles[0].id)
  await expect(page.getByLabel('我的复习回答')).toHaveValue('A：课程练习，不是生产部署。'); await expect(page.getByLabel('简历版式')).toHaveValue('classic'); await expect(page.getByLabel('排版密度')).toHaveValue('compact'); await expect(paper).toContainText('整理课程说明'); await expect(paper).not.toContainText('我会逐项核对')
  await page.getByLabel('当前岗位').selectOption(saved.roles[1].id); await expect(page.getByLabel('我的复习回答')).toHaveValue('B：仅有课程基础，部署是学习准备。')
  await page.emulateMedia({ media: 'print' }); await paper.screenshot({ path: info.outputPath('resume_multi_role_print.png') }); const pdf = await page.pdf({ path: info.outputPath('resume_multi_role_native.pdf'), format: 'A4', preferCSSPageSize: true }); expect((pdf.toString('latin1').match(/\/Type \/Page\b/g) ?? []).length).toBe(1); await page.emulateMedia({ media: 'screen' })
  expect(effects).toEqual([]); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
})
test('legacy file migrates explicitly; corrupt multi-role graph and unknown versions clear all old views', async ({ page }) => {
  const legacy = saveDraft(newDraft(importText(raw)))
  await page.goto('/resume-lab'); await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: 'legacy-v1.json', mimeType: 'application/json', buffer: Buffer.from(legacy) })
  await expect(page.getByRole('status')).toContainText('显式迁移为v3的一个岗位'); await expect(page.getByLabel('完整简历原文')).toHaveText(raw)
  const event = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click(); const download = await event, saved = JSON.parse((await readFile((await download.path())!)).toString('utf8'))
  const invalid = [{ ...saved, contract: 'local-job-resume-draft-v4' }, { ...saved, active_role_id: '00000000-0000-4000-8000-000000000000' }, { ...saved, roles: [saved.roles[0], saved.roles[0]] }, { ...saved, profile: { ...saved.profile, authenticated: true } }]
  for (const value of invalid) { await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) }); await expect(page.getByRole('alert')).toContainText('草稿未恢复'); await expect(page.getByLabel('当前岗位')).toHaveCount(0); await expect(page.getByLabel('完整简历原文')).toHaveCount(0) }
})
test('shared rejection cannot be bypassed by switching roles, suggestions or undo', async ({ page }) => {
  await page.goto('/resume-lab'); await page.getByLabel('简历原文').fill('我编写了Python脚本。'); await page.getByRole('button', { name: '导入并核对原文' }).click()
  const a = await page.getByLabel('当前岗位').inputValue(); await page.getByRole('button', { name: '新增Python后端实习生草稿' }).click(); const b = await page.getByLabel('当前岗位').inputValue()
  await page.getByLabel('选用条目 1', { exact: true }).check(); await page.getByRole('button', { name: '开始岗位三题' }).click(); await page.getByLabel('我的复习回答').fill('未证明独立。')
  await page.getByLabel('当前岗位').selectOption(a); await page.getByRole('button', { name: '拒绝本地条目 1', exact: true }).click(); await page.getByLabel('当前岗位').selectOption(b)
  await expect(page.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled(); await expect(page.getByLabel('我的复习回答')).toHaveCount(0); await expect(page.getByRole('button', { name: '选用原句并前移 · 1', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '撤销上一步（拒绝记录保留）' }).click(); await expect(page.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled()
})

test('long multilingual paragraph remains complete across native print pages and mobile layout', async ({ page }, info) => {
  const long = 'Python课程练习记录，中英文排版需人工核对。'.repeat(140)
  await page.goto('/resume-lab'); await page.getByLabel('简历原文').fill('项目经历\n' + long); await page.getByRole('button', { name: '导入并核对原文' }).click(); await page.getByLabel('选用条目 1', { exact: true }).check(); await page.getByLabel('分页目标').selectOption('multiple')
  const paper = page.getByRole('article', { name: '用户自述简历草稿' }); await expect(paper.locator('.paper-entry-long>p')).toHaveText(long)
  const pdf = await page.pdf({ path: info.outputPath('resume_long_paragraph_native.pdf'), format: 'A4', preferCSSPageSize: true })
  expect((pdf.toString('latin1').match(/\/Type \/Page\b/g) ?? []).length).toBeGreaterThan(1)
  await page.setViewportSize({ width: 390, height: 844 }); await expect(paper.locator('.paper-entry-long>p')).toHaveText(long)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('region', { name: '多岗位与基本信息' }).screenshot({ path: info.outputPath('resume_multi_role_mobile.png') })
})

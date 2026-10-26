import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'
const resume = '教育背景\r\n合成大学 · 计算机本科应届生\r\n\r\n项目经历\r\n课程作业：我编写了图像读取脚本。\r\n\r\n团队演示由同学负责，我只整理公开样例。\r\n\r\n我计划学习部署，尚未部署服务。\r\n\r\n技能\r\nPython课程基础。\r\n\r\n实习经历\r\n暂无实习经历或真实项目，无量化指标。'
async function start(page: import('@playwright/test').Page, raw = resume) {
  await page.goto('/resume-lab'); await page.getByLabel('选择本地文本文件').setInputFiles({ name: 'synthetic-graduate.md', mimeType: 'text/markdown', buffer: Buffer.from(raw) })
  await expect(page.getByLabel('完整简历原文')).toHaveText(raw)
  await page.getByRole('button', { name: '填入视觉算法实习 JD' }).click(); await page.getByRole('button', { name: '分析本地岗位' }).click()
}
test('complete graduate journey: real file, JD, draft edits, download, refresh, restoration, print and three questions without requests', async ({ page, context }, info) => {
  const effects: string[] = []
  page.on('request', r => { if (r.method() !== 'GET' || r.url().includes('/api/') || !r.url().startsWith('http://127.0.0.1:15191/')) effects.push(r.url()) })
  await page.setViewportSize({ width: 1440, height: 1000 }); await start(page)
  await expect(page.getByRole('region', { name: '必备岗位条件' })).toContainText('Python')
  await expect(page.getByRole('region', { name: '加分岗位条件' })).toContainText('部署')
  await expect(page.getByRole('region', { name: '待核实岗位条件' })).toBeVisible()
  await page.getByLabel(/我的判断 jd-/).first().selectOption('gap')
  await expect(page.getByText('真实能力缺口（用户明确自评，非系统推断）')).toBeVisible()
  await page.getByRole('region', { name: '岗位策略' }).screenshot({ path: info.outputPath('resume_job_strategy.png') })
  for (const i of [1, 2, 3, 4]) await page.getByLabel(`选用条目 ${i}`, { exact: true }).check()
  await page.getByRole('textbox', { name: '岗位草稿 2', exact: true }).fill('课程作业：我编写了图像读取脚本，整理了使用说明。')
  await page.getByRole('button', { name: '上移条目 2', exact: true }).click()
  await page.getByLabel('排版密度').selectOption('compact')
  const paper = page.getByRole('article', { name: '用户自述简历草稿' })
  await expect(paper).toContainText('用户改写；原文：课程作业：我编写了图像读取脚本。')
  await expect(paper).toContainText('背景、计划与限制 · 不是已完成个人贡献'); await expect(paper).not.toContainText('99%')
  const downloadPromise = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click(); const download = await downloadPromise
  const bytes = await readFile((await download.path())!), saved = JSON.parse(bytes.toString('utf8'))
  expect(saved.contract).toBe('local-job-resume-draft-v3'); expect(saved.roles).toHaveLength(1); expect(saved.trust).toBe('user_draft_not_verified'); expect(saved.workbench.source.text).toBe(resume)
  expect(saved.roles[0].content.entries[0].state).toBe('user_edited'); expect(saved).not.toHaveProperty('operation_key'); expect(saved).not.toHaveProperty('token')
  await page.reload(); await expect(page.getByRole('article', { name: '用户自述简历草稿' })).toHaveCount(0)
  await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: download.suggestedFilename(), mimeType: 'application/json', buffer: bytes })
  await expect(paper).toContainText('整理了使用说明'); await expect(page.getByLabel('排版密度')).toHaveValue('compact')
  expect(effects).toEqual([]); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
  await context.setOffline(true)
  await page.evaluate(() => { window.print = () => { document.body.dataset.printed = 'yes' } })
  await page.getByRole('button', { name: '打印用户草稿 / 保存 PDF' }).click(); expect(await page.locator('body').getAttribute('data-printed')).toBe('yes')
  await page.emulateMedia({ media: 'print' }); await expect(paper).toBeVisible(); await expect(page.getByRole('heading', { name: '从已有材料开始' })).not.toBeVisible()
  await paper.screenshot({ path: info.outputPath('resume_user_draft_print.png') }); await page.emulateMedia({ media: 'screen' })
  await page.getByRole('button', { name: '开始岗位三题' }).click(); await expect(page.getByText('第 1 / 3 题')).toBeVisible()
  await expect(page.getByRole('region', { name: '岗位三题复习' })).toContainText('原始片段：课程作业：我编写了图像读取脚本。')
  await page.getByLabel('我的复习回答').fill('这是课程作业，没有真实项目或量化业绩。'); await page.getByRole('button', { name: '下一道岗位问题' }).click(); await page.getByRole('button', { name: '跳过岗位问题' }).click(); await page.getByRole('button', { name: '完成岗位复习' }).click()
  await expect(page.getByText('三题复盘 · 不猜经历、不打分')).toBeVisible(); expect(effects).toEqual([])
})
test('team, plan and negation cannot become completed personal work through edits; original restoration and undo work', async ({ page }) => {
  await start(page, '我计划部署服务，团队负责，我尚未参与。')
  await page.getByLabel('选用条目 1', { exact: true }).check()
  const paper = page.getByRole('article', { name: '用户自述简历草稿' })
  await expect(paper).toContainText('背景、计划与限制')
  await page.getByRole('textbox', { name: '岗位草稿 1', exact: true }).fill('我独立完成部署，提升99%。'); await expect(paper).not.toContainText('99%'); await expect(page.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled()
  await page.getByRole('button', { name: '撤销上一步（拒绝记录保留）' }).click(); await expect(page.getByRole('textbox', { name: '岗位草稿 1', exact: true })).toHaveValue('我计划部署服务，团队负责，我尚未参与。')
  await page.getByRole('textbox', { name: '岗位草稿 1', exact: true }).fill('我部署了服务。'); await page.getByRole('button', { name: '恢复原文 1', exact: true }).click(); await expect(paper).toContainText('我尚未参与')
})
test('rejected exact original remains blocked after undo, local file replay, and new source IDs', async ({ page }) => {
  await start(page, '我编写了图像脚本。'); await page.getByLabel('选用条目 1', { exact: true }).check()
  const before = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click(); const download = await before, bytes = await readFile((await download.path())!)
  await page.getByRole('button', { name: '拒绝本地条目 1', exact: true }).click(); await page.getByRole('button', { name: '撤销上一步（拒绝记录保留）' }).click()
  await expect(page.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled()
  await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: 'old.json', mimeType: 'application/json', buffer: bytes })
  await expect(page.getByRole('button', { name: '打印用户草稿 / 保存 PDF' })).toBeDisabled()
  await page.getByRole('textbox', { name: '简历原文', exact: true }).fill('项目经历\n我编写了图像脚本。'); await page.getByRole('button', { name: '导入并核对原文' }).click()
  await expect(page.getByLabel('选用条目 1', { exact: true })).toBeDisabled()
})
test('strict restoration rejects versions, damaged references, duplicate keys, invalid fields, encodings and file limits without partial display', async ({ page }) => {
  await start(page); await page.getByLabel('选用条目 1', { exact: true }).check()
  const event = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click(); const download = await event, bytes = await readFile((await download.path())!), good = bytes.toString('utf8'), d = JSON.parse(good)
  const badQuote = structuredClone(d); badQuote.workbench.excerpts[0].quote = '伪造原话'
  const fakeFact = structuredClone(d); fakeFact.roles[0].content.entries[0].status = 'user_confirmed'
  const badState = structuredClone(d); badState.roles[0].content.entries[0].text = '28条' // still claims original
  const invalid = [JSON.stringify({ ...d, contract: 'future-v99' }), JSON.stringify(badQuote), JSON.stringify(fakeFact), JSON.stringify(badState), good.replace('"contract":', '"contract":"future", "contract":')]
  for (const raw of invalid) {
    await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer: Buffer.from(raw) })
    await expect(page.getByRole('alert')).toContainText('草稿未恢复'); await expect(page.getByRole('article', { name: '用户自述简历草稿' })).toHaveCount(0)
  }
  for (const buffer of [Buffer.from([0xff, 0xfe]), Buffer.alloc(2 * 1024 * 1024 + 1), Buffer.alloc(0)]) {
    await page.getByLabel('恢复本地草稿 JSON').setInputFiles({ name: 'bad.json', mimeType: 'application/json', buffer }); await expect(page.getByRole('alert')).toContainText('草稿未恢复')
  }
})
test('same original with differing local draft states is excluded as a group and no duplicate is printed', async ({ page }) => {
  await start(page, '我编写了脚本。')
  await page.getByRole('textbox', { name: '手工声明', exact: true }).fill('我编写了脚本。'); await page.getByRole('button', { name: '添加未审核声明' }).click()
  const available = page.getByRole('checkbox', { name: /选用条目/ }).filter({ visible: true })
  for (const box of await available.all()) if (await box.isEnabled()) await box.check()
  const paper = page.getByRole('article', { name: '用户自述简历草稿' }); await expect(paper.locator('.paper-entry')).toHaveCount(1)
  await page.getByRole('textbox', { name: '岗位草稿 1', exact: true }).fill('新的用户草稿'); await expect(paper.locator('.paper-entry')).toHaveCount(0)
  await expect(page.getByText('同原句存在不同编辑状态或正文，整组不打印。')).toHaveCount(2)
})
test('malicious draft stays inert and mobile editing/printing preview does not overflow', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 }); await start(page, '我编写了图像读取脚本。')
  await page.getByLabel('选用条目 1', { exact: true }).check(); const payload = '<img src="https://example.invalid/x" onerror="alert(1)"> 用户自述草稿'
  const remote: string[] = []; page.on('request', r => { if (r.url().includes('example.invalid')) remote.push(r.url()) })
  await page.getByRole('textbox', { name: '岗位草稿 1', exact: true }).fill(payload); await expect(page.getByRole('article', { name: '用户自述简历草稿' })).toContainText(payload)
  await expect(page.locator('.resume-lab img,.resume-lab script')).toHaveCount(0); expect(remote).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.getByRole('region', { name: '用户草稿打印' }).screenshot({ path: info.outputPath('resume_draft_mobile.png') })
})

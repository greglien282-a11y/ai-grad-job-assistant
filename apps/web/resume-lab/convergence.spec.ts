import { expect, test, type Page } from '@playwright/test'
import { readFile } from 'node:fs/promises'

const raw = '项目经历\n👩‍💻 é 我编写了Python课程脚本。\n\n技能\nPython课程基础。\n\n团队负责，我计划学习部署。'
async function start(page: Page) {
  await page.goto('/resume-lab'); await page.getByLabel('简历原文', { exact: true }).fill(raw)
  await page.getByRole('button', { name: '导入并核对原文' }).click()
  await page.getByRole('button', { name: '新增Python后端实习生草稿' }).click()
  await page.getByLabel('选用条目 1', { exact: true }).check()
  await page.getByRole('button', { name: '开始岗位三题' }).click()
  await page.getByLabel('我的复习回答').fill('仅有课程记录，不是部署业绩。')
}
async function snapshot(page: Page) {
  const event = page.waitForEvent('download'); await page.getByRole('button', { name: '下载本地草稿 JSON' }).click()
  return JSON.parse((await readFile((await (await event).path())!)).toString('utf8'))
}

test('P2-A/C views and appearance preserve all content; source review is excluded even when printing from it', async ({ page }, info) => {
  const effects: string[] = []
  page.on('request', r => { if (r.method() !== 'GET' || r.url().includes('/api/') || !r.url().startsWith('http://127.0.0.1:15191/')) effects.push(r.url()) })
  await start(page); const before = await snapshot(page)
  await page.getByLabel('排版密度').selectOption('compact'); await page.getByLabel('简历版式').selectOption('minimal'); await page.getByLabel('分页目标').selectOption('multiple')
  await expect(page.getByLabel('我的复习回答')).toHaveValue('仅有课程记录，不是部署业绩。')
  const changed = await snapshot(page)
  expect(changed.roles.map((r: any) => r.content.review)).toEqual(before.roles.map((r: any) => r.content.review))
  const paper = page.getByRole('article', { name: '用户自述简历草稿' })
  await expect(paper).not.toContainText('导入原文'); await expect(paper).not.toContainText('G4')
  await page.getByRole('button', { name: '来源审查', exact: true }).click()
  const review = page.getByRole('region', { name: '来源审查详情' }); await expect(review).toContainText('导入原文'); await expect(review).toContainText('JD原句')
  await expect(paper).not.toBeVisible(); expect(await snapshot(page)).toEqual(changed)
  await review.screenshot({ path: info.outputPath('resume_p2_source_review.png') })
  await page.emulateMedia({ media: 'print' }); await expect(review).not.toBeVisible(); await expect(paper).toBeVisible()
  await paper.screenshot({ path: info.outputPath('resume_p2_clean_print.png') })
  const pdf = await page.pdf({ path: info.outputPath('resume_p2_clean_native.pdf'), format: 'A4', preferCSSPageSize: true })
  expect((pdf.toString('latin1').match(/\/Type \/Page\b/g) ?? []).length).toBe(1)
  await page.emulateMedia({ media: 'screen' }); await page.getByRole('button', { name: '简历输出', exact: true }).click()
  await page.getByRole('textbox', { name: '岗位草稿 1', exact: true }).fill('用户补写课程说明。'); await expect(page.getByLabel('我的复习回答')).toHaveCount(0)
  await page.getByRole('button', { name: '开始岗位三题' }).click(); await page.getByLabel('我的复习回答').fill('新回答')
  await page.getByLabel('目标岗位原文').fill('新的岗位\nPython课程基础。'); await expect(page.getByLabel('我的复习回答')).toHaveCount(0)
  expect(effects).toEqual([]); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
})

test('P2-B metadata edits preserve two roles exactly; range changes require confirm, cancel preserves and confirm resets safely', async ({ page }, info) => {
  await start(page); const before = await snapshot(page)
  await page.getByLabel('段落标题 1', { exact: true }).fill('课程脚本'); await page.getByRole('combobox', { name: '段落类型 1', exact: true }).selectOption('skill'); await page.getByRole('button', { name: '应用段落 1', exact: true }).click()
  await page.getByRole('button', { name: '下移段落 1', exact: true }).click()
  const after = await snapshot(page); expect(after.roles).toEqual(before.roles); expect(after.workbench.source).toEqual(before.workbench.source)
  expect(after.workbench.excerpts.find((e: any) => e.id === before.workbench.excerpts[0].id).quote).toEqual(before.workbench.excerpts[0].quote)
  await page.getByLabel('我的复习回答').fill('仍保留在相同来源上')
  await page.getByLabel('起点 2', { exact: true }).fill('7'); await page.getByRole('button', { name: '应用段落 2', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('引用身份、区间或原句改变'); await expect(page.getByRole('textbox', { name: '岗位草稿 1', exact: true })).toHaveCount(0)
  await page.getByRole('alertdialog').screenshot({ path: info.outputPath('resume_p2_source_confirmation.png') })
  await page.getByRole('button', { name: '取消变更，保留原岗位' }).click(); await expect(page.getByLabel('我的复习回答')).toHaveValue('仍保留在相同来源上')
  await page.getByLabel('起点 2', { exact: true }).fill('7'); await page.getByRole('button', { name: '应用段落 2', exact: true }).click(); await page.getByRole('button', { name: '确认更换来源并重置岗位' }).click()
  expect((await snapshot(page)).roles).toHaveLength(1); await expect(page.getByLabel('我的复习回答')).toHaveCount(0)
})

test('P2-D explicit batch applies only exact eligible sources, keeps boundaries and rejected text excluded', async ({ page }, info) => {
  await start(page)
  const panel = page.getByRole('region', { name: '可解释岗位建议' }); await expect(panel).toContainText('匹配词：python'); await expect(panel).toContainText('建议依据：必备：Python基础与测试意识。')
  await panel.getByRole('button', { name: /选用全部可解释原句/ }).click()
  const saved = await snapshot(page), active = saved.roles.find((r: any) => r.id === saved.active_role_id)
  expect(active.content.entries.filter((e: any) => e.selected).every((e: any) => e.text === e.original && !e.original.includes('团队'))).toBe(true)
  await page.getByLabel('选用条目 3', { exact: true }).check(); await page.getByRole('textbox', { name: '岗位草稿 3', exact: true }).fill('我独立部署了服务，提升99%。')
  await page.getByRole('button', { name: '拒绝本地条目 1', exact: true }).click()
  await page.getByRole('button', { name: '来源审查', exact: true }).click(); await expect(page.getByRole('region', { name: '来源审查详情' })).toContainText('我独立部署了服务，提升99%。')
  await page.getByRole('button', { name: '简历输出', exact: true }).click()
  const paper = page.getByRole('article', { name: '用户自述简历草稿' }); await expect(paper).not.toContainText('99%'); await expect(paper).not.toContainText('我编写了Python课程脚本')
  await panel.screenshot({ path: info.outputPath('resume_p2_explainable_suggestions.png') })
})

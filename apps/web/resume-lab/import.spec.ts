import { test, expect } from '@playwright/test'
const raw = '教育背景\r\n合成应届生，没有实习经历。\r\n\r\n项目经历\r\n👩‍💻 é 我没有部署服务。\r\n团队负责展示，我只整理样例。\r\n\r\n技能\r\nPython课程基础。'
test('home import accepts real local UTF-8 files, exact Unicode sources and manual structure with zero effects', async ({ page }, info) => {
  const effects: string[] = []
  page.on('request', r => { if (r.method() !== 'GET' || r.url().includes('/api/') || !r.url().startsWith('http://127.0.0.1:15191/')) effects.push(r.url()) })
  await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/'); await page.getByRole('link', { name: /我已经有简历/ }).click()
  await page.getByLabel('选择本地文本文件').setInputFiles({ name: 'graduate.md', mimeType: 'text/markdown', buffer: Buffer.from(raw) })
  await expect(page.getByLabel('完整简历原文')).toHaveText(raw)
  const quote = page.getByRole('region', { name: '原文与候选结构' }).locator('blockquote').nth(1)
  await expect(quote).toHaveText('👩‍💻 é 我没有部署服务。\r\n团队负责展示，我只整理样例。')
  await page.getByLabel('段落类型 2').selectOption('other'); await page.getByLabel('段落标题 2').fill('职责边界'); await page.getByRole('button', { name: '应用段落 2' }).click()
  await page.getByRole('textbox', { name: '手工声明', exact: true }).fill('我计划继续学习，暂无量化指标。'); await page.getByRole('button', { name: '添加未审核声明' }).click()
  await expect(page.getByRole('region', { name: '用户手工声明' })).toContainText('用户手工声明 · local_unverified')
  await page.screenshot({ path: info.outputPath('resume_import_sources.png'), fullPage: true })
  expect(effects).toEqual([]); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
  await page.reload(); await expect(page.getByLabel('完整简历原文')).toHaveCount(0)
})
test('invalid encoding, type, empty and oversized files fail closed and clear old results', async ({ page }) => {
  await page.goto('/resume-lab')
  for (const file of [{ name: 'bad.txt', buffer: Buffer.from([0xff, 0xfe, 0x41, 0]) }, { name: 'bad.pdf', buffer: Buffer.from('abc') }, { name: 'empty.txt', buffer: Buffer.alloc(0) }, { name: 'large.md', buffer: Buffer.alloc(128 * 1024 + 1, 65) }]) {
    await page.getByLabel('选择本地文本文件').setInputFiles({ ...file, mimeType: 'text/plain' })
    await expect(page.getByRole('alert')).toContainText('未导入'); await expect(page.getByLabel('完整简历原文')).toHaveCount(0)
  }
})
test('markup remains inert text and privacy/invalid Unicode are safely handled', async ({ page }) => {
  const remote: string[] = []; page.on('request', r => { if (r.url().includes('example.invalid')) remote.push(r.url()) })
  await page.goto('/resume-lab'); const malicious = '<img src="https://example.invalid/x" onerror="alert(1)">\n<script>fetch("https://example.invalid")</script>\ngraduate@example.invalid'
  await page.getByLabel('简历原文').fill(malicious); await page.getByRole('button', { name: '导入并核对原文' }).click()
  await expect(page.getByLabel('完整简历原文')).toHaveText(malicious); await expect(page.getByRole('note')).toContainText('疑似邮箱')
  await expect(page.locator('.resume-lab img,.resume-lab script')).toHaveCount(0); expect(remote).toEqual([])
  await page.getByRole('textbox', { name: '简历原文', exact: true }).fill('文字\u202E隐藏'); await page.getByRole('button', { name: '导入并核对原文' }).click(); await expect(page.getByRole('alert')).toBeVisible()
})
test('manual cross-paragraph citations remain exact, invalid ranges do not replace sources, and mobile fits', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/resume-lab'); await page.getByLabel('简历原文').fill(raw)
  await page.getByRole('button', { name: '导入并核对原文' }).click()
  const saved = await page.getByLabel('完整简历原文').textContent()
  await page.getByLabel('起点 1', { exact: true }).fill('0'); await page.getByLabel('终点 1', { exact: true }).fill(String(Array.from(saved!).length)); await page.getByRole('button', { name: '应用段落 1', exact: true }).click()
  await expect(page.getByRole('region', { name: '原文与候选结构' }).locator('blockquote').first()).toHaveText(saved!)
  await page.getByLabel('终点 1', { exact: true }).fill('999999'); await page.getByRole('button', { name: '应用段落 1', exact: true }).click(); await expect(page.getByRole('alert')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('resume_import_mobile.png'), fullPage: true })
})

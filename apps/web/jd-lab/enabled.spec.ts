import { test, expect } from '@playwright/test'
const start = async (page: import('@playwright/test').Page) => {
  await page.goto('/jd-lab'); await page.getByRole('button', { name: '使用合成 JD 样例' }).click(); await page.getByRole('button', { name: '分析岗位要求 →' }).click()
}
test('home path C reaches the complete JD to resume to three-question journey, with zero API effects', async ({ page }, info) => {
  const business: string[] = [], foreign: string[] = []
  page.on('request', r => { if (r.url().includes('/api/') || r.method() !== 'GET') business.push(r.method() + r.url()); if (!r.url().startsWith('http://127.0.0.1:15187/') && !r.url().startsWith('data:')) foreign.push(r.url()) })
  await page.setViewportSize({ width: 1440, height: 1000 }); await page.goto('/')
  await page.getByRole('link', { name: /我找到了一份目标岗位/ }).click()
  await page.getByRole('button', { name: '使用合成 JD 样例' }).click(); await page.getByRole('button', { name: '分析岗位要求 →' }).click()
  await expect(page.getByRole('region', { name: '结构化岗位要求' })).toBeVisible()
  await expect(page.getByText('缺少可展示证据；不等于已经证明没有能力').first()).toBeVisible()
  const resume = page.getByRole('article', { name: '可打印简历预览' })
  await expect(resume).toContainText('我测试了3个导出按钮。'); await expect(resume).not.toContainText('我计划部署服务。')
  await page.screenshot({ path: info.outputPath('jd_overview.png') }); await resume.screenshot({ path: info.outputPath('resume_originals.png') })
  await page.getByRole('button', { name: '上移 2', exact: true }).click(); await expect(resume.locator('li').first()).toHaveText('我编写了清洗脚本。')
  await page.getByRole('button', { name: '开始三题复习' }).click(); await expect(page.getByText('第 1 / 3 题')).toBeVisible()
  await page.getByLabel('复习回答').fill('我记不清具体检查次数，需要核对。'); await page.getByRole('button', { name: '下一题', exact: true }).click()
  await page.getByRole('button', { name: '跳过这题' }).click(); await expect(page.getByText('第 3 / 3 题')).toBeVisible(); await page.getByRole('button', { name: '完成复习' }).click()
  await expect(page.getByText('复盘 · 不打分，不猜经历')).toBeVisible()
  expect(business).toEqual([]); expect(foreign).toEqual([]); expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0])
})
test('fabricated metrics and technology stay outside printable resume, print media contains originals only', async ({ page }) => {
  await start(page); await page.getByLabel(/本地预览文字 /).first().fill('我用Python部署100台服务器，提升99%。')
  await expect(page.getByText(/未核实的本地改写/)).toBeVisible()
  const resume = page.getByRole('article', { name: '可打印简历预览' })
  await expect(resume).not.toContainText('99%'); await expect(resume).not.toContainText('Python')
  await page.emulateMedia({ media: 'print' }); await expect(resume).toBeVisible(); await expect(page.getByRole('heading', { name: '粘贴岗位描述' })).not.toBeVisible()
})
test('manual adjustments retain exact Unicode quote and new JD invalidates all downstream output', async ({ page }) => {
  await page.goto('/jd-lab'); const raw = '👩‍💻é测试岗位\r\n必须测试。无需测试经验。'
  await page.getByLabel('岗位 JD 原文').fill(raw); await page.getByRole('button', { name: '分析岗位要求 →' }).click()
  await page.getByLabel(/要求描述 jd-/).first().fill('本地调整')
  await expect(page.getByText('用户调整，未重新认证 JD 含义')).toBeVisible()
  await expect(page.getByRole('region', { name: '结构化岗位要求' }).locator('blockquote').first()).toHaveText('👩‍💻é测试岗位')
  await page.getByLabel('岗位 JD 原文').fill(''); await expect(page.getByRole('article', { name: '可打印简历预览' })).toHaveCount(0)
  await page.getByRole('button', { name: '分析岗位要求 →' }).click(); await expect(page.getByRole('alert')).toHaveText('请先粘贴岗位描述。')
})
test('mobile layout has no horizontal overflow and excluded material is not a contribution', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 }); await start(page)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  const resume = page.getByRole('article', { name: '可打印简历预览' })
  for (const text of ['我计划部署服务。', '团队部署了服务。', '我不知道。', '我验证了3个导出按钮。']) await expect(resume).not.toContainText(text)
  await page.screenshot({ path: info.outputPath('jd_mobile.png') })
})

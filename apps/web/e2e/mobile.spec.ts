import { test, expect, create, probe } from './helpers.ts'

test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true })

test('narrow touch layout handles long synthetic statements', async ({ page }, info) => {
  await create(page)
  await page.getByLabel('新的事实陈述').fill('Synthetic long statement: ' + 'implementation_reference_'.repeat(12))
  await page.getByRole('button', { name: '新增待确认事实', exact: true }).tap()
  await expect(page.getByRole('article', { name: '事实 1', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认事实', exact: true }).tap()
  await expect(page.getByText('用户确认', { exact: true })).toBeVisible()
  expect(probe().facts[0].status).toBe('user_confirmed')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true)
  await page.getByText(/查看来源与历史/).tap()
  await expect(page.getByText('原始自述（历史起点）', { exact: true })).toBeVisible()
  await page.screenshot({ path: info.outputPath('mobile_workspace.png'), fullPage: true })
})

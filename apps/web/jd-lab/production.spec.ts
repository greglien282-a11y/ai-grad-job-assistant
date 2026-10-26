import { test, expect } from '@playwright/test'
test('built production route and homepage remain closed despite a preview-server environment flag', async ({ page }) => {
  await page.goto('/jd-lab'); await expect(page.getByRole('heading', { name: '开发预览未启用' })).toBeVisible()
  await expect(page.getByLabel('岗位 JD 原文')).toHaveCount(0)
  await page.goto('/'); await expect(page.getByText('岗位分析 · 开发中')).toBeVisible(); await expect(page.getByRole('link', { name: /我找到了一份目标岗位/ })).toHaveCount(0)
})

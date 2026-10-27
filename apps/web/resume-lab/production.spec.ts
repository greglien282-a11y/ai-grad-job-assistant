import { expect, test } from '@playwright/test'
test('production build keeps local import closed even with the development environment flag', async ({ page }) => {
  await page.goto('/resume-lab'); await expect(page.getByText('本地简历实验未启用')).toBeVisible(); await expect(page.getByLabel('简历原文')).toHaveCount(0)
  await page.goto('/'); await expect(page.locator('a[href="/resume-lab"]')).toHaveCount(0)
})

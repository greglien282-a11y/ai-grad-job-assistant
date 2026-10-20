import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { test, expect, forward } from './helpers.js'
import type { Page } from '@playwright/test'
import { factV3Schema, exportV2Schema, summaryV2Schema } from '../src/lib/experience-read-contract.js'

function fixture(action: string): Record<string, string | string[]> {
  const out = execFileSync(process.env.PATHWISE_E2E_PYTHON!, [fileURLToPath(new URL('./typed_probe.py', import.meta.url)), action], { encoding: 'utf8', windowsHide: true })
  return out.trim() ? JSON.parse(out) : {}
}
async function open(page: Page, b: Record<string, string | string[]>) {
  await page.goto('/typed-read')
  await page.getByLabel('会话 ID', { exact: true }).fill(b.sessionId as string)
  await page.getByLabel('项目 ID', { exact: true }).fill(b.projectId as string)
  await page.getByLabel('会话凭证', { exact: true }).fill(b.token as string)
}
test('real typed summary → independent Fact v3 → explicit full technical download; every table unchanged', async ({ page }) => {
  const b = fixture('seed'); const before = fixture('audit'); const requests: string[] = []
  page.on('request', r => { if (r.url().includes('/api/')) { expect(r.method()).toBe('GET'); expect(r.url()).not.toContain(b.token); requests.push(new URL(r.url()).pathname) } })
  await open(page, b); expect(requests).toEqual([])
  const summaryResponse = page.waitForResponse(r => r.url().endsWith('/experience-summary'))
  await page.getByRole('button', { name: '读取新版资料', exact: true }).click()
  const response = await summaryResponse; expect(response.status()).toBe(200)
  const s = summaryV2Schema.parse(await response.json())
  await expect(page.getByRole('heading', { name: '已审核的非成果资料', exact: true })).toBeVisible()
  for (const label of ['未分类', '个人行动', '进行中', '计划', '背景', '边界', '分类尚未审核']) await expect(page.getByText(label, { exact: false }).first()).toBeVisible()
  for (const reason of ['行动仍在进行', '计划不属于已完成成果', '背景资料', '边界说明']) await expect(page.getByText(reason, { exact: true }).first()).toBeVisible()
  expect(s.confirmed.map(f => f.id)).toContain(b.material)
  expect(s.pending.map(f => f.id)).toEqual([b.pending])
  const all = [...s.confirmed, ...s.pending, ...s.reviewed_non_contributions.map(e => e.fact)]
  expect(all.map(f => f.id)).not.toContain(b.rejected)
  const f = s.confirmed.find(f => f.id === b.material)!
  const detailResponse = page.waitForResponse(r => r.url().endsWith(`/facts/${f.id}`))
  await page.getByRole('button', { name: `查看来源 ${f.id}`, exact: true }).click()
  const detail = factV3Schema.parse(await (await detailResponse).json()); expect(detail).toEqual(f)
  const region = page.getByRole('region', { name: '事实来源详情' })
  await expect(region.getByText('暂无分类依据记录', { exact: true })).toBeVisible()
  const q = f.current_statement_citations[0]; expect(Array.from(q.quote).length).toBe(q.end - q.start)
  expect(q.quote).toContain('🧪'); expect(q.quote).toContain('\r\n'); expect(q.quote).toContain('e\u0301')
  await expect(region.locator('blockquote .typed-original').first()).toHaveText(q.quote, { useInnerText: false })
  expect(detail.classification_citations).toEqual([])
  // Rejected is readable on its explicit v3 route, never contribution text.
  await page.getByLabel('单独核对事实 ID', { exact: true }).fill(b.rejected as string)
  await page.getByRole('button', { name: '读取独立事实', exact: true }).click()
  await expect(region.getByText('已拒绝', { exact: false })).toBeVisible()
  expect(requests.filter(p => p.endsWith('/export'))).toHaveLength(0)
  const [download, exportResponse] = await Promise.all([
    page.waitForEvent('download'), page.waitForResponse(r => r.url().endsWith('/export')),
    page.getByRole('button', { name: '下载技术备份 v2', exact: true }).click(),
  ])
  const out = exportV2Schema.parse(await exportResponse.json()); expect(out.data.facts).toContainEqual(f)
  expect(out.data.facts.some(f => f.id === b.rejected && f.status === 'rejected')).toBe(true)
  expect(download.suggestedFilename()).toBe(`pathwise-v2-${b.sessionId}.json`)
  expect(requests.every(p => p.startsWith('/api/v2/experience/'))).toBe(true)
  expect(requests.filter(p => p.endsWith('/experience-summary'))).toHaveLength(1)
  expect(fixture('audit')).toEqual(before)
  expect(await page.evaluate(() => ({ query: location.search, storage: sessionStorage.length }))).toEqual({ query: '', storage: 0 })
})

for (const fault of ['foreign', 'permission', 'schema', 'corrupt', 'disabled', 'network', 'version', 'unauthorized', 'conflict'] as const) {
  test(`typed read fails closed: ${fault}; no v1, writes or partial display`, async ({ page }) => {
    const b = fixture('seed')
    if (fault === 'foreign') b.token = b.foreignToken
    if (fault === 'permission') fixture('permission-off')
    if (fault === 'schema') fixture('schema-off')
    if (fault === 'corrupt') fixture('corrupt')
    const before = fixture('audit'); const paths: string[] = []
    page.on('request', r => { if (r.url().includes('/api/')) { paths.push(new URL(r.url()).pathname); expect(r.method()).toBe('GET') } })
    await page.route('**/api/v2/experience/**', async route => {
      if (fault === 'network') return route.abort('failed')
      if (fault === 'disabled') return route.continue({ headers: { ...route.request().headers(), 'x-pathwise-e2e-read-disabled': '1' } })
      if (fault === 'unauthorized') { const h = { ...route.request().headers() }; delete h.authorization; return route.continue({ headers: h }) }
      const response = await forward(route)
      if (fault === 'version') { expect(response.status()).toBe(200); return route.fulfill({ response, json: { ...(await response.json()), summary_contract_version: 99 } }) }
      if (fault === 'conflict') return route.fulfill({ status: 409, json: { error: { code: 'version_conflict' } } })
      return route.fulfill({ response })
    })
    try {
      await open(page, b); await page.getByRole('button', { name: '读取新版资料', exact: true }).click()
      const messages = { foreign: '资料不存在或不属于当前会话', permission: '暂时无法安全读取完整资料', schema: '暂时无法安全读取完整资料', corrupt: '暂时无法安全读取完整资料',
        disabled: '新版读取暂不可用', network: '网络连接中断', version: '服务返回了尚不支持的读取版本', unauthorized: '需要有效的会话凭证', conflict: '资料版本或状态已变化' }
      await expect(page.getByRole('alert')).toContainText(messages[fault])
      await expect(page.getByRole('heading', { name: '可进入贡献正文的已审核事实', exact: true })).toHaveCount(0)
      expect(paths).toHaveLength(1); expect(paths[0]).toContain('/api/v2/experience/')
      expect(fixture('audit')).toEqual(before)
    } finally {
      if (fault === 'permission') fixture('permission-on')
      if (fault === 'schema') fixture('schema-on')
    }
  })
}

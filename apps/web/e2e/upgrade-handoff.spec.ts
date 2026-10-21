import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { test, expect, forward } from './helpers.js'
import type { Page } from '@playwright/test'

type Access = { sessionId: string; projectId: string; token: string; foreignToken: string; fid: string }
function fixture(action: string, data?: Access): Record<string, string> {
  const out = execFileSync(process.env.PATHWISE_E2E_PYTHON!, [fileURLToPath(new URL('./typed_probe.py', import.meta.url)), action],
    { encoding: 'utf8', windowsHide: true, input: data ? JSON.stringify(data) : undefined })
  return out.trim() ? JSON.parse(out) : {}
}
async function open(page: Page, view: 'workspace' | 'summary', b: Access) {
  await page.context().setExtraHTTPHeaders({ 'x-pathwise-e2e-legacy-read': '1' })
  await page.goto('/discovery')
  await page.evaluate(b => sessionStorage.setItem('pathwise.development.session', JSON.stringify({ sessionId: b.sessionId, token: b.token })), b)
  await page.goto(view === 'summary' ? '/discovery/summary' : '/discovery')
  if (view === 'summary') await expect(page.getByRole('article', { name: '已确认经历正文' })).toBeVisible()
  else await expect(page.getByRole('heading', { name: '1 条已确认，可以阅读了' })).toBeVisible()
}
async function storage(page: Page) {
  return page.evaluate(() => JSON.stringify(Object.entries(sessionStorage).sort(([a], [b]) => a.localeCompare(b))))
}
async function assertUpgrade(page: Page) {
  await expect(page.getByRole('heading', { name: '当前会话需要新版读取' })).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('本次读取没有修改资料')
  await expect(page.getByRole('button')).toHaveCount(0)
  await expect(page.locator('.summary-text, .result-sources, .workspace-toolbar, .result-entry, .fact-card')).toHaveCount(0)
  await expect(page.getByRole('link', { name: '由我进入新版只读页面' })).toHaveAttribute('href', '/typed-read')
}

for (const mode of ['session-workspace', 'session-summary', 'summary-workspace', 'summary-summary', 'export', 'history-only'] as const) {
  test(`real restricted legacy GET handoff: ${mode}, no stale display or business effects`, async ({ page }) => {
    const b = fixture('seed-legacy') as Access
    const view = mode.endsWith('summary') ? 'summary' : 'workspace'
    await open(page, view, b)
    if (view === 'workspace') {
      await page.getByRole('button', { name: '结束会话', exact: true }).click()
      await expect(page.getByRole('button', { name: '确认结束会话', exact: true })).toBeVisible()
    }
    if (mode.startsWith('summary-')) {
      // Hold an actually valid v1 SessionView, add synthetic typed records,
      // then forward it: the following real summary GET must refuse upgrade.
      let injected = false
      await page.route(`**/api/v1/experience/sessions/${b.sessionId}`, async route => {
        const old = await forward(route)
        expect(old.status()).toBe(200)
        fixture('upgrade-existing', b); injected = true
        before = fixture('audit'); saved = await storage(page)
        await route.fulfill({ response: old })
      })
      expect(injected).toBe(false)
    } else fixture(mode === 'history-only' ? 'history-only' : 'upgrade-existing', b)
    let before = fixture('audit'), saved = await storage(page)
    const requests: { path: string; method: string }[] = []
    page.on('request', r => { if (r.url().includes('/api/')) requests.push({ path: new URL(r.url()).pathname, method: r.method() }) })
    const target = mode === 'export' ? '/export' : mode.startsWith('summary-') ? '/experience-summary' : `/sessions/${b.sessionId}`
    const refused = page.waitForResponse(r => r.url().endsWith(target) && r.status() === 409)
    if (mode === 'export') {
      await page.getByText('技术备份（JSON，非正式简历）').click()
      await page.getByRole('button', { name: '下载 JSON 技术备份' }).click()
    } else if (view === 'summary') {
      await page.getByRole('link', { name: '02 回答与核对', exact: true }).click()
      await page.getByRole('link', { name: '03 阅读整理稿', exact: true }).click()
    } else await page.getByRole('button', { name: '重新读取', exact: true }).click()
    const body = await (await refused).json()
    expect(body.error.code).toBe(mode === 'export' ? 'export_contract_upgrade_required' : mode.startsWith('summary-') ? 'summary_contract_upgrade_required' : 'fact_contract_upgrade_required')
    await assertUpgrade(page)
    expect(await page.evaluate(expected => JSON.stringify(Object.entries(sessionStorage).sort(([a], [b]) => a.localeCompare(b))) === expected, saved)).toBe(true)
    expect(fixture('audit')).toEqual(before)
    expect(requests.every(r => r.method === 'GET' && r.path.startsWith('/api/v1/'))).toBe(true)
    const count = requests.length
    await page.getByRole('link', { name: '由我进入新版只读页面' }).click()
    await expect(page).toHaveURL('http://127.0.0.1:15173/typed-read')
    for (const label of ['会话 ID', '项目 ID', '会话凭证']) await expect(page.getByLabel(label, { exact: true })).toHaveValue('')
    expect(requests).toHaveLength(count)
    expect(fixture('audit')).toEqual(before)
  })
}

test('pending keys survive actual typed refusal and explicit navigation to a default-closed new reader', async ({ page }) => {
  const b = fixture('seed-legacy') as Access
  await open(page, 'workspace', b)
  await page.evaluate(async b => {
    const miningPath = '/src/lib/pending-mining.ts', creationPath = '/src/lib/idempotency.ts'
    const mining = await import(miningPath), creation = await import(creationPath)
    mining.storeMining(await mining.newMining(b, { project_id: b.projectId, base_revision: 1, content: 'Synthetic unsubmitted answer', input_turn_id: null, retry_of: null, confirm_retry: false }))
    creation.storePending(await creation.newPending('Synthetic unsubmitted creation'))
  }, b)
  await page.reload()
  await expect(page.getByText('未找到原操作。重新输入完全一致的原回答，保留原问题关联，可用同一操作键重试。')).toBeVisible()
  const saved = await storage(page)
  fixture('upgrade-existing', b); const before = fixture('audit')
  const paths: string[] = []
  page.on('request', r => { if (r.url().includes('/api/')) { expect(r.method()).toBe('GET'); paths.push(new URL(r.url()).pathname) } })
  await page.getByRole('button', { name: '查询刚才的整理结果', exact: true }).click()
  await assertUpgrade(page)
  expect(await page.evaluate(expected => JSON.stringify(Object.entries(sessionStorage).sort(([a], [b]) => a.localeCompare(b))) === expected, saved)).toBe(true)
  expect(paths).toHaveLength(1)
  await page.getByRole('link', { name: '由我进入新版只读页面' }).click()
  await expect(page.getByLabel('会话凭证', { exact: true })).toHaveValue('')
  await page.route('**/api/v2/experience/**', r => r.continue({ headers: { ...r.request().headers(), 'x-pathwise-e2e-read-disabled': '1' } }))
  await page.getByLabel('会话 ID', { exact: true }).fill(b.sessionId)
  await page.getByLabel('项目 ID', { exact: true }).fill(b.projectId)
  try { await page.getByLabel('会话凭证', { exact: true }).fill(b.token) } catch { throw new Error('Synthetic credential input failed; diagnostics suppressed') }
  await page.getByRole('button', { name: '读取新版资料', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('新版读取暂不可用')
  expect(paths).toHaveLength(2); expect(paths[1]).toContain('/api/v2/')
  expect(await page.evaluate(expected => JSON.stringify(Object.entries(sessionStorage).sort(([a], [b]) => a.localeCompare(b))) === expected, saved)).toBe(true)
  expect(fixture('audit')).toEqual(before)
})

for (const mode of ['foreign', 'network', 'unknown', 'conflict'] as const) {
  test(`ordinary legacy ${mode} remains distinct, no writes or automatic handoff`, async ({ page }) => {
    const b = fixture('seed-legacy') as Access
    await open(page, 'summary', b)
    if (mode === 'foreign') {
      fixture('upgrade-existing', b)
      await page.evaluate(b => sessionStorage.setItem('pathwise.development.session', JSON.stringify({ sessionId: b.sessionId, token: b.foreignToken })), b)
    } else await page.route('**/api/v1/experience/**', async r => mode === 'network' ? r.abort('failed') : r.fulfill({ status: 409, json: { error: { code: mode === 'unknown' ? 'unknown_contract_code' : 'context_conflict' } } }))
    const before = fixture('audit'), saved = await storage(page)
    const methods: string[] = []
    page.on('request', r => { if (r.url().includes('/api/')) methods.push(r.method()) })
    await page.reload(); await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('heading', { name: '当前会话需要新版读取' })).toHaveCount(0)
    await expect(page.getByRole('article', { name: '已确认经历正文' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: '复制经历文本' })).toHaveCount(0)
    expect(methods.every(m => m === 'GET')).toBe(true)
    expect(fixture('audit')).toEqual(before)
    expect(await page.evaluate(expected => JSON.stringify(Object.entries(sessionStorage).sort(([a], [b]) => a.localeCompare(b))) === expected, saved)).toBe(true)
  })
}

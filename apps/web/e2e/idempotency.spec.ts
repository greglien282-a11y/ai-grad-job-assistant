import { test as base, expect, type Page, type Route } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

function audit(reset = false) {
  if (process.env.PATHWISE_E2E !== '1' || !process.env.PATHWISE_E2E_RUN_FILE || !process.env.PATHWISE_E2E_PYTHON) throw new Error('Validated isolated harness required')
  const output = execFileSync(process.env.PATHWISE_E2E_PYTHON, [fileURLToPath(new URL('./probe.py', import.meta.url)), reset ? 'reset' : 'audit'], { encoding: 'utf8', windowsHide: true })
  return reset ? null : JSON.parse(output)
}
const test = base.extend<{ isolated: void }>({ isolated: [async ({ context }, use) => {
  audit(true)
  await context.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:15173' ? route.continue() : route.abort())
  try { await use() } finally { await context.unrouteAll({ behavior: 'wait' }); audit(true) }
}, { auto: true }] })
async function forward(route: Route) {
  try { return await route.fetch({ maxRetries: 0, maxRedirects: 0 }) }
  catch { throw new Error('Isolated upstream failed; private headers suppressed') }
}
async function create(page: Page) {
  await page.goto('/manual')
  await page.getByLabel('原始经历', { exact: true }).fill('Synthetic refresh recovery project')
  await page.getByRole('button', { name: '创建经历会话 →', exact: true }).click()
}
async function add(page: Page) {
  await page.getByLabel('新的事实陈述').fill('Synthetic recoverable source')
  await page.getByRole('button', { name: '新增待确认事实', exact: true }).click()
}

test('lost creation and lost recovery response survive refresh with zero extra POST', async ({ page }) => {
  let posts = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/sessions')) posts++ })
  await page.route('**/api/v1/experience/sessions', async route => { expect((await forward(route)).status()).toBe(201); await route.abort('connectionreset') }, { times: 1 })
  await page.route('**/api/v1/experience/session-creations/recovery', route => route.abort('connectionreset'), { times: 1 })
  await create(page)
  await expect(page.getByRole('alert')).toBeVisible()
  expect(audit().sessions.length).toBe(1)
  expect(await page.evaluate(() => sessionStorage.getItem('pathwise.development.pendingCreate') !== null)).toBe(true)
  await page.reload()
  await expect(page.getByRole('heading', { name: '你的事实清单' })).toBeVisible()
  expect(posts).toBe(1)
  expect(audit().sessions.length).toBe(1)
  await page.getByRole('button', { name: '删除会话', exact: true }).click()
  await page.getByRole('button', { name: '确认永久删除', exact: true }).click()
  expect(audit().sessions.length).toBe(0)
})

test('unsubmitted creation refresh stays read-only and original body gates same-key retry', async ({ page }) => {
  let posts = 0, original = '', repeated = ''
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/sessions')) { posts++; if (!original) original = request.headers()['idempotency-key']; else repeated = request.headers()['idempotency-key'] } })
  await page.route('**/api/v1/experience/sessions', route => route.abort('internetdisconnected'), { times: 1 })
  await create(page); await expect(page.getByRole('alert')).toContainText('尚未找到')
  expect(audit().sessions.length).toBe(0)
  await page.reload(); await expect(page.getByRole('alert')).toContainText('尚未找到')
  expect(posts).toBe(1)
  await page.getByLabel('原始经历').fill('Synthetic changed body')
  await page.getByRole('button', { name: '用原输入重试创建' }).click()
  await expect(page.getByRole('alert')).toContainText('先前提交不同')
  expect(posts).toBe(1)
  await page.getByLabel('原始经历').fill('Synthetic refresh recovery project')
  await page.getByRole('button', { name: '用原输入重试创建' }).click()
  await expect(page.getByRole('heading', { name: '你的事实清单' })).toBeVisible()
  expect(Boolean(original) && original === repeated).toBe(true)
  expect(audit().sessions.length).toBe(1)
})

test('committed source turn with lost response is reused without duplicate source or history', async ({ page }) => {
  await create(page); await expect(page.getByRole('heading', { name: '你的事实清单' })).toBeVisible()
  await page.route('**/api/v1/experience/sessions/*/turns', async route => { expect((await forward(route)).status()).toBe(201); await route.abort('connectionreset') }, { times: 1 })
  await add(page); await expect(page.getByRole('alert')).toBeVisible()
  expect(audit().turns).toBe(2); expect(audit().facts.length).toBe(0)
  await page.getByRole('button', { name: '新增待确认事实' }).click()
  await expect(page.getByRole('article', { name: '事实 1' })).toBeVisible()
  expect(audit().turns).toBe(2); expect(audit().facts.length).toBe(1)
  expect(audit().sources).toBe(1); expect(audit().history).toBe(1)
})

test('deleted pending creation cannot be restored or silently recreated after refresh', async ({ page }) => {
  await page.route('**/api/v1/experience/sessions', async route => { await forward(route); await route.abort('connectionreset') }, { times: 1 })
  await page.route('**/api/v1/experience/session-creations/recovery', route => route.abort('connectionreset'), { times: 1 })
  await create(page); await expect(page.getByRole('alert')).toBeVisible()
  const p = await page.evaluate(() => JSON.parse(sessionStorage.getItem('pathwise.development.pendingCreate')!))
  try {
    const headers = { Authorization: `Bearer ${p.token}`, 'Idempotency-Key': p.key }
    const recovery = await page.request.get('/api/v1/experience/session-creations/recovery', { headers })
    if (recovery.status() !== 200) throw new Error()
    const sid = (await recovery.json()).session_id
    const removed = await page.request.delete(`/api/v1/experience/sessions/${sid}`, { headers: { Authorization: headers.Authorization } })
    if (removed.status() !== 204) throw new Error()
  } catch { throw new Error('Isolated delete failed; private request diagnostics suppressed') }
  await page.reload()
  await expect(page.getByRole('alert')).toContainText('不是长期账号恢复')
  await expect(page.getByRole('button', { name: '创建经历会话 →' })).toBeDisabled()
  expect(audit().sessions.length).toBe(0)
  expect(await page.evaluate(() => sessionStorage.getItem('pathwise.development.pendingCreate') === null)).toBe(true)
})

test('replay of original fact creation returns edited B without extra history', async ({ page }) => {
  await create(page); await expect(page.getByRole('heading', { name: '你的事实清单' })).toBeVisible()
  let captured: { url: string; headers: Record<string, string>; body: unknown } | undefined
  await page.route('**/api/v1/experience/projects/*/facts', route => {
    const request = route.request()
    captured = { url: request.url(), headers: request.headers(), body: request.postDataJSON() }
    return route.continue()
  })
  await add(page); await expect(page.getByRole('article', { name: '事实 1' })).toBeVisible()
  await page.getByRole('button', { name: '确认事实', exact: true }).click()
  await expect(page.getByText('用户确认', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '编辑陈述' }).click()
  await page.getByLabel('编辑事实 1').fill('Synthetic edited B')
  await page.getByRole('button', { name: '保存编辑' }).click()
  await expect(page.getByText('待确认', { exact: true })).toBeVisible()
  const before = audit().history
  if (!captured) throw new Error('Original operation not captured')
  try {
    const response = await page.request.post(captured.url, { headers: { Authorization: captured.headers.authorization, 'Idempotency-Key': captured.headers['idempotency-key'] }, data: captured.body })
    expect(response.status()).toBe(201)
    const value = await response.json()
    expect(value.statement).toBe('Synthetic edited B'); expect(value.source_kind).toBe('user_edit')
  } catch { throw new Error('Isolated replay failed; private request diagnostics suppressed') }
  expect(audit().history).toBe(before); expect(audit().facts.length).toBe(1)
})

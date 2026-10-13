import { test as base, expect, type Page, type Route } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

export { expect }
// Auto fixture executes for every test across files; imported hook registration
// would be cached and could leave the next file without cleanup.
export const test = base.extend<{ isolatedData: void }>({
  isolatedData: [async ({ context }, use) => {
    probe('reset')
    const empty = probe()
    if (empty.sessions.length || empty.facts.length || empty.turns || empty.history || empty.sources || empty.evidence || empty.projects) {
      throw new Error('Test schema was not empty after isolated reset')
    }
    await context.route('**/*', route => new URL(route.request().url()).origin === 'http://127.0.0.1:15173'
      ? route.continue() : route.abort('blockedbyclient'))
    try { await use() } finally { await context.unrouteAll({ behavior: 'wait' }); probe('reset') }
  }, { auto: true }],
})
type Credentials = { sessionId: string; token: string }
export type Audit = { sessions: { id: string; status: string }[]; facts: { id: string; statement: string; status: string; version: number }[]; turns: number; history: number; evidence: number; sources: number; projects: number;
  changes: { id: string; action: string; before: Record<string, unknown> | null; after: Record<string, unknown> }[];
  materials: { material_reference: string; basis: string; reviewer: string }[]; original_sources: string[] }
export function probe(action = 'audit'): Audit {
  const python = process.env.PATHWISE_E2E_PYTHON
  if (!python || !process.env.PATHWISE_E2E_RUN_FILE) throw new Error('Isolated probe unavailable')
  const result = execFileSync(python, [fileURLToPath(new URL('./probe.py', import.meta.url)), action], { encoding: 'utf8', windowsHide: true })
  return action === 'reset' ? {} as Audit : JSON.parse(result)
}
export async function create(page: Page) {
  await page.goto('/')
  await page.getByLabel('原始经历', { exact: true }).fill('Synthetic course project: built a task tracker.')
  await page.getByRole('button', { name: '创建经历会话 →', exact: true }).click()
  await expect(page.getByRole('heading', { name: '你的事实清单', exact: true })).toBeVisible()
}
export async function add(page: Page) {
  await page.getByLabel('新的事实陈述', { exact: true }).fill('Synthetic A: implemented the task list UI.')
  await page.getByRole('button', { name: '新增待确认事实', exact: true }).click()
  await expect(page.getByRole('article', { name: '事实 1', exact: true })).toBeVisible()
}
export async function credentials(page: Page): Promise<Credentials> {
  const value = await page.evaluate(() => JSON.parse(sessionStorage.getItem('pathwise.development.session') ?? 'null'))
  if (!value) throw new Error('Browser has no recoverable session credential')
  return value
}
export async function apiRead(page: Page) {
  const c = await credentials(page)
  try {
    const result = await page.request.get(`/api/v1/experience/sessions/${c.sessionId}`, { headers: { Authorization: `Bearer ${c.token}` } })
    if (result.status() !== 200) throw new Error('Unexpected isolated API read status')
    return await result.json()
  } catch { throw new Error('Isolated API read failed (credential details suppressed)') }
}
export async function editFromAnotherClient(page: Page) {
  const c = await credentials(page)
  const current = await apiRead(page)
  const fact = current.facts[0]
  try {
    const result = await page.request.patch(`/api/v1/experience/facts/${fact.id}`, {
      headers: { Authorization: `Bearer ${c.token}` },
      data: { action: 'edit', expected_version: fact.version, statement: 'Synthetic remote edit: wrote deployment scripts.' },
    })
    if (result.status() !== 200) throw new Error('Unexpected concurrent edit status')
  } catch { throw new Error('Concurrent isolated edit failed (credential details suppressed)') }
}
export async function forward(route: Route) {
  try { return await route.fetch({ maxRetries: 0, maxRedirects: 0 }) }
  catch { throw new Error('Isolated upstream request failed (network diagnostics suppressed)') }
}

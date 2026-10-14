import { test, expect, probe, apiRead, editFromAnotherClient } from './helpers.js'
import type { Page, Route } from '@playwright/test'
type Audit = { runs: { id: string; input_turn_id: string; state: string }[]; answers: { turn_id: string; question_id: string; question_version: number }[]; questions: { id: string; state: string; content: string | null; version: number }[]; user_turns: number }
const audit = () => probe('mining-audit') as unknown as Audit
async function ready(page: Page) {
  await page.goto('/discovery')
  await page.getByLabel('描述一段经历').fill('合成课程项目：制作任务管理工具，我负责列表界面，团队一起演示。')
  await page.getByRole('button', { name: '开始合成整理', exact: true }).click()
  await expect(page.getByRole('article', { name: '合成追问' })).toHaveCount(2)
  await expect(page.getByRole('button', { name: '保存回答并合成整理' })).toBeDisabled()
  await expect(page.getByRole('button', { name: '重新读取', exact: true })).toBeEnabled()
}
async function answer(page: Page, text = '合成补充：我实现了筛选和空状态提示，没有做后台部署。') {
  await page.getByRole('checkbox').first().check()
  await page.getByLabel('你的回答或自由补充').fill(text)
  await page.getByRole('button', { name: '保存回答并合成整理' }).click()
}
async function forward(route: Route) {
  try { return await route.fetch({ maxRetries: 0, maxRedirects: 0 }) }
  catch { throw new Error('Isolated upstream failed; private headers suppressed') }
}

test('discovery full real UI / HTTP / PostgreSQL flow and desktop evidence', async ({ page, context }, info) => {
  // Grant only the disposable test origin; exercise the real clipboard, no mock.
  await context.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: 'http://127.0.0.1:15173' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  await expect(page.getByRole('region', { name: '三个首页入口' })).toBeVisible()
  await expect(page.getByLabel('原始经历', { exact: true })).toHaveCount(0)
  await expect(page.getByLabel('描述一段经历')).toHaveCount(0)
  await page.screenshot({ path: info.outputPath('home.png'), fullPage: true })
  await page.getByRole('link', { name: /我还没有一份像样的简历/ }).click()
  await page.getByLabel('描述一段经历').fill('合成课程项目：任务列表，我负责页面交互，团队负责整体演示。')
  await page.getByRole('button', { name: '开始合成整理', exact: true }).click()
  await expect(page.getByRole('article', { name: '合成追问' })).toHaveCount(2)
  await expect(page.getByRole('button', { name: '重新读取', exact: true })).toBeEnabled()
  await answer(page)
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  const state = await apiRead(page), last = state.mining_runs.at(-1)
  expect(last.answered_questions).toHaveLength(1)
  expect(audit().answers[0].question_id).toBe(last.answered_questions[0].question_id)
  expect(audit().answers[0].turn_id).toBe(last.input_turn_id)
  expect(probe().facts.every(f => f.status === 'pending')).toBe(true)
  const card = page.getByRole('article', { name: '事实 2', exact: true })
  await card.getByLabel('记忆状态 2').selectOption('certain')
  await expect(card.getByLabel('记忆状态 2')).toHaveValue('certain')
  await expect(page.getByRole('button', { name: '重新读取', exact: true })).toBeEnabled()
  await card.getByRole('button', { name: '确认事实', exact: true }).click()
  await expect(card.getByText('用户确认', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '编辑陈述', exact: true }).click()
  await card.getByLabel('编辑事实 2').fill('合成确认：实现任务筛选、空状态提示和键盘操作。')
  await card.getByRole('button', { name: '保存编辑' }).click()
  await expect(card.getByText('待确认', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '确认事实', exact: true }).click()
  await expect(card.getByText('用户确认', { exact: true })).toBeVisible()
  await card.getByRole('button', { name: '材料核实', exact: true }).click()
  await card.getByLabel('材料引用 2').fill('合成报告第 2 节')
  await card.getByLabel('核实依据 2').fill('用户自行比对交互截图')
  await card.getByRole('button', { name: '记录材料核实' }).click()
  await expect(card.getByText('材料辅助核实', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '复制经历文本' }).click()
  await expect(page.getByText('已复制确认后的经历文本。')).toBeVisible()
  const confirmed = (await apiRead(page)).facts.find((f: { id: string }) => f.id === probe().facts[1].id)
  const clipboardMatches = await page.evaluate(expected => navigator.clipboard.readText().then(text => text === expected), confirmed.statement)
  expect(clipboardMatches).toBe(true)
  expect(confirmed.source_kind).toBe('user_edit')
  expect(confirmed.source_turn_ids).toHaveLength(0)
  await page.reload()
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  await expect(page.locator('.summary-text')).toHaveText(confirmed.statement)
  await page.screenshot({ path: info.outputPath('discovery_desktop.png'), fullPage: true })
  await page.getByRole('button', { name: '停止追问', exact: true }).click()
  await page.getByRole('button', { name: '取消', exact: true }).click()
  await expect(page.getByLabel('你的回答或自由补充')).toBeVisible()
  await page.getByRole('button', { name: '停止追问', exact: true }).click()
  await page.getByRole('button', { name: '确认停止追问' }).click()
  await expect(page.getByLabel('你的回答或自由补充')).toHaveCount(0)
  await page.getByRole('button', { name: '结束会话', exact: true }).click()
  await page.getByRole('button', { name: '确认结束会话' }).click()
  await expect(page.getByRole('button', { name: '停止追问', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: '删除会话', exact: true }).click()
  await page.getByRole('button', { name: '确认永久删除' }).click()
  await expect(page.getByLabel('描述一段经历')).toBeVisible()
  expect(probe().sessions).toHaveLength(0);expect(audit().runs).toHaveLength(0);expect(audit().answers).toHaveLength(0)
})

test('lost committed mining response and refresh recover without new POST', async ({ page }) => {
  await ready(page)
  let posts = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/mining-runs')) posts++ })
  await page.route('**/mining-runs', async route => { expect((await forward(route)).status()).toBe(201); await route.abort('connectionreset') }, { times: 1 })
  await answer(page)
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  await page.reload()
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  expect(posts).toBe(1);expect(audit().answers).toHaveLength(1);expect(audit().user_turns).toBe(2)
})

test('disconnected answer refresh is read-only, then explicit same-key retry writes once', async ({ page }) => {
  await ready(page)
  const keys: string[] = []
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/mining-runs')) keys.push(request.headers()['idempotency-key']) })
  await page.route('**/mining-runs', route => route.abort('internetdisconnected'), { times: 1 })
  const original = '合成断线测试：我制作了状态筛选。'
  await answer(page, original)
  await expect(page.getByRole('heading', { name: '先核对上一条操作' })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: '我已核对，放弃未找到的操作' })).toBeEnabled()
  expect(keys).toHaveLength(1);expect(audit().answers).toHaveLength(0)
  await page.getByLabel('你的回答或自由补充').fill(original)
  await page.getByRole('button', { name: '用原回答同键重试' }).click()
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  expect(keys).toHaveLength(2);expect(keys[0] === keys[1]).toBe(true)
  expect(audit().answers).toHaveLength(1);expect(audit().user_turns).toBe(2)
  const privateContentSaved = await page.evaluate(value => Object.keys(sessionStorage).some(k => (sessionStorage.getItem(k) ?? '').includes(value)), original)
  expect(privateContentSaved).toBe(false)
})

test('fact conflict preserves draft and blocks open delete panel until successful read', async ({ page }) => {
  await ready(page)
  const card = page.getByRole('article', { name: '事实 1', exact: true })
  await card.getByRole('button', { name: '编辑陈述' }).click()
  await card.getByLabel('编辑事实 1').fill('合成未保存草稿：本人制作列表页面。')
  await page.getByRole('button', { name: '删除会话', exact: true }).click()
  await editFromAnotherClient(page)
  const routePattern = /\/api\/v1\/experience\/sessions\/[0-9a-f-]+$/
  await page.route(routePattern, route => route.request().method() === 'GET' ? route.abort('connectionreset') : route.continue())
  await card.getByRole('button', { name: '保存编辑' }).click()
  await expect(page.getByRole('button', { name: '确认永久删除' })).toBeDisabled()
  await expect(card.getByLabel('编辑事实 1')).toHaveValue('合成未保存草稿：本人制作列表页面。')
  await page.unroute(routePattern)
  await page.getByRole('button', { name: '重新读取', exact: true }).click()
  await expect(page.getByRole('button', { name: '确认永久删除' })).toBeEnabled()
  await expect(card.getByRole('button', { name: '保存编辑' })).toBeDisabled()
  await expect(card.getByLabel('编辑事实 1')).toHaveValue('合成未保存草稿：本人制作列表页面。')
})

test('mobile conversation / review / summary tabs and 200 percent zoom evidence', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await ready(page)
  await answer(page)
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  await page.getByRole('button', { name: '事实审核 (2)', exact: true }).click()
  const card = page.getByRole('article', { name: '事实 2', exact: true })
  await card.getByRole('button', { name: '确认事实', exact: true }).click()
  await expect(card.getByText('用户确认', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '整理结果', exact: true }).click()
  await expect(page.locator('.summary-text')).toContainText('合成补充')
  await page.getByRole('button', { name: '对话', exact: true }).click()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: info.outputPath('discovery_mobile.png'), fullPage: true })
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.evaluate(() => { document.body.style.zoom = '2' })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('navigation', { name: '工作台视图' })).toBeVisible()
  expect(await page.locator('.conversation-panel').evaluate(el => el.getBoundingClientRect().width > window.innerWidth * 0.6)).toBe(true)
  await page.screenshot({ path: info.outputPath('discovery_zoom.png'), fullPage: true })
})

test('question correction / skip / hide / delete preserves answer identity and sources', async ({ page }) => {
  await ready(page)
  const first = page.getByRole('article', { name: '合成追问' }).first(), second = page.getByRole('article', { name: '合成追问' }).nth(1)
  const original = (await apiRead(page)).mining_runs[0].questions
  await second.getByRole('button', { name: '跳过', exact: true }).click()
  await expect(second.getByText('已跳过', { exact: true })).toBeVisible()
  await first.getByRole('button', { name: '纠正问题' }).click()
  await first.getByLabel('纠正后的问题').fill('合成自定义问题：你亲手做了哪段交互？')
  await first.getByRole('button', { name: '保存问题纠正' }).click()
  await expect(first.getByText('已纠正', { exact: true })).toBeVisible()
  await answer(page)
  await expect(page.getByText('已关联 1 个问题')).toBeVisible()
  expect(audit().answers[0].question_id).toBe(original[0].id)
  expect(audit().answers[0].question_version).toBe(2)
  await page.getByText('已保存的历史追问 · 2 题', { exact: true }).click()
  const historical = page.locator(`[data-question-id="${original[0].id}"]`)
  await historical.getByRole('button', { name: '隐藏', exact: true }).click()
  await expect(page.getByText('合成自定义问题：你亲手做了哪段交互？', { exact: true })).toHaveCount(0)
  await historical.getByRole('button', { name: '删除问题', exact: true }).click()
  await historical.getByRole('button', { name: '确认删除问题' }).click()
  const row = audit().questions.find(q => q.id === original[0].id)!
  expect(row.state).toBe('deleted');expect(row.content).toBeNull();expect(audit().answers).toHaveLength(1)
  expect(probe().facts).toHaveLength(2)
})

test('discovery lost creation and recovery response refresh never auto-creates or mines', async ({ page }) => {
  await page.goto('/discovery')
  let creates = 0, mines = 0
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/sessions')) creates++
    if (request.method() === 'POST' && request.url().endsWith('/mining-runs')) mines++
  })
  await page.route('**/api/v1/experience/sessions', async route => { expect((await forward(route)).status()).toBe(201); await route.abort('connectionreset') }, { times: 1 })
  await page.route('**/session-creations/recovery', route => route.abort('connectionreset'), { times: 1 })
  await page.getByLabel('描述一段经历').fill('合成：创建恢复测试项目。')
  await page.getByRole('button', { name: '开始合成整理', exact: true }).click()
  await expect(page.getByRole('alert')).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: '根据已保存经历开始合成整理' })).toBeEnabled()
  expect(creates).toBe(1);expect(mines).toBe(0);expect(probe().sessions).toHaveLength(1)
  await page.getByRole('button', { name: '根据已保存经历开始合成整理' }).click()
  await expect(page.getByRole('article', { name: '合成追问' })).toHaveCount(2)
  expect(mines).toBe(1)
})


test('creation never received: refresh reads real 404, identical same-key retry creates once', async ({ page }) => {
  await page.goto('/discovery')
  const original = '合成：从未发送到服务端的课程经历。', keys: string[] = []
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/sessions')) keys.push(request.headers()['idempotency-key']) })
  await page.route('**/api/v1/experience/sessions', route => route.abort('internetdisconnected'), { times: 1 })
  await page.getByLabel('描述一段经历').fill(original)
  await page.getByRole('button', { name: '开始合成整理', exact: true }).click()
  await expect(page.getByText(/明确未找到创建结果/)).toBeVisible()
  expect(probe().sessions).toHaveLength(0)
  const recovery = page.waitForResponse(r => r.url().endsWith('/session-creations/recovery'))
  await page.reload()
  expect((await recovery).status()).toBe(404)
  await expect(page.getByText(/明确未找到创建结果/)).toBeVisible()
  expect(keys).toHaveLength(1);expect(probe().sessions).toHaveLength(0)
  await page.getByLabel('描述一段经历').fill('合成：与原文不同。')
  await page.getByRole('button', { name: '用原描述同键重试' }).click()
  await expect(page.getByText(/这次输入与先前提交不同/)).toBeVisible()
  expect(keys).toHaveLength(1);expect(probe().sessions).toHaveLength(0)
  await page.getByLabel('描述一段经历').fill(original)
  await page.getByRole('button', { name: '用原描述同键重试' }).click()
  await expect(page.getByRole('article', { name: '合成追问' })).toHaveCount(2)
  expect(keys).toHaveLength(2);expect(keys[0] === keys[1]).toBe(true)
  expect(probe().sessions).toHaveLength(1);expect(audit().user_turns).toBe(1);expect(audit().runs).toHaveLength(1)
  expect((await apiRead(page)).turns.find((t: { role: string }) => t.role === 'user').content).toBe(original)
  await page.reload()
  await expect(page.getByRole('article', { name: '合成追问' })).toHaveCount(2)
  expect(keys).toHaveLength(2)
})

for (const boundary of ['expired', 'damaged'] as const) {
  test(`creation ${boundary} storage blocks writes after refresh`, async ({ page }) => {
    await page.goto('/discovery')
    let creates = 0
    page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/sessions')) creates++ })
    await page.route('**/api/v1/experience/sessions', route => route.abort('internetdisconnected'), { times: 1 })
    await page.getByLabel('描述一段经历').fill('合成：恢复窗口边界。')
    await page.getByRole('button', { name: '开始合成整理', exact: true }).click()
    await expect(page.getByText(/明确未找到创建结果/)).toBeVisible()
    await page.evaluate(async kind => {
      const name = 'pathwise.development.pendingCreate'
      const p = JSON.parse(sessionStorage.getItem(name)!)
      if (kind === 'damaged') p.bodyTag = 'damaged'
      else {
        // Generate an actually valid expired proof, never expose secrets in output.
        const issued = Math.floor(Date.now() / 1000) - 86401, nonce = p.key.split('.')[2]
        const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(p.token), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
        const proof = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(`pathwise-idempotency-v1\ncreate_session\nglobal\n${issued}\n${nonce}`)))
        const encoded = btoa(String.fromCharCode(...proof)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')
        p.key = `v1.${issued}.${nonce}.${encoded}`;p.expiresAt = (issued + 86400) * 1000
      }
      sessionStorage.setItem(name, JSON.stringify(p))
    }, boundary)
    await page.reload()
    await expect(page.getByRole('alert')).toContainText(boundary === 'expired' ? '24 小时临时恢复窗口已结束' : '临时恢复记录异常')
    await page.getByLabel('描述一段经历').fill('合成：恢复窗口边界。')
    await expect(page.getByRole('button', { name: '开始合成整理', exact: true })).toBeDisabled()
    expect(creates).toBe(1);expect(probe().sessions).toHaveLength(0);expect(audit().runs).toHaveLength(0)
  })
}

test('uncertain creation recovery never authorizes retry, even after a previous definite 404', async ({ page }) => {
  await page.goto('/discovery')
  let creates = 0
  page.on('request', request => { if (request.method() === 'POST' && request.url().endsWith('/sessions')) creates++ })
  await page.route('**/api/v1/experience/sessions', route => route.abort('internetdisconnected'), { times: 1 })
  await page.getByLabel('描述一段经历').fill('合成：结果不确定边界。')
  await page.getByRole('button', { name: '开始合成整理', exact: true }).click()
  await expect(page.getByText(/明确未找到创建结果/)).toBeVisible()
  await page.route('**/session-creations/recovery', route => route.abort('connectionreset'))
  await page.reload()
  await expect(page.getByText(/创建结果仍不确定/)).toBeVisible()
  await page.getByLabel('描述一段经历').fill('合成：结果不确定边界。')
  await expect(page.getByRole('button', { name: '用原描述同键重试' })).toBeDisabled()
  await page.unroute('**/session-creations/recovery')
  await page.getByRole('button', { name: '只读恢复创建结果' }).click()
  await expect(page.getByRole('button', { name: '用原描述同键重试' })).toBeEnabled()
  expect(creates).toBe(1);expect(probe().sessions).toHaveLength(0)
})

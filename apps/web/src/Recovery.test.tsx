import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import fixtures from './test/api-fixtures.json'
import { createExperienceApi, SESSION_KEY } from './lib/experience'
import { newPending, PENDING_KEY, storePending } from './lib/idempotency'

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })
const raw = 'Synthetic recoverable project'
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
function setup(options: { lostCreate?: boolean; lostTurn?: boolean; lostFact?: boolean; conflict?: boolean; pendingToken?: string; exists?: boolean; deleted?: boolean; orphan?: boolean } = {}) {
  let exists = options.exists ?? false, fact = false, token = options.pendingToken ?? '', loseTurn = options.lostTurn, loseFact = options.lostFact
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input), method = init?.method ?? 'GET', headers = init?.headers as Record<string, string>
    if (path.endsWith('/recovery')) {
      if (options.deleted) return json({ error: { code: 'idempotency_resource_deleted' } }, 410)
      return exists ? json({ ...fixtures.created, access_token: token }) : json({ error: { code: 'idempotency_creation_not_found' } }, 404)
    }
    if (method === 'GET') return json(fact ? fixtures.pending : options.orphan ? { ...fixtures.empty, turns: [...fixtures.empty.turns, fixtures.turn] } : fixtures.empty)
    if (path.endsWith('/sessions')) {
      // Assert privacy through a boolean, never print pending tokens on failures.
      const saved = JSON.parse(sessionStorage.getItem(PENDING_KEY)!)
      const valid = saved.token === headers.Authorization.slice(7) && saved.key === headers['Idempotency-Key'] && !JSON.stringify(saved).includes(raw)
      expect(valid).toBe(true)
      token = saved.token; exists = true
      if (options.lostCreate) throw new TypeError('Synthetic connection lost')
      return json({ ...fixtures.created, access_token: token }, 201)
    }
    if (path.endsWith('/turns')) {
      if (loseTurn) { loseTurn = false; throw new TypeError('Synthetic lost turn response') }
      return json(fixtures.turn, 201)
    }
    if (path.endsWith('/facts')) {
      if (options.conflict) return json({ error: { code: 'idempotency_payload_mismatch' } }, 409)
      fact = true
      if (loseFact) { loseFact = false; throw new TypeError('Synthetic lost fact response') }
      return json(fixtures.pending.facts[0], 201)
    }
    throw new Error('Unexpected contract call')
  })
  const view = render(<App api={createExperienceApi(fetcher)} />)
  return { fetcher, view }
}
function writes(fetcher: ReturnType<typeof setup>['fetcher'], ending: string) { return fetcher.mock.calls.filter(([path,init]) => String(path).endsWith(ending) && init?.method === 'POST') }

describe('temporary creation recovery, stable operation keys and conflict boundaries', () => {
  it('persists before POST and recovers a lost 201 with only a read', async () => {
    const { fetcher } = setup({ lostCreate: true })
    await userEvent.type(screen.getByLabelText('原始经历'), raw)
    await userEvent.click(screen.getByRole('button', { name: '创建经历会话 →' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('创建响应未收到，已恢复')
    await screen.findByRole('heading', { name: '你的事实清单' })
    expect(writes(fetcher, '/sessions')).toHaveLength(1)
    expect(fetcher.mock.calls.filter(([path]) => String(path).endsWith('/recovery'))).toHaveLength(1)
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull()
    expect(Object.keys(JSON.parse(sessionStorage.getItem(SESSION_KEY)!)).sort()).toEqual(['sessionId', 'token'])
  })
  it('refresh with pending reads an existing receipt and never POSTs', async () => {
    const pending = await newPending(raw); storePending(pending)
    const { fetcher } = setup({ pendingToken: pending.token, exists: true })
    await screen.findByRole('heading', { name: '你的事实清单' })
    expect(writes(fetcher, '/sessions')).toHaveLength(0)
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull()
    expect(screen.getByRole('alert')).toHaveTextContent('只读查询恢复')
  })
  it('refresh missing receipt requires original input and an explicit same-key POST', async () => {
    const pending = await newPending(raw); storePending(pending)
    const { fetcher } = setup({ pendingToken: pending.token })
    await screen.findByRole('alert')
    expect(writes(fetcher, '/sessions')).toHaveLength(0)
    expect(screen.getByLabelText('原始经历')).toHaveValue('')
    await userEvent.type(screen.getByLabelText('原始经历'), 'Synthetic different input')
    await userEvent.click(screen.getByRole('button', { name: '用原输入重试创建' }))
    expect(screen.getByRole('alert')).toHaveTextContent('先前提交不同')
    expect(writes(fetcher, '/sessions')).toHaveLength(0)
    await userEvent.clear(screen.getByLabelText('原始经历')); await userEvent.type(screen.getByLabelText('原始经历'), raw)
    await userEvent.click(screen.getByRole('button', { name: '用原输入重试创建' }))
    await screen.findByRole('heading', { name: '你的事实清单' })
    const same = (writes(fetcher, '/sessions')[0][1]?.headers as Record<string,string>)['Idempotency-Key'] === pending.key
    expect(same).toBe(true)
  })
  it('storage failure or missing crypto sends no creation request', async () => {
    const context = setup()
    const write = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Synthetic unavailable storage') })
    await userEvent.type(screen.getByLabelText('原始经历'), raw)
    await userEvent.click(screen.getByRole('button', { name: '创建经历会话 →' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未发送创建请求')
    expect(context.fetcher).not.toHaveBeenCalled()
    write.mockRestore(); vi.stubGlobal('crypto', undefined)
    await userEvent.click(screen.getByRole('button', { name: '创建经历会话 →' }))
    expect(screen.getByRole('alert')).toHaveTextContent('安全随机数不可用')
    expect(context.fetcher).not.toHaveBeenCalled()
  })
  it('deleted recovery clears temporary data and cannot silently recreate', async () => {
    const p = await newPending(raw); storePending(p)
    const { fetcher } = setup({ pendingToken: p.token, deleted: true })
    expect(await screen.findByRole('alert')).toHaveTextContent('不是长期账号恢复')
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull()
    expect(screen.getByRole('button', { name: '创建经历会话 →' })).toBeDisabled()
    expect(writes(fetcher, '/sessions')).toHaveLength(0)
  })
  it.each(['lostTurn','lostFact'] as const)('manual retry reuses keys for %s', async mode => {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ sessionId: fixtures.created.session_id, token: fixtures.created.access_token }))
    const { fetcher } = setup({ [mode]: true })
    await screen.findByRole('heading', { name: '你的事实清单' })
    await userEvent.type(screen.getByLabelText('新的事实陈述'), fixtures.turn.content)
    await userEvent.click(screen.getByRole('button', { name: '新增待确认事实' }))
    await screen.findByRole('alert')
    await userEvent.click(screen.getByRole('button', { name: '新增待确认事实' }))
    await screen.findByRole('article', { name: '事实 1' })
    const retried = writes(fetcher, mode === 'lostTurn' ? '/turns' : '/facts')
    expect(retried).toHaveLength(2)
    const same = (retried[0][1]?.headers as Record<string,string>)['Idempotency-Key'] === (retried[1][1]?.headers as Record<string,string>)['Idempotency-Key']
    expect(same).toBe(true)
    if (mode === 'lostFact') expect(writes(fetcher, '/turns')).toHaveLength(1)
  })
  it('idempotency 409 preserves draft without the version-conflict auto-read', async () => {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify({ sessionId: fixtures.created.session_id, token: fixtures.created.access_token }))
    const { fetcher } = setup({ conflict: true })
    await screen.findByRole('heading', { name: '你的事实清单' })
    await userEvent.type(screen.getByLabelText('新的事实陈述'), fixtures.turn.content)
    await userEvent.click(screen.getByRole('button', { name: '新增待确认事实' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('先前提交不同')
    expect(screen.getByLabelText('新的事实陈述')).toHaveValue(fixtures.turn.content)
    expect(fetcher.mock.calls.filter(([,init]) => init?.method === 'GET')).toHaveLength(1)
  })
  it('rapid clicks generate one creation operation', async () => {
    const { fetcher } = setup()
    fireEvent.change(screen.getByLabelText('原始经历'), { target: { value: raw } })
    const button = screen.getByRole('button', { name: '创建经历会话 →' })
    fireEvent.click(button); fireEvent.click(button)
    await screen.findByRole('heading', { name: '你的事实清单' })
    expect(writes(fetcher, '/sessions')).toHaveLength(1)
  })
  it('expired pending displays the bounded recovery limit, sends no POST', async () => {
    const p = await newPending(raw); storePending(p)
    vi.spyOn(Date, 'now').mockReturnValue(p.expiresAt + 1)
    const { fetcher } = setup()
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('临时恢复窗口已结束'))
    expect(fetcher).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '创建经历会话 →' })).toBeDisabled()
    expect(sessionStorage.getItem(PENDING_KEY)).toBeNull()
  })
  it('retains pending when formal storage migration fails after real-contract success', async () => {
    const original = Storage.prototype.setItem
    vi.spyOn(Storage.prototype,'setItem').mockImplementation(function (this: Storage,key,value) {
      if (key === SESSION_KEY) throw new Error('Synthetic formal storage failure')
      original.call(this,key,value)
    })
    const { fetcher } = setup()
    await userEvent.type(screen.getByLabelText('原始经历'),raw)
    await userEvent.click(screen.getByRole('button',{name:'创建经历会话 →'}))
    await screen.findByRole('heading',{name:'你的事实清单'})
    expect(screen.getByRole('status')).toHaveTextContent('临时恢复记录保留')
    expect(sessionStorage.getItem(PENDING_KEY) !== null).toBe(true)
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull()
    expect(writes(fetcher,'/sessions')).toHaveLength(1)
  })
  it('explicit orphan selection reuses its source and rejects a different statement', async () => {
    sessionStorage.setItem(SESSION_KEY,JSON.stringify({sessionId:fixtures.created.session_id,token:fixtures.created.access_token}))
    const { fetcher }=setup({orphan:true})
    await screen.findByRole('heading',{name:'你的事实清单'})
    await userEvent.selectOptions(screen.getByLabelText('继续已有补充回合'),fixtures.turn.id)
    await userEvent.clear(screen.getByLabelText('新的事实陈述')); await userEvent.type(screen.getByLabelText('新的事实陈述'),'Synthetic unsupported change')
    await userEvent.click(screen.getByRole('button',{name:'新增待确认事实'}))
    expect(await screen.findByRole('alert')).toHaveTextContent('所选补充回合不同')
    expect(writes(fetcher,'/facts')).toHaveLength(0)
    await userEvent.clear(screen.getByLabelText('新的事实陈述')); await userEvent.type(screen.getByLabelText('新的事实陈述'),fixtures.turn.content)
    await userEvent.click(screen.getByRole('button',{name:'新增待确认事实'}))
    await screen.findByRole('article',{name:'事实 1'})
    expect(writes(fetcher,'/turns')).toHaveLength(0)
    expect(writes(fetcher,'/facts')).toHaveLength(1)
  })
})

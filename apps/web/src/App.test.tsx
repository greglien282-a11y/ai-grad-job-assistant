import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from './App'
import fixtures from './test/api-fixtures.json'
import { createExperienceApi, SESSION_KEY } from './lib/experience'

type Stage = 'empty' | 'pending' | 'confirmed' | 'edited' | 'editedConfirmed' | 'verified' | 'rejected' | 'ended'
const credentials = { sessionId: fixtures.created.session_id, token: fixtures.created.access_token }
function setup(initial: Stage | null = 'pending') {
  let state: Stage = initial ?? 'empty'
  let conflict = false
  let failAdd = false
  let failReads = false
  let readFailureStatus = 503
  if (initial) sessionStorage.setItem(SESSION_KEY, JSON.stringify(credentials))
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input)
    const method = init?.method ?? 'GET'
    const body = init?.body ? JSON.parse(String(init.body)) : null
    const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
    if (method === 'GET' && failReads) return json({ error: { code: 'database_unavailable' } }, readFailureStatus)
    if (path.endsWith('/export')) return json(fixtures.exported)
    if (method === 'GET') return json(fixtures[state])
    if (method === 'DELETE') return new Response(null, { status: 204 })
    if (path.endsWith('/sessions')) return json({ ...fixtures.created, access_token: (init?.headers as Record<string, string>).Authorization.slice(7) }, 201)
    if (path.endsWith('/turns')) return json(fixtures.turn, 201)
    if (path.endsWith('/end')) { state = 'ended'; return json(fixtures.ended) }
    if (method === 'POST') {
      if (failAdd) { failAdd = false; return json({ error: { code: 'database_unavailable' } }, 503) }
      state = 'pending'; return json(fixtures.pending.facts[0], 201)
    }
    if (conflict) { conflict = false; state = 'edited'; return json({ error: { code: 'version_conflict' } }, 409) }
    state = body.action === 'edit' ? 'edited' : body.action === 'verify_material' ? 'verified'
      : body.action === 'reject' ? 'rejected' : state === 'edited' ? 'editedConfirmed' : 'confirmed'
    return json(fixtures[state].facts[0])
  })
  const download = vi.fn()
  const api = createExperienceApi(fetcher as typeof fetch)
  const view = render(<App api={api} download={download} />)
  return { fetcher, download, api, view, setConflict: () => { conflict = true }, failNextAdd: () => { failAdd = true },
    failReads: (status = 503) => { failReads = true; readFailureStatus = status }, recoverReads: () => { failReads = false } }
}
const factCard = () => screen.getByRole('article', { name: '事实 1' })
const patchCalls = (fetcher: ReturnType<typeof setup>['fetcher']) => fetcher.mock.calls.filter(([, init]) => init?.method === 'PATCH')

describe('experience workspace with recorded FastAPI contracts', () => {
  it('creates a real-contract session and stores only ID and credential', async () => {
    const { fetcher } = setup(null)
    await userEvent.type(screen.getByLabelText('原始经历'), fixtures.empty.projects[0].raw_input)
    await userEvent.click(screen.getByRole('button', { name: /创建经历会话/ }))
    await screen.findByRole('heading', { name: '你的事实清单' })
    const createdCredential = { sessionId: credentials.sessionId, token: (fetcher.mock.calls[0][1]?.headers as Record<string, string>).Authorization.slice(7) }
    expect(JSON.parse(sessionStorage.getItem(SESSION_KEY)!)).toEqual(createdCredential)
    expect(sessionStorage.length).toBe(1)
    expect(localStorage.length).toBe(0)
    expect(fetcher.mock.calls[0][1]?.body).toBe(JSON.stringify({ raw_input: fixtures.empty.projects[0].raw_input }))
    const read = fetcher.mock.calls.find(([, init]) => init?.method === 'GET')!
    expect(read[0]).not.toContain(createdCredential.token)
    expect(read[1]?.headers).toMatchObject({ Authorization: `Bearer ${createdCredential.token}` })
  })

  it('adds a user source turn first and reuses it if fact creation fails', async () => {
    const context = setup('empty')
    await screen.findByRole('heading', { name: '你的事实清单' })
    context.failNextAdd()
    await userEvent.type(screen.getByLabelText('新的事实陈述'), fixtures.turn.content)
    await userEvent.click(screen.getByRole('button', { name: '新增待确认事实' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('新的事实陈述')).toHaveValue(fixtures.turn.content)
    await userEvent.click(screen.getByRole('button', { name: '新增待确认事实' }))
    await screen.findByRole('article', { name: '事实 1' })
    expect(context.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/turns'))).toHaveLength(1)
    const added = context.fetcher.mock.calls.filter(([path, init]) => String(path).endsWith('/facts') && init?.method === 'POST')
    expect(added).toHaveLength(2)
    expect(JSON.parse(String(added[1][1]?.body))).toEqual({ statement: fixtures.turn.content, source_turn_ids: [fixtures.turn.id] })
    expect(screen.getByLabelText('新的事实陈述')).toHaveValue('')
  })

  it('requires separate confirmation after editing and traces the new source', async () => {
    const { fetcher } = setup('confirmed')
    await screen.findByRole('article', { name: '事实 1' })
    await userEvent.click(within(factCard()).getByRole('button', { name: '编辑陈述' }))
    const edit = screen.getByLabelText('编辑事实 1')
    await userEvent.clear(edit); await userEvent.type(edit, fixtures.edited.facts[0].statement)
    expect(within(factCard()).getByRole('button', { name: '确认事实' })).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: '保存编辑' }))
    await waitFor(() => expect(screen.queryByLabelText('编辑事实 1')).not.toBeInTheDocument())
    expect(within(factCard()).getByText('待确认')).toBeInTheDocument()
    expect(patchCalls(fetcher)).toHaveLength(1)
    expect(JSON.parse(String(patchCalls(fetcher)[0][1]?.body))).toEqual({ action: 'edit', expected_version: 2, statement: fixtures.edited.facts[0].statement })
    await userEvent.click(within(factCard()).getByRole('button', { name: '确认事实' }))
    await waitFor(() => expect(within(factCard()).getByText('用户确认')).toBeInTheDocument())
    expect(JSON.parse(String(patchCalls(fetcher)[1][1]?.body))).toEqual({ action: 'confirm', expected_version: 3 })
    await userEvent.click(within(factCard()).getByText(/查看来源与历史/))
    expect(within(factCard()).getByText('当前陈述来源：用户后续编辑')).toBeInTheDocument()
    expect(within(factCard()).getByText('原始自述（历史起点）')).toBeInTheDocument()
    expect(within(factCard()).getAllByText(fixtures.turn.content).length).toBeGreaterThan(0)
  })

  it('refreshes a 409 without overwriting drafts or automatically replaying edits', async () => {
    const context = setup('confirmed')
    await screen.findByRole('article', { name: '事实 1' })
    await userEvent.click(within(factCard()).getByRole('button', { name: '编辑陈述' }))
    await userEvent.clear(screen.getByLabelText('编辑事实 1'))
    await userEvent.type(screen.getByLabelText('编辑事实 1'), 'My unsubmitted draft')
    context.setConflict()
    await userEvent.click(screen.getByRole('button', { name: '保存编辑' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('发生冲突，已读取最新资料')
    expect(screen.getByLabelText('编辑事实 1')).toHaveValue('My unsubmitted draft')
    expect(within(factCard()).getByRole('heading')).toHaveTextContent(fixtures.edited.facts[0].statement)
    expect(screen.getByRole('button', { name: '保存编辑' })).toBeDisabled()
    expect(patchCalls(context.fetcher)).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: '我已复核最新版本' }))
    expect(screen.getByRole('button', { name: '保存编辑' })).toBeEnabled()
    expect(patchCalls(context.fetcher)).toHaveLength(1)
  })

  it('records user-reviewed materials, allows rejection and exports a credential-free document', async () => {
    const context = setup('editedConfirmed')
    await screen.findByRole('article', { name: '事实 1' })
    await userEvent.click(within(factCard()).getByRole('button', { name: '材料核实' }))
    await userEvent.type(screen.getByLabelText('材料引用 1'), 'Synthetic report section 2')
    await userEvent.type(screen.getByLabelText('核实依据 1'), 'User compared script with report.')
    await userEvent.click(screen.getByRole('button', { name: '记录材料核实' }))
    await waitFor(() => expect(within(factCard()).getByText('材料辅助核实')).toBeInTheDocument())
    expect(JSON.parse(String(patchCalls(context.fetcher)[0][1]?.body))).toEqual({ action: 'verify_material', expected_version: 4, material_reference: 'Synthetic report section 2', basis: 'User compared script with report.' })
    await userEvent.click(within(factCard()).getByRole('button', { name: '拒绝事实' }))
    await waitFor(() => expect(within(factCard()).getByText('已拒绝')).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: '导出资料' }))
    await waitFor(() => expect(context.download).toHaveBeenCalledOnce())
    expect(JSON.stringify(context.download.mock.calls[0])).not.toContain(credentials.token)
  })

  it('blocks writes after a conflict refresh fails until latest data is explicitly retrieved', async () => {
    const context = setup('confirmed')
    await screen.findByRole('article', { name: '事实 1' })
    await userEvent.click(within(factCard()).getByRole('button', { name: '编辑陈述' }))
    fireEvent.change(screen.getByLabelText('编辑事实 1'), { target: { value: 'Preserved conflict draft' } })
    context.setConflict(); context.failReads()
    await userEvent.click(screen.getByRole('button', { name: '保存编辑' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('最新资料读取失败')
    expect(screen.getByRole('button', { name: '保存编辑' })).toBeDisabled()
    expect(screen.getByLabelText('编辑事实 1')).toHaveValue('Preserved conflict draft')
    context.recoverReads()
    await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await screen.findByRole('button', { name: '我已复核最新版本' })
    expect(screen.getByRole('button', { name: '保存编辑' })).toBeDisabled()
    expect(patchCalls(context.fetcher)).toHaveLength(1)
  })

  it.each([401, 404])('removes stale displayed data on inaccessible sessions (%s) and disables open management panels', async status => {
    const context = setup('pending')
    await screen.findByRole('article', { name: '事实 1' })
    await userEvent.click(screen.getByRole('button', { name: '删除会话' }))
    context.failReads(status)
    await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await screen.findByRole('button', { name: '清除本页凭证' })
    expect(screen.getByRole('button', { name: '确认永久删除' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '结束会话' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '删除会话' })).toBeDisabled()
    expect(screen.queryByRole('article', { name: '事实 1' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '清除本页凭证' }))
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull()
    expect(context.fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(0)
  })

  it.each(['end', 'delete'] as const)('blocks %s even in an open confirmation panel until conflict recovery succeeds', async operation => {
    const context = setup('confirmed')
    await screen.findByRole('article', { name: '事实 1' })
    const openLabel = operation === 'end' ? '结束会话' : '删除会话'
    const confirmLabel = operation === 'end' ? '确认结束会话' : '确认永久删除'
    await userEvent.click(screen.getByRole('button', { name: openLabel }))
    await userEvent.click(within(factCard()).getByRole('button', { name: '编辑陈述' }))
    fireEvent.change(screen.getByLabelText('编辑事实 1'), { target: { value: 'Preserved draft during management confirmation' } })
    context.setConflict(); context.failReads()
    await userEvent.click(screen.getByRole('button', { name: '保存编辑' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('最新资料读取失败')
    expect(screen.getByRole('button', { name: '结束会话' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '删除会话' })).toBeDisabled()
    expect(screen.getByRole('button', { name: confirmLabel })).toBeDisabled()
    expect(screen.getByRole('button', { name: '重新读取' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '导出资料' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: confirmLabel }))
    const managementCalls = () => context.fetcher.mock.calls.filter(([path, init]) => String(path).endsWith('/end') || init?.method === 'DELETE')
    expect(managementCalls()).toHaveLength(0)
    context.recoverReads()
    await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await waitFor(() => expect(screen.getByRole('button', { name: confirmLabel })).toBeEnabled())
    expect(managementCalls()).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: confirmLabel }))
    if (operation === 'end') await screen.findByText('已结束 · 只读')
    else await screen.findByRole('button', { name: /创建经历会话/ })
    expect(managementCalls()).toHaveLength(1)
  })

  it('disables irreversible operations while session state has not loaded', async () => {
    setup('pending')
    expect(screen.getByRole('button', { name: '结束会话' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '删除会话' })).toBeDisabled()
    await screen.findByRole('article', { name: '事实 1' })
  })

  it('does not overwrite an unsaved draft when the edit button is clicked again', async () => {
    setup('confirmed')
    await screen.findByRole('article', { name: '事实 1' })
    const editButton = within(factCard()).getByRole('button', { name: '编辑陈述' })
    await userEvent.click(editButton)
    fireEvent.change(screen.getByLabelText('编辑事实 1'), { target: { value: 'Unsaved user correction' } })
    expect(editButton).toBeDisabled()
    await userEvent.click(editButton)
    expect(screen.getByLabelText('编辑事实 1')).toHaveValue('Unsaved user correction')
  })

  it('restores via GET after remount, ends read-only, and deletes only after confirmation', async () => {
    const context = setup('pending')
    await screen.findByRole('article', { name: '事实 1' })
    context.view.unmount()
    render(<App api={context.api} download={context.download} />)
    await screen.findByRole('article', { name: '事实 1' })
    expect(context.fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '结束会话' }))
    expect(context.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/end'))).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '取消结束' }))
    expect(context.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/end'))).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '结束会话' }))
    expect(screen.getByRole('region', { name: '结束确认' })).toHaveTextContent('无法重新开启')
    await userEvent.click(screen.getByRole('button', { name: '确认结束会话' }))
    await screen.findByText('已结束 · 只读')
    expect(context.fetcher.mock.calls.filter(([path]) => String(path).endsWith('/end'))).toHaveLength(1)
    expect(screen.getByRole('button', { name: '新增待确认事实' })).toBeDisabled()
    expect(within(factCard()).getByRole('button', { name: '编辑陈述' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '导出资料' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '删除会话' }))
    expect(context.fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '取消删除' }))
    await userEvent.click(screen.getByRole('button', { name: '删除会话' }))
    await userEvent.click(screen.getByRole('button', { name: '确认永久删除' }))
    await screen.findByRole('button', { name: /创建经历会话/ })
    expect(sessionStorage.getItem(SESSION_KEY)).toBeNull()
  })

  it('preserves inputs and reports recovery failures without creating a replacement session', async () => {
    const context = setup('pending')
    await screen.findByRole('article', { name: '事实 1' })
    context.failReads()
    fireEvent.change(screen.getByLabelText('新的事实陈述'), { target: { value: 'Unsaved input' } })
    await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await screen.findByRole('alert')
    expect(screen.getByLabelText('新的事实陈述')).toHaveValue('Unsaved input')
    expect(context.fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })
})

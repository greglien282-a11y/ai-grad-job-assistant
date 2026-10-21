import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import fixtures from '../../test/mining-fixtures.json'
import { ApiError, createExperienceApi, isContractUpgrade, SESSION_KEY } from '../../lib/experience'
import { newPending, PENDING_KEY, storePending } from '../../lib/idempotency'
import { MINING_KEY, newMining, storeMining } from '../../lib/pending-mining'
import DiscoveryWorkbench from './DiscoveryWorkbench'
import { useDiscovery } from './useDiscovery'

const c = { sessionId: fixtures.created.session_id, token: fixtures.created.access_token }
const pid = fixtures.created.project_id
const response = (code: string, status = 409) => Response.json({ error: { code, message: 'PRIVATE SERVER DETAIL' } }, { status })
function setup() {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(c))
  let fault = '', target = 'session', status = 409, offline = false
  const fetcher = vi.fn<typeof fetch>(async (input, options) => {
    const path = String(input)
    if (offline) throw new Error('PRIVATE NETWORK DIAGNOSTIC')
    if (fault && (target === 'session' ? path.endsWith('/sessions/' + c.sessionId) : target === 'summary' ? path.endsWith('/experience-summary') : path.endsWith('/export'))) return response(fault, status)
    if (path.endsWith('/experience-summary')) return Response.json(fixtures.confirmedSummary)
    if (path.endsWith('/mining-runs/recovery')) return Response.json(fixtures.answerRun)
    if (options?.method === 'PATCH') return Response.json(fixtures.confirmed.facts[1])
    return Response.json(fixtures.confirmed)
  })
  return { api: createExperienceApi(fetcher), fetcher,
    fail: (code: string, where = 'session', http = 409) => { fault = code; target = where; status = http },
    offline: () => { offline = true }, online: () => { fault = ''; offline = false } }
}

it.each(['fact_contract_upgrade_required', 'summary_contract_upgrade_required', 'export_contract_upgrade_required'])('recognizes only the authenticated fixed 409 %s', async code => {
  expect(isContractUpgrade(new ApiError(409, code))).toBe(true)
  for (const status of [401, 404, 503]) expect(isContractUpgrade(new ApiError(status, code))).toBe(false)
  expect(isContractUpgrade(new ApiError(409, code + '_future'))).toBe(false)
  const x = setup(); x.fail(code)
  await expect(x.api.read(c)).rejects.toMatchObject({ code })
  for (const method of ['GET', 'POST', 'PATCH', 'DELETE']) await expect(x.api.request('/sessions/' + c.sessionId, null, c, method)).rejects.toMatchObject({ code })
  expect(x.fetcher).toHaveBeenCalledTimes(1)
})

it.each([
  ['workspace', 'session', 'fact_contract_upgrade_required'], ['summary', 'session', 'fact_contract_upgrade_required'],
  ['workspace', 'summary', 'summary_contract_upgrade_required'], ['summary', 'summary', 'summary_contract_upgrade_required'],
  ['workspace', 'export', 'export_contract_upgrade_required'],
] as const)('clears every previous v1 surface at %s / %s refusal', async (view, target, code) => {
  const x = setup(), copy = vi.fn(async () => {})
  const rendered = render(<DiscoveryWorkbench api={x.api} view={view} copy={copy} />)
  await waitFor(() => expect(screen.getByRole('button', { name: view === 'summary' ? '复制经历文本' : '重新读取' })).toBeEnabled())
  if (view === 'summary') expect(screen.getByRole('article', { name: '已确认经历正文' })).toHaveTextContent(fixtures.confirmedSummary.text)
  else expect(screen.getByRole('heading', { name: '1 条已确认，可以阅读了' })).toBeVisible()
  x.fail(code, target)
  if (target === 'export') {
    fireEvent.click(screen.getByText('技术备份（JSON，非正式简历）'))
    fireEvent.click(screen.getByRole('button', { name: '下载 JSON 技术备份' }))
  } else if (view === 'summary') {
    rendered.rerender(<DiscoveryWorkbench api={x.api} view="workspace" copy={copy} />)
    rendered.rerender(<DiscoveryWorkbench api={x.api} view="summary" copy={copy} />)
  } else fireEvent.click(screen.getByRole('button', { name: '重新读取' }))
  await screen.findByRole('heading', { name: '当前会话需要新版读取' })
  expect(document.querySelector('[data-contract-state="upgrade_required"]')).not.toBeNull()
  expect(screen.getByRole('alert')).toHaveTextContent('本次读取没有修改资料')
  expect(screen.queryByText(fixtures.confirmedSummary.text)).not.toBeInTheDocument()
  expect(screen.queryByRole('article', { name: '已确认经历正文' })).not.toBeInTheDocument()
  expect(screen.queryAllByRole('button')).toHaveLength(0)
  expect(screen.getByRole('link', { name: '由我进入新版只读页面' })).toHaveAttribute('href', '/typed-read')
  expect(x.fetcher.mock.calls.every(([path]) => !String(path).includes('/api/v2/'))).toBe(true)
  expect(copy).not.toHaveBeenCalled()
})

it('keeps creation and mining records and rejects stale hook callbacks after upgrade', async () => {
  const x = setup(), p = await newPending('Synthetic pending creation')
  storePending(p)
  storeMining(await newMining(c, { project_id: pid, base_revision: fixtures.confirmed.context_revision, content: 'Synthetic retained answer', input_turn_id: null, retry_of: null, confirm_retry: false }))
  const saved = { create: sessionStorage.getItem(PENDING_KEY), mining: sessionStorage.getItem(MINING_KEY), session: sessionStorage.getItem(SESSION_KEY) }
  x.fail('fact_contract_upgrade_required')
  const { result } = renderHook(() => useDiscovery(x.api))
  await waitFor(() => expect(result.current.contractState).toBe('upgrade_required'))
  const d = result.current, count = x.fetcher.mock.calls.length
  for (const work of [d.create, d.refresh, d.startInitial, d.submitAnswer, () => d.retrySaved(fixtures.answerRun as Parameters<typeof d.retrySaved>[0]),
    () => d.mutate(fixtures.confirmed.facts[0] as Parameters<typeof d.mutate>[0], { action: 'confirm', expected_version: 1 }),
    () => d.question(fixtures.initialRun.questions[0] as Parameters<typeof d.question>[0], 'skip'), () => d.manage('stop'), () => d.manage('end'), () => d.manage('delete')]) {
    await act(async () => { await expect(work()).rejects.toBeInstanceOf(ApiError) })
  }
  act(() => d.abandon())
  await act(async () => { expect(await d.act(async () => { throw new Error('Work must not run') })).toBe(false) })
  expect(x.fetcher).toHaveBeenCalledTimes(count)
  expect({ create: sessionStorage.getItem(PENDING_KEY), mining: sessionStorage.getItem(MINING_KEY), session: sessionStorage.getItem(SESSION_KEY) }).toEqual(saved)
  expect(d.session).toBeNull(); expect(d.summary).toBeNull()
})

it('preserves a recovered creation key when SessionView then requires upgrade', async () => {
  const p = await newPending('Synthetic recovered creation'); storePending(p)
  const before = sessionStorage.getItem(PENDING_KEY)
  const fetcher = vi.fn<typeof fetch>(async input => String(input).endsWith('/session-creations/recovery')
    ? Response.json({ ...fixtures.created, access_token: p.token }) : response('fact_contract_upgrade_required'))
  render(<DiscoveryWorkbench api={createExperienceApi(fetcher)} />)
  await screen.findByRole('heading', { name: '当前会话需要新版读取' })
  expect(sessionStorage.getItem(PENDING_KEY)).toBe(before)
  expect(fetcher.mock.calls).toHaveLength(2)
  expect(fetcher.mock.calls.every(([, options]) => options?.method === 'GET')).toBe(true)
})

it('does not mask an upgrade in GET recovery with the original POST network failure', async () => {
  const x = setup(); let posted = false
  const fetcher = vi.fn<typeof fetch>(async (input, options) => {
    const path = String(input)
    if (options?.method === 'POST') { posted = true; throw new Error('Synthetic lost POST response') }
    if (path.endsWith('/mining-runs/recovery')) return Response.json(fixtures.initialRun)
    if (posted) return response('fact_contract_upgrade_required')
    return path.endsWith('/experience-summary') ? Response.json(fixtures.initialSummary) : Response.json(fixtures.initial)
  })
  const { result } = renderHook(() => useDiscovery(createExperienceApi(fetcher)))
  await waitFor(() => expect(result.current.session).not.toBeNull())
  await act(async () => { await result.current.act(result.current.startInitial) })
  expect(result.current.contractState).toBe('upgrade_required')
  expect(sessionStorage.getItem(MINING_KEY)).not.toBeNull()
  expect(fetcher.mock.calls.filter(([, o]) => o?.method === 'POST')).toHaveLength(1)
  expect(fetcher.mock.calls.filter(([p]) => String(p).endsWith('/mining-runs/recovery'))).toHaveLength(1)
  expect(x.fetcher).not.toHaveBeenCalled()
})

it('rejects a late successful old response after another request established upgrade', async () => {
  let finish!: (r: Response) => void
  const fetcher = vi.fn<typeof fetch>().mockImplementationOnce(() => new Promise(r => { finish = r })).mockResolvedValueOnce(response('export_contract_upgrade_required'))
  const api = createExperienceApi(fetcher), pending = api.read(c)
  await expect(api.export(c)).rejects.toMatchObject({ code: 'export_contract_upgrade_required' })
  finish(Response.json(fixtures.confirmed))
  await expect(pending).rejects.toMatchObject({ code: 'export_contract_upgrade_required' })
})

it.each([[401, 'credential_required'], [404, 'resource_unavailable'], [409, 'context_conflict'], [503, 'fact_classification_schema_unavailable'], [503, 'fact_contract_upgrade_required'], [409, 'unknown_contract_code']] as const)('keeps ordinary %i / %s distinct and fail-closed', async (status, code) => {
  const x = setup(); x.fail(code, 'session', status)
  render(<DiscoveryWorkbench api={x.api} view="summary" />)
  await screen.findByRole('alert')
  expect(screen.queryByRole('heading', { name: '当前会话需要新版读取' })).not.toBeInTheDocument()
  expect(screen.queryByRole('article', { name: '已确认经历正文' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: '复制经历文本' })).not.toBeInTheDocument()
  expect(x.fetcher.mock.calls.every(([, o]) => o?.method === 'GET')).toBe(true)
})

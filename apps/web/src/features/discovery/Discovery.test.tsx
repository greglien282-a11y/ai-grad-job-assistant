import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import fixtures from '../../test/mining-fixtures.json'
import { createExperienceApi, SESSION_KEY } from '../../lib/experience'
import { newPending, PENDING_KEY, storePending } from '../../lib/idempotency'
import { MINING_KEY } from '../../lib/pending-mining'
import DiscoveryWorkbench from './DiscoveryWorkbench'

type Stage = 'empty' | 'initial' | 'answered' | 'confirmed'
function setup(initial: Stage | null = 'initial', viewMode: 'workspace' | 'summary' = 'workspace') {
  let stage: Stage = initial ?? 'empty', failReads = false, disabled = false, lost = false, missing = false, conflict = false, creationMissing = false, creationUnknown = false, staleSummary = false
  if (initial) sessionStorage.setItem(SESSION_KEY, JSON.stringify({ sessionId: fixtures.created.session_id, token: fixtures.created.access_token }))
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input), method = init?.method ?? 'GET'
    const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
    if (method === 'GET' && failReads) throw new Error('Synthetic offline')
    if (path.endsWith('/experience-summary')) {
      const result = structuredClone(fixtures[`${stage}Summary`])
      if (staleSummary && result.confirmed.length) result.confirmed[0].version++
      return json(result)
    }
    if (path.endsWith('/mining-runs/recovery')) return missing ? json({ error: { code: 'mining_operation_not_found' } }, 404) : json(stage === 'initial' ? fixtures.initialRun : fixtures.answerRun)
    if (path.endsWith('/session-creations/recovery')) return json({ error: { code: creationUnknown ? 'resource_unavailable' : 'idempotency_creation_not_found' } }, 404)
    if (method === 'GET') return json(fixtures[stage])
    if (path.endsWith('/sessions') && creationMissing) throw new Error('Synthetic creation never received')
    if (path.endsWith('/sessions')) return json({ ...fixtures.created, access_token: (init?.headers as Record<string, string>).Authorization.slice(7) }, 201)
    if (path.endsWith('/mining-runs')) {
      if (disabled) return json({ error: { code: 'ai_disabled' } }, 503)
      if (missing) throw new Error('Synthetic request not received')
      // Real-contract response only; assertions verify durable keys preceded POST.
      expect(Boolean(sessionStorage.getItem(MINING_KEY))).toBe(true)
      stage = stage === 'empty' ? 'initial' : 'answered'
      if (lost) { lost = false; throw new Error('Synthetic response lost after commit') }
      return json(stage === 'initial' ? fixtures.initialRun : fixtures.answerRun, 201)
    }
    if (method === 'PATCH') {
      if (conflict) { failReads = true; return json({ error: { code: 'version_conflict' } }, 409) }
      stage = 'confirmed'; return json(fixtures.confirmed.facts[1])
    }
    return json(fixtures[stage])
  })
  const api = createExperienceApi(fetcher as typeof fetch), copy = vi.fn(async () => {})
  const view = render(<DiscoveryWorkbench api={api} copy={copy} view={viewMode} />)
  return { fetcher, api, copy, view, stale: () => { staleSummary = true }, creationMissing: () => { creationMissing = true }, creationUnknown: () => { creationUnknown = true }, creationOnline: () => { creationMissing = false; creationUnknown = false }, loseResponse: () => { lost = true }, missing: () => { missing = true }, enable: () => { missing = false }, disable: () => { disabled = true }, offline: () => { failReads = true }, online: () => { failReads = false; conflict = false }, conflict: () => { conflict = true } }
}
const posts = (fetcher: ReturnType<typeof setup>['fetcher']) => fetcher.mock.calls.filter(([, init]) => init?.method === 'POST')
const waitReady = () => waitFor(() => expect(screen.getByRole('button', { name: '重新读取' })).not.toBeDisabled())

describe('scripted conversation with recorded FastAPI contracts', () => {
  it('creates then mines the initial user turn, and labels synthetic mode', async () => {
    const { fetcher } = setup(null)
    await userEvent.type(screen.getByLabelText('描述一段经历'), 'Synthetic project: I built the filter UI.')
    await userEvent.click(screen.getByRole('button', { name: '开始合成整理' }))
    await screen.findByRole('heading', { name: '一起回忆你的经历' })
    await waitFor(() => expect(posts(fetcher)).toHaveLength(2))
    const body = JSON.parse(String(posts(fetcher)[1][1]?.body))
    expect(body.input_turn_id).toBe(fixtures.created.initial_turn_id)
    expect(body.content).toBeNull()
    expect(screen.getByText(/真实 AI 尚未启用/)).toBeInTheDocument()
    const stored = JSON.stringify(Object.keys(sessionStorage).map(key => sessionStorage.getItem(key)))
    expect(stored.includes('Synthetic project:')).toBe(false)
  })
  it('refresh creation 404 permits only explicit identical same-key retry', async () => {
    const original = 'Synthetic unsubmitted creation.'
    const x = setup(null);x.creationMissing()
    fireEvent.change(screen.getByLabelText('描述一段经历'), { target: { value: original } })
    await userEvent.click(screen.getByRole('button', { name: '开始合成整理' }))
    await screen.findByText(/明确未找到创建结果/)
    const key = JSON.parse(sessionStorage.getItem(PENDING_KEY)!).key
    x.view.unmount();const restored = render(<DiscoveryWorkbench api={x.api} />)
    await screen.findByText(/明确未找到创建结果/)
    expect(posts(x.fetcher)).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('描述一段经历'), { target: { value: 'Different original' } })
    await userEvent.click(screen.getByRole('button', { name: '用原描述同键重试' }))
    await screen.findByText(/这次输入与先前提交不同/)
    expect(posts(x.fetcher)).toHaveLength(1)
    fireEvent.change(screen.getByLabelText('描述一段经历'), { target: { value: original } })
    x.creationUnknown();await userEvent.click(screen.getByRole('button', { name: '只读恢复创建结果' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '用原描述同键重试' })).toBeDisabled())
    expect(posts(x.fetcher)).toHaveLength(1)
    x.creationOnline();await userEvent.click(screen.getByRole('button', { name: '只读恢复创建结果' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '用原描述同键重试' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '用原描述同键重试' }))
    await screen.findByRole('heading', { name: '一起回忆你的经历' })
    expect(posts(x.fetcher)[1][1]?.headers).toMatchObject({ 'Idempotency-Key': key })
    restored.unmount()
  })
  it.each(['expired', 'damaged'] as const)('blocks %s creation storage without any POST', async kind => {
    const p = await newPending('Synthetic pending creation.')
    if (kind === 'expired') {
      const issued = Math.floor(Date.now() / 1000) - 86401
      p.key = p.key.replace(p.key.split('.')[1], String(issued));p.expiresAt = (issued + 86400) * 1000
      storePending(p)
    } else sessionStorage.setItem(PENDING_KEY, JSON.stringify({ ...p, bodyTag: 'damaged' }))
    const x = setup(null)
    await screen.findByRole('alert')
    fireEvent.change(screen.getByLabelText('描述一段经历'), { target: { value: 'Synthetic pending creation.' } })
    expect(screen.getByRole('button', { name: '开始合成整理' })).toBeDisabled()
    expect(posts(x.fetcher)).toHaveLength(0)
  })
  it('independent summary allows an empty result and guides back without management controls', async () => {
    const x = setup('initial', 'summary')
    await screen.findByRole('heading', { name: '先确认一件你做过的事' })
    expect(screen.getByRole('link', { name: '返回继续完善' })).toHaveAttribute('href', '/discovery')
    expect(screen.getByRole('button', { name: '复制经历文本' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: '确认事实' })).not.toBeInTheDocument()
    expect(posts(x.fetcher)).toHaveLength(0)
  })
  it('shows only current confirmed text and distinct original provenance', async () => {
    setup('confirmed', 'summary')
    const document = await screen.findByRole('article', { name: '已确认经历正文' })
    expect(within(document).getByText(fixtures.confirmedSummary.text)).toBeInTheDocument()
    expect(document).not.toHaveTextContent(fixtures.confirmed.facts[0].statement)
    await userEvent.click(screen.getByText('查看事实依据'))
    expect(within(screen.getByRole('region', { name: '整理依据 1' })).getByText('用户原始自述', { exact: true })).toBeInTheDocument()
  })
  it('summary read failure hides previous text and disables copying until successful GET', async () => {
    const x = setup('confirmed', 'summary')
    await screen.findByRole('article', { name: '已确认经历正文' })
    x.offline()
    x.view.rerender(<DiscoveryWorkbench api={x.api} copy={x.copy} view="workspace" />)
    x.view.rerender(<DiscoveryWorkbench api={x.api} copy={x.copy} view="summary" />)
    await screen.findByRole('heading', { name: '先恢复并核对资料' })
    expect(screen.queryByRole('article', { name: '已确认经历正文' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '复制经历文本' })).not.toBeInTheDocument()
    x.online();await userEvent.click(screen.getByRole('button', { name: '重新读取成果' }))
    await screen.findByRole('article', { name: '已确认经历正文' })
    expect(posts(x.fetcher)).toHaveLength(0)
  })
  it('rejects an older/different summary fact version even at the same revision', async () => {
    const x = setup('confirmed');await waitReady();x.stale()
    x.view.rerender(<DiscoveryWorkbench api={x.api} view="summary" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('整理稿与当前事实版本不一致，请重新读取后核对。')
    expect(screen.queryByRole('article', { name: '已确认经历正文' })).not.toBeInTheDocument()
    expect(posts(x.fetcher)).toHaveLength(0)
  })
  it('moving to the result and back preserves unsaved answer and fact drafts', async () => {
    const x = setup();await waitReady()
    fireEvent.change(screen.getByLabelText('你的回答或自由补充'), { target: { value: 'Synthetic unsaved answer' } })
    await userEvent.click(screen.getByRole('button', { name: '编辑陈述' }))
    fireEvent.change(screen.getByLabelText('编辑事实 1'), { target: { value: 'Synthetic unsaved edit' } })
    x.view.rerender(<DiscoveryWorkbench api={x.api} view="summary" />)
    await screen.findByRole('heading', { name: '先确认一件你做过的事' })
    x.view.rerender(<DiscoveryWorkbench api={x.api} view="workspace" />)
    expect(screen.getByLabelText('你的回答或自由补充')).toHaveValue('Synthetic unsaved answer')
    expect(screen.getByLabelText('编辑事实 1')).toHaveValue('Synthetic unsaved edit')
    expect(posts(x.fetcher)).toHaveLength(0)
  })
  it('binds only the selected question, leaving unselected questions unbound', async () => {
    const { fetcher } = setup()
    await waitReady()
    await userEvent.click(screen.getAllByRole('checkbox')[0])
    await userEvent.type(screen.getByLabelText('你的回答或自由补充'), 'Synthetic answer: I built the filter UI.')
    await userEvent.click(screen.getByRole('button', { name: '保存回答并合成整理' }))
    await screen.findByText('已关联 1 个问题')
    const payload = JSON.parse(String(posts(fetcher)[0][1]?.body))
    expect(payload.answered_question_ids).toEqual([fixtures.initialRun.questions[0].id])
  })
  it('free supplementary input does not fabricate an answered-question relation', async () => {
    const { fetcher } = setup()
    await waitReady()
    fireEvent.change(screen.getByLabelText('你的回答或自由补充'), { target: { value: 'Synthetic free detail.' } })
    await userEvent.click(screen.getByRole('button', { name: '保存回答并合成整理' }))
    await waitFor(() => expect(posts(fetcher)).toHaveLength(1))
    expect(JSON.parse(String(posts(fetcher)[0][1]?.body)).answered_question_ids).toBeUndefined()
  })
  it('restores question identity and copies only the confirmed summary', async () => {
    const { copy } = setup('confirmed', 'summary')
    await screen.findByRole('article', { name: '已确认经历正文' })
    expect(screen.getByText('已关联 1 个问题')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '复制经历文本' }))
    expect(copy).toHaveBeenCalledWith(fixtures.confirmedSummary.text)
    expect(screen.getByText('技术备份（JSON，非正式简历）')).toBeInTheDocument()
  })
  it('clipboard denial explains manual copying without claiming success', async () => {
    const x = setup('confirmed', 'summary');await screen.findByRole('article', { name: '已确认经历正文' })
    x.copy.mockRejectedValueOnce(new DOMException('Denied', 'NotAllowedError'))
    await userEvent.click(screen.getByRole('button', { name: '复制经历文本' }))
    await screen.findByText('剪贴板不可用，请选中上方文字手动复制。')
    expect(screen.queryByText('已复制确认后的经历文本。')).not.toBeInTheDocument()
  })
  it('lost committed response invokes only a GET recovery, not a second POST', async () => {
    const { fetcher, loseResponse } = setup()
    await waitReady();loseResponse()
    fireEvent.change(screen.getByLabelText('你的回答或自由补充'), { target: { value: 'Synthetic answer: I built the filter UI.' } })
    await userEvent.click(screen.getByRole('button', { name: '保存回答并合成整理' }))
    await screen.findByText('已关联 1 个问题')
    expect(posts(fetcher)).toHaveLength(1)
    expect(fetcher.mock.calls.some(([path, init]) => String(path).endsWith('/mining-runs/recovery') && init?.method === 'GET')).toBe(true)
    expect(sessionStorage.getItem(MINING_KEY)).toBeNull()
  })
  it('refresh with an unsubmitted answer only queries and requires original body before same-key retry', async () => {
    const x = setup();await waitReady();x.missing()
    fireEvent.change(screen.getByLabelText('你的回答或自由补充'), { target: { value: 'Synthetic unanswered body.' } })
    await userEvent.click(screen.getByRole('button', { name: '保存回答并合成整理' }))
    await screen.findByText('未找到原操作。重新输入完全一致的原回答，保留原问题关联，可用同一操作键重试。')
    const count = posts(x.fetcher).length
    x.view.unmount();render(<DiscoveryWorkbench api={x.api} />)
    await screen.findByRole('heading', { name: '先核对上一条操作' })
    await waitFor(() => expect(screen.getByLabelText('你的回答或自由补充')).not.toBeDisabled())
    expect(posts(x.fetcher)).toHaveLength(count)
    fireEvent.change(screen.getByLabelText('你的回答或自由补充'), { target: { value: 'Changed body' } })
    await userEvent.click(screen.getByRole('button', { name: '用原回答同键重试' }))
    await screen.findByText('请重新输入完全一致的原回答，保留原问题关联；不会换键发送。')
    expect(posts(x.fetcher)).toHaveLength(count)
  })
  it('storage failure prevents any mining write', async () => {
    const x = setup();await waitReady()
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Synthetic storage blocked') })
    fireEvent.change(screen.getByLabelText('你的回答或自由补充'), { target: { value: 'Synthetic unsubmitted answer' } })
    await userEvent.click(screen.getByRole('button', { name: '保存回答并合成整理' }))
    await screen.findByRole('alert')
    expect(posts(x.fetcher)).toHaveLength(0)
    storage.mockRestore()
  })
  it('keeps IME Enter from sending and supports explicit Ctrl Enter submission', async () => {
    const x = setup();await waitReady()
    const input = screen.getByLabelText('你的回答或自由补充')
    fireEvent.change(input, { target: { value: '合成：我做了列表。' } })
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true, isComposing: true, keyCode: 229 })
    expect(posts(x.fetcher)).toHaveLength(0)
    fireEvent.keyDown(input, { key: 'Enter', ctrlKey: true })
    await waitFor(() => expect(posts(x.fetcher)).toHaveLength(1))
  })
  it('cancelled management does not POST; failed reads block an already open panel', async () => {
    const x = setup();await waitReady()
    await userEvent.click(screen.getByRole('button', { name: '结束会话' }))
    await userEvent.click(within(screen.getByRole('group', { name: '管理确认' })).getByRole('button', { name: '取消' }))
    expect(posts(x.fetcher)).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: '删除会话' }))
    x.offline();await userEvent.click(screen.getByRole('button', { name: '重新读取' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '确认永久删除' })).toBeDisabled())
  })
  it('fact conflict preserves draft and disables management when reload fails', async () => {
    const x = setup();await waitReady()
    const card = screen.getAllByRole('article', { name: '事实 1' })[0]
    await userEvent.click(within(card).getByRole('button', { name: '编辑陈述' }))
    fireEvent.change(screen.getByLabelText('编辑事实 1'), { target: { value: 'Synthetic retained edit draft' } })
    x.conflict();await userEvent.click(within(card).getByRole('button', { name: '保存编辑' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '结束会话' })).toBeDisabled())
    expect(screen.getByLabelText('编辑事实 1')).toHaveValue('Synthetic retained edit draft')
  })
  it('disabled AI gives manual fallback without fake questions', async () => {
    const x = setup('empty');await waitReady();x.disable()
    await userEvent.click(screen.getByRole('button', { name: '根据已保存经历开始合成整理' }))
    await screen.findByText('合成挖掘未启用。真实模型尚未接入；原始经历已保存，可使用手工工作台继续。')
    expect(screen.queryByRole('article', { name: '合成追问' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: '手工工作台' })).toHaveAttribute('href', '/manual')
  })
})

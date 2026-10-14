import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import fixtures from '../../test/mining-fixtures.json'
import { createExperienceApi, SESSION_KEY } from '../../lib/experience'
import { MINING_KEY } from '../../lib/pending-mining'
import DiscoveryWorkbench from './DiscoveryWorkbench'

type Stage = 'empty' | 'initial' | 'answered' | 'confirmed'
function setup(initial: Stage | null = 'initial') {
  let stage: Stage = initial ?? 'empty', failReads = false, disabled = false, lost = false, missing = false, conflict = false
  if (initial) sessionStorage.setItem(SESSION_KEY, JSON.stringify({ sessionId: fixtures.created.session_id, token: fixtures.created.access_token }))
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input), method = init?.method ?? 'GET'
    const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status })
    if (method === 'GET' && failReads) throw new Error('Synthetic offline')
    if (path.endsWith('/experience-summary')) return json(fixtures[`${stage}Summary`])
    if (path.endsWith('/mining-runs/recovery')) return missing ? json({ error: { code: 'mining_operation_not_found' } }, 404) : json(stage === 'initial' ? fixtures.initialRun : fixtures.answerRun)
    if (method === 'GET') return json(fixtures[stage])
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
  const view = render(<DiscoveryWorkbench api={api} copy={copy} />)
  return { fetcher, api, copy, view, loseResponse: () => { lost = true }, missing: () => { missing = true }, enable: () => { missing = false }, disable: () => { disabled = true }, offline: () => { failReads = true }, online: () => { failReads = false; conflict = false }, conflict: () => { conflict = true } }
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
    const { copy } = setup('confirmed')
    await waitReady()
    expect(screen.getByText('已关联 1 个问题')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '复制经历文本' }))
    expect(copy).toHaveBeenCalledWith(fixtures.confirmedSummary.text)
    expect(screen.getByText('技术备份（JSON，非正式简历）')).toBeInTheDocument()
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

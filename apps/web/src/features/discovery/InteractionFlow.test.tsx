import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import fixtures from '../../test/mining-fixtures.json'
import { createExperienceApi, sessionSchema, SESSION_KEY } from '../../lib/experience'
import type { MiningRun } from '../../lib/mining-contract'
import { MINING_KEY } from '../../lib/pending-mining'
import * as pendingMining from '../../lib/pending-mining'
import DiscoveryWorkbench from './DiscoveryWorkbench'

function harness(outcome: MiningRun['state'] | 'empty' | 'conflict' = 'completed', hold = false, unstarted = false, holdRead = false) {
  let data = sessionSchema.parse(structuredClone(unstarted ? fixtures.empty : fixtures.initial))
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let releaseRead!: () => void
  let readGate = new Promise<void>(resolve => { releaseRead = resolve })
  const heldRead = vi.fn(), finishedRead = vi.fn()
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path=String(input), method=init?.method ?? 'GET'
    const json=(value: unknown,status=200)=>new Response(JSON.stringify(value),{status})
    if (method==='GET' && path.endsWith(`/sessions/${data.id}`) && holdRead) {
      heldRead();await readGate;holdRead=false;finishedRead()
    }
    if (path.endsWith('/mining-runs') && method==='POST') {
      expect(sessionStorage.getItem(MINING_KEY)).not.toBeNull()
      if (hold) await gate
      if (outcome==='conflict') { data.context_revision=(data.context_revision ?? 0)+1;return json({error:{code:'context_conflict'}},409) }
      const payload=JSON.parse(String(init?.body))
      data=sessionSchema.parse(structuredClone(payload.input_turn_id ? fixtures.initial : fixtures.answered))
      const run=data.mining_runs!.at(-1)!
      run.state=outcome==='empty' ? 'completed' : outcome
      if (outcome!=='completed') {
        const removed=new Set(run.candidate_fact_ids)
        run.candidate_fact_ids=[]
        data.facts=data.facts.filter(f=>!removed.has(f.id))
        data.history=data.history.filter(h=>!removed.has(h.fact_id))
      }
      if (outcome!=='completed' && outcome!=='empty') {
        run.questions=[]
        run.error_code=outcome==='failed' ? 'provider_output_invalid' : outcome==='stale' ? 'context_changed' : outcome==='unknown' ? 'provider_outcome_unknown' : null
        if (outcome==='running' || outcome==='reserved') run.lease_until=new Date(Date.now()+60000).toISOString()
        // No synthetic assistant completion or candidate on a failed/active run.
        data.turns=data.turns.filter(t=>t.id!==fixtures.answered.turns.at(-1)!.id)
      }
      return json(run,['running','reserved'].includes(run.state)?202:201)
    }
    if (path.endsWith('/mining-runs/recovery')) return outcome==='conflict' ? json({error:{code:'mining_operation_not_found'}},404) : json(data.mining_runs!.at(-1))
    if (path.endsWith('/experience-summary')) {
      const confirmed=data.facts.filter(f=>['user_confirmed','evidence_supported'].includes(f.status))
      return json({project_id:data.projects[0].id,context_revision:data.context_revision,confirmed,
        pending:data.facts.filter(f=>f.status==='pending'),text:confirmed.map(f=>f.statement).join('\n'),incomplete:!confirmed.length})
    }
    return json(data)
  })
  sessionStorage.setItem(SESSION_KEY,JSON.stringify({sessionId:data.id,token:fixtures.created.access_token}))
  const api=createExperienceApi(fetcher as typeof fetch)
  const view=render(<DiscoveryWorkbench api={api} />)
  return {fetcher,release,releaseRead:()=>releaseRead(),heldRead,finishedRead,view,api,
    holdNextRead:()=>{holdRead=true;readGate=new Promise<void>(resolve=>{releaseRead=resolve})},
    complete:()=>{ const run=data.mining_runs!.at(-1)!;run.state='completed';run.error_code=null }}
}
const writes=(x:ReturnType<typeof harness>)=>x.fetcher.mock.calls.filter(([,init])=>init?.method==='POST')
const status=()=>screen.getByRole('status',{name:'整理交互状态'})
async function ready() { await waitFor(()=>expect(screen.getByRole('button',{name:'重新读取'})).toBeEnabled()) }
async function answer() {
  fireEvent.change(screen.getByLabelText('你的回答或自由补充'),{target:{value:fixtures.answered.turns.find(t=>t.id===fixtures.answerRun.input_turn_id)!.content}})
  await userEvent.click(screen.getByRole('button',{name:'保存回答并合成整理'}))
}

it('waits for explicit first mining rather than treating GET as thinking',async()=>{
  const x=harness('completed',false,true);await ready()
  expect(status()).toHaveAttribute('data-state','not_started')
  expect(writes(x)).toHaveLength(0)
  await userEvent.click(screen.getByRole('button',{name:'重新读取'}))
  expect(writes(x)).toHaveLength(0)
  expect(status()).toHaveAttribute('data-state','not_started')
})
it('shows an ordinary delayed GET as reading, without any inference submission',async()=>{
  const x=harness('completed',false,false,true)
  await screen.findByText('正在读取或处理资料 · 不代表模型正在思考')
  expect(writes(x)).toHaveLength(0)
  x.releaseRead();await ready()
  expect(status()).toHaveAttribute('data-state','completed')
})
it('initial mining does not clear a separate unsubmitted answer draft',async()=>{
  const x=harness('completed',false,true);await ready()
  fireEvent.change(screen.getByLabelText('你的回答或自由补充'),{target:{value:'Synthetic future answer not submitted'}})
  await userEvent.click(screen.getByRole('button',{name:'根据已保存经历开始合成整理'}))
  await waitFor(()=>expect(status()).toHaveAttribute('data-state','completed'))
  expect(screen.getByLabelText('你的回答或自由补充')).toHaveValue('Synthetic future answer not submitted')
  expect(JSON.parse(String(writes(x)[0][1]?.body)).content).toBeNull()
})
it('changes from POST submission to ordinary reading while the follow-up GET is held',async()=>{
  let releasePreparation!: () => void
  const preparationGate = new Promise<void>(resolve => { releasePreparation = resolve })
  const newMining = pendingMining.newMining
  const preparation = vi.spyOn(pendingMining,'newMining').mockImplementationOnce(async (...args) => {
    await preparationGate
    return newMining(...args)
  })
  const x=harness('completed',true)
  try {
    await ready()
    expect(writes(x)).toHaveLength(0)
    x.holdNextRead();await answer()
    await waitFor(()=>expect(preparation).toHaveBeenCalledOnce())
    // busy also projects reading before asynchronous key preparation finishes.
    await waitFor(()=>expect(status()).toHaveAttribute('data-state','reading'))
    expect(writes(x)).toHaveLength(0)
    expect(x.heldRead).not.toHaveBeenCalled()
    releasePreparation()
    await waitFor(()=>expect(writes(x)).toHaveLength(1))
    expect(String(writes(x)[0][0])).toMatch(/\/mining-runs$/)
    await waitFor(()=>expect(status()).toHaveAttribute('data-state','submitting'))
    x.release()
    // Synchronize on the actual follow-up GET, which remains unresolved here.
    await waitFor(()=>expect(x.heldRead).toHaveBeenCalledOnce())
    await waitFor(()=>expect(status()).toHaveAttribute('data-state','reading'))
    expect(x.finishedRead).not.toHaveBeenCalled()
    expect(status()).not.toHaveTextContent('正在提交并进行合成整理')
    expect(writes(x)).toHaveLength(1)
    x.releaseRead();await ready()
    expect(x.finishedRead).toHaveBeenCalledOnce()
    expect(status()).toHaveAttribute('data-state','completed')
    expect(writes(x)).toHaveLength(1)
  } finally {
    x.view.unmount();releasePreparation();x.release();x.releaseRead();preparation.mockRestore()
  }
})
it('uses the actual POST lifecycle and submits two explicit question links only once',async()=>{
  const x=harness('completed',true);await ready()
  for(const box of screen.getAllByRole('checkbox')) await userEvent.click(box)
  await answer()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state','submitting'))
  expect(screen.getByRole('button',{name:'正在提交合成整理…'})).toBeDisabled()
  expect(writes(x)).toHaveLength(1)
  const payload=JSON.parse(String(writes(x)[0][1]?.body))
  expect(payload.answered_question_ids).toEqual(fixtures.initialRun.questions.map(q=>q.id).sort())
  x.release()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state','completed'))
  expect(status()).toHaveTextContent('本轮有 1 条候选事实待确认')
  // Session contains two pending facts; latest run has exactly one, never two.
  expect(status()).toHaveTextContent('本轮当前共有 1 条候选')
})
it('does not claim extraction success for a completed zero-candidate run with questions',async()=>{
  const x=harness('empty');await ready();await answer()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state','no_new_facts'))
  expect(status()).toHaveTextContent('仍有已保存的合法追问')
  expect(screen.getAllByRole('button',{name:'回答这题'})).toHaveLength(2)
  expect(writes(x)).toHaveLength(1)
})
it.each(['reserved','running','unknown'] as const)('retains %s operation keys, drafts and GET-only recovery across refresh',async state=>{
  const x=harness(state);await ready();await answer()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state',state))
  const stored=sessionStorage.getItem(MINING_KEY)
  expect(stored).not.toBeNull()
  expect(screen.getByLabelText('你的回答或自由补充')).not.toHaveValue('')
  expect(screen.getByLabelText('你的回答或自由补充')).toBeDisabled()
  expect(screen.getByRole('button',{name:'用原回答同键重试'})).toBeDisabled()
  expect(screen.queryByRole('button',{name:'重新整理已保存回答'})).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole('button',{name:'查询本轮状态（只读）'}))
  await ready()
  expect(status()).toHaveAttribute('data-state',state)
  expect(writes(x)).toHaveLength(1)
  expect(sessionStorage.getItem(MINING_KEY)).toBe(stored)
  x.view.unmount();render(<DiscoveryWorkbench api={x.api} />);await ready()
  expect(status()).toHaveAttribute('data-state',state)
  expect(writes(x)).toHaveLength(1)
  expect(sessionStorage.getItem(MINING_KEY)).toBe(stored)
})
it('only a confirmed completed GET resolves unknown, never a timer or automatic retry',async()=>{
  const x=harness('unknown');await ready();await answer()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state','unknown'))
  expect(sessionStorage.getItem(MINING_KEY)).not.toBeNull()
  x.complete()
  // Merely changing the server fixture cannot trigger a background poll.
  expect(status()).toHaveAttribute('data-state','unknown')
  await userEvent.click(screen.getByRole('button',{name:'查询本轮状态（只读）'}))
  await ready()
  expect(status()).toHaveAttribute('data-state','no_new_facts')
  expect(sessionStorage.getItem(MINING_KEY)).toBeNull()
  expect(writes(x)).toHaveLength(1)
})
it('keeps a context conflict paused even when the automatic read succeeds',async()=>{
  const x=harness('conflict');await ready();await answer()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state','conflict'))
  expect(screen.getByRole('button',{name:'只读恢复最新资料'})).toBeEnabled()
  expect(screen.getByRole('button',{name:'用原回答同键重试'})).toBeDisabled()
  expect(writes(x)).toHaveLength(1)
})
it.each(['failed','stale'] as const)('pauses new answers on %s and requires a separate retry confirmation',async state=>{
  const x=harness(state);await ready();await answer()
  await waitFor(()=>expect(status()).toHaveAttribute('data-state',state))
  if(state==='failed') expect(status()).toHaveTextContent('输出未通过校验')
  fireEvent.change(screen.getByLabelText('你的回答或自由补充'),{target:{value:'Synthetic unsubmitted next answer'}})
  expect(screen.getByRole('button',{name:'保存回答并合成整理'})).toBeDisabled()
  await userEvent.click(screen.getByRole('button',{name:'重新整理已保存回答'}))
  expect(screen.getByRole('button',{name:'确认重新整理'})).toBeEnabled()
  await userEvent.click(screen.getByRole('button',{name:'取消重新整理'}))
  expect(writes(x)).toHaveLength(1)
  expect(screen.getByLabelText('你的回答或自由补充')).toHaveValue('Synthetic unsubmitted next answer')
})
it('labels every projected status as synthetic and never displays persisted assistant boilerplate as AI text',async()=>{
  harness();await ready()
  expect(status()).toHaveTextContent('零费用 · 合成流程状态')
  expect(screen.getByText('合成流程记录 · 不是模型回复')).toBeInTheDocument()
  expect(screen.queryByText('Synthetic provider: candidate review available.')).not.toBeInTheDocument()
})

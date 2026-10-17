import { describe, expect, it } from 'vitest'
import fixtures from '../../test/mining-fixtures.json'
import { sessionSchema } from '../../lib/experience'
import { miningRunSchema } from '../../lib/mining-contract'
import { interactionState, type InteractionInput } from './interactionState'

function input(): InteractionInput {
  return { session: sessionSchema.parse(structuredClone(fixtures.initial)), hasCredentials: true,
    busy: false, phase: 'idle', needsReload: false, storageError: false, pending: false, notFound: false, failureCode: null }
}
describe('trusted interaction projection, not model messages', () => {
  it('distinguishes description, saved but unstarted, and user-submitted POST from normal reads', () => {
    const x=input()
    expect(interactionState({ ...x, session:null, hasCredentials:false }).key).toBe('describe')
    x.session!.mining_runs=[]
    expect(interactionState(x).key).toBe('not_started')
    expect(interactionState({ ...x,busy:true,phase:'submitting' }).key).toBe('submitting')
    for (const phase of ['idle','reading','recovering'] as const) {
      const state=interactionState({ ...x,busy:true,phase })
      expect(state.key).toBe('reading')
      expect(state.title).not.toContain('思考')
      expect(state.title).not.toContain('提交')
    }
  })
  it('counts only this run current server facts, not all session pending facts or model claims', () => {
    const x=input(), run=x.session!.mining_runs![0]
    expect(interactionState(x)).toMatchObject({key:'completed',candidateCount:1,pendingCount:1})
    x.session!.facts.push({ ...x.session!.facts[0], id:crypto.randomUUID(),ai_run_id:null })
    expect(interactionState(x).pendingCount).toBe(1)
    x.session!.facts[0].status='user_confirmed'
    expect(interactionState(x)).toMatchObject({ key:'awaiting_answer',pendingCount:0 })
    run.candidate_fact_ids=[]
    expect(interactionState(x)).toMatchObject({key:'no_new_facts',candidateCount:0,pendingCount:0})
    expect(interactionState(x).next).toContain('继续澄清')
    run.questions=[]
    expect(interactionState(x).next).toContain('自由补充')
  })
  it.each(['reserved','running','unknown'] as const)('holds %s without reclassifying it after a GET', state => {
    const x=input();x.session!.mining_runs![0].state=state
    const before=structuredClone(x)
    expect(interactionState(x)).toMatchObject({ key:state,pauseMining:true,recoverOnly:true,query:true })
    expect(interactionState({ ...x,phase:'reading',busy:true }).key).toBe('reading')
    expect(interactionState(x).key).toBe(state)
    expect(x).toEqual(before)
  })
  it('separates validation failure from other explicit failures without exposing arbitrary error text', () => {
    const x=input(),run=x.session!.mining_runs![0];run.state='failed';run.error_code='provider_output_invalid'
    expect(interactionState(x).title).toContain('未通过校验')
    run.error_code='private arbitrary provider content'
    const state=interactionState(x)
    expect(state.title).toBe('本轮整理明确失败')
    expect(JSON.stringify(state)).not.toContain(run.error_code)
  })
  it('pauses on conflicts, stale output, incomplete facts, local uncertainty and corrupted storage', () => {
    const x=input()
    expect(interactionState({ ...x,needsReload:true,failureCode:'context_conflict' })).toMatchObject({key:'conflict',recoverOnly:true})
    x.session!.mining_runs![0].state='stale'
    expect(interactionState(x)).toMatchObject({key:'stale',pauseMining:true,query:true})
    x.session!.mining_runs![0].state='completed';x.session!.facts=[]
    expect(interactionState(x)).toMatchObject({key:'recovery_required',recoverOnly:true})
    expect(interactionState({ ...input(),pending:true }).key).toBe('unknown')
    expect(interactionState({ ...input(),pending:true,notFound:true })).toMatchObject({key:'not_found',pauseMining:false})
    expect(interactionState({ ...input(),storageError:true }).recoverOnly).toBe(true)
  })
  it('does not invent stopping reasons and excludes already answered questions', () => {
    const x=input(), run=x.session!.mining_runs![0]
    x.session!.turns[0].answered_questions=run.questions.map(q=>({question_id:q.id,question_version:q.version}))
    expect(interactionState(x).questionCount).toBe(0)
    x.session!.mining_status='stopped'
    expect(interactionState(x)).toMatchObject({key:'stopped',pauseMining:true,recoverOnly:false})
    expect(interactionState(x).description).toContain('不提供具体停止原因')
    x.session!.status='ended'
    expect(interactionState(x).key).toBe('ended')
    expect(interactionState({ ...input(),failureCode:'mining_round_limit' }).key).toBe('limit')
  })
  it('does not loosen the current synthetic provider gate or accept future fields as implemented', () => {
    expect(miningRunSchema.safeParse({ ...fixtures.initialRun,provider:'deepseek_official',synthetic:false }).success).toBe(false)
  })
})

import { useEffect, useRef, useState } from 'react'
import { ApiError, readCredentials, saveCredentials, SESSION_KEY, type Credentials, type ExperienceApi, type ExperienceSession, type Fact, type Mutation } from '../../lib/experience'
import { checkBody, clearPending, newPending, readPending, storePending, type PendingCreate } from '../../lib/idempotency'
import { createMiningApi, type Summary } from '../../lib/mining'
import { clearMining, newMining, originalBody, readMining, storeMining, verifyMining, type PendingMining } from '../../lib/pending-mining'
import type { MiningBody, MiningRun, Question, QuestionAction } from '../../lib/mining-contract'
import type { RequestPhase } from './interactionState'

export function useDiscovery(api: ExperienceApi) {
  const apiRef = useRef(api), mineRef = useRef(createMiningApi(api))
  const [credentials, setCredentials] = useState(readCredentials)
  const [session, setSession] = useState<ExperienceSession | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [raw, setRaw] = useState(''), [answer, setAnswer] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [creation, setCreation] = useState(readPending)
  const [mining, setMining] = useState(readMining)
  const [createNotFound, setCreateNotFound] = useState(false), [miningNotFound, setMiningNotFound] = useState(false)
  const [busy, setBusy] = useState(false), [needsReload, setNeedsReload] = useState(false)
  const [phase, setPhase] = useState<RequestPhase>('idle')
  const [failureCode, setFailureCode] = useState<string | null>(null)
  const [error, setError] = useState(creation.error || mining.error), [notice, setNotice] = useState('')
  const locked = useRef(false)
  function ensureWrite() {
    if (needsReload || mining.error || creation.error) throw new Error('请先恢复并核对最新资料，写入已暂停。')
    if (session?.status === 'ended') throw new Error('会话已结束，资料只读。')
    if (['reserved', 'running', 'unknown'].includes(session?.mining_runs?.at(-1)?.state ?? '')) throw new Error('本轮结果尚未确定，请先只读查询；不会重新提交或推理。')
  }
  async function load(c = credentials, active = () => true) {
    if (!c) return
    const data = await apiRef.current.read(c, AbortSignal.timeout(10000))
    if (!data.context_revision || !data.mining_runs || !data.mining_status) throw new Error('后端需要先升级至 0005；已停止写入，请使用隔离预览或手工入口。')
    const organized = await mineRef.current.summary(c, data.projects[0].id)
    if (organized.context_revision !== data.context_revision) throw new Error('读取期间资料发生变化，请重新读取后核对。')
    const confirmed = data.facts.filter(f => ['user_confirmed', 'evidence_supported'].includes(f.status))
    if (organized.project_id !== data.projects[0].id || organized.confirmed.length !== confirmed.length || organized.confirmed.some(f => !confirmed.some(current => current.id === f.id && JSON.stringify(current) === JSON.stringify(f)))) throw new Error('整理稿与当前事实版本不一致，请重新读取后核对。')
    if (active()) { setSession(data); setSummary(organized); setNeedsReload(false) }
    return data
  }
  function adopt(data: { session_id: string; access_token: string }, p: { token: string }) {
    if (data.access_token !== p.token) throw new Error('恢复凭证不一致，已停止操作。')
    const c = { sessionId: data.session_id, token: p.token }
    saveCredentials(c); clearPending(); setCreation({ value: null, error: '' }); setCredentials(c); setRaw('')
    return c
  }
  async function recoverCreation(p: PendingCreate, active = () => true) {
    // Only the creation contract's explicit 404 establishes absence. A transport
    // error, another 404, or an expired key must never authorize a write.
    try {
      const result = await apiRef.current.recover(p)
      if (active()) setCreateNotFound(false)
      return result
    } catch (cause) {
      if (active()) {
        const absent = cause instanceof ApiError && cause.status === 404 && cause.code === 'idempotency_creation_not_found' && Date.now() < p.expiresAt
        setCreateNotFound(absent); setNeedsReload(!absent)
        setNotice(absent ? '明确未找到创建结果。请重新输入完全一致的原描述，再显式同键重试；不会自动新建。' : '创建结果仍不确定，写入已暂停。请先只读恢复，不会换键或自动重发。')
      }
      throw cause
    }
  }
  async function acceptRun(c: Credentials, p: PendingMining, result: MiningRun) {
    if (result.session_id !== c.sessionId || result.project_id !== p.project_id) throw new Error('恢复资料归属不一致。')
    await load(c)
    if (!['running', 'reserved', 'unknown'].includes(result.state)) {
      clearMining(); setMining({ value: null, error: '' }); setMiningNotFound(false)
      if (p.mode === 'answer') { setAnswer(''); setSelected([]) }
      setNotice(result.state === 'completed' ? '本轮整理记录已读取，请核对实际候选事实和问题。' : '回答已保存，本轮整理未完成。可以查看原回答，并明确选择重新整理；不会自动执行。')
    } else setNotice(result.state === 'unknown' ? '本轮结果不确定，保留原操作记录；只能先只读查询，不会重新推理。' : '回答已保存，合成整理仍在运行。请查询状态，不要再次提交。')
  }
  async function recoverMine(c = credentials, p = mining.value) {
    if (!c || !p) return
    if (c.sessionId !== p.sessionId) throw new Error('暂存操作与会话不一致，已停止恢复。')
    setPhase('recovering')
    try { await acceptRun(c, p, await mineRef.current.recover(c, p.key)) }
    catch (cause) {
      if (cause instanceof ApiError && cause.code === 'mining_operation_not_found') setMiningNotFound(true)
      throw cause
    }
    finally { setPhase('idle') }
  }
  useEffect(() => {
    let active = true
    async function boot() {
      locked.current = true; setBusy(true); setPhase('reading')
      let loaded = false
      try {
        let c = credentials
        if (!c && creation.value && !creation.error) c = adopt(await recoverCreation(creation.value, () => active), creation.value)
        if (c) {
          await load(c, () => active)
          loaded = true
          if (active && mining.value && !mining.error) await recoverMine(c, mining.value)
        }
      } catch (cause) {
        if (!active) return
        const absent = !credentials && creation.value && !creation.error && Date.now() < creation.value.expiresAt && cause instanceof ApiError && cause.status === 404 && cause.code === 'idempotency_creation_not_found'
        setNeedsReload(!(absent || (loaded && cause instanceof ApiError && cause.code === 'mining_operation_not_found')))
        setError(cause instanceof Error ? cause.message : '恢复失败，请只读查询。')
      } finally { if (active) { locked.current = false; setBusy(false); setPhase('idle') } }
    }
    void boot()
    return () => { active = false }
  }, [])
  async function act(work: () => Promise<void>) {
    if (locked.current) return false
    locked.current = true; setBusy(true); setError(''); setNotice(''); setFailureCode(null)
    try { await work(); return true }
    catch (cause) {
      if (cause instanceof ApiError) setFailureCode(cause.code)
      if (cause instanceof ApiError && ['ai_disabled', 'ai_provider_unapproved'].includes(cause.code)) {
        setError('合成挖掘未启用。真实模型尚未接入；原始经历已保存，可使用手工工作台继续。')
      } else if (cause instanceof ApiError && cause.code === 'idempotency_payload_mismatch') {
        setNeedsReload(true); setError(cause.message); setNotice('请查询原操作结果，不会按事实版本冲突覆盖或重新提交。')
      } else {
        if (credentials) {
          setNeedsReload(true)
          try {
            await load(); setNotice('已读取当前资料，请核对操作是否保存。未保存输入保留，不会自动覆盖或重发。')
            if (cause instanceof ApiError && ['context_conflict', 'version_conflict'].includes(cause.code)) setNeedsReload(true)
          }
          catch { setNotice('最新资料读取失败。请先重新读取，结束、删除和复制已暂停。') }
        }
        setError(cause instanceof Error ? cause.message : '请求结果不确定，请只读查询。')
      }
      return false
    } finally { locked.current = false; setBusy(false); setPhase('idle') }
  }
  function body(data: ExperienceSession, opts: Partial<MiningBody>): MiningBody {
    return { project_id: data.projects[0].id, base_revision: data.context_revision!, content: null, input_turn_id: null, retry_of: null, confirm_retry: false, ...opts }
  }
  async function send(c: Credentials, payload: MiningBody, p?: PendingMining) {
    const record = p ?? await newMining(c, payload)
    await verifyMining(c, record, payload)
    storeMining(record); setMining({ value: record, error: '' }); setMiningNotFound(false)
    setPhase('submitting')
    try {
      const result = await mineRef.current.start(c, payload, record.key)
      setPhase('reading')
      await acceptRun(c, record, result)
    }
    catch (cause) {
      if (cause instanceof ApiError && ['ai_disabled', 'ai_provider_unapproved'].includes(cause.code)) {
        clearMining(); setMining({ value: null, error: '' }); throw cause
      }
      // POST uncertainty is reconciled only with a GET; never another inference/write.
      try { await recoverMine(c, record) } catch { throw cause }
    }
    finally { setPhase('idle') }
  }
  async function create() {
    if (needsReload || creation.error || mining.error) throw new Error('暂存异常，请先核对恢复记录。')
    if (creation.value && !createNotFound) throw new Error('请先查询刚才的创建结果，不会新建第二份。')
    const p = creation.value ?? await newPending(raw)
    await checkBody(p, raw); storePending(p); setCreation({ value: p, error: '' })
    setCreateNotFound(false)
    let c: Credentials
    try { c = adopt(await apiRef.current.create(raw, p), p) }
    catch (cause) {
      try { c = adopt(await recoverCreation(p), p) }
      catch { throw cause }
    }
    const data = await load(c)
    if (data) await send(c, body(data, { input_turn_id: data.turns.find(t => t.role === 'user')!.id }))
  }
  async function startInitial() {
    ensureWrite()
    if (!credentials || !session) return
    await send(credentials, body(session, { input_turn_id: session.turns.find(t => t.role === 'user')!.id }))
  }
  async function submitAnswer() {
    ensureWrite()
    if (!credentials || !session) return
    if (!mining.value && ['failed', 'stale'].includes(session.mining_runs?.at(-1)?.state ?? '')) throw new Error('本轮未完成，请先核对；重新整理已保存回答必须明确确认。')
    if (mining.value) {
      if (!miningNotFound) throw new Error('请先查询上次结果，不会重复写入回答。')
      await send(credentials, originalBody(mining.value, answer), mining.value)
    } else await send(credentials, body(session, { content: answer, ...(selected.length ? { answered_question_ids: [...selected].sort() } : {}) }))
  }
  async function retrySaved(run: MiningRun) {
    ensureWrite()
    if (!credentials || !session) return
    await send(credentials, body(session, { retry_of: run.id, confirm_retry: true }))
  }
  async function refresh() {
    setPhase('reading')
    try {
      if (!credentials) {
        if (creation.value) { const c = adopt(await recoverCreation(creation.value), creation.value); await load(c) }
      } else { await load(); if (mining.value) await recoverMine() }
    } finally { setPhase('idle') }
  }
  async function mutate(fact: Fact, mutation: Mutation) {
    ensureWrite()
    if (!credentials || needsReload) return
    await apiRef.current.mutate(credentials, fact.id, mutation); await load()
  }
  async function question(q: Question, action: QuestionAction, content?: string) {
    ensureWrite()
    if (!credentials || !session || needsReload) return
    await mineRef.current.question(credentials, q.id, session.context_revision!, q.version, action, content)
    setSelected(ids => ids.filter(id => id !== q.id)); await load()
  }
  async function manage(action: 'stop' | 'end' | 'delete') {
    if (!credentials || !session || needsReload || mining.value || mining.error || creation.error || ['reserved', 'running', 'unknown'].includes(session.mining_runs?.at(-1)?.state ?? '')) return
    if (action === 'delete') {
      await apiRef.current.remove(credentials)
      clearMining(); clearPending(); sessionStorage.removeItem(SESSION_KEY)
      setCredentials(null); setSession(null); setSummary(null); setNotice('会话及业务资料已删除。')
      setAnswer(''); setSelected([])
    } else {
      if (action === 'stop') await mineRef.current.stop(credentials, session.context_revision!)
      else await apiRef.current.end(credentials)
      await load(); setNotice(action === 'stop' ? '已停止追问，仍可审核事实和阅读整理结果。' : '会话已结束，资料只读。')
    }
  }
  function abandon() {
    if ((!miningNotFound && !(mining.value && Date.now() >= mining.value.expiresAt)) || needsReload) return
    clearMining(); setMining({ value: null, error: '' }); setMiningNotFound(false)
    setNotice('已明确清除本页操作记录；没有删除已保存回答，也不会自动提交。')
  }
  return { credentials, session, summary, raw, setRaw, answer, setAnswer, selected, setSelected, busy, phase, failureCode, needsReload, error, notice,
    creation, createNotFound, mining, miningNotFound, act, create, refresh, startInitial, submitAnswer, retrySaved, mutate, question, manage, abandon,
    api: apiRef.current }
}

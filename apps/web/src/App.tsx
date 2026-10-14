import { useEffect, useRef, useState } from 'react'
import { ApiError, createExperienceApi, downloadJson, readCredentials, saveCredentials, SESSION_KEY } from './lib/experience'
import type { CreatedSession, Credentials, ExperienceApi, ExperienceSession, Fact, Mutation } from './lib/experience'
import { checkBody, clearPending, newPending, operation, readPending, storePending } from './lib/idempotency'
import type { PendingCreate } from './lib/idempotency'
import { FactCard } from './features/FactCard'
import type { ReactNode } from 'react'

export default function App({ api = createExperienceApi(), download = downloadJson, intro }: { api?: ExperienceApi; download?: typeof downloadJson; intro?: ReactNode }) {
  const apiRef = useRef(api)
  const [credentials, setCredentials] = useState<Credentials | null>(readCredentials)
  const [initialPending] = useState(readPending)
  const [pending, setPending] = useState(initialPending.value)
  const [creationBlocked, setCreationBlocked] = useState(Boolean(initialPending.error))
  const [createRetry, setCreateRetry] = useState(false)
  const [session, setSession] = useState<ExperienceSession | null>(null)
  const [busy, setBusy] = useState(false)
  const locked = useRef(false)
  const [error, setError] = useState(initialPending.error)
  const [notice, setNotice] = useState('')
  const [raw, setRaw] = useState('')
  const [statement, setStatement] = useState('')
  const pendingAdd = useRef<{ content: string; turnKey?: string; turnId?: string; factKey?: string } | null>(null)
  const [sourceTurn, setSourceTurn] = useState('')
  const [deletePrompt, setDeletePrompt] = useState(false)
  const [endPrompt, setEndPrompt] = useState(false)
  const [needsReload, setNeedsReload] = useState(false)

  function blockExpiredCreate() {
    setCreationBlocked(true); setCreateRetry(false)
    try { clearPending(); setPending(null) } catch { setNotice('临时记录无法清除，请检查浏览器暂存。') }
  }

  useEffect(() => {
    if (!pending) return
    const timer = setTimeout(() => { blockExpiredCreate(); setError('24 小时临时恢复窗口已结束。之前可能已创建，无法保证找回；不会自动新建。') }, Math.max(0, pending.expiresAt - Date.now()))
    return () => clearTimeout(timer)
  }, [pending])

  function adopt(data: CreatedSession, p: PendingCreate) {
    if (data.access_token !== p.token) throw new Error('服务返回凭证与临时记录不一致。已停止创建，请恢复并核对。')
    const c = { sessionId: data.session_id, token: data.access_token }
    try {
      saveCredentials(c)
      clearPending(); setPending(null)
    } catch { setNotice('正式凭证暂存失败，临时恢复记录保留；请先导出或删除，不保证刷新恢复。') }
    setCredentials(c); setRaw(''); setCreateRetry(false)
  }

  useEffect(() => {
    if (credentials) {
      if (initialPending.value) {
        if (credentials.token !== initialPending.value.token) { setError('正式与临时凭证不一致，已停止操作。请核对暂存。'); setNeedsReload(true) }
        else { try { clearPending(); setPending(null) } catch { setNotice('残留临时记录无法清除，请检查浏览器暂存。') } }
      }
      return
    }
    if (!initialPending.value) return
    const p = initialPending.value, controller = new AbortController()
    let current = true
    locked.current = true; setBusy(true)
    apiRef.current.recover(p, controller.signal).then(data => {
      if (current) { adopt(data, p); setError('已通过只读查询恢复刚才的会话，请核对资料。') }
    }).catch(cause => {
      if (!current) return
      if (cause instanceof ApiError && cause.code === 'idempotency_creation_not_found') setCreateRetry(true)
      if (cause instanceof ApiError && cause.status === 410) blockExpiredCreate()
      setError(cause instanceof Error ? cause.message : '恢复结果不确定，请重新只读查询。')
    }).finally(() => { if (current) { locked.current = false; setBusy(false) } })
    return () => { current = false; controller.abort() }
  }, [])

  useEffect(() => {
    if (!credentials) { pendingAdd.current = null; return }
    const controller = new AbortController()
    let current = true
    setBusy(true); locked.current = true
    apiRef.current.read(credentials, controller.signal).then(value => { if (current) setSession(value) })
      .catch(cause => { if (current) { setNeedsReload(true); setError(cause instanceof Error ? cause.message : '恢复失败，请重新读取。') } })
      .finally(() => { if (current) { setBusy(false); locked.current = false } })
    return () => { current = false; controller.abort() }
  }, [credentials])

  async function refresh(c = credentials) {
    if (c) { setSession(await apiRef.current.read(c)); setNeedsReload(false) }
  }
  async function afterWrite() {
    try { await refresh() } catch { setNeedsReload(true); throw new Error('操作已保存，但最新资料读取失败。请重新读取，勿重复提交。') }
  }
  async function run(operation: () => Promise<void>) {
    if (locked.current) return false
    locked.current = true; setBusy(true); setError(''); setNotice('')
    try { await operation(); return true } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409 && cause.code !== 'idempotency_payload_mismatch') {
        setNeedsReload(true)
        try { await refresh(); setError('发生冲突，已读取最新资料。你的未保存输入仍保留，请对照新内容重新审核后操作。') }
        catch { setError('发生冲突，最新资料读取失败。请先重新读取，勿重复提交。') }
      } else {
        if (cause instanceof ApiError && [401, 404].includes(cause.status)) setSession(null)
        setError(cause instanceof Error ? cause.message + (cause instanceof ApiError && cause.retryAt > Date.now() ? ` 请等待 ${Math.ceil((cause.retryAt - Date.now()) / 1000)} 秒后手动重试。` : '') : '操作未完成，请重试。')
      }
      return false
    } finally { locked.current = false; setBusy(false) }
  }
  async function create() {
    if (creationBlocked) return
    if (pending && !createRetry) throw new Error('创建结果不确定，请先恢复刚才的创建操作。不会自动新建。')
    const p = pending ?? await newPending(raw)
    await checkBody(p, raw)
    storePending(p); setPending(p)
    try { adopt(await apiRef.current.create(raw, p), p) }
    catch (cause) {
      if (cause instanceof ApiError && cause.status === 410) blockExpiredCreate()
      if (cause instanceof ApiError && cause.status < 500) throw cause
      try {
        const data = await apiRef.current.recover(p)
        adopt(data, p)
        setError('创建响应未收到，已恢复刚才的会话，请核对资料。')
      } catch (recovery) {
        if (recovery instanceof ApiError && recovery.code === 'idempotency_creation_not_found') setCreateRetry(true)
        if (recovery instanceof ApiError && recovery.status === 410) blockExpiredCreate()
        throw recovery
      }
    }
  }
  async function recover() {
    if (!pending) return
    try {
      adopt(await apiRef.current.recover(pending), pending)
      setError('已通过只读查询恢复刚才的会话，请核对资料。')
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === 'idempotency_creation_not_found') setCreateRetry(true)
      if (cause instanceof ApiError && cause.status === 410) blockExpiredCreate()
      throw cause
    }
  }
  async function add() {
    if (!credentials || !session) return
    if (pendingAdd.current && pendingAdd.current.content !== statement) throw new Error('上次补充结果不确定。请重新读取核对，再恢复上次补充输入重试；不会换键重复写入。')
    if (!pendingAdd.current && sourceTurn && session.turns.find(t => t.id === sourceTurn)?.content !== statement) throw new Error('当前陈述与所选补充回合不同。请选择新的补充输入，记录当前陈述的真实来源。')
    if (!pendingAdd.current) {
      const turnKey = sourceTurn ? undefined : (await operation(credentials.token, 'add_turn', `session:${credentials.sessionId}`, { content: statement })).key
      pendingAdd.current = { content: statement, turnKey, turnId: sourceTurn || undefined }
    }
    const p = pendingAdd.current
    if (!p.turnId) p.turnId = (await apiRef.current.turn(credentials, p.content, p.turnKey!)).id
    if (!p.factKey) p.factKey = (await operation(credentials.token, 'add_fact', `project:${session.projects[0].id}`, { statement: p.content, source_turn_ids: [p.turnId] })).key
    await apiRef.current.add(credentials, session.projects[0].id, p.content, p.turnId, p.factKey)
    pendingAdd.current = null; setSourceTurn(''); setStatement(''); await afterWrite()
  }
  async function mutate(fact: Fact, body: Mutation) {
    if (!credentials) return
    await apiRef.current.mutate(credentials, fact.id, body); await afterWrite()
  }
  async function endSession() {
    if (!credentials || !session || needsReload || session.status !== 'active') return
    setSession(await apiRef.current.end(credentials))
    setEndPrompt(false)
    setNotice('会话已结束，仍可查看、导出或删除。')
  }
  async function deleteSession() {
    if (!credentials || !session || needsReload) return
    await apiRef.current.remove(credentials)
    try { sessionStorage.removeItem(SESSION_KEY); clearPending(); setPending(null) } catch { /* Storage may be disabled. */ }
    setSession(null); setCredentials(null); setDeletePrompt(false); setEndPrompt(false)
    setRaw(''); setSourceTurn(''); setStatement(''); pendingAdd.current = null; setNotice('会话及其资料已删除。')
  }
  const readonly = session?.status === 'ended'
  const managementBlocked = busy || needsReload || !session
  const confirmed = session?.facts.filter(f => ['user_confirmed', 'evidence_supported'].includes(f.status)).length ?? 0
  const unusedTurns = session?.turns.filter((turn, i) => i > 0 && turn.role === 'user' && !session.facts.some(f => f.original_source_turn_ids.includes(turn.id))) ?? []
  return <div className="page">
    <header className="header"><a className="brand" href="#"><span className="brand-symbol">✦</span>启程 <span className="brand-en">Pathwise</span></a><span className="stage">真实经历库 · 开发版</span></header>
    {intro}
    <main className="workspace"><div className="page-heading"><p className="eyebrow">YOUR EXPERIENCE, YOUR WORDS</p><h1>让真实经历，成为你的底气。</h1><p className="intro">从一句自述开始，逐条整理、核对与确认。每一条事实，都能回到它的来源。</p></div>
      <div className="principles"><span>01 记录经历</span><span>02 核对事实</span><span>03 保存与复用</span></div>
      {error && <div className="alert" role="alert">{error}</div>}{notice && <p className="notice" role="status">{notice}</p>}{busy && <p role="status" className="loading">正在与经历库同步…</p>}
      {session && !readonly && unusedTurns.length > 0 && <section className="card"><label htmlFor="source-turn">继续已有补充回合</label><p>这些用户自述尚未引用到事实。核对后可明确选用，避免重复录入；不会自动提交。</p><select id="source-turn" value={sourceTurn} disabled={busy || needsReload || Boolean(pendingAdd.current)} onChange={e => { setSourceTurn(e.target.value); const turn = unusedTurns.find(t => t.id === e.target.value); if (turn) setStatement(turn.content) }}><option value="">使用新的补充输入</option>{unusedTurns.map(turn => <option key={turn.id} value={turn.id}>{turn.content.slice(0, 80)}</option>)}</select></section>}
      {pendingAdd.current && !readonly && <button className="secondary" disabled={busy} onClick={() => setStatement(pendingAdd.current!.content)}>恢复上次补充输入</button>}
      {!credentials ? <section className="card start-card"><p className="eyebrow">从这里开始</p><h2>你做过的一件事</h2><p>课程项目、实习、比赛或校园实践都可以。不需要先写得专业。</p>
        {pending && <div className="conflict-note"><p>刚才的创建结果可能已经保存。请先恢复；刷新不会自动重新创建，原正文未写入浏览器暂存。</p><button className="secondary" disabled={busy || creationBlocked} onClick={() => void run(recover)}>恢复刚才的创建操作</button></div>}
        <form onSubmit={e => { e.preventDefault(); void run(create) }}><label htmlFor="raw">原始经历</label><textarea id="raw" value={raw} onChange={e => setRaw(e.target.value)} maxLength={10000} required disabled={busy || creationBlocked} placeholder="例如：做过一个课程任务管理工具，负责界面和数据展示。" /><div className="form-foot"><small>原始自述会保留，后续编辑不会覆盖它。</small><button disabled={busy || creationBlocked || !raw.trim() || Boolean(pending && !createRetry)}>{pending ? '用原输入重试创建' : '创建经历会话 →'}</button></div></form>
        {creationBlocked && <button className="secondary" disabled={busy} onClick={() => { try { clearPending(); setPending(null); setCreationBlocked(false); setCreateRetry(false); setError(''); setNotice('已明确选择新操作；之前的未知会话没有被删除。') } catch { setError('浏览器暂存不可用，不能安全创建。') } }}>我已核对，开始新操作</button>}
        <p className="footnote">24 小时仅为本标签页的临时创建恢复窗口，不是账号或长期档案恢复。到期、关闭标签页或清空暂存后，匿名会话可能无法找回。</p>
        <p className="footnote">本阶段由你手动整理事实，尚未接入 AI。会话凭证仅在当前标签页暂存；关闭标签页后不保证恢复。</p>
      </section> : <>
        <div className="session-bar"><div><span className={`pill ${readonly ? '' : 'green'}`}>{readonly ? '已结束 · 只读' : '整理中'}</span><span className="session-summary">{confirmed} / {session?.facts.length ?? 0} 条已确认</span></div><div className="button-row">
          <button className="secondary" disabled={busy} onClick={() => void run(() => refresh())}>重新读取</button>
          <button className="secondary" disabled={busy || !session} onClick={() => void run(async () => { const value = await apiRef.current.export(credentials); download(value, `pathwise-${credentials.sessionId}.json`); setNotice('已导出完整会话资料。请妥善保管下载文件。') })}>导出资料</button>
          <button className="secondary" disabled={managementBlocked || readonly} onClick={() => { setDeletePrompt(false); setEndPrompt(true) }}>结束会话</button>
          <button className="danger" disabled={managementBlocked} onClick={() => { setEndPrompt(false); setDeletePrompt(true) }}>删除会话</button></div></div>
        {endPrompt && <section className="card" aria-label="结束确认"><h2>确认结束这次会话？</h2><p>结束后会话只读，无法重新开启或继续新增、编辑事实。仍可查看、导出或删除资料。</p><div className="button-row"><button disabled={managementBlocked || readonly} onClick={() => void run(endSession)}>确认结束会话</button><button className="secondary" disabled={busy} onClick={() => setEndPrompt(false)}>取消结束</button></div></section>}
        {deletePrompt && <section className="delete-panel" aria-label="删除确认"><h2>永久删除这次会话？</h2><p>原始自述、事实、材料依据和历史记录将一起删除，无法恢复。建议先导出。</p><div className="button-row"><button className="danger" disabled={managementBlocked} onClick={() => void run(deleteSession)}>确认永久删除</button><button className="secondary" disabled={busy} onClick={() => setDeletePrompt(false)}>取消删除</button></div></section>}
        {!session ? <section className="card"><h2>正在恢复你的会话</h2><p>资料从服务端读取。连接失败时可重新读取；如凭证失效，可清除本页暂存重新开始。</p><button className="secondary" disabled={busy} onClick={() => { try { sessionStorage.removeItem(SESSION_KEY) } catch { /* Storage may be disabled. */ } setCredentials(null); setError(''); setNotice('已清除本页凭证；没有删除服务端资料。') }}>清除本页凭证</button></section> : <div className="workspace-grid">
          <aside className="context-column"><section className="card"><p className="eyebrow">原始自述</p><h2>经历的起点</h2>{session.projects.map(p => <p className="original" key={p.id}>{p.raw_input}</p>)}<small>原始内容保留在这里，事实编辑另记来源。</small></section>
            <section className="card"><h2>补充一条事实</h2><p>写你亲手做过的事。每条补充会先记录为用户自述，再进入待确认列表。</p><form onSubmit={e => { e.preventDefault(); void run(add) }}><label htmlFor="statement">新的事实陈述</label><textarea id="statement" value={statement} onChange={e => setStatement(e.target.value)} maxLength={10000} required disabled={busy || readonly || needsReload} placeholder="例如：我负责任务列表页面，以及筛选交互。" /><button disabled={busy || readonly || needsReload || !statement.trim() || !session.projects.length}>新增待确认事实</button></form>{readonly && <small>已结束的会话不能新增或编辑。</small>}</section>
            <section className="card guide"><h2>确认 ≠ 独立认证</h2><p>“用户确认”表示你的自述；“材料辅助核实”表示你提供材料并自行核实。平台不作独立认证。</p><small>开发期请使用合成资料。此页没有 AI 自动提取或生成。</small></section></aside>
          <section className="facts-column" aria-label="事实确认列表"><div className="section-heading"><div><p className="eyebrow">逐条核对</p><h2>你的事实清单</h2></div><span className="pill">{session.facts.length} 条事实</span></div>
            {!session.facts.length && <div className="card empty"><span className="empty-mark">✦</span><h3>每一条事实，都从你开始</h3><p>在左侧补充一条具体陈述，然后确认、修正或拒绝。</p></div>}
            {session.facts.map((fact, i) => <FactCard key={fact.id} fact={fact} index={i + 1} session={session} disabled={busy || readonly || needsReload} onMutate={body => run(() => mutate(fact, body))} />)}</section></div>}
      </>}
      <footer className="footnote">经历可以更清晰，事实不能凭空增加。 · Pathwise</footer></main></div>
}

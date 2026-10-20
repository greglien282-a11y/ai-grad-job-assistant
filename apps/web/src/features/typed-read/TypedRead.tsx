import { useEffect, useRef, useState } from 'react'
import { createReadApi, ReadError, validateAccess, type FactV3, type ReadAccess } from '../../lib/experience-read'
import type { ExperienceSummaryV2 } from '../../lib/experience-read-contract'
import './TypedRead.css'

const api = createReadApi((...args) => fetch(...args))
const kinds = { legacy_unspecified: '未分类', personal_action: '个人行动', plan: '计划', background: '背景', boundary: '边界' }
const stages = { legacy_unknown: '进度未知', completed: '已完成', in_progress: '进行中', planned: '计划中', not_applicable: '不适用' }
const statuses = { pending: '待审核', user_confirmed: '用户确认', evidence_supported: '用户提供材料支持', rejected: '已拒绝' }
const reasons = { classification_unreviewed: '分类尚未审核', action_in_progress: '行动仍在进行', plan_not_contribution: '计划不属于已完成成果', background_context: '背景资料', boundary_limitation: '边界说明' }
const message = (e: unknown) => e instanceof ReadError ? e.message : '暂时无法安全读取完整资料。'
function Fact({ f }: { f: FactV3 }) {
  return <article aria-label={`事实 ${f.id}`}>
    <p className="typed-original">{f.statement}</p>
    <p>{statuses[f.status]} · {kinds[f.fact_kind]} · {stages[f.progress_stage]} · 版本 {f.version}</p>
    {f.classification_contract === 'legacy-v0' && <p>legacy 未分类：保留旧资料，不表示已判断为完成。</p>}
  </article>
}
function Sources({ f }: { f: FactV3 }) {
  return <section aria-label="事实来源详情"><h2>独立事实 v3 · 来源详情</h2><Fact f={f} />
    <h3>当前文字来源</h3><p>{f.source_kind === 'user_edit' ? '后续用户编辑' : '原始建档文字'}</p>
    <ul>{f.current_statement_source_turn_ids.map(id => <li key={id}>Turn {id}</li>)}</ul>
    {f.current_statement_citations.length === 0 && <p>暂无当前文字的精确引用记录。</p>}
    {f.current_statement_citations.map((q, i) => <blockquote key={i}><p className="typed-original">{q.quote}</p><p>Unicode code-point [{q.start}, {q.end}) · Turn {q.turn_id}</p></blockquote>)}
    <h3>原始建档来源</h3><ul>{f.original_source_turn_ids.map(id => <li key={id}>Turn {id}</li>)}</ul>
    {f.current_statement_citations.filter(q => q.source_kind === 'original_source').map((q, i) => <blockquote key={i}><p className="typed-original">{q.quote}</p><p>建档原始引用 · Unicode code-point [{q.start}, {q.end})</p></blockquote>)}
    <p>建档来源与当前文字来源分别记录；完整原始引用与历史保留在技术备份中。</p>
    <h3>分类依据</h3><p>暂无分类依据记录</p><p>{f.classification_basis_status === 'legacy_unclassified' ? 'legacy 未分类' : 'not_recorded'}；文字引用不等于分类证据。</p>
  </section>
}
export default function TypedRead() {
  const [access, setAccess] = useState<ReadAccess>({ sessionId: '', projectId: '', token: '' })
  const [summary, setSummary] = useState<ExperienceSummaryV2 | null>(null)
  const [detail, setDetail] = useState<FactV3 | null>(null)
  const [fid, setFid] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => { generation.current++; controller.current?.abort() }, [])
  function change(key: keyof ReadAccess, value: string) {
    generation.current++; controller.current?.abort(); setBusy(false); setSummary(null); setDetail(null); setError(''); setFid('')
    setAccess(a => ({ ...a, [key]: value }))
  }
  async function run(action: 'summary' | 'fact' | 'export', id = fid) {
    const g = ++generation.current
    controller.current?.abort(); const abort = new AbortController(); controller.current = abort
    setError(''); setBusy(true); setDetail(null)
    if (action === 'summary') setSummary(null)
    try {
      validateAccess(access)
      if (action === 'summary') {
        const value = await api.summary(access, abort.signal)
        if (g === generation.current) setSummary(value)
      } else if (action === 'fact') {
        const value = await api.fact(access, id, abort.signal)
        const expected = summary && [...summary.confirmed, ...summary.pending, ...summary.reviewed_non_contributions.map(e => e.fact)].find(f => f.id === id)
        if (expected && JSON.stringify(value) !== JSON.stringify(expected)) throw new ReadError('conflict')
        if (g === generation.current) setDetail(value)
      } else {
        const value = await api.export(access, abort.signal)
        if (summary && (value.data.context_revision !== summary.context_revision ||
          [...summary.confirmed, ...summary.pending, ...summary.reviewed_non_contributions.map(e => e.fact)].some(f =>
            !value.data.facts.some(other => JSON.stringify(other) === JSON.stringify(f))))) throw new ReadError('conflict')
        if (g !== generation.current) return
        const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
        const a = document.createElement('a'); a.href = url; a.download = `pathwise-v2-${access.sessionId}.json`; a.click(); URL.revokeObjectURL(url)
      }
    } catch (e) { if (g === generation.current) { setSummary(null); setDetail(null); setError(message(e)) } }
    finally { if (g === generation.current) setBusy(false) }
  }
  return <main className="typed-read"><h1>类型化资料 · 只读预览</h1>
    <p>独立读取入口。用户确认和用户提供材料支持均不代表平台独立认证。此页不提供审核、编辑或模型提交。</p>
    <p>凭证仅用于当前页面内存，不写入地址或浏览器存储。</p>
    <form onSubmit={e => { e.preventDefault(); void run('summary') }}>
      <label>会话 ID<input value={access.sessionId} onChange={e => change('sessionId', e.target.value)} autoComplete="off" /></label>
      <label>项目 ID<input value={access.projectId} onChange={e => change('projectId', e.target.value)} autoComplete="off" /></label>
      <label>会话凭证<input type="password" value={access.token} onChange={e => change('token', e.target.value)} autoComplete="off" /></label>
      <button disabled={busy}>读取新版资料</button>
    </form>
    {busy && <p role="status">正在只读获取资料…</p>}{error && <p role="alert">{error} 本次没有保存或修改资料。</p>}
    {summary && <><p>summary v2 · revision {summary.context_revision}</p>
      <h2>可进入贡献正文的已审核事实</h2>{summary.incomplete && <p>暂无符合正文资格的事实。</p>}
      {summary.confirmed.map(f => <div key={f.id}><Fact f={f} /><button disabled={busy} onClick={() => void run('fact', f.id)}>查看来源 {f.id}</button></div>)}
      <h2>待审核事实</h2>{summary.pending.map(f => <div key={f.id}><Fact f={f} /><button disabled={busy} onClick={() => void run('fact', f.id)}>查看来源 {f.id}</button></div>)}
      <h2>已审核的非成果资料</h2>{summary.reviewed_non_contributions.map(e => <div key={e.fact.id}><Fact f={e.fact} /><p>{reasons[e.reason]}</p><button disabled={busy} onClick={() => void run('fact', e.fact.id)}>查看来源 {e.fact.id}</button></div>)}
      <p>已拒绝事实不进入上述列表。已知事实 ID 可单独只读核对；技术备份保留全部状态。</p>
      <label>单独核对事实 ID<input value={fid} onChange={e => { generation.current++; controller.current?.abort(); setBusy(false); setDetail(null); setFid(e.target.value) }} autoComplete="off" /></label>
      <button disabled={busy} onClick={() => void run('fact')}>读取独立事实</button>
      <p>技术备份含完整原文、历史、来源及已拒绝资料，可能包含私人信息；它不是正式简历。</p>
      <button disabled={busy} onClick={() => void run('export')}>下载技术备份 v2</button>
    </>}{detail && <Sources f={detail} />}
  </main>
}

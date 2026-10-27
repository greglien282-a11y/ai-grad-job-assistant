import { useState, type ReactNode } from 'react'
import { validate, adjustRequirement, admission, emptyReview, printable, provenance, questions, setJob, strategies, type Draft, type Entry } from './draft'
import { visionJD } from './fixtures'

const priorities = { must: '必备', bonus: '加分', uncertain: '待核实' }
export default function DraftStudio({ value: d, onChange, onUndo, canUndo, paper }: { value: Draft; onChange: (d: Draft) => void; onUndo: () => void; canUndo: boolean; paper?: ReactNode }) {
  const [view, setView] = useState<'resume' | 'review'>('resume')
  const [rawJD, setRawJD] = useState(d.job?.raw ?? ''), [error, setError] = useState('')
  const revise = (patch: Partial<Draft>) => { onChange(validate({ ...d, ...patch, review: emptyReview() })); setError('') }
  function adjust(id: string, patch: Parameters<typeof adjustRequirement>[2]) { try { onChange({ ...adjustRequirement(d, id, patch), review: emptyReview() }); setError('') } catch { setError('条件调整包含不受支持的内容，未应用。') } }
  function edit(id: string, patch: Partial<Entry>) {
    revise({ entries: d.entries.map(e => { if (e.id !== id) return e; const next = { ...e, ...patch }; return { ...next, state: next.text === next.original ? 'original' : 'user_edited' } }) })
  }
  function move(id: string, delta: number) { const entries = [...d.entries], index = entries.findIndex(e => e.id === id), next = index + delta; if (next < 0 || next >= entries.length) return; [entries[index], entries[next]] = [entries[next], entries[index]]; revise({ entries }) }
  const shown = printable(d), qs = questions(d), q = qs[d.review.step - 1]
  function advance(skip: boolean) {
    const answers = [...d.review.answers] as Draft['review']['answers']; if (skip) answers[d.review.step - 1] = ''
    onChange({ ...d, review: { answers, step: Math.min(3, d.review.step + 1), complete: d.review.step === 3 } })
  }
  return <>
    <section className="resume-panel" aria-label="岗位策略"><p className="resume-kicker">02 / READ THE ROLE, KEEP THE EVIDENCE</p><h2>为一个岗位做选择</h2><p>要求保留JD原文。字面关联不是AI语义匹配；缺少记录不等于没有能力。真实能力缺口只能由用户明确自评。</p>
      <button className="secondary" onClick={() => { setRawJD(visionJD); revise({ job: null, assessments: [] }) }}>填入视觉算法实习 JD</button>
      <label>目标岗位原文<textarea value={rawJD} maxLength={24000} onChange={e => { setRawJD(e.target.value); revise({ job: null, assessments: [] }) }} /></label>
      <button onClick={() => { try { onChange(setJob(d, rawJD)); setError('') } catch { setError('岗位原文为空、过长或含不安全字符，停止分析；没有上传。') } }}>分析本地岗位</button>
      {error && <p role="alert">{error}</p>}
      {d.job && <><h3>{d.job.title}</h3><div className="strategy-grid">{Object.entries(priorities).map(([priority, label]) => <section key={priority} aria-label={`${label}岗位条件`}><h3>{label}</h3>{strategies(d).filter(s => s.requirement.priority === priority).map(({ requirement: r, matches, label: result, explanation }) => <article key={r.id} className="resume-card">
        <label>条件描述 {r.id}<input value={r.text} onChange={e => adjust(r.id, { text: e.target.value })} /></label>
        <label>条件分组 {r.id}<select value={r.priority} disabled={r.conflict} onChange={e => adjust(r.id, { priority: e.target.value as typeof r.priority })}>{Object.entries(priorities).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
        <blockquote>{r.quote}</blockquote><small>JD原文 [{r.start}, {r.end}){r.adjusted && ' · 用户调整，原引文未变'}{r.conflict && ' · 冲突条件不可强行确认为必备'}</small>
        <label>我的判断 {r.id}<select value={d.assessments.find(a => a.requirement_id === r.id)!.state} onChange={e => revise({ assessments: d.assessments.map(a => a.requirement_id === r.id ? { ...a, state: e.target.value as typeof a.state } : a) })}><option value="needs_evidence">需要补充证据</option><option value="can_explain">我能直接说明（仍须来源支持）</option><option value="gap">我明确未掌握 / 未做过</option></select></label>
        <strong>{result}</strong><p>{explanation}</p>{matches.map(e => <details key={e.id}><summary>字面来源：{e.original.slice(0, 45)}</summary><blockquote>{e.original}</blockquote><small>{provenance(d, e)}</small><p>{admission(d, e).reason}</p></details>)}
      </article>)}</section>)}</div></>}
    </section>
    <section className="resume-panel" aria-label="原文与岗位草稿"><p className="resume-kicker">03 / WRITE YOUR OWN DRAFT</p><h2>原文对照，用户负责核对</h2><p>这是独立的用户自述简历草稿，编辑可进入此草稿打印，但绝不进入原受限可信预览或回写Fact。计划、团队、否定边界保留；不自动生成技术或指标。</p><button className="secondary" disabled={!canUndo} onClick={onUndo}>撤销上一步（拒绝记录保留）</button>
      {d.entries.map((e, i) => { const a = admission(d, e); return <article className="resume-card resume-columns" key={e.id} aria-label={`原文对照条目 ${i + 1}`}><div><h3>原始片段 {i + 1}</h3><blockquote>{e.original}</blockquote><small>{provenance(d, e)}</small><p>{e.source_kind === 'user_manual_statement' ? '用户手工声明，无导入引用' : '本地导入原文，未审核'}</p></div><div>
        <label><input type="checkbox" checked={e.selected} disabled={a.kind === 'blocked' && !e.selected} onChange={event => edit(e.id, { selected: event.target.checked })} />选用条目 {i + 1}</label>
        <label>岗位草稿 {i + 1}<textarea value={e.text} maxLength={40000} onChange={event => edit(e.id, { text: event.target.value })} /></label><p>{e.state === 'user_edited' ? '用户改写草稿 · 未核实' : '原文未改 · 仍未核实'}</p><p>{a.reason}</p>
        <div className="resume-actions"><button className="secondary" disabled={i === 0} onClick={() => move(e.id, -1)}>上移条目 {i + 1}</button><button className="secondary" disabled={i === d.entries.length - 1} onClick={() => move(e.id, 1)}>下移条目 {i + 1}</button><button className="secondary" onClick={() => edit(e.id, { text: e.original })}>恢复原文 {i + 1}</button><button className="secondary" disabled={d.rejected_statements.includes(e.original)} onClick={() => revise({ rejected_statements: [...new Set([...d.rejected_statements, e.original])] })}>拒绝本地条目 {i + 1}</button></div>
      </div></article> })}
      {d.rejected_statements.length > 0 && <details><summary>保留的本地拒绝记录（不是正式FactChange历史）</summary>{d.rejected_statements.map(s => <blockquote key={s}>{s}</blockquote>)}<p>精确原句保护不解决数字/同义/新来源的R03语义问题。刷新或篡改本地文件后无法证明历史完整。</p></details>}
    </section>
    <section className="resume-panel" aria-label="用户草稿打印"><div className="resume-actions"><label>排版密度<select value={d.layout} onChange={e => onChange(validate({ ...d, layout: e.target.value as Draft['layout'] }))}><option value="comfortable">舒展</option><option value="compact">紧凑</option></select></label><button disabled={!shown.length} onClick={() => window.print()}>打印用户草稿 / 保存 PDF</button></div>
      <p>打印的是用户自述简历，由用户核对；不是平台认证。来源、修改及限制可在来源审查中逐项查看，两种视图使用相同准入规则。</p>
      <div className="resume-actions" aria-label="输出视图"><button aria-pressed={view === 'resume'} onClick={() => setView('resume')}>简历输出</button><button aria-pressed={view === 'review'} onClick={() => setView('review')}>来源审查</button></div>
      <div className={view === 'review' ? 'resume-output review-active' : 'resume-output'}>
      {paper ?? <article className={`local-resume-paper ${d.layout}`} aria-label="用户自述简历草稿"><p className="paper-label">PATHWISE · 用户自述草稿 / 未经平台核实</p><h2>{d.job?.title ?? '岗位简历草稿'}</h2>
        {(['draft', 'context'] as const).map(kind => { const list = shown.filter(e => admission(d, e).kind === kind); return list.length > 0 && <section key={kind}><h3>{kind === 'draft' ? '经历与技能 · 用户自述' : '背景、计划与限制 · 不是已完成个人贡献'}</h3>{list.map(e => <div className="paper-entry" key={e.id}><p>{e.text}</p></div>)}</section> })}
        {!shown.length && <p>没有选用且可安全展示的条目，保持空白。</p>}<footer>用户自述，内容由本人核对。</footer>
      </article>}</div>
      {view === 'review' && <section className="source-review" aria-label="来源审查详情"><h3>原文、用户修改与岗位依据</h3><p>全部内容均为用户自述，未核实。计划和团队责任不能因改写而消失；被阻断条目不进入简历输出。</p>{d.entries.map(e => <article className="resume-card" key={e.id}><p>{admission(d, e).reason}</p><blockquote>原始片段：{e.original}</blockquote><p>当前文字：{e.text}</p><p>{e.state === 'user_edited' ? `用户改写；原文：${e.original}` : '保留原文；用户自述未核实'}</p><small>{provenance(d, e)}</small>{strategies(d).filter(s => s.matches.some(x => x.id === e.id)).map(s => <blockquote key={s.requirement.id}>JD原句：{s.requirement.quote} [{s.requirement.start}, {s.requirement.end})</blockquote>)}</article>)}</section>}
    </section>
    <section className="resume-panel" aria-label="岗位三题复习"><p className="resume-kicker">04 / BE READY TO EXPLAIN</p><h2>准备解释你写下的每一句</h2><p>问题只绑定本次可打印条目和岗位引文；回答是用户回忆草稿，不是证据或标准答案。</p>
      {d.review.step === 0 && <button disabled={qs.length !== 3} onClick={() => onChange({ ...d, review: { ...emptyReview(), step: 1 } })}>开始岗位三题</button>}
      {!d.review.complete && q && <><p>第 {d.review.step} / 3 题</p><h3>{q.prompt}</h3><blockquote>岗位依据：{q.requirement.quote}</blockquote><blockquote>当前草稿：{q.entry.text}</blockquote><blockquote>原始片段：{q.entry.original}</blockquote><small>{q.provenance}</small><label>我的复习回答<textarea value={d.review.answers[d.review.step - 1]} onChange={e => { const answers = [...d.review.answers] as Draft['review']['answers']; answers[d.review.step - 1] = e.target.value; onChange({ ...d, review: { ...d.review, answers } }) }} /></label><div className="resume-actions"><button onClick={() => advance(false)}>{d.review.step === 3 ? '完成岗位复习' : '下一道岗位问题'}</button><button className="secondary" onClick={() => advance(true)}>跳过岗位问题</button></div></>}
      {d.review.complete && <div role="status"><h3>三题复盘 · 不猜经历、不打分</h3><p>已记录 {d.review.answers.filter(a => a.trim()).length} 条用户回忆，未用于确认或补写事实。</p><button className="secondary" onClick={() => onChange({ ...d, review: emptyReview() })}>重新准备三题</button></div>}
    </section>
  </>
}

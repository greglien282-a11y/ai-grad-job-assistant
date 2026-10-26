import { useMemo, useState } from 'react'
import { analyzeJD } from './jd'
import type { Category, Job, Priority } from './jd'
import { deduplicate, matchRequirements, printableText, reviewQuestions } from './policy'
import { exampleJD, samples } from './fixtures'
import './JdLab.css'

const priorities = { must: '必备条件', bonus: '加分条件', uncertain: '待人工判断' }
const categories = { technical: '技术要求', education: '学历 / 专业', experience: '经验要求', other: '其他条件' }
const statusLabel = { pending: '待审核', user_confirmed: '用户自述确认', evidence_supported: '用户材料支持', rejected: '已拒绝' }
export default function JdLab() {
  const [raw, setRaw] = useState(''), [job, setJob] = useState<Job | null>(null), [error, setError] = useState('')
  const [selected, setSelected] = useState<string[]>([]), [drafts, setDrafts] = useState<Record<string, string>>({})
  const [review, setReview] = useState<number | null>(null), [responses, setResponses] = useState<Record<number, string>>({}), [finished, setFinished] = useState(false)
  const evidence = useMemo(() => deduplicate(samples), [])
  const usable = evidence.filter(e => e.bucket === 'usable' && e.fact)
  const matches = matchRequirements(job?.requirements ?? [], evidence)
  const chosen = selected.flatMap(id => usable.find(e => e.fact!.id === id)?.fact ?? [])
  const originalChosen = chosen.filter(f => printableText(f.statement, drafts[f.id] ?? f.statement) !== null)
  const questions = reviewQuestions(originalChosen, job?.requirements ?? [])
  function resetPreview() { setSelected([]); setDrafts({}); setReview(null); setResponses({}); setFinished(false) }
  function analyze() {
    try {
      const next = analyzeJD(raw); setJob(next); setError(''); resetPreview()
      const matched = matchRequirements(next.requirements, evidence).flatMap(m => m.usable.map(e => e.fact!.id))
      setSelected([...new Set(matched)])
    } catch (cause) { setJob(null); resetPreview(); setError(cause instanceof Error ? cause.message : '无法安全解析，请人工核对。') }
  }
  function move(id: string) {
    const index = selected.indexOf(id)
    if (index < 1) return
    const next = [...selected]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; setSelected(next)
  }
  return <div className="jd-lab">
    <header className="jd-header"><a href="/" className="jd-brand">✦ 启程 <span>Pathwise</span></a><span className="jd-badge">M2 · 本地产品实验室</span><a href="#jd-review">三题快速复习 ↗</a></header>
    <main>
      <section className="jd-hero"><div><p className="jd-eyebrow">ONE ROLE. YOUR REAL EXPERIENCE.</p><h1>看懂这个岗位，<br />讲清你做过的事。</h1><p>先找证据，再选内容。让每一条简历，都能回到经历的原话。</p></div><aside><span>本轮旅程</span><ol><li>岗位要求与原文</li><li>经历证据与缺口</li><li>简历对比与复习</li></ol></aside></section>
      <p className="jd-scope" role="note">离线开发预览 · 经历全部为公开合成样例 · 输入与编辑仅保留在内存，刷新即清除 · 无数据库、模型、正式保存或自动请求。请勿填写真实招聘资料。用户自述确认 / 用户材料支持均不代表平台独立认证。</p>
      <section className="jd-input jd-panel" aria-labelledby="jd-input-heading"><div><p className="jd-eyebrow">01 / READ THE ROLE</p><h2 id="jd-input-heading">粘贴岗位描述</h2><p>使用有限词汇与确定性分句。没有把握的条件，留给你判断。</p><button className="jd-secondary" onClick={() => { setRaw(exampleJD); setJob(null); resetPreview(); setError('') }}>使用合成 JD 样例</button></div><form onSubmit={e => { e.preventDefault(); analyze() }}><label htmlFor="jd-raw">岗位 JD 原文</label><textarea id="jd-raw" value={raw} maxLength={12000} placeholder="岗位名称、职责和任职要求…" onChange={e => { setRaw(e.target.value); setJob(null); resetPreview(); setError('') }} /><div className="jd-form-foot"><small>{Array.from(raw).length} / 12000 code points · 不自动分析</small><button type="submit">分析岗位要求 →</button></div></form></section>
      {error && <p role="alert" className="jd-error">{error}</p>}
      {job && <>
        <section className="jd-panel" aria-label="结构化岗位要求"><p className="jd-eyebrow">02 / REQUIREMENTS & EVIDENCE</p><h2>{job.title}</h2><p>每项保留 JD 原句。手动调整只改变本地求职策略，不改变经历事实。字面相关不代表完全满足要求；不输出匹配百分比。</p><details><summary>查看完整岗位原文</summary><pre>{job.raw}</pre></details>
          <div className="jd-requirements">{matches.map(({ requirement: r, usable: available, review: uncertain, excluded, conclusion }) => <article key={r.id} className="jd-requirement">
            <div className="jd-tags"><span>{categories[r.category]}</span><span className={r.priority}>{priorities[r.priority]}</span>{r.adjusted && <span>用户调整，未重新认证 JD 含义</span>}{r.conflict && <span>要求存在冲突</span>}</div>
            <label>要求描述<input aria-label={`要求描述 ${r.id}`} value={r.text} onChange={e => { setJob({ ...job, requirements: job.requirements.map(x => x.id === r.id ? { ...x, text: e.target.value, adjusted: true } : x) }); setReview(null); setFinished(false) }} /></label>
            <div className="jd-selects"><label>条件优先级<select aria-label={`条件优先级 ${r.id}`} value={r.priority} onChange={e => setJob({ ...job, requirements: job.requirements.map(x => x.id === r.id ? { ...x, priority: e.target.value as Priority, adjusted: true } : x) })}>{Object.entries(priorities).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label><label>要求分类<select aria-label={`要求分类 ${r.id}`} value={r.category} onChange={e => setJob({ ...job, requirements: job.requirements.map(x => x.id === r.id ? { ...x, category: e.target.value as Category, adjusted: true } : x) })}>{Object.entries(categories).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label></div>
            <blockquote>{r.quote}</blockquote><small>JD 原文 [{r.start}, {r.end}) · Unicode code-point</small><p className="jd-conclusion">{conclusion}</p>
            {available.map(e => <p key={e.fact!.id}>可选原句：{e.fact!.statement}</p>)}
            {uncertain.map(e => <p key={e.fact!.id}>可能相关 / 需核实：{e.fact!.statement} — {e.reason}</p>)}
            {excluded.length > 0 && <small>{excluded.length} 条相关资料不属于已完成贡献，不纳入正文。</small>}
          </article>)}</div>
        </section>
        <section className="jd-panel" aria-label="合成经历与来源"><h2>经历有边界，证据要分开</h2><p>FactV3 保持原合同：classification_citations 为空，分类依据未记录。另附的 G2.1 合成声明包只服务本地预览；不是正式事实分类依据写入，也不提升真实简历资格。</p>
          <div className="jd-evidence">{evidence.map((e, i) => <article key={e.fact?.id ?? i}><div className="jd-tags"><span>{e.fact ? statusLabel[e.fact.status] : '合同不可用'}</span><span>{e.fact?.fact_kind} / {e.fact?.progress_stage}</span></div><h3>{e.fact?.statement ?? '不展示损坏正文'}</h3><p>{e.reason}</p><details><summary>核对原话与分类来源</summary><p>来源 Fact：{e.fact?.id}</p><p>旧事实读取：{e.fact?.classification_basis_status === 'legacy_unclassified' ? 'legacy 未分类' : '暂无分类依据记录'}</p>{e.declaration ? <><p>独立合成分类声明：用户选择记录，不是平台认证</p>{e.declaration.turns.map(t => <blockquote key={t.id}>{t.content}</blockquote>)}{e.fact?.current_statement_citations.map(c => <p key={c.turn_id}>原话 [{c.start}, {c.end})：{c.quote}</p>)}</> : <p>无可用于贡献预览的完整分类/来源依据；不编造引用。</p>}</details></article>)}</div>
        </section>
        <section className="jd-panel" aria-label="简历对比"><p className="jd-eyebrow">03 / TAILOR WITHOUT INVENTING</p><h2>一岗一选择，经历仍是原话</h2><div className="jd-comparison"><div><h3>基础经历 · 合成已审核原句</h3>{usable.map(e => <div key={e.fact!.id} className="jd-base-row"><label><input type="checkbox" checked={selected.includes(e.fact!.id)} onChange={ev => { setSelected(ev.target.checked ? [...selected, e.fact!.id] : selected.filter(id => id !== e.fact!.id)); setReview(null); setFinished(false) }} />{e.fact!.statement}</label><small>{e.fact!.status === 'user_confirmed' ? '用户自述确认' : '用户材料支持'} · 未独立认证</small></div>)}</div><div><h3>岗位定制 · 顺序与本地草稿</h3>{chosen.length === 0 && <p>暂无选中条目。缺证据时保留空白，不生成经历。</p>}{chosen.map((f, i) => <article key={f.id} className="jd-draft"><span>0{i + 1} · 来源 Fact {f.id.slice(-4)}</span><button className="jd-secondary" onClick={() => move(f.id)} disabled={i === 0}>上移 {i + 1}</button><p>选用理由：{matches.filter(m => m.usable.some(e => e.fact!.id === f.id)).map(m => m.requirement.text).join(' / ') || '用户手动选用，岗位相关性待判断'}</p><label>本地预览文字<textarea aria-label={`本地预览文字 ${f.id}`} value={drafts[f.id] ?? f.statement} onChange={e => { setDrafts({ ...drafts, [f.id]: e.target.value }); setReview(null); setFinished(false) }} /></label>{printableText(f.statement, drafts[f.id] ?? f.statement) === null && <><p role="status" className="jd-warning">未核实的本地改写：不进入可打印简历或复习事实，不回写经历库。</p><button className="jd-secondary" onClick={() => setDrafts({ ...drafts, [f.id]: f.statement })}>恢复原句 {i + 1}</button></>}</article>)}</div></div>
          <div className="jd-print-controls"><button disabled={!originalChosen.length} onClick={() => window.print()}>打印预览 / 浏览器保存 PDF</button><small>只打印仍与已选原句完全一致的条目。新增数字/技术/结果草稿不打印。</small></div>
          <article className="jd-resume" aria-label="可打印简历预览"><p className="jd-resume-label">PATHWISE · 合成资料 / 本地预览 / 非正式简历</p><h2>项目经历 · {job.title}</h2><ul>{originalChosen.map(f => <li key={f.id}>{f.statement}</li>)}</ul>{!originalChosen.length && <p>缺少可核对条目，保持空白。</p>}<footer>用户自述 / 用户提供材料，不代表平台独立核实。真实资料尚未接入。</footer></article>
        </section>
        <section className="jd-panel jd-review" id="jd-review" aria-label="三题快速复习"><p className="jd-eyebrow">04 / OWN YOUR STORY</p><h2>准备好解释你写下的每一句。</h2><p>仅依据当前可打印原句与岗位要求。没有标准答案，不生成个人事实。</p>{review === null && !finished && <button disabled={questions.length !== 3} onClick={() => { setReview(0); setResponses({}) }}>开始三题复习</button>}
          {review !== null && questions[review] && <div><span>第 {review + 1} / 3 题</span><h3>{questions[review].prompt}</h3><p>岗位依据：{questions[review].requirement.quote}</p><blockquote>经历原句：{questions[review].fact.statement}</blockquote><label>我的回忆（本地草稿，非证据）<textarea aria-label="复习回答" value={responses[review] ?? ''} onChange={e => setResponses({ ...responses, [review]: e.target.value })} /></label><div className="jd-actions"><button onClick={() => { if (review === 2) { setReview(null); setFinished(true) } else setReview(review + 1) }}>{review === 2 ? '完成复习' : '下一题'}</button><button className="jd-secondary" onClick={() => { setResponses({ ...responses, [review]: '' }); if (review === 2) { setReview(null); setFinished(true) } else setReview(review + 1) }}>跳过这题</button><button className="jd-secondary" onClick={() => { setReview(null); setFinished(true) }}>结束并复盘</button></div></div>}
          {finished && <div role="status"><h3>复盘 · 不打分，不猜经历</h3><p>已记录 {Object.values(responses).filter(s => s.trim()).length} 条本地回答，其余可继续准备。回答未用于确认、补造或修改事实。</p><button className="jd-secondary" onClick={() => { setFinished(false); setReview(0); setResponses({}) }}>重新复习三题</button></div>}
        </section>
      </>}
      <footer className="jd-footer">经历可以更清晰，事实不能凭空增加。<span>Pathwise · 产品预览 / 无正式写入</span></footer>
    </main>
  </div>
}

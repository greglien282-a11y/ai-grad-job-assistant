import { suggestions, applySourceSuggestion } from './workspace'
import { provenance, type Draft } from './draft'
export default function RoleSuggestions({ value: d, onChange }: { value: Draft; onChange: (d: Draft) => void }) {
  return <section className="resume-panel" aria-label="可解释岗位建议"><h2>按原话做取舍，不替你编经历</h2><p>只比较有限字面词，不给匹配率、不推断掌握。应用建议只把原句选用并前移，仍是待核对用户草稿；你的改写、原句和打印内容分别可见。</p>
    {!d.job && <p>先分析当前岗位JD，再查看来源关联。</p>}
    {d.job && suggestions(d).map(s => <article className="resume-card" key={s.entry.id}><blockquote>{s.entry.original}</blockquote><small>{provenance(d, s.entry)}</small><p>{s.reason}</p>{s.requirements.map(r => <p key={r.id}>建议依据：{r.quote} · JD [{r.start}, {r.end})</p>)}<button className="secondary" disabled={!s.eligible} onClick={() => onChange(applySourceSuggestion(d, s.entry.id))}>选用原句并前移 · {d.entries.indexOf(s.entry) + 1}</button></article>)}
  </section>
}

import { suggestions, applySourceSuggestion, applySourceSuggestions } from './workspace'
import { provenance, type Draft } from './draft'
export default function RoleSuggestions({ value: d, onChange }: { value: Draft; onChange: (d: Draft) => void }) {
  const items = suggestions(d), eligible = items.filter(s => s.eligible)
  return <section className="resume-panel" aria-label="可解释岗位建议"><h2>按原话做取舍，不替你编经历</h2><p>只比较有限字面词，不给匹配率、不推断掌握。应用建议只把原句选用并前移，仍是待核对用户草稿；你的改写、原句和打印内容分别可见。</p>
    {!d.job && <p>先分析当前岗位JD，再查看来源关联。</p>}
    {d.job && <><p>先展示有明确原句依据的建议；重复原句沿用原准入去重，不重复选用。</p><button disabled={!eligible.length} onClick={() => onChange(applySourceSuggestions(d))}>选用全部可解释原句（{eligible.length}）</button></>}
    {d.job && items.map(s => <article className="resume-card" key={s.entry.id}><blockquote>{s.entry.original}</blockquote><p>{s.entry.source_kind === 'user_manual_statement' ? '来源：用户手工声明（不是导入材料）' : '来源：本地简历原始片段（不是认证事实）'}</p><small>{provenance(d, s.entry)}</small><p>{s.reason}</p>{s.links.map(({ requirement: r, words, assessment }) => <div key={r.id}><p>匹配词：{words.join('、')} · 字面相关，不是语义或能力认证</p><p>建议依据：{r.quote} · JD [{r.start}, {r.end})</p><p>{assessment === 'gap' ? '用户明确自评：能力缺口，不能据此声称掌握' : assessment === 'can_explain' ? '用户自评可说明，仍需证据' : '需要补充证据，未认定掌握'}</p></div>)}<button className="secondary" disabled={!s.eligible} onClick={() => onChange(applySourceSuggestion(d, s.entry.id))}>选用原句并前移 · {d.entries.indexOf(s.entry) + 1}</button></article>)}
  </section>
}

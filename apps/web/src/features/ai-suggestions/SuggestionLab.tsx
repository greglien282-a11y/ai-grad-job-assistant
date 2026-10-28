import { useState } from 'react'
import { provenance, type Draft } from '../resume-lab/draft'
import { applyCandidate, binding, candidateGate, decisionContext, parsePacketJSON, type CandidatePacket } from './contract'
import { generateCandidates } from './adapters'

export default function SuggestionLab({ value: d, roleId, onChange }: { value: Draft; roleId: string; onChange: (d: Draft) => void }) {
  const context = d.job ? decisionContext(d, roleId) : ''
  const [loaded, setLoaded] = useState<{ context: string; packet: CandidatePacket } | null>(null)
  const [raw, setRaw] = useState(''), [error, setError] = useState(''), [notice, setNotice] = useState('')
  const [notes, setNotes] = useState<Record<string, { text: string; decision: 'reviewing' | 'rejected' | 'edited' }>>({})
  const packet = loaded?.context === context ? loaded.packet : null
  const key = (id: string) => `${context}\n${id}`
  function generate(mode: string) {
    setLoaded(null); setError(''); setNotice('')
    try { setLoaded({ context, packet: generateCandidates(mode, d, roleId) }) }
    catch { setError('候选不可用：先分析JD；当前材料可能超过本地合同限制。没有上传、保存或调用模型。') }
  }
  function load() {
    setLoaded(null); setError(''); setNotice('')
    try { setLoaded({ context, packet: parsePacketJSON(raw, binding(d, roleId)) }) }
    catch { setError('候选未载入：版本、字段、来源、Unicode引用或岗位快照不一致。已清除旧候选，没有部分结果或请求。') }
  }
  return <section className="resume-panel ai-suggestion-lab" aria-label="离线AI建议审核实验室">
    <p className="resume-kicker">OFFLINE CANDIDATES · REVIEW BEFORE USE</p><h2>建议先可核对，再由你决定</h2>
    <p>默认关闭的离线实验；Mock不是模型，字面关联不是语义理解。用户草稿不是平台认证，参考标注仍为 draft_unreviewed。本页没有真实Provider、密钥读取或网络调用路径。</p>
    <div className="resume-actions"><button disabled={!d.job} onClick={() => generate('keyword')}>生成关键词对照候选</button><button disabled={!d.job} onClick={() => generate('mock')}>生成离线Mock候选</button><button className="secondary" disabled={!d.job} onClick={() => generate('risk_fixture')}>查看公开合成风险反例</button></div>
    {!d.job && <p>先在下方岗位策略中粘贴并分析JD。</p>}
    <details><summary>载入本地标准候选 JSON（不上传）</summary><label>候选 JSON<textarea value={raw} maxLength={524288} onChange={e => { setRaw(e.target.value); setLoaded(null); setError('') }} /></label><button disabled={!d.job} onClick={load}>严格载入候选</button></details>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    {loaded && !packet && <p role="status">岗位、内容、选用或风险状态已变化，旧候选已失效；重新生成后再审核。</p>}
    {packet && <><p>合同：{packet.contract}。优先序是建议展示次序，不是匹配分数。来源标识只是候选自述，不证明模型身份或用户认证。</p>
      {!packet.suggestions.length && <p role="status">没有足够字面来源，暂不推荐。可以补充原始材料或人工澄清，不生成不存在的经历。</p>}
      {[...packet.suggestions].sort((a, b) => a.priority - b.priority).map(c => {
        const gate = candidateGate(d, c), note = notes[key(c.id)], e = d.entries.find(e => e.id === c.source.paragraph_id)!
        return <article className="resume-card" key={c.id} aria-label={`建议候选 ${c.id}`}>
          <h3>展示优先序 {c.priority} · {c.provenance.kind} / {c.provenance.id} / {c.provenance.version}</h3>
          <div className="resume-columns"><div><h4>原始经历</h4><blockquote>{c.source.quote}</blockquote><p>{c.source.kind === 'user_manual_statement' ? '用户手工声明，无导入原文认证' : provenance(d, e)}</p><small>本地审查快照 [{c.source.start}, {c.source.end})；不是原文件字节或数据库Turn。</small><h4>JD 条件</h4><blockquote>{c.jd.quote}</blockquote><small>JD code points [{c.jd.start}, {c.jd.end})</small></div>
          <div><h4>候选建议</h4><blockquote>{c.rewrite_text ?? c.source.quote}</blockquote><p>理由：{c.reason}</p><p>变化说明：{c.rewrite_text && c.rewrite_text !== c.source.quote ? '原句已变化，语义与新增主张尚未独立审核；不可直接应用。' : '正文未改，只建议选择或顺序。'}</p>
            <p>需要证据的新增主张：{c.new_claims.length ? c.new_claims.join('；') : '候选未列出（不代表已证明没有新增主张）'}</p><p>证据或能力缺口：{c.evidence_gap ?? '候选未说明，仍须用户核对'}</p><strong>{gate.status === 'original_only' ? '仅原句可用 · 未认证' : gate.status === 'blocked' ? '已阻断' : '需要人工澄清'}</strong><p>{gate.reason}</p>
          </div></div>
          <div className="resume-actions"><button disabled={gate.status !== 'original_only' || note?.decision === 'rejected'} onClick={() => {
            try { onChange(applyCandidate(d, roleId, packet, c.id)); setNotice('已仅把完整原句选用并前移到未经认证的本地草稿；未保存事实。') }
            catch { setLoaded(null); setError('当前来源或风险状态不再允许应用，候选已失效。') }
          }}>接受原句顺序 · {c.id}</button><button className="secondary" disabled={note?.decision === 'rejected'} onClick={() => { setNotes(n => ({ ...n, [key(c.id)]: { text: n[key(c.id)]?.text ?? c.rewrite_text ?? c.source.quote, decision: 'rejected' } })); setNotice('已拒绝这条建议；没有删除原文、清除历史或解锁写入。') }}>拒绝候选 · {c.id}</button></div>
          <label>待核对候选文字 · {c.id}<textarea maxLength={20000} disabled={note?.decision === 'rejected'} value={note?.text ?? c.rewrite_text ?? c.source.quote} onChange={ev => setNotes(n => ({ ...n, [key(c.id)]: { text: ev.target.value, decision: 'reviewing' } }))} /></label>
          <button className="secondary" disabled={note?.decision === 'rejected'} onClick={() => {
            setNotes(n => ({ ...n, [key(c.id)]: { text: n[key(c.id)]?.text ?? c.rewrite_text ?? c.source.quote, decision: 'edited' } })); setNotice('已留在本页待核对区；不进入打印、不回写Fact、不构成证据。刷新即清空。')
          }}>保留编辑到待核对区 · {c.id}</button>
          {note && <p>本页决定：{note.decision === 'rejected' ? '已拒绝（重新生成同一候选不解除）' : note.decision === 'edited' ? '用户编辑待核对，未应用' : '正在核对'}。本地记录不是不可变审核历史，R03仍未解决。</p>}
        </article>
      })}</>}
  </section>
}

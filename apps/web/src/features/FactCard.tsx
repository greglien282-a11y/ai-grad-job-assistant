import { useState } from 'react'
import type { ExperienceSession, Fact, Mutation } from '../lib/experience'

export const statusLabels = { pending: '待确认', user_confirmed: '用户确认', evidence_supported: '材料辅助核实', rejected: '已拒绝' }
export function FactCard({ fact, index, session, disabled, onMutate }: {
  fact: Fact; index: number; session: ExperienceSession; disabled: boolean; onMutate: (body: Mutation) => Promise<boolean>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(fact.statement)
  const [editVersion, setEditVersion] = useState(fact.version)
  const [verifying, setVerifying] = useState(false)
  const [material, setMaterial] = useState('')
  const [basis, setBasis] = useState('')
  const [verifyVersion, setVerifyVersion] = useState(fact.version)
  const edit = session.history.find(item => item.id === fact.source_change_id)
  const evidence = session.evidence.find(item => item.id === fact.evidence_id)
  const history = session.history.filter(item => item.fact_id === fact.id)
  const editConflict = editing && editVersion !== fact.version
  const verificationConflict = verifying && verifyVersion !== fact.version
  return <article className="card fact-card" aria-label={`事实 ${index}`}>
    <div className="fact-top"><span className="fact-number">{String(index).padStart(2, '0')}</span><span className={`pill ${fact.status}`}>{statusLabels[fact.status]}</span><small>版本 {fact.version}</small></div>
    <h3 className="statement">{fact.statement}</h3>
    {fact.origin === 'ai_extracted' && <p className="fact-origin">{fact.source_kind === 'user_edit' ? '最初由合成流程提取；当前陈述来源为用户编辑。' : '由合成流程引用用户原文整理 · 需用户审核'}</p>}
    {fact.memory_state && <label className="memory-label">记忆状态 {index}<select aria-label={`记忆状态 ${index}`} value={fact.memory_state} disabled={disabled || editing} onChange={e => void onMutate({ action: 'set_memory', expected_version: fact.version, memory_state: e.target.value as 'unspecified' | 'certain' | 'approximate' | 'needs_check' })}><option value="unspecified">未标记</option><option value="certain">确定做过</option><option value="approximate">大概记得</option><option value="needs_check">需要核实</option></select></label>}
    <div className="fact-actions"><button className="secondary" disabled={disabled || editing} onClick={() => { if (editing) return; setDraft(fact.statement); setEditVersion(fact.version); setEditing(true); setVerifying(false) }}>编辑陈述</button>
      <button disabled={disabled || fact.status !== 'pending' || editing} onClick={() => void onMutate({ action: 'confirm', expected_version: fact.version })}>确认事实</button>
      <button className="secondary" disabled={disabled || fact.status === 'rejected' || editing} onClick={() => void onMutate({ action: 'reject', expected_version: fact.version })}>拒绝事实</button>
      <button className="secondary" disabled={disabled || fact.status !== 'user_confirmed' || editing} onClick={() => { setVerifyVersion(fact.version); setVerifying(true) }}>材料核实</button></div>
    {editing && <form className="inline-form" onSubmit={async e => { e.preventDefault(); if (await onMutate({ action: 'edit', expected_version: editVersion, statement: draft })) setEditing(false) }}><label htmlFor={`edit-${fact.id}`}>编辑事实 {index}</label><textarea id={`edit-${fact.id}`} required maxLength={10000} value={draft} onChange={e => setDraft(e.target.value)} disabled={disabled} /><p>保存后重新进入待确认，原始自述与旧历史不会被覆盖。</p>
      {editConflict && <div className="conflict-note"><p>服务端版本已变化。上方是最新陈述，你的输入保留在编辑框中。请复核后决定是否再次保存。</p><button type="button" className="secondary" disabled={disabled} onClick={() => setEditVersion(fact.version)}>我已复核最新版本</button></div>}
      <div className="button-row"><button disabled={disabled || editConflict || !draft.trim() || draft === fact.statement}>保存编辑</button><button type="button" className="secondary" disabled={disabled} onClick={() => setEditing(false)}>关闭编辑</button></div></form>}
    {verifying && <form className="inline-form" onSubmit={async e => { e.preventDefault(); if (await onMutate({ action: 'verify_material', expected_version: verifyVersion, material_reference: material, basis })) { setVerifying(false); setMaterial(''); setBasis('') } }}>
      <label htmlFor={`material-${fact.id}`}>材料引用 {index}</label><input id={`material-${fact.id}`} value={material} onChange={e => setMaterial(e.target.value)} required maxLength={10000} disabled={disabled} placeholder="例如：合成项目报告第 2 节" />
      <label htmlFor={`basis-${fact.id}`}>核实依据 {index}</label><textarea id={`basis-${fact.id}`} value={basis} onChange={e => setBasis(e.target.value)} required maxLength={10000} disabled={disabled} /><p>用户提供材料并自行核实；此处记录引用，不上传附件、不作平台独立认证。</p>
      {verificationConflict && <div className="conflict-note"><p>事实版本已变化，请先重新审核陈述与材料依据。</p><button type="button" disabled={disabled || fact.status !== 'user_confirmed'} onClick={() => setVerifyVersion(fact.version)}>我已复核材料与最新版本</button></div>}
      <div className="button-row"><button disabled={disabled || verificationConflict || fact.status !== 'user_confirmed' || !material.trim() || !basis.trim()}>记录材料核实</button><button type="button" className="secondary" disabled={disabled} onClick={() => setVerifying(false)}>关闭核实</button></div></form>}
    <details className="trace"><summary>查看来源与历史 · {history.length} 次记录</summary><div className="trace-body"><strong>当前陈述来源：{fact.source_kind === 'user_edit' ? '用户后续编辑' : '用户原始自述'}</strong>
      {fact.source_kind === 'user_edit' ? <p>{edit ? edit.after.statement : '编辑事件待重新读取'}<small>用户编辑 · {edit ? new Date(edit.created_at).toLocaleString() : ''}</small></p> : fact.source_turn_ids.map(id => <p key={id}>{session.turns.find(t => t.id === id)?.content ?? '来源回合待重新读取'}</p>)}
      <strong>原始自述（历史起点）</strong>{fact.original_source_turn_ids.map(id => <p key={id}>{session.turns.find(t => t.id === id)?.content ?? '来源回合待重新读取'}</p>)}
      {evidence && <div><strong>用户提供材料并自行核实</strong><p>{evidence.material_reference}<br />{evidence.basis}</p></div>}
      <strong>变更记录</strong><ol>{history.map(item => <li key={item.id}><small>{new Date(item.created_at).toLocaleString()} · {item.action === 'edited' ? '用户编辑' : item.action === 'created' ? '事实建档' : '用户更新确认状态'}</small>{item.before && <p>变更前：{item.before.statement} · {statusLabels[item.before.status]}</p>}<p>变更后：{item.after.statement} · {statusLabels[item.after.status]}</p></li>)}</ol>
    </div></details>
  </article>
}

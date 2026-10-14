import { useState } from 'react'
import type { Question, QuestionAction } from '../../lib/mining-contract'
export function QuestionCard({ question: q, current, selected, disabled, onSelect, onAction }: {
  question: Question; current: boolean; selected: boolean; disabled: boolean; onSelect: () => void;
  onAction: (action: QuestionAction, content?: string) => Promise<boolean>
}) {
  const [editing, setEditing] = useState(false), [draft, setDraft] = useState(''), [version, setVersion] = useState(q.version)
  const [deleting, setDeleting] = useState(false)
  const answerable = current && ['active', 'corrected'].includes(q.state)
  const label = { active: '待回答', corrected: '已纠正', skipped: '已跳过', hidden: '已隐藏', deleted: '已删除' }[q.state]
  return <article className="question-card" aria-label="合成追问" data-question-id={q.id}>
    <div className="question-meta"><span>{label}{!current && ' · 历史轮次'}</span><span>问题版本 {q.version}</span></div>
    {q.state !== 'hidden' && q.state !== 'deleted' && <p>{q.content}</p>}
    {answerable && <label className="question-choice"><input type="checkbox" checked={selected} disabled={disabled} onChange={onSelect} />将我的下一条回答关联到这题</label>}
    {q.state !== 'deleted' && <div className="question-tools">
      <button className="secondary" disabled={disabled || editing} onClick={() => { setDraft(q.content ?? ''); setVersion(q.version); setEditing(true) }}>{q.state === 'hidden' ? '显示并纠正' : '纠正问题'}</button>
      <button className="secondary" disabled={disabled || q.state === 'skipped'} onClick={() => void onAction('skip')}>跳过</button>
      <button className="secondary" disabled={disabled || q.state === 'hidden'} onClick={() => void onAction('hide')}>隐藏</button>
      <button className="danger" disabled={disabled} onClick={() => setDeleting(true)}>删除问题</button>
    </div>}
    {editing && <form onSubmit={async e => { e.preventDefault(); if (!disabled && draft.trim() && version === q.version && await onAction('correct', draft)) setEditing(false) }}>
      <label>纠正后的问题<textarea value={draft} onChange={e => setDraft(e.target.value)} maxLength={500} disabled={disabled} /></label>
      {version !== q.version && <p>问题版本已变化，草稿保留。<button type="button" disabled={disabled} onClick={() => setVersion(q.version)}>我已核对最新问题版本</button></p>}
      <div className="button-row"><button disabled={disabled || !draft.trim() || version !== q.version}>保存问题纠正</button><button type="button" className="secondary" onClick={() => setEditing(false)}>关闭纠正</button></div>
    </form>}
    {deleting && <div className="confirm-box" role="group" aria-label="删除问题确认"><p>删除问题正文，原回答和已确认事实仍保留。不能恢复。</p><button className="danger" disabled={disabled} onClick={async () => { if (await onAction('delete')) setDeleting(false) }}>确认删除问题</button><button className="secondary" onClick={() => setDeleting(false)}>取消删除问题</button></div>}
  </article>
}

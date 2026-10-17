import type { useDiscovery } from './useDiscovery'

export function AnswerComposer({ d, blocked }: { d: ReturnType<typeof useDiscovery>; blocked: boolean }) {
  const questions = [...(d.session?.mining_runs ?? [])].reverse().find(r => r.state === 'completed')?.questions ?? []
  return <form className="answer-composer" onSubmit={e => { e.preventDefault(); void d.act(d.submitAnswer) }}>
    <div className="composer-heading"><h3>写下你记得的部分</h3><span>回答后再核对事实</span></div>
    <div id="answer-association" className="association-note" role="status">
      {d.mining.value ? <p>重试保留原关联 {(d.mining.value.answered_question_ids ?? []).length} 题；请使用原回答，不会自动重发。</p>
        : d.selected.length ? <><p>本回答关联 {d.selected.length} 题，可取消勾选：</p><ul>{questions.filter(q => d.selected.includes(q.id)).map(q => <li key={q.id}>{q.content}</li>)}</ul></>
          : <p>自由补充 · 不绑定问题。想回答指定问题？请先勾选上方对应题目（最多两题）。</p>}
    </div>
    <label htmlFor="discovery-answer">你的回答或自由补充</label>
    <textarea id="discovery-answer" aria-describedby="answer-association" rows={4} value={d.answer} onChange={e => d.setAnswer(e.target.value)} maxLength={10000} required disabled={d.busy || d.needsReload || Boolean(d.mining.value && !d.miningNotFound)}
      onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter' && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); e.currentTarget.form?.requestSubmit() } }}
      placeholder="只写你记得、做过的部分。记不清也可以跳过问题。" />
    <div className="composer-footer"><small>先保存回答，再进行零费用合成整理。Ctrl/⌘ + Enter 提交</small><button disabled={blocked || !d.answer.trim() || Boolean(d.mining.value && !d.miningNotFound)}>{d.phase === 'submitting' ? '正在提交合成整理…' : d.mining.value ? '用原回答同键重试' : '保存回答并合成整理'}</button></div>
    {d.selected.length > 0 && !d.mining.value && <button type="button" className="secondary clear-association" disabled={blocked} onClick={() => d.setSelected([])}>清除问题关联，作为自由补充</button>}
  </form>
}

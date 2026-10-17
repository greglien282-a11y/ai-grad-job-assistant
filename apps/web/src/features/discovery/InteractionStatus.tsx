import type { interactionState } from './interactionState'

export function InteractionStatus({ state, busy, onRead }: {
  state: ReturnType<typeof interactionState>; busy: boolean; onRead: () => void
}) {
  return <section className="interaction-state" role="status" aria-label="整理交互状态" data-state={state.key}>
    <div className="interaction-heading"><h3>{state.title}</h3><span>零费用 · 合成流程状态</span></div>
    <p>{state.description}</p><p className="interaction-next">{state.next}</p>
    {state.query && <button type="button" className="secondary" disabled={busy} onClick={onRead}>查询本轮状态（只读）</button>}
  </section>
}

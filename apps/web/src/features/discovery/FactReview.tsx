import { FactCard } from '../FactCard'
import type { useDiscovery } from './useDiscovery'

export function FactReview({ d, active, disabled }: { d: ReturnType<typeof useDiscovery>; active: boolean; disabled: boolean }) {
  const session = d.session!
  const pending = session.facts.filter(f => f.status === 'pending').length
  // Keep original numbering and a single keyed list: sorting must not reset drafts.
  const facts = session.facts.map((fact, index) => ({ fact, index }))
    .sort((a, b) => Number(b.fact.status === 'pending') - Number(a.fact.status === 'pending'))
  return <section id="discovery-facts" tabIndex={-1} className="fact-review-panel" data-active={active} aria-label="候选事实审核">
    <div className="panel-heading"><h2>你说过的事实</h2><span>{pending} 条待核对</span></div>
    <div className="review-guidance"><strong>{pending ? '先核对待确认的内容' : '当前没有待确认事实'}</strong><p>对照原文：准确就确认，有出入先编辑，不属实就拒绝。编辑后需要重新确认。</p></div>
    <p>合成整理只引用原文。确认表示用户自述，不是平台独立认证。</p>
    {facts.length === 0 && <div className="empty-review"><h3>候选会出现在这里</h3><p>你可以先回答，也可以直接手工整理。</p></div>}
    {facts.map(({ fact, index }) => <FactCard key={fact.id} fact={fact} index={index + 1} session={session} disabled={disabled} onMutate={mutation => d.act(() => d.mutate(fact, mutation))} />)}
  </section>
}

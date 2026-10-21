import { useEffect, useRef, useState } from 'react'
import type { useDiscovery } from './useDiscovery'
import { DiscoveryLink } from './DiscoveryLink'
import { UpgradeNotice } from './UpgradeNotice'
import './SummaryView.css'

export default function SummaryView({ d, copy }: { d: ReturnType<typeof useDiscovery>; copy: (text: string) => Promise<void> }) {
  const [notice, setNotice] = useState('')
  const title = useRef<HTMLHeadingElement>(null)
  useEffect(() => { title.current?.focus() }, [])
  const available = !d.busy && !d.needsReload && !d.creation.error && !d.mining.error && !!d.session && !!d.summary
  const facts = available ? d.summary!.confirmed : []
  if (d.contractState === 'upgrade_required') return <UpgradeNotice />
  return <main className="result-shell">
    <nav className="result-nav" aria-label="当前步骤"><DiscoveryLink href="/discovery">02 回答与核对</DiscoveryLink><span aria-current="step">03 阅读整理稿</span></nav>
    <div className="result-heading"><p className="kicker">你的经历 · 整理结果</p><h1 ref={title} tabIndex={-1}>把确认过的事，清楚地留下。</h1><p>当前为合成测试的原文整理，不是 AI 专业改写、完整简历或 PDF。</p></div>
    {d.error && <p className="alert" role="alert">{d.error}</p>}
    {!available ? <section className="result-empty" aria-label="成果读取状态"><h2>{d.busy ? '正在读取已保存的经历' : d.credentials || d.creation.value || d.creation.error || d.mining.error ? '先恢复并核对资料' : '还没有可恢复的经历'}</h2><p>读取成功前不展示或复制整理正文。恢复只查询，不重新提交回答或启动整理。</p>{(d.credentials || d.creation.value) && <button disabled={d.busy} onClick={() => void d.act(d.refresh)}>重新读取成果</button>}<DiscoveryLink href="/discovery">返回继续完善</DiscoveryLink></section>
      : <>
        <article className="result-document" aria-label="已确认经历正文"><div className="document-meta"><span>经历整理稿</span><span>{facts.length} 条已确认事实</span></div>
          {facts.length ? <div className="summary-text">{d.summary!.text}</div> : <div className="result-empty"><h2>先确认一件你做过的事</h2><p>你的经历已保存。待确认或已拒绝的内容不会进入整理正文，回到 02 核对一条事实就能开始。</p></div>}
        </article>
        <div className="result-actions"><button disabled={!facts.length} onClick={async () => { try { if (d.isUpgradeRequired()) return; await copy(d.summary!.text); if (!d.isUpgradeRequired()) setNotice('已复制确认后的经历文本。') } catch { setNotice('剪贴板不可用，请选中上方文字手动复制。') } }}>复制经历文本</button><DiscoveryLink href="/discovery">返回继续完善</DiscoveryLink></div>
        {notice && <p role="status">{notice}</p>}
        {!!facts.length && <details className="result-sources"><summary>查看事实依据</summary><p>依据单独展示，不加入整理正文；材料由用户提供并自行核实，不是平台独立认证。</p>{facts.map((fact, index) => {
          const edit = d.session!.history.find(item => item.id === fact.source_change_id)
          const evidence = d.session!.evidence.find(item => item.id === fact.evidence_id)
          return <section key={fact.id} aria-label={`整理依据 ${index + 1}`}><h2>事实 {index + 1} · 当前版本 {fact.version}</h2><p>{fact.statement}</p><strong>{fact.source_kind === 'user_edit' ? '用户后续编辑' : '用户原始自述'}</strong>{fact.source_kind === 'user_edit' ? <p>{edit?.after.statement ?? '编辑依据待重新读取'}</p> : fact.source_turn_ids.map(id => <p key={id}>{d.session!.turns.find(turn => turn.id === id)?.content ?? '来源待重新读取'}</p>)}{evidence && <p>用户提供材料并自行核实：{evidence.material_reference}<br />核实依据：{evidence.basis}</p>}<p>原始自述与完整变更历史可返回 02 查看。</p></section>
        })}</details>}
      </>}
    <footer className="discovery-footer">仅当前已确认或材料辅助核实事实 · 临时标签页凭证不提供长期账号恢复</footer>
  </main>
}

import { useEffect, useState } from 'react'
import { createExperienceApi, downloadJson, type ExperienceApi } from '../../lib/experience'
import type { MiningRun } from '../../lib/mining-contract'
import { FactReview } from './FactReview'
import { AnswerComposer } from './AnswerComposer'
import { useDiscovery } from './useDiscovery'
import { Conversation } from './Conversation'
import './Discovery.css'
import SummaryView from './SummaryView'
import { DiscoveryLink } from './DiscoveryLink'
import { interactionState } from './interactionState'
import { InteractionStatus } from './InteractionStatus'

export default function DiscoveryWorkbench({ api = createExperienceApi(), view = 'workspace', copy = (text: string) => navigator.clipboard.writeText(text) }: { api?: ExperienceApi; view?: 'workspace' | 'summary'; copy?: (text: string) => Promise<void> }) {
  const d = useDiscovery(api)
  useEffect(() => { if (view === 'summary' && d.session) void d.act(d.refresh) }, [view])
  const [tab, setTab] = useState('conversation'), [prompt, setPrompt] = useState<'stop' | 'end' | 'delete' | null>(null)
  const [retry, setRetry] = useState<MiningRun | null>(null)
  const s = d.session, readonly = s?.status === 'ended'
  const interaction = interactionState({ session: s, hasCredentials: Boolean(d.credentials), busy: d.busy, phase: d.phase,
    needsReload: d.needsReload, storageError: Boolean(d.mining.error || d.creation.error), pending: Boolean(d.mining.value), notFound: d.miningNotFound, failureCode: d.failureCode })
  const blocked = d.busy || d.needsReload || Boolean(d.mining.error || d.creation.error) || interaction.recoverOnly
  const manageBlocked = blocked || !s || Boolean(d.mining.value)
  const latest = s?.mining_runs?.at(-1)
  const pendingCount = s?.facts.filter(f => f.status === 'pending').length ?? 0
  const confirmedCount = s?.facts.filter(f => ['user_confirmed', 'evidence_supported'].includes(f.status)).length ?? 0
  const reviewFacts = () => {
    setTab('facts')
    requestAnimationFrame(() => { const panel = document.getElementById('discovery-facts'); panel?.focus(); panel?.scrollIntoView({ block: 'start', behavior: 'instant' }) })
  }
  const toggle = (id: string) => d.setSelected(ids => ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id].slice(0, 2))
  const answerQuestion = (id: string) => {
    const current = [...(s?.mining_runs ?? [])].reverse().find(r => r.state === 'completed')
    if (blocked || interaction.pauseMining || readonly || d.mining.value || s?.mining_status !== 'active' ||
      !current?.questions.some(q => q.id === id && ['active', 'corrected'].includes(q.state)) ||
      (!d.selected.includes(id) && d.selected.length >= 2)) return
    d.setSelected(ids => ids.includes(id) ? ids : [...ids, id])
    setTab('conversation')
    requestAnimationFrame(() => {
      const input = document.getElementById('discovery-answer')
      input?.focus({ preventScroll: true }); input?.scrollIntoView({ block: 'center', behavior: 'instant' })
    })
  }
  return <div className="discovery">
    <header className="discovery-header"><a className="brand" href="/">✦ 启程 <span>Pathwise</span></a><nav><a href="/manual">手工工作台</a><span className="mode-tag">零费用 · 合成测试模式</span></nav></header>
    {view === 'summary' && <SummaryView d={d} copy={copy} />}
    <main className="discovery-shell" data-review={Boolean(s)} hidden={view === 'summary'}><div className="discovery-heading"><div><p className="kicker">从零整理 · 路径 B</p><h1>{s ? '回答与核对，慢慢补全经历。' : '从一段经历，找到你做过的事。'}</h1><p>用自己的话说，慢慢回忆。每一条候选都有原文，确认权在你。</p></div><span className="mode-note">真实 AI 尚未启用<br />固定追问不代表自适应能力</span></div>
      <ol className="step-strip" aria-label="当前步骤"><li aria-current={!s ? 'step' : undefined}>01 描述经历</li><li aria-current={s ? 'step' : undefined}>02 回答与核对</li><li><DiscoveryLink href="/discovery/summary">03 阅读整理稿</DiscoveryLink></li></ol>
      <div className="sync-status" role="status">{d.busy ? (d.phase === 'submitting' ? '正在提交本轮合成整理 · 请勿重复点击' : '正在读取或处理资料 · 不代表模型正在思考') : d.needsReload ? '恢复失败 · 请先重新读取' : s ? '资料已从服务端读取 · 候选仍需核对' : '先描述一段课程、项目或实践经历'}</div>
      {d.error && <div className="alert" role="alert">{d.error}</div>}{d.needsReload && d.credentials && <div className="recovery-panel"><p>最新资料尚未核对，写入与会话管理已暂停。先只读恢复，不会重新提交回答或运行推理。</p><button disabled={d.busy} onClick={() => void d.act(d.refresh)}>只读恢复最新资料</button></div>}{d.notice && <p className="notice" role="status">{d.notice}</p>}
      {!d.credentials ? <section className="discovery-start card"><h2>不需要一份完整简历</h2><p>写一件你做过的事，哪怕只记得一个关键词。这里仅使用合成资料，不要输入真实个人信息。</p>
        <form onSubmit={e => { e.preventDefault(); void d.act(d.create) }}><label htmlFor="discovery-raw">描述一段经历</label><textarea id="discovery-raw" rows={5} maxLength={10000} value={d.raw} onChange={e => d.setRaw(e.target.value)} disabled={d.busy} placeholder="合成示例：数据库课程设计，我负责列表页面，其他细节有些记不清。" required />
          <div className="composer-footer"><small>原始描述会保留，后续编辑另记来源。</small><button disabled={blocked || !d.raw.trim() || Boolean(d.creation.value && !d.createNotFound)}>{d.creation.value ? '用原描述同键重试' : '开始合成整理'}</button></div></form>
        {d.creation.value && <button className="secondary" disabled={d.busy} onClick={() => void d.act(d.refresh)}>只读恢复创建结果</button>}
        <p className="privacy-note">凭证仅暂存于当前标签页。24 小时是临时创建恢复窗口，不是长期账号恢复；关闭标签页可能失去访问。</p>
      </section> : <>
        <section className="work-guide" aria-label="本轮操作指引"><div><span className="kicker">接下来</span><h2>先回答，再核对你说过的事</h2><p>选题作答或自由补充 → 审核候选事实 → 阅读已确认的整理稿</p></div><button className="secondary" onClick={reviewFacts}>审核待确认事实（{pendingCount}）</button></section>
        {d.mining.value && <section className="recovery-panel"><h2>先核对上一条操作</h2><p>当前只读查询不会重新保存回答或运行推理。刷新不会自动重发，回答正文未写入浏览器暂存。</p><button disabled={d.busy} onClick={() => void d.act(d.refresh)}>查询刚才的整理结果</button>{Date.now() >= d.mining.value.expiresAt && <button className="secondary" disabled={d.busy || d.needsReload} onClick={d.abandon}>我已核对，清除过期操作记录</button>}{d.miningNotFound && <><p>未找到原操作。重新输入完全一致的原回答，保留原问题关联，可用同一操作键重试。</p>{d.mining.value.mode !== 'answer' && <button disabled={blocked} onClick={() => void d.act(() => d.submitAnswer())}>同键重试原整理操作</button>}<button className="secondary" disabled={blocked} onClick={d.abandon}>我已核对，放弃未找到的操作</button></>}</section>}
        {!s && <div className="card"><h2>正在恢复会话资料</h2><p>读取成功前不能写入。请确认 API 指向已升级的隔离环境。</p><a href="/manual">使用手工入口</a></div>}
        {s && <><nav className="mobile-tabs" aria-label="工作台视图">{[['conversation', '对话'], ['facts', `事实审核 (${pendingCount})`]].map(([value, label]) => <button key={value} className={tab === value ? 'selected' : 'secondary'} aria-pressed={tab === value} onClick={() => setTab(value)}>{label}</button>)}<DiscoveryLink href="/discovery/summary">整理结果</DiscoveryLink></nav>
          <div className="discovery-grid"><section className="conversation-panel" data-active={tab === 'conversation'} aria-label="对话工作区"><div className="panel-heading"><h2>一起回忆你的经历</h2><span>每轮最多两题</span></div><Conversation session={s} selected={d.selected} onSelect={toggle} onAnswer={answerQuestion} disabled={blocked || interaction.pauseMining || !!readonly || Boolean(d.mining.value)} onQuestion={(q, action, content) => d.act(() => d.question(q, action, content))} /><InteractionStatus state={interaction} busy={d.busy} onRead={() => void d.act(d.refresh)} />
            {!s.mining_runs?.length && <button disabled={blocked || !!readonly || Boolean(d.mining.value)} onClick={() => void d.act(d.startInitial)}>根据已保存经历开始合成整理</button>}
            {latest && ['failed', 'stale'].includes(latest.state) && <div className="recovery-panel"><p>本轮回答已保存，整理状态：{latest.state === 'stale' ? '上下文已变化' : latest.error_code === 'provider_output_invalid' ? '输出未通过校验' : '整理明确失败'}。</p><button disabled={manageBlocked || !!readonly || s.mining_status === 'stopped'} onClick={() => setRetry(latest)}>重新整理已保存回答</button></div>}
            {retry && <div className="confirm-box" aria-label="重新整理确认"><p>将明确运行一次零费用合成整理，复用原回答及问题关联，不新增回答。不会自动重试。</p><button disabled={manageBlocked} onClick={() => void d.act(async () => { await d.retrySaved(retry); setRetry(null) })}>确认重新整理</button><button className="secondary" onClick={() => setRetry(null)}>取消重新整理</button></div>}
            {s.mining_status !== 'stopped' && !readonly && <AnswerComposer d={d} blocked={blocked || interaction.pauseMining} />}
          </section><aside className="review-column"><FactReview d={d} active={tab === 'facts'} disabled={blocked || !!readonly} />
            <section className="result-entry"><h2>{confirmedCount ? `${confirmedCount} 条已确认，可以阅读了` : '确认一条事实，就能看到整理稿'}</h2><p>{confirmedCount ? '前往 03 查看当前已确认的原文整理，之后仍可返回完善。' : '待确认或已拒绝的内容不会进入正文；也可以先看看空白成果页。'}</p><p className="result-disclaimer">这是原文整理，不是 AI 专业改写或正式简历。</p><DiscoveryLink href="/discovery/summary">03 阅读整理稿 →</DiscoveryLink><details className="technical-backup"><summary>技术备份（JSON，非正式简历）</summary><p>包含原文、待确认/拒绝事实、来源与历史，仅供资料备份。</p><button className="secondary" disabled={blocked} onClick={() => void d.act(async () => { downloadJson(await d.api.export(d.credentials!), 'pathwise-technical-backup.json') })}>下载 JSON 技术备份</button></details></section>
          </aside></div></>}
      </>}
      {d.credentials && <section className="session-management" aria-label="会话管理">
        <div className="workspace-toolbar"><span>{readonly ? '已结束 · 只读' : s?.mining_status === 'stopped' ? '已停止追问 · 可继续核对' : '经历整理中'} · {confirmedCount} 条已确认</span><span className="management-label">会话管理</span><div className="button-row"><button className="secondary" disabled={d.busy} onClick={() => void d.act(d.refresh)}>重新读取</button><button className="secondary" disabled={manageBlocked || readonly || s?.mining_status === 'stopped'} onClick={() => setPrompt('stop')}>停止追问</button><button className="secondary" disabled={manageBlocked || readonly} onClick={() => setPrompt('end')}>结束会话</button><button className="danger" disabled={manageBlocked} onClick={() => setPrompt('delete')}>删除会话</button></div></div>
        {prompt && <section className="confirm-box" role="group" aria-label="管理确认"><h2>{prompt === 'stop' ? '停止本次追问？' : prompt === 'end' ? '结束并设为只读？' : '永久删除这次资料？'}</h2><p>{prompt === 'stop' ? '停止后仍可确认、编辑事实和阅读整理稿。不会继续生成追问。' : prompt === 'end' ? '结束后不能新增或编辑，仍可阅读和技术备份。' : '原始描述、回答、事实、问题及历史一起删除，无法恢复。'}</p><button disabled={manageBlocked} onClick={() => void d.act(async () => { await d.manage(prompt); setPrompt(null) })}>确认{prompt === 'stop' ? '停止追问' : prompt === 'end' ? '结束会话' : '永久删除'}</button><button className="secondary" onClick={() => setPrompt(null)}>取消</button></section>}
      </section>}
      <footer className="discovery-footer">合成测试仅供体验验收 · 不输入真实个人资料 · 临时会话不具备跨设备或长期恢复能力</footer>
    </main></div>
}

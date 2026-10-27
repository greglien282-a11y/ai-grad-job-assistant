import { useEffect, useRef, useState } from 'react'
import ResumeWorkbench from './ResumeWorkbench'
import { sourceTransition } from './source-transition'
import { isReviewed, type Workbench } from './import'
import DraftStudio from './DraftStudio'
import ResumePaper from './ResumePaper'
import RoleControls from './RoleControls'
import RoleSuggestions from './RoleSuggestions'
import { emptyReview, validate, type Draft } from './draft'
import { mergeRejections, newWorkspace, readWorkspace, roleDraft, saveWorkspace, updateRole, validateWorkspace, type Workspace } from './workspace'
import './resume.css'

export default function LocalResumeLab() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null), [retained, setRetained] = useState<string[]>([]), [history, setHistory] = useState<Record<string, Draft[]>>({}), [epoch, setEpoch] = useState(0), [error, setError] = useState(''), [notice, setNotice] = useState(''), [loading, setLoading] = useState(false)
  const [pendingSource, setPendingSource] = useState<{ next: Workbench | null; reason: string; affected: string[] } | null>(null)
  const generation = useRef(0)
  useEffect(() => () => { generation.current++ }, [])
  function source(w: Workbench | null) {
    generation.current++; setLoading(false); setError(''); setNotice('')
    if (w && workspace) {
      const impact = sourceTransition(workspace.workbench, w)
      if (impact.preserve) {
        // Pure metadata cannot invalidate a previously checked text snapshot.
        const workbench = w.contract === 'local-resume-workbench-v2' && workspace.workbench.contract === w.contract
          ? { ...w, source: { ...w.source, review: w.source.review === 'user_checked_text' ? w.source.review : workspace.workbench.source.review } } : w
        setWorkspace(validateWorkspace({ ...workspace, workbench }))
        setHistory(h => Object.fromEntries(Object.entries(h).map(([id, drafts]) => [id, drafts.map(d => validate({ ...d, workbench }))])))
        setPendingSource(null); return
      }
      setPendingSource({ next: w, reason: impact.reason, affected: impact.affected }); return
    }
    if (workspace) { setPendingSource({ next: null, reason: '正在更换导入材料，旧岗位尚未清除', affected: workspace.workbench.excerpts.map(e => e.label) }); return }
    setWorkspace(w ? newWorkspace(w, retained) : null); setHistory({}); setPendingSource(null)
  }
  function confirmSource() {
    if (!pendingSource) return
    setWorkspace(pendingSource.next ? newWorkspace(pendingSource.next, retained) : null)
    setPendingSource(null); setHistory({}); setEpoch(n => n + 1)
  }

  function update(next: Workspace) {
    try { const checked = mergeRejections(validateWorkspace(next), retained); setWorkspace(checked); setRetained(checked.rejected_statements); setError('') }
    catch { setError('岗位修改未通过来源、版本或状态校验，未应用。没有上传或保存。') }
  }
  function commit(next: Draft) {
    if (!workspace) return
    try {
      const checked = updateRole(workspace, validate(next)), id = workspace.active_role_id, previous = roleDraft(workspace)
      const merged = mergeRejections(checked, retained)
      setHistory(h => ({ ...h, [id]: [...(h[id] ?? []).slice(-29), previous] })); setWorkspace(merged); setRetained(merged.rejected_statements); setError('')
    } catch { setError('草稿修改未通过安全校验，未应用；没有上传或保存。') }
  }
  function undo() {
    if (!workspace) return
    const id = workspace.active_role_id, previous = history[id]?.at(-1)
    if (!previous) return
    try { const d = validate({ ...previous, rejected_statements: [...new Set([...retained, ...workspace.rejected_statements])], review: emptyReview() }); setWorkspace(updateRole(workspace, d)); setHistory(h => ({ ...h, [id]: h[id].slice(0, -1) })); setError('') }
    catch { setError('不能安全撤销，拒绝记录仍保留。') }
  }
  async function restore(file: File | undefined) {
    if (!file) return
    const g = ++generation.current; setPendingSource(null); setWorkspace(null); setHistory({}); setError(''); setNotice(''); setLoading(true); setEpoch(n => n + 1)
    try { const result = await readWorkspace(file, retained); if (g === generation.current) { setWorkspace(result.workspace); setRetained(result.workspace.rejected_statements); setNotice(result.migrated ? '已把旧版单岗位草稿显式迁移为v3的一个岗位。没有补造文件指纹、审核或分类依据。' : '已校验v3多岗位来源与状态；恢复不代表认证或事实保存。'); setEpoch(n => n + 1) } }
    catch { if (g === generation.current) setError('草稿未恢复：文件类型、UTF-8、大小、版本、字段、来源关系或状态不受支持。没有部分结果，也没有执行任何请求。') }
    finally { if (g === generation.current) setLoading(false) }
  }
  function download() {
    try { if (!workspace) return; const url = URL.createObjectURL(new Blob([saveWorkspace(workspace)], { type: 'application/json' })); const link = window.document.createElement('a'); link.href = url; link.download = 'pathwise-local-multi-role-v3.json'; link.click(); URL.revokeObjectURL(url); setError('') }
    catch { setError('草稿未下载：校验失败、尚未核对文本或超过2 MiB，请检查。') }
  }
  const d = workspace ? roleDraft(workspace) : null, active = workspace?.roles.find(r => r.id === workspace.active_role_id)
  return <div className="resume-lab"><header><a href="/">✦ Pathwise</a><span>本地简历工作台 · 开发预览</span><a href="/jd-lab">合成可信预览（独立入口）</a></header><main>
    <section className="resume-hero"><p className="resume-kicker">YOUR WORDS. YOUR NEXT STEP.</p><h1>从你已有的经历，<br />走向下一份岗位。</h1><p>没有亮眼指标也能开始。先保留原话，再看清证据与边界。</p></section>
    <aside className="resume-notice">本地材料和手工声明均未经平台核实；不自动确认、分类或保存到事实库。合成已审核FactV3仅在原独立实验入口，不可与导入文字混淆。正式数据库与认证结果未接入；无网络、AI或G4正式写入。</aside>
    <section className="resume-panel" aria-label="主动保存与恢复"><h2>本地草稿，由你决定保存</h2><p>下载文件包含完整简历原文、联系方式、所有岗位编辑和复习回答，请妥善保管。没有凭证、数据库认证或操作回执；文件可被改动，不保证事实真实或历史完整。刷新不自动恢复。v3支持最多5个岗位；旧v1/v2严格校验后只迁移为一个岗位，未知版本拒绝。</p><div className="resume-actions"><button disabled={!workspace || !!pendingSource || !isReviewed(workspace.workbench) || loading} onClick={download}>下载本地草稿 JSON</button><label className="resume-file">恢复本地草稿 JSON<input type="file" accept=".json,application/json" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; void restore(file) }} /></label></div>{loading && <p role="status">正在本地校验草稿…</p>}{error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}</section>
    <ResumeWorkbench key={`source-${epoch}`} value={pendingSource ? pendingSource.next : workspace?.workbench ?? null} onChange={source} />
    {pendingSource && <section className="resume-panel" role="alertdialog" aria-label="来源变更确认"><h2>先确认来源变更影响</h2><p>{pendingSource.reason}。当前岗位内容暂停展示，旧数据尚未删除。</p><p>受影响段落：{pendingSource.affected.join('、') || '新增来源或声明'}。确认后将重建所有岗位，清除岗位草稿、选用顺序、撤销与复习回答；本地拒绝记录保留。</p><button onClick={confirmSource}>确认更换来源并重置岗位</button><button className="secondary" onClick={() => { setPendingSource(null); setEpoch(n => n + 1) }}>取消变更，保留原岗位</button></section>}
    {!pendingSource && workspace && d && active && isReviewed(workspace.workbench) && <><RoleControls value={workspace} onChange={update} /><RoleSuggestions value={d} onChange={commit} />
      <DraftStudio key={`studio-${workspace.workbench.source.id}-${workspace.active_role_id}-${epoch}`} value={d} onChange={commit} canUndo={(history[workspace.active_role_id]?.length ?? 0) > 0} onUndo={undo} paper={<ResumePaper draft={d} role={active} profile={workspace.profile} />} />
    </>}
  </main></div>
}

import { useEffect, useRef, useState } from 'react'
import ResumeWorkbench from './ResumeWorkbench'
import type { Workbench } from './import'
import DraftStudio from './DraftStudio'
import { emptyReview, newDraft, readDraft, saveDraft, validate, type Draft } from './draft'
import './resume.css'

export default function LocalResumeLab() {
  const [document, setDocument] = useState<Draft | null>(null), [retained, setRetained] = useState<string[]>([]), [history, setHistory] = useState<Draft[]>([]), [epoch, setEpoch] = useState(0), [error, setError] = useState(''), [loading, setLoading] = useState(false)
  const generation = useRef(0)
  useEffect(() => () => { generation.current++ }, [])
  function source(w: Workbench | null) { generation.current++; setLoading(false); setDocument(w ? newDraft(w, retained) : null); setHistory([]); setError('') }
  function commit(next: Draft) {
    try { const rejected = [...new Set([...retained, ...next.rejected_statements])]; const checked = validate({ ...next, rejected_statements: rejected }); setRetained(rejected); if (document) setHistory(h => [...h.slice(-29), document]); setDocument(checked); setError('') }
    catch { setError('草稿修改未通过安全校验，未应用；没有上传或保存。') }
  }
  async function restore(file: File | undefined) {
    if (!file) return
    const g = ++generation.current; setDocument(null); setHistory([]); setError(''); setLoading(true); setEpoch(n => n + 1)
    try { const d = await readDraft(file, retained); if (g === generation.current) { setDocument(d); setRetained(d.rejected_statements); setEpoch(n => n + 1) } }
    catch { if (g === generation.current) setError('草稿未恢复：文件类型、UTF-8、大小、版本、字段、引用或状态不受支持。没有部分结果，也没有执行任何请求。') }
    finally { if (g === generation.current) setLoading(false) }
  }
  function download() {
    try { if (!document) return; const url = URL.createObjectURL(new Blob([saveDraft(document)], { type: 'application/json' })); const link = window.document.createElement('a'); link.href = url; link.download = 'pathwise-local-draft-v1.json'; link.click(); URL.revokeObjectURL(url); setError('') }
    catch { setError('草稿未下载：内容校验失败或超过512 KiB，请缩减并检查。') }
  }
  return <div className="resume-lab"><header><a href="/">✦ Pathwise</a><span>本地简历工作台 · 开发预览</span><a href="/jd-lab">合成可信预览（独立入口）</a></header><main>
    <section className="resume-hero"><p className="resume-kicker">YOUR WORDS. YOUR NEXT STEP.</p><h1>从你已有的经历，<br />走向下一份岗位。</h1><p>没有亮眼指标也能开始。先保留原话，再看清证据与边界。</p></section>
    <aside className="resume-notice">本地材料和手工声明均未经平台核实；不自动确认、分类或保存到事实库。合成已审核FactV3仅在原独立实验入口，不可与导入文字混淆。正式数据库与认证结果未接入；无网络、AI或G4正式写入。</aside>
    <section className="resume-panel" aria-label="主动保存与恢复"><h2>本地草稿，由你决定保存</h2><p>下载文件包含完整原文、编辑和复习回答，请妥善保管。没有凭证、数据库认证或操作回执；文件可被改动，不保证事实真实或历史完整。刷新不自动恢复。</p><div className="resume-actions"><button disabled={!document || loading} onClick={download}>下载本地草稿 JSON</button><label className="resume-file">恢复本地草稿 JSON<input type="file" accept=".json,application/json" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; void restore(file) }} /></label></div>{loading && <p role="status">正在本地校验草稿…</p>}{error && <p role="alert">{error}</p>}</section>
    <ResumeWorkbench key={`source-${epoch}`} value={document?.workbench ?? null} onChange={source} />
    {document && <DraftStudio key={`studio-${document.workbench.source.id}-${epoch}`} value={document} onChange={commit} canUndo={history.length > 0} onUndo={() => { const previous = history.at(-1); if (!previous) return; try { setDocument(validate({ ...previous, rejected_statements: [...new Set([...previous.rejected_statements, ...retained])], review: emptyReview() })); setHistory(h => h.slice(0, -1)); setError('') } catch { setError('不能安全撤销，拒绝记录仍保留。') } }} />}
  </main></div>
}

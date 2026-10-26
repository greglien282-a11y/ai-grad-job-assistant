import { useEffect, useRef, useState } from 'react'
import { addManual, excerpt, importText, privacyWarnings, readFile, sections, workbenchSchema, type Section, type Workbench } from './import'
import { graduateResume } from './fixtures'

export default function ResumeWorkbench({ value, onChange }: { value: Workbench | null; onChange: (w: Workbench | null) => void }) {
  const [raw, setRaw] = useState(''), [manual, setManual] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const generation = useRef(0)
  useEffect(() => () => { generation.current++ }, [])
  function invalidate() { generation.current++; setBusy(false); onChange(null); setError('') }
  function apply(w: Workbench) { onChange(w); setError(''); setManual('') }
  async function choose(file: File | undefined) {
    invalidate(); if (!file) return
    const g = generation.current; setBusy(true)
    try { const w = await readFile(file); if (g === generation.current) { setRaw(''); apply(w) } }
    catch { if (g === generation.current) setError('文件未导入：请选择有效UTF-8、非空且128 KiB以内的 .txt / .md，并移除凭证或隐藏控制字符。') }
    finally { if (g === generation.current) setBusy(false) }
  }
  function attempt(action: () => void) { try { action(); setError('') } catch { setError('内容或引用校验失败，未应用修改。请核对Unicode code-point半开区间、完整原文及隐私。') } }
  return <>
    <section className="resume-panel" aria-label="本地简历导入"><p className="resume-kicker">01 / BRING YOUR OWN WORDS</p><h2>从已有材料开始</h2><p>粘贴或选择本地UTF-8文字。只留当前运行内存；刷新清空，不上传、不遥测、不自动保存。疑似凭证拒绝，联系方式提示核对。</p>
      <button className="secondary" onClick={() => { invalidate(); setRaw(graduateResume) }}>填入公开合成简历</button>
      <label>简历原文<textarea value={raw} maxLength={40000} onChange={e => { invalidate(); setRaw(e.target.value) }} /></label>
      <div className="resume-actions"><button disabled={busy} onClick={() => attempt(() => apply(importText(raw)))}>导入并核对原文</button><label className="resume-file">选择本地文本文件<input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; void choose(file) }} /></label></div>
      {busy && <p role="status">正在本地读取文件…</p>}{error && <p role="alert">{error} 本次没有上传或保存。</p>}
    </section>
    {value && <>
      <section className="resume-panel" aria-label="原文与候选结构"><h2>逐段核对，来源不变</h2><p>候选分段不等于事实分类。位置按Unicode code points计算；手工修改结构不会产生确认或认证。修改材料/结构会清除后续岗位草稿，避免沿用旧引用。</p>
        {privacyWarnings(value.source.text).map(w => <p role="note" key={w}>{w}</p>)}
        <div className="resume-columns"><div><h3>完整导入原文 · 未审核</h3><p>{value.source.origin === 'file' ? value.source.name : '本地粘贴'} · local_unverified</p><pre aria-label="完整简历原文">{value.source.text}</pre></div>
        <div><h3>候选段落</h3>{value.excerpts.map((e, i) => <article className="resume-card" key={e.id}><p>段落 {i + 1} · {sections[e.section]} · [{e.start}, {e.end})</p><blockquote>{e.quote}</blockquote>
          <form onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); attempt(() => { const updated = excerpt(value, Number(data.get('start')), Number(data.get('end')), data.get('section') as Section, e.id, String(data.get('label'))); apply(workbenchSchema.parse({ ...value, excerpts: value.excerpts.map(x => x.id === e.id ? updated : x) })) }) }}>
            <label>段落标题 {i + 1}<input name="label" defaultValue={e.label} maxLength={100} /></label>
            <label>段落类型 {i + 1}<select name="section" defaultValue={e.section}>{Object.entries(sections).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
            <div className="resume-range"><label>起点 {i + 1}<input name="start" type="number" min="0" defaultValue={e.start} /></label><label>终点 {i + 1}<input name="end" type="number" min="1" defaultValue={e.end} /></label></div>
            <button className="secondary">应用段落 {i + 1}</button>
          </form></article>)}
          {!value.excerpts.length && <p>没有可自动识别的正文段落，请补充原文。</p>}
        </div></div>
      </section>
      <section className="resume-panel" aria-label="用户手工声明"><h2>补充一条自己的说明</h2><p>单独标记为用户手工声明，无导入原文引用；不成为FactV3、分类依据或已审核个人贡献。</p>
        <label>手工声明<textarea value={manual} onChange={e => setManual(e.target.value)} maxLength={40000} /></label><button onClick={() => attempt(() => apply(addManual(value, manual)))}>添加未审核声明</button>
        {value.manual.map(m => <article key={m.id} className="resume-card"><span>用户手工声明 · local_unverified</span><blockquote>{m.text}</blockquote></article>)}
      </section>
    </>}
  </>
}

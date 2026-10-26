import { admission, printable, provenance, type Draft } from './draft'
import { sections, type Section } from './import'
import type { Role, Workspace } from './workspace'
export default function ResumePaper({ draft: d, role, profile }: { draft: Draft; role: Role; profile: Workspace['profile'] }) {
  const shown = printable(d), section = (id: string): Section => d.workbench.excerpts.find(e => e.id === id)?.section ?? 'other'
  // Estimate is guidance only. Actual pagination belongs to native browser print.
  const estimatedPages = Math.max(1, Math.ceil(shown.reduce((n, e) => n + Array.from(e.text + e.original).length + 100, 0) / (d.layout === 'compact' ? 1700 : 1300)))
  return <><p className="page-estimate">{role.page_goal === 'one' ? '一页目标' : '多页排版'} · 当前内容粗估 {estimatedPages} 页；仅为提示，实际分页以浏览器打印为准。内容不截断、不自动缩写；长段落允许换页。</p>
    <article className={`local-resume-paper resume-template-${role.template} ${d.layout}`} aria-label="用户自述简历草稿" data-template={role.template}>
      <p className="paper-label">PATHWISE · 用户自述草稿 / 未经平台核实</p><div className="paper-profile"><h2>{profile.name || '你的姓名 · 待填写'}</h2>{profile.contact && <p>{profile.contact}</p>}{profile.location && <p>{profile.location}</p>}{profile.headline && <p>{profile.headline}</p>}</div>
      <p className="paper-target">目标岗位：{d.job?.title ?? role.name}</p>
      {Array.from(new Set(shown.filter(e => admission(d, e).kind === 'draft').map(e => section(e.id)))).map(key => { const list = shown.filter(e => section(e.id) === key && admission(d, e).kind === 'draft'); return list.length > 0 && <section key={key}><h3>{sections[key]} · 用户自述</h3>{list.map(e => <div className={`paper-entry ${Array.from(e.text).length > 400 ? 'paper-entry-long' : ''}`} key={e.id}><p>{e.text}</p><small>{e.state === 'user_edited' ? `用户改写；原文：${e.original}` : '保留原文；用户自述未核实'}</small><small>{provenance(d, e)}</small></div>)}</section> })}
      {shown.some(e => admission(d, e).kind === 'context') && <section><h3>背景、计划与限制 · 不是已完成个人贡献</h3>{shown.filter(e => admission(d, e).kind === 'context').map(e => <div className="paper-entry" key={e.id}><p>{e.text}</p><small>原文保留 · 不能用作个人完成的证明</small><small>{provenance(d, e)}</small></div>)}</section>}
      {!shown.length && <p>没有选用且可安全展示的条目，保持空白。</p>}<footer>本地材料由用户提供并负责核对。无平台真实性认证、正式事实保存或G4准入。计划和背景不等同于个人完成成果。</footer>
    </article></>
}

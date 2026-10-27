import { useState } from 'react'
import { addRole, rolePresets, type Workspace } from './workspace'
export default function RoleControls({ value: w, onChange }: { value: Workspace; onChange: (w: Workspace) => void }) {
  const [name, setName] = useState(''), [error, setError] = useState(''), current = w.roles.find(r => r.id === w.active_role_id)!
  function attempt(action: () => Workspace) { try { onChange(action()); setError('') } catch { setError('岗位名称或资料不合法，或已达到5个岗位上限。修改未应用。') } }
  return <section className="resume-panel" aria-label="多岗位与基本信息"><p className="resume-kicker">ONE SOURCE. DIFFERENT ROLES.</p><h2>一份材料，分别准备每个岗位</h2><p>原始材料共用且不随切换改变。JD、选用顺序、草稿、条件判断、版式和三题回答按岗位独立保留。最多5个；不自动保存。</p>
    <label>当前岗位<select value={w.active_role_id} onChange={e => onChange({ ...w, active_role_id: e.target.value })}>{w.roles.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label>
    <label>岗位草稿名称<input maxLength={80} value={current.name} onChange={e => { if (e.target.value.trim()) attempt(() => ({ ...w, roles: w.roles.map(r => r.id === current.id ? { ...r, name: e.target.value } : r) })) }} /></label>
    <div className="resume-actions">{Object.entries(rolePresets).map(([key, preset]) => <button key={key} className="secondary" disabled={w.roles.length >= 5} onClick={() => attempt(() => addRole(w, preset.name, preset.jd))}>新增{preset.name}草稿</button>)}</div>
    <label>新岗位名称<input value={name} maxLength={80} onChange={e => setName(e.target.value)} /></label><button disabled={w.roles.length >= 5 || !name.trim()} onClick={() => attempt(() => addRole(w, name))}>新增空白岗位草稿</button>
    <h3>基本信息 · 用户自行填写</h3><p>只留运行内存。不会从文件自动认证身份；下载将包含以下联系方式。</p><div className="profile-grid">{([['name', '姓名'], ['contact', '联系信息'], ['location', '所在城市'], ['headline', '简历抬头说明']] as const).map(([key, label]) => <label key={key}>{label}<input value={w.profile[key]} maxLength={key === 'contact' ? 240 : key === 'headline' ? 200 : 80} onChange={e => attempt(() => ({ ...w, profile: { ...w.profile, [key]: e.target.value } }))} /></label>)}</div>
    <div className="resume-actions"><label>简历版式<select value={current.template} onChange={e => attempt(() => ({ ...w, roles: w.roles.map(r => r.id === current.id ? { ...r, template: e.target.value as typeof r.template } : r) }))}><option value="classic">清晰分栏标题</option><option value="minimal">简洁居中抬头</option></select></label><label>分页目标<select value={current.page_goal} onChange={e => attempt(() => ({ ...w, roles: w.roles.map(r => r.id === current.id ? { ...r, page_goal: e.target.value as typeof r.page_goal } : r) }))}><option value="one">一页目标（不裁切）</option><option value="multiple">允许多页</option></select></label></div>
    {error && <p role="alert">{error}</p>}
  </section>
}

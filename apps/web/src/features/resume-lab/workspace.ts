import { z } from 'zod'
import { checkText, isReviewed, workbenchSchema, type Workbench } from './import'
import { admission, draftBodySchema, emptyReview, newDraft, noDuplicateKeys, restoreDraft, setJob, strategies, terms, validate, type Draft } from './draft'
export const WORKSPACE_CONTRACT = 'local-job-resume-draft-v3'
export const MAX_WORKSPACE_BYTES = 2 * 1024 * 1024
const field = (max: number) => z.string().max(max).superRefine((v, ctx) => { if (v) try { checkText(v) } catch { ctx.addIssue({ code: 'custom', message: 'Unsafe local text' }) } })
export const profileSchema = z.strictObject({ name: field(80), contact: field(240), location: field(80), headline: field(200) })
const contentSchema = draftBodySchema.omit({ workbench: true, rejected_statements: true })
const roleSchema = z.strictObject({ id: z.string().uuid(), name: field(80).min(1), content: contentSchema, template: z.enum(['classic', 'minimal']), page_goal: z.enum(['one', 'multiple']) })
const workspaceSchema = z.strictObject({ contract: z.literal(WORKSPACE_CONTRACT), trust: z.literal('user_draft_not_verified'), workbench: workbenchSchema, profile: profileSchema, roles: z.array(roleSchema).min(1).max(5), active_role_id: z.string().uuid(), rejected_statements: z.array(field(20000).min(1)).max(100) })
export type Workspace = z.infer<typeof workspaceSchema>
export type Role = Workspace['roles'][number]
export const blankProfile = (): Workspace['profile'] => ({ name: '', contact: '', location: '', headline: '' })
export function roleDraft(w: Workspace, id = w.active_role_id): Draft {
  const role = w.roles.find(r => r.id === id); if (!role) throw new Error('Unknown role')
  return validate({ ...role.content, contract: w.workbench.contract === 'local-resume-workbench-v1' ? 'local-job-resume-draft-v1' : 'local-job-resume-draft-v2', workbench: w.workbench, rejected_statements: w.rejected_statements })
}
function body(d: Draft): Role['content'] { const { contract: _contract, workbench: _source, rejected_statements: _rejected, ...content } = d; return content }
export function validateWorkspace(raw: unknown): Workspace {
  const w = workspaceSchema.parse(raw), ids = w.roles.map(r => r.id)
  if (new Set(ids).size !== ids.length || !ids.includes(w.active_role_id) || new Set(w.rejected_statements).size !== w.rejected_statements.length || w.roles.some(r => !r.name.trim())) throw new Error('Invalid workspace graph')
  for (const r of w.roles) roleDraft(w, r.id)
  return w
}
export function fromDraft(d: Draft): Workspace {
  const id = crypto.randomUUID()
  return validateWorkspace({ contract: WORKSPACE_CONTRACT, trust: 'user_draft_not_verified', workbench: d.workbench, profile: blankProfile(), active_role_id: id, rejected_statements: d.rejected_statements, roles: [{ id, name: Array.from(d.job?.title ?? '我的第一个岗位').slice(0, 80).join(''), content: body(d), template: 'classic', page_goal: 'one' }] })
}
export const newWorkspace = (source: Workbench, rejected: string[] = []) => fromDraft(newDraft(source, rejected))
export function updateRole(w: Workspace, d: Draft): Workspace {
  // Shared source cannot be silently changed through a role editor.
  if (JSON.stringify(d.workbench) !== JSON.stringify(w.workbench)) throw new Error('Source changed')
  const rejected = [...new Set([...w.rejected_statements, ...d.rejected_statements])], newRejection = rejected.length !== w.rejected_statements.length
  return validateWorkspace({ ...w, rejected_statements: rejected, roles: w.roles.map(r => ({ ...r, content: { ...(r.id === w.active_role_id ? body(d) : r.content), ...(newRejection ? { review: emptyReview() } : {}) } })) })
}
export function addRole(w: Workspace, name: string, rawJD?: string): Workspace {
  if (w.roles.length >= 5) throw new Error('最多5个岗位')
  const id = crypto.randomUUID(), d = rawJD ? setJob(newDraft(w.workbench, w.rejected_statements), rawJD) : newDraft(w.workbench, w.rejected_statements)
  return validateWorkspace({ ...w, active_role_id: id, roles: [...w.roles, { id, name, content: body(d), template: 'classic', page_goal: 'one' }] })
}
export function mergeRejections(w: Workspace, retained: string[]): Workspace {
  const rejected = [...new Set([...retained, ...w.rejected_statements])]
  return validateWorkspace({ ...w, rejected_statements: rejected, roles: w.roles.map(r => ({ ...r, content: { ...r.content, review: rejected.length !== w.rejected_statements.length ? emptyReview() : r.content.review } })) })
}
export function restoreWorkspace(raw: string, retained: string[] = []): { workspace: Workspace; migrated: boolean } {
  if (new TextEncoder().encode(raw).length > MAX_WORKSPACE_BYTES) throw new Error('File too large')
  const value = noDuplicateKeys(raw)
  if (typeof value !== 'object' || !value || !('contract' in value)) throw new Error('Unknown contract')
  if (value.contract === WORKSPACE_CONTRACT) return { workspace: mergeRejections(validateWorkspace(value), retained), migrated: false }
  if (value.contract === 'local-job-resume-draft-v1' || value.contract === 'local-job-resume-draft-v2') return { workspace: fromDraft(restoreDraft(raw, retained)), migrated: true }
  throw new Error('Unknown contract')
}
export async function readWorkspace(file: File, retained: string[]) {
  if (!/^[^\\/\x00-\x1f]{1,120}\.json$/i.test(file.name) || !file.size || file.size > MAX_WORKSPACE_BYTES) throw new Error('Invalid file')
  const result = restoreWorkspace(new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer()), retained)
  const w = result.workspace.workbench
  if (w.contract === 'local-resume-workbench-v2') {
    const { sha256 } = await import('./document-import')
    if (await sha256(new TextEncoder().encode(w.source.text)) !== w.source.extraction.text_sha256) throw new Error('Snapshot mismatch')
  }
  return result
}
export function saveWorkspace(w: Workspace): string {
  const checked = validateWorkspace(w)
  if (!isReviewed(checked.workbench)) throw new Error('Review text before export')
  const raw = JSON.stringify(checked, null, 2)
  if (new TextEncoder().encode(raw).length > MAX_WORKSPACE_BYTES) throw new Error('File too large')
  return raw
}
export function suggestions(d: Draft) {
  return d.entries.map((e, index) => {
    const links = strategies(d).filter(s => s.matches.some(m => m.id === e.id)).map(s => ({
      ...s, words: terms(s.requirement.quote).filter(t => terms(s.requirement.text).includes(t) && terms(e.original).includes(t)),
      assessment: d.assessments.find(a => a.requirement_id === s.requirement.id)!.state,
    })).filter(s => s.words.length > 0)
    const allowed = admission(d, e).kind === 'draft', usable = links.filter(s => s.assessment !== 'gap')
    const status = !allowed ? 'boundary' : links.length && !usable.length ? 'gap' : usable.length ? 'literal' : 'insufficient'
    return { entry: e, requirements: links.map(s => s.requirement), links, status, eligible: allowed && usable.length > 0, index,
      reason: !allowed ? '来源存在计划、团队、否定或冲突限制；不建议改写成个人完成。' : status === 'gap' ? '用户明确自评尚未掌握；词汇出现不能覆盖能力缺口。' : usable.length ? '原句与以下岗位引文有字面关联；可优先展示，不证明掌握或完成。' : '证据不足：未找到原句与JD原句的字面关联；不代表没有能力。' }
  }).sort((a, b) => Number(b.eligible) - Number(a.eligible) || a.index - b.index)
}
export function applySourceSuggestions(d: Draft): Draft {
  const ids = new Set(suggestions(d).filter(s => s.eligible).map(s => s.entry.id))
  // Explicit application retains order and exact words; admission excludes conflicts.
  return validate({ ...d, entries: [...d.entries.filter(e => ids.has(e.id)).map(e => ({ ...e, text: e.original, state: 'original' as const, selected: true })), ...d.entries.filter(e => !ids.has(e.id))], review: emptyReview() })
}
export function applySourceSuggestion(d: Draft, id: string): Draft {
  const suggestion = suggestions(d).find(s => s.entry.id === id)
  if (!suggestion?.eligible) throw new Error('No safe source suggestion')
  // Explicit application restores the exact source, never synthesizes a rewritten achievement.
  const target = { ...suggestion.entry, text: suggestion.entry.original, state: 'original' as const, selected: true }
  return validate({ ...d, entries: [target, ...d.entries.filter(e => e.id !== id)], review: emptyReview() })
}
export const rolePresets = {
  vision: { name: '视觉算法实习生', jd: '视觉算法实习生\n必备：Python、图像处理课程基础。\n加分：PyTorch、OpenCV项目。\n待核实：是否要求部署经验。' },
  backend: { name: 'Python后端实习生', jd: 'Python后端实习生\n必备：Python基础与测试意识。\n加分：部署经历。\n待核实：本科教育要求。' },
  testing: { name: '软件测试实习生', jd: '软件测试实习生\n必备：测试与Python课程基础。\n加分：项目记录。\n待核实：是否要求实习经验。' },
} as const

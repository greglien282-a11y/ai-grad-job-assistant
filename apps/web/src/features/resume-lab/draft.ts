import { z } from 'zod'
import { analyzeJD, type Job, type Requirement } from '../jd-lab/jd'
import { checkText, workbenchSchema, legacyWorkbenchSchema, extractedWorkbenchSchema, type Workbench } from './import'

export const DRAFT_CONTRACT = 'local-job-resume-draft-v1'
export const MAX_DRAFT_BYTES = 512 * 1024
const text = z.string().superRefine((v, ctx) => { try { checkText(v) } catch { ctx.addIssue({ code: 'custom', message: 'Unsafe text' }) } })
const optionalText = z.union([z.literal(''), text])
const requirement = z.strictObject({ id: z.string(), text: optionalText, quote: text, start: z.number().int().nonnegative(), end: z.number().int().positive(), category: z.enum(['technical', 'education', 'experience', 'other']), priority: z.enum(['must', 'bonus', 'uncertain']), adjusted: z.boolean(), conflict: z.boolean() })
const entry = z.strictObject({ id: z.string().uuid(), source_kind: z.enum(['resume_excerpt', 'user_manual_statement']), original: text, text: optionalText, state: z.enum(['original', 'user_edited']), selected: z.boolean() })
const assessment = z.strictObject({ requirement_id: z.string(), state: z.enum(['needs_evidence', 'can_explain', 'gap']) })
export const draftBodySchema = z.strictObject({ trust: z.literal('user_draft_not_verified'), workbench: workbenchSchema,
  job: z.strictObject({ title: text, raw: text, requirements: z.array(requirement).max(200) }).nullable(),
  entries: z.array(entry).max(150), assessments: z.array(assessment).max(200), rejected_statements: z.array(text).max(100),
  layout: z.enum(['comfortable', 'compact']), review: z.strictObject({ step: z.number().int().min(0).max(3), complete: z.boolean(), answers: z.tuple([optionalText, optionalText, optionalText]) }),
})
const schema = z.union([draftBodySchema.extend({ contract: z.literal(DRAFT_CONTRACT), workbench: legacyWorkbenchSchema }), draftBodySchema.extend({ contract: z.literal('local-job-resume-draft-v2'), workbench: extractedWorkbenchSchema })])
export type Draft = z.infer<typeof schema>
export type Entry = Draft['entries'][number]
export const emptyReview = (): Draft['review'] => ({ step: 0, complete: false, answers: ['', '', ''] })
export function originals(w: Workbench) {
  return [...w.excerpts.map(e => ({ id: e.id, source_kind: e.kind, original: e.quote })), ...w.manual.map(m => ({ id: m.id, source_kind: m.kind, original: m.text }))]
}
export function newDraft(workbench: Workbench, rejected_statements: string[] = []): Draft {
  return validate({ contract: workbench.contract === 'local-resume-workbench-v1' ? DRAFT_CONTRACT : 'local-job-resume-draft-v2', trust: 'user_draft_not_verified', workbench, job: null,
    entries: originals(workbench).map(e => ({ ...e, text: e.original, state: 'original', selected: false })),
    assessments: [], rejected_statements: [...new Set(rejected_statements)], layout: 'comfortable', review: emptyReview() })
}
export function validate(raw: unknown): Draft {
  const d = schema.parse(raw), os = originals(d.workbench), used = new Set<string>()
  for (const e of d.workbench.excerpts) checkText(e.label)
  if (d.entries.length !== os.length || d.entries.some(e => {
    const o = os.find(x => x.id === e.id)
    if (used.has(e.id)) return true
    used.add(e.id)
    return !o || e.source_kind !== o.source_kind || e.original !== o.original || e.state !== (e.text === e.original ? 'original' : 'user_edited')
  }) || new Set(d.rejected_statements).size !== d.rejected_statements.length) throw new Error('Invalid source/entry/state relation')
  if (d.job) {
    const canonical = analyzeJD(d.job.raw)
    if (d.job.title !== canonical.title || d.job.requirements.length !== canonical.requirements.length || d.job.requirements.some((r, i) => {
      const c = canonical.requirements[i]
      return r.id !== c.id || r.quote !== c.quote || r.start !== c.start || r.end !== c.end || r.conflict !== c.conflict ||
        (c.conflict && r.priority !== 'uncertain') || (!r.adjusted && JSON.stringify(r) !== JSON.stringify(c))
    })) throw new Error('Invalid job provenance')
  }
  const required = d.job?.requirements ?? []
  if (d.assessments.length !== required.length || new Set(d.assessments.map(a => a.requirement_id)).size !== required.length || d.assessments.some(a => !required.some(r => r.id === a.requirement_id))) throw new Error('Invalid strategy relation')
  if (d.review.step > 0 && (!d.job || !printable(d).length)) throw new Error('Review has no source')
  if (d.review.complete && d.review.step !== 3) throw new Error('Invalid review state')
  return d
}
export function setJob(d: Draft, raw: string): Draft {
  checkText(raw)
  const job = analyzeJD(raw)
  return validate({ ...d, job, assessments: job.requirements.map(r => ({ requirement_id: r.id, state: 'needs_evidence' })), review: emptyReview() })
}
// Literal matching explains overlap only; no synonyms, proficiency or missing-skill inference.
const vocabulary = ['python', 'pytorch', 'opencv', '图像处理', '视觉', '标注', '部署', '测试', '项目', '团队', '本科', '实习', '量化']
export const terms = (s: string) => vocabulary.filter(t => /^[a-z]+$/.test(t) ? new RegExp(`\\b${t}\\b`, 'i').test(s) : s.includes(t))
export const caution = (s: string) => /计划|正在|尚未|没有|不确定|未参与|不知道|团队|我们|只|暂无|未做|未掌握|并非|不是|不具备|尚无|不熟悉|未完成|不会|非本人|被拒绝|已拒绝/.test(s)
export function provenance(d: Draft, e: Entry): string {
  const q = d.workbench.excerpts.find(x => x.id === e.id)
  return q ? `${d.workbench.contract === 'local-resume-workbench-v2' ? '解析文本快照 CP' : '导入原文'} [${q.start}, ${q.end}) · ${d.workbench.source.name ?? '本地粘贴'}` : '用户手工声明 · 无导入原文引用'
}
export function admission(d: Draft, e: Entry): { kind: 'draft' | 'context' | 'blocked'; reason: string } {
  if (!e.text.trim()) return { kind: 'blocked', reason: '空白草稿不打印，也不作为复习来源。' }
  if (d.rejected_statements.includes(e.original) || /已拒绝|被拒绝/.test(e.original)) return { kind: 'blocked', reason: '本地拒绝记录保留；换来源ID或恢复文件不解除。R03语义独立仍需审核。' }
  const peers = d.entries.filter(x => x.original === e.original)
  if (peers.some(x => x.text !== e.text || x.state !== e.state)) return { kind: 'blocked', reason: '同原句存在不同编辑状态或正文，整组不打印。' }
  if (peers.some(x => x.id < e.id)) return { kind: 'blocked', reason: '相同原句只打印一次，不重复计算。' }
  const q = d.workbench.excerpts.find(x => x.id === e.id)
  // A manually cropped quote never proves the context outside it disappeared.
  const points = Array.from(d.workbench.source.text)
  const sourceContext = q ? (points.slice(0, q.start).join('').split(/\r?\n[ \t]*\r?\n/).at(-1) ?? '') + q.quote + points.slice(q.end).join('').split(/\r?\n[ \t]*\r?\n/)[0] : e.original
  const context = caution(sourceContext) || caution(e.original) || caution(e.text)
  if (context && e.state === 'user_edited') return { kind: 'blocked', reason: '来源存在责任/计划/否定限制，改写不能消除边界；恢复原文后仅作背景与限制。' }
  return context ? { kind: 'context', reason: '背景、计划或限制 / 待核对；不是已完成个人贡献。' } : { kind: 'draft', reason: '用户自述草稿，内容由用户核对；未通过平台或G4认证。' }
}
export function strategies(d: Draft) {
  return (d.job?.requirements ?? []).map(r => {
    const matches = d.entries.filter(e => terms(r.text).some(t => terms(e.original).includes(t)))
    const assessment = d.assessments.find(a => a.requirement_id === r.id)!.state
    const canExplain = assessment === 'can_explain' && !r.conflict && matches.some(e => admission(d, e).kind === 'draft' && e.state === 'original')
    return { requirement: r, matches, label: assessment === 'gap' ? '真实能力缺口（用户明确自评，非系统推断）' : canExplain ? '可以直接说明（用户自评，非平台核实）' : '需要补充证据 / 核对职责',
      explanation: matches.length ? '仅有原文字面关联；不证明熟练度、项目真实性或完成状态。' : '没有找到字面来源，不等于证明你没有能力。' }
  })
}
export function printable(d: Draft) { return d.entries.filter(e => e.selected && admission(d, e).kind !== 'blocked') }
export function questions(d: Draft) {
  if (!d.job || !d.job.requirements.length) return []
  const selected = printable(d)
  return selected.length ? ['你实际做了什么？请区分个人、团队及尚未完成的部分。', '有哪些结果能回到原始记录？没有数字时请明确说没有。', '这个岗位还缺什么证据或能力？哪些内容尚需核对？'].map((prompt, i) => {
    const e = selected[i % selected.length], linked = strategies(d).find(s => s.matches.some(x => x.id === e.id))
    return { prompt, entry: e, requirement: linked?.requirement ?? d.job!.requirements[i % d.job!.requirements.length], provenance: provenance(d, e) }
  }) : []
}
export function noDuplicateKeys(raw: string): unknown {
  const value: unknown = JSON.parse(raw), stack: (Set<string> | null)[] = []
  const token = /"(?:\\[\s\S]|[^"\\])*"|[{}\[\]]/g
  for (const match of raw.matchAll(token)) {
    const t = match[0]
    if (t === '{' || t === '[') { stack.push(t === '{' ? new Set() : null); if (stack.length > 32) throw new Error('Nesting limit') }
    else if (t === '}' || t === ']') stack.pop()
    else if (/^\s*:/.test(raw.slice(match.index! + t.length))) {
      const keys = stack[stack.length - 1], key: string = JSON.parse(t)
      if (!keys || keys.has(key)) throw new Error('Duplicate JSON key')
      keys.add(key)
    }
  }
  return value
}
export function restoreDraft(raw: string, retainedRejections: string[] = []): Draft {
  if (new TextEncoder().encode(raw).length > MAX_DRAFT_BYTES) throw new Error('File too large')
  const d = validate(noDuplicateKeys(raw))
  return validate({ ...d, rejected_statements: [...new Set([...retainedRejections, ...d.rejected_statements])] })
}
export function saveDraft(d: Draft): string {
  const raw = JSON.stringify(validate(d), null, 2)
  if (new TextEncoder().encode(raw).length > MAX_DRAFT_BYTES) throw new Error('File too large')
  return raw
}
export async function readDraft(file: File, rejected: string[]): Promise<Draft> {
  if (!/^[^\\/\u0000-\u001F]{1,120}\.json$/i.test(file.name) || !file.size || file.size > MAX_DRAFT_BYTES) throw new Error('Invalid file')
  const raw = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer())
  const d = restoreDraft(raw, rejected)
  if (d.workbench.contract === 'local-resume-workbench-v2') {
    const { sha256 } = await import('./document-import')
    if (await sha256(new TextEncoder().encode(d.workbench.source.text)) !== d.workbench.source.extraction.text_sha256) throw new Error('Snapshot mismatch')
  }
  return d
}
export function adjustRequirement(d: Draft, id: string, patch: Partial<Pick<Requirement, 'text' | 'priority'>>): Draft {
  return validate({ ...d, job: { ...d.job, requirements: d.job!.requirements.map(r => r.id === id ? { ...r, ...patch, priority: r.conflict ? 'uncertain' : patch.priority ?? r.priority, adjusted: true } : r) } })
}
export type { Job }

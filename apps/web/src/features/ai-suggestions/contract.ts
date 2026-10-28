import { z } from 'zod'
import { admission, emptyReview, noDuplicateKeys, validate, type Draft } from '../resume-lab/draft'
import { checkText } from '../resume-lab/import'

export const SUGGESTION_CONTRACT = 'local-suggestion-candidates-v1'
export const MAX_CANDIDATE_BYTES = 512 * 1024
const text = z.string().min(1).max(20000).superRefine((v, ctx) => { try { checkText(v) } catch { ctx.addIssue({ code: 'custom', message: 'Unsafe candidate text' }) } })
const id = z.string().min(1).max(200).regex(/^[A-Za-z0-9_.:-]+$/)
const span = { start: z.number().int().nonnegative(), end: z.number().int().positive(), quote: text }
const kind = z.enum(['resume_excerpt', 'user_manual_statement'])
const schema = z.strictObject({
  contract: z.literal(SUGGESTION_CONTRACT), role_id: id,
  source_snapshot: z.strictObject({ id, text, paragraphs: z.array(z.strictObject({ id, kind, ...span })).max(150) }),
  jd_snapshot: z.strictObject({ text, requirements: z.array(z.strictObject({ id, ...span })).min(1).max(200) }),
  suggestions: z.array(z.strictObject({ id,
    source: z.strictObject({ source_id: id, paragraph_id: id, kind, ...span }),
    jd: z.strictObject({ requirement_id: id, ...span }),
    priority: z.number().int().min(1).max(100), rewrite_text: text.nullable(), reason: text,
    new_claims: z.array(text).max(20), evidence_gap: text.nullable(),
    provenance: z.strictObject({ kind: z.enum(['deterministic_rule', 'offline_mock', 'supplied_offline']), id, version: id }),
  })).max(100),
})
export type CandidatePacket = z.infer<typeof schema>
export type Candidate = CandidatePacket['suggestions'][number]
type Binding = Pick<CandidatePacket, 'role_id' | 'source_snapshot' | 'jd_snapshot'>

// This local review snapshot is NOT an original file, user Turn or audit event.
// Appended manual declarations have their own kind and review-snapshot offsets.
export function binding(d: Draft, roleId: string): Binding {
  validate(d)
  if (!d.job) throw new Error('Analyze a job before generating candidates')
  let raw = d.workbench.source.text
  const paragraphs: CandidatePacket['source_snapshot']['paragraphs'] = d.workbench.excerpts.map(e => ({ id: e.id, kind: e.kind, start: e.start, end: e.end, quote: e.quote }))
  for (const m of d.workbench.manual) {
    raw += '\n\n[用户手工声明]\n'
    const start = Array.from(raw).length
    raw += m.text
    paragraphs.push({ id: m.id, kind: m.kind, start, end: Array.from(raw).length, quote: m.text })
  }
  return { role_id: roleId, source_snapshot: { id: `review:${d.workbench.source.id}:${roleId}`, text: raw, paragraphs },
    jd_snapshot: { text: d.job.raw, requirements: d.job.requirements.map(r => ({ id: r.id, start: r.start, end: r.end, quote: r.quote })) } }
}
const exactSpan = (a: { start: number; end: number; quote: string }, b: typeof a) => a.start === b.start && a.end === b.end && a.quote === b.quote
const unique = (xs: { id: string }[]) => new Set(xs.map(x => x.id)).size === xs.length
export function parsePacket(raw: unknown, expected?: Binding): CandidatePacket {
  if (new TextEncoder().encode(JSON.stringify(raw)).length > MAX_CANDIDATE_BYTES) throw new Error('Candidate packet exceeds local budget')
  const p = schema.parse(raw), source = Array.from(p.source_snapshot.text), jd = Array.from(p.jd_snapshot.text)
  if (!unique(p.source_snapshot.paragraphs) || !unique(p.jd_snapshot.requirements) || !unique(p.suggestions)) throw new Error('Duplicate identities')
  for (const q of [...p.source_snapshot.paragraphs.map(q => ({ q, points: source })), ...p.jd_snapshot.requirements.map(q => ({ q, points: jd }))]) {
    if (q.q.end <= q.q.start || q.q.end > q.points.length || q.points.slice(q.q.start, q.q.end).join('') !== q.q.quote) throw new Error('Invalid code-point source quote')
  }
  const pairs = new Set<string>()
  for (const s of p.suggestions) {
    const q = p.source_snapshot.paragraphs.find(q => q.id === s.source.paragraph_id), r = p.jd_snapshot.requirements.find(r => r.id === s.jd.requirement_id)
    const pair = JSON.stringify([s.source.paragraph_id, s.jd.requirement_id])
    if (!q || !r || s.source.source_id !== p.source_snapshot.id || s.source.kind !== q.kind || !exactSpan(s.source, q) || !exactSpan(s.jd, r) || pairs.has(pair)) throw new Error('Cross-source, incomplete or duplicate candidate binding')
    pairs.add(pair)
  }
  if (expected && JSON.stringify({ role_id: p.role_id, source_snapshot: p.source_snapshot, jd_snapshot: p.jd_snapshot }) !== JSON.stringify(expected)) throw new Error('Stale or foreign source/job/role snapshot')
  return p
}
export function parsePacketJSON(raw: string, expected?: Binding) {
  if (new TextEncoder().encode(raw).length > MAX_CANDIDATE_BYTES) throw new Error('Candidate input too large')
  return parsePacket(noDuplicateKeys(raw), expected)
}

export function decisionContext(d: Draft, roleId: string) {
  // Layout/review answers have no effect on the source basis; content and risks do.
  return JSON.stringify({ ...binding(d, roleId), job: d.job, entries: d.entries, assessments: d.assessments, rejected: d.rejected_statements })
}
export function candidateGate(d: Draft, c: Candidate): { status: 'original_only' | 'requires_review' | 'blocked'; reason: string } {
  const e = d.entries.find(e => e.id === c.source.paragraph_id)
  if (!e || e.original !== c.source.quote || e.source_kind !== c.source.kind) return { status: 'blocked', reason: '来源不存在或当前原句不一致。' }
  const a = admission(d, e), r = d.job?.requirements.find(r => r.id === c.jd.requirement_id)
  if (a.kind !== 'draft') return { status: 'blocked', reason: a.reason }
  if (!r || r.conflict || d.assessments.find(x => x.requirement_id === r.id)?.state === 'gap') return { status: 'requires_review', reason: '岗位条件冲突或用户明确自评能力缺口，不能据候选认定匹配。' }
  if (c.new_claims.length || c.evidence_gap || (c.rewrite_text !== null && c.rewrite_text !== e.original)) return { status: 'requires_review', reason: '改写或新增主张尚无独立证据，只能留在待核对区；用户单击接受不能证明真实性。' }
  if (e.state !== 'original') return { status: 'requires_review', reason: '当前已有用户改写，先回到原文编辑区核对，候选不能静默覆盖。' }
  return { status: 'original_only', reason: '只能选用并前移这条完整原句，仍为未经认证的用户草稿。' }
}
export function applyCandidate(d: Draft, roleId: string, raw: unknown, candidateId: string): Draft {
  const p = parsePacket(raw, binding(d, roleId)), c = p.suggestions.find(c => c.id === candidateId)
  if (!c || candidateGate(d, c).status !== 'original_only') throw new Error('Candidate requires evidence or is blocked')
  const e = d.entries.find(e => e.id === c.source.paragraph_id)!
  return validate({ ...d, entries: [{ ...e, selected: true }, ...d.entries.filter(x => x.id !== e.id)], review: emptyReview() })
}

/** Synthetic read DTO only; never a trusted projector, writer or truth check. */
export const READ_CONTRACT = 'classification-declaration-read-candidate-v1'
export const DECLARATION_CONTRACT = 'explicit-user-classification-declaration-candidate-v1'
export type Classification = {
  fact_kind: 'legacy_unspecified' | 'personal_action' | 'plan' | 'background' | 'boundary'
  progress_stage: 'legacy_unknown' | 'in_progress' | 'completed' | 'planned' | 'not_applicable'
  classification_contract: 'legacy-v0' | 'unclassified-v1' | 'explicit-typed-v1'
}
export type Citation = { turn_id: string; start: number; end: number; quote: string }
export type Turn = { id: string; session_id: string; role: 'user' | 'assistant'; content: string }
export type TextGroup = { availability: 'exact_quotes' | 'unquoted_source'; turn_ids: string[]; citations: Citation[] }
export type Subject = Classification & { fact_id: string; session_id: string; project_id: string;
  fact_version: number; statement: string; status: 'pending' | 'user_confirmed' | 'evidence_supported' | 'rejected' }
export type Declaration = { declaration_contract: typeof DECLARATION_CONTRACT; declaration_id: string;
  record_type: 'explicit_user_choice'; actor: 'user'; fact_id: string; fact_version: number;
  session_id: string; project_id: string; classification: Classification; statement_citations: Citation[];
  declaration_source: Citation; recorded_at: string;
  recorded_validation: { contract: 'typed-semantic-spike-v1'; status: 'eligible_candidate'; code: 'finite_rule_match' } }
export type Envelope = { read_contract: typeof READ_CONTRACT; synthetic: true; subject: Subject; turns: Turn[];
  text_provenance: { original: TextGroup; current: TextGroup };
  basis: { status: 'legacy_unclassified' | 'not_recorded'; declaration: null } |
    { status: 'user_declaration_recorded'; declaration: Declaration } }
export type Result = { status: 'parsed_candidate' | 'rejected'; code: string; view: Envelope | null;
  evidence_class: 'synthetic_contract_only'; authentication_verified: false; database_history_verified: false;
  language_validation_replayed: false; truth_verified: false; persistence_authorized: false }
const classificationKeys = ['fact_kind', 'progress_stage', 'classification_contract']
const flags = { evidence_class: 'synthetic_contract_only', authentication_verified: false,
  database_history_verified: false, language_validation_replayed: false, truth_verified: false,
  persistence_authorized: false } as const
type Dict = Record<string, unknown>
class Invalid extends Error {}
function requireThat(condition: unknown, code = 'candidate_shape_invalid'): asserts condition {
  if (!condition) throw new Invalid(code)
}
function object(value: unknown, keys: string[]): Dict {
  requireThat(typeof value === 'object' && value !== null && !Array.isArray(value))
  const actual = Object.keys(value)
  requireThat(actual.length === keys.length && keys.every(k => Object.hasOwn(value, k)))
  return value as Dict
}
function array(value: unknown, min = 0, max = 5): unknown[] {
  requireThat(Array.isArray(value) && value.length >= min && value.length <= max)
  return value
}
function string(value: unknown, max = 10000): string {
  requireThat(typeof value === 'string' && Array.from(value).length > 0 && Array.from(value).length <= max && !value.includes('\0'))
  // Reject lone UTF-16 surrogates; preserve valid pairs without normalization.
  for (const cp of value) {
    requireThat(cp.length !== 1 || cp.charCodeAt(0) < 0xd800 || cp.charCodeAt(0) > 0xdfff, 'candidate_text_invalid')
  }
  return value
}
function id(value: unknown): string {
  requireThat(typeof value === 'string')
  requireThat(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value), 'candidate_identifier_invalid')
  return value
}
function integer(value: unknown, min = 1): number {
  requireThat(typeof value === 'number' && Number.isSafeInteger(value) && value >= min)
  return value
}
function classification(v: Dict) {
  const k = v.fact_kind, p = v.progress_stage, c = v.classification_contract
  const stages: Record<string, string[]> = { personal_action: ['in_progress', 'completed'],
    plan: ['planned', 'in_progress'], background: ['not_applicable'], boundary: ['not_applicable'] }
  requireThat(typeof k === 'string' && typeof p === 'string' && typeof c === 'string' &&
    (k === 'legacy_unspecified' ? p === 'legacy_unknown' && ['legacy-v0', 'unclassified-v1'].includes(c) :
      c === 'explicit-typed-v1' && Object.hasOwn(stages, k) && stages[k].includes(p)), 'candidate_classification_invalid')
}
export function declarationText(v: Classification): string {
  return `我选择事实类型为 ${v.fact_kind}，进度为 ${v.progress_stage}。`
}
function cites(value: unknown, turns: Map<string, Turn>): Set<string> {
  const keys = new Set<string>(), ends = new Map<string, number>()
  for (const v of array(value)) {
    const c = object(v, ['turn_id', 'start', 'end', 'quote'])
    const tid = id(c.turn_id), start = integer(c.start, 0), end = integer(c.end), quote = string(c.quote, 500)
    const turn = turns.get(tid)
    requireThat(turn && turn.role === 'user', 'candidate_source_invalid')
    const raw = Array.from(turn.content)
    requireThat(start < end && end <= raw.length && raw.slice(start, end).join('') === quote, 'candidate_quote_mismatch')
    const key = `${tid}:${start}:${end}`
    requireThat(!keys.has(key), 'candidate_duplicate_source')
    requireThat(start >= (ends.get(tid) ?? 0), 'candidate_source_order_invalid')
    ends.set(tid, end); keys.add(key)
  }
  return keys
}
function same(a: Set<string>, b: Set<string>) { return a.size === b.size && [...a].every(k => b.has(k)) }
function group(value: unknown, turns: Map<string, Turn>, statement?: string): { ids: Set<string>; keys: Set<string> } {
  const g = object(value, ['availability', 'turn_ids', 'citations'])
  const ids = array(g.turn_ids, 1).map(id)
  for (const tid of ids) requireThat(turns.get(tid)?.role === 'user', 'candidate_source_invalid')
  requireThat(new Set(ids).size === ids.length, 'candidate_duplicate_source')
  const keys = cites(g.citations, turns)
  if (g.availability === 'unquoted_source') requireThat(keys.size === 0, 'candidate_source_status_mismatch')
  else if (g.availability === 'exact_quotes') {
    requireThat(keys.size > 0 && same(new Set([...keys].map(k => k.slice(0, 36))), new Set(ids)), 'candidate_source_status_mismatch')
    if (statement !== undefined) requireThat((g.citations as Citation[]).every(c => c.quote === statement), 'candidate_statement_mismatch')
  } else throw new Invalid('candidate_source_status_unsupported')
  return { ids: new Set(ids), keys }
}
function checked(payload: unknown): Envelope {
  const root = object(payload, ['read_contract', 'synthetic', 'subject', 'turns', 'text_provenance', 'basis'])
  requireThat(root.read_contract === READ_CONTRACT, 'candidate_version_unsupported')
  requireThat(root.synthetic === true, 'candidate_scope_required')
  const s = object(root.subject, [...classificationKeys, 'fact_id', 'session_id', 'project_id', 'fact_version', 'statement', 'status'])
  classification(s)
  for (const k of ['fact_id', 'session_id', 'project_id']) id(s[k])
  integer(s.fact_version); const statement = string(s.statement, 500)
  requireThat(typeof s.status === 'string' && ['pending', 'user_confirmed', 'evidence_supported', 'rejected'].includes(s.status))
  const turns = new Map<string, Turn>()
  for (const raw of array(root.turns, 1, 10)) {
    const t = object(raw, ['id', 'session_id', 'role', 'content'])
    const tid = id(t.id); id(t.session_id); string(t.content)
    requireThat(t.session_id === s.session_id, 'candidate_session_mismatch')
    requireThat(t.role === 'user' || t.role === 'assistant')
    requireThat(!turns.has(tid), 'candidate_duplicate_source'); turns.set(tid, t as Turn)
  }
  const provenance = object(root.text_provenance, ['original', 'current'])
  const original = group(provenance.original, turns), current = group(provenance.current, turns, statement)
  const basis = object(root.basis, ['status', 'declaration'])
  const declarationIds = new Set<string>()
  if (basis.status === 'legacy_unclassified' || basis.status === 'not_recorded') {
    requireThat(basis.status === (s.classification_contract === 'legacy-v0' ? 'legacy_unclassified' : 'not_recorded') &&
      basis.declaration === null, 'candidate_basis_status_mismatch')
  } else if (basis.status === 'user_declaration_recorded') {
    requireThat(s.classification_contract === 'explicit-typed-v1', 'candidate_basis_status_mismatch')
    const d = object(basis.declaration, ['declaration_contract', 'declaration_id', 'record_type', 'actor', 'fact_id',
      'fact_version', 'session_id', 'project_id', 'classification', 'statement_citations', 'declaration_source', 'recorded_at', 'recorded_validation'])
    requireThat(d.declaration_contract === DECLARATION_CONTRACT, 'candidate_declaration_version_unsupported'); id(d.declaration_id)
    requireThat(d.record_type === 'explicit_user_choice' && d.actor === 'user', 'candidate_declaration_origin_invalid')
    for (const k of ['fact_id', 'session_id', 'project_id']) { id(d[k]); requireThat(d[k] === s[k], 'candidate_declaration_subject_mismatch') }
    integer(d.fact_version); requireThat(d.fact_version === s.fact_version, 'candidate_declaration_version_mismatch')
    const labels = object(d.classification, classificationKeys); classification(labels)
    requireThat(classificationKeys.every(k => labels[k] === s[k]), 'candidate_declaration_classification_mismatch')
    const sourceKeys = cites([d.declaration_source], turns)
    for (const key of sourceKeys) declarationIds.add(key.slice(0, 36))
    requireThat([...declarationIds].every(k => !original.ids.has(k) && !current.ids.has(k)), 'candidate_declaration_origin_invalid')
    const source = d.declaration_source as Citation, turn = turns.get(source.turn_id)!
    requireThat(source.start === 0 && source.end === Array.from(turn.content).length &&
      source.quote === declarationText(s as Classification), 'candidate_declaration_choice_mismatch')
    const stamp = d.recorded_at
    requireThat(typeof stamp === 'string' && /^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$/.test(stamp) &&
      !stamp.startsWith('0000-') && Number.isFinite(Date.parse(stamp)) &&
      new Date(stamp).toISOString().replace('.000Z', 'Z') === stamp, 'candidate_timestamp_invalid')
    const keys = cites(d.statement_citations, turns)
    requireThat(keys.size > 0 && same(keys, current.keys), 'candidate_declaration_source_mismatch')
    requireThat((d.statement_citations as Citation[]).every(c => c.quote === statement), 'candidate_statement_mismatch')
    const validation = object(d.recorded_validation, ['contract', 'status', 'code'])
    requireThat(validation.contract === 'typed-semantic-spike-v1' && validation.status === 'eligible_candidate' &&
      validation.code === 'finite_rule_match', 'candidate_validation_record_unsupported')
  } else throw new Invalid('candidate_basis_status_unsupported')
  requireThat(same(new Set(turns.keys()), new Set([...original.ids, ...current.ids, ...declarationIds])), 'candidate_unreferenced_source')
  return payload as Envelope
}
export function parse(payload: unknown): Result {
  try { return { status: 'parsed_candidate', code: 'candidate_internally_consistent', view: structuredClone(checked(payload)), ...flags } }
  catch (e) { return { status: 'rejected', code: e instanceof Invalid ? e.message : 'candidate_shape_invalid', view: null, ...flags } }
}

/** Strict JSON scanner: catches duplicate keys before native JSON.parse loses them.
 * This DTO has integer numeric fields only. Decimal/exponent lexemes are rejected.
 * Direct JS object input cannot distinguish 1 from 1.0; use parseJson at text boundaries.
 */
export function parseJson(input: unknown): Result {
  try {
    requireThat(typeof input === 'string' && Array.from(input).length <= 150000)
    const text = input
    let pos = 0
    function space() { while (/^[ \r\n\t]$/.test(text[pos] ?? '')) pos++ }
    function quoted(): string {
      const start = pos++
      while (pos < text.length) {
        const ch = text[pos++]
        if (ch === '\\') { pos++; continue }
        if (ch === '"') return JSON.parse(text.slice(start, pos)) as string
      }
      throw new Invalid('candidate_json_invalid')
    }
    function value(depth: number): void {
      requireThat(depth < 100, 'candidate_json_invalid'); space()
      const ch = text[pos]
      if (ch === '"') { quoted(); return }
      if (ch === '{') {
        pos++; space(); const seen = new Set<string>()
        if (text[pos] === '}') { pos++; return }
        while (true) {
          space(); requireThat(text[pos] === '"', 'candidate_json_invalid')
          const key = quoted(); requireThat(!seen.has(key), 'candidate_duplicate_key'); seen.add(key)
          space(); requireThat(text[pos++] === ':', 'candidate_json_invalid'); value(depth + 1); space()
          if (text[pos] === '}') { pos++; return }
          requireThat(text[pos++] === ',', 'candidate_json_invalid')
        }
      }
      if (ch === '[') {
        pos++; space(); if (text[pos] === ']') { pos++; return }
        while (true) { value(depth + 1); space(); if (text[pos] === ']') { pos++; return }; requireThat(text[pos++] === ',', 'candidate_json_invalid') }
      }
      const literal = /^(true|false|null)/.exec(text.slice(pos))
      if (literal) { pos += literal[0].length; return }
      const number = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(pos))
      requireThat(number, 'candidate_json_invalid')
      requireThat(!/[.eE]/.test(number[0]) && Number.isSafeInteger(Number(number[0])), 'candidate_shape_invalid')
      pos += number[0].length
    }
    value(0); space(); requireThat(pos === text.length, 'candidate_json_invalid')
    return parse(JSON.parse(text))
  } catch (e) { return { status: 'rejected', code: e instanceof Invalid ? e.message : 'candidate_json_invalid', view: null, ...flags } }
}

export function basisLabel(view: Envelope): string {
  return view.basis.status === 'legacy_unclassified' ? '旧资料未分类，未推断完成情况' :
    view.basis.status === 'not_recorded' ? '暂无分类依据记录' : '用户已声明分类；不代表平台独立认证'
}

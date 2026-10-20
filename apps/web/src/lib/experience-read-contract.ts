// Explicit opt-in DTOs only. The legacy workbench does not consume this module.
import { z } from 'zod'

const id = z.string().uuid()
const integer = z.number().int().positive()
const date = z.string().datetime({ offset: true })
const classificationShape = {
  fact_kind: z.enum(['legacy_unspecified', 'personal_action', 'plan', 'background', 'boundary']),
  progress_stage: z.enum(['legacy_unknown', 'in_progress', 'completed', 'planned', 'not_applicable']),
  classification_contract: z.enum(['legacy-v0', 'unclassified-v1', 'explicit-typed-v1']),
}
type Classification = { fact_kind: string; progress_stage: string; classification_contract: string }
function validPair(f: Classification) {
  if (f.fact_kind === 'legacy_unspecified') return f.progress_stage === 'legacy_unknown' && ['legacy-v0', 'unclassified-v1'].includes(f.classification_contract)
  const stages: Record<string, string[]> = { personal_action: ['in_progress', 'completed'], plan: ['planned', 'in_progress'], background: ['not_applicable'], boundary: ['not_applicable'] }
  return f.classification_contract === 'explicit-typed-v1' && (stages[f.fact_kind]?.includes(f.progress_stage) ?? false)
}
const citationSchema = z.strictObject({ turn_id: id, start: z.number().int().nonnegative(), end: integer,
  quote: z.string(), change_id: id, fact_version: integer, source_kind: z.enum(['original_source', 'conversation_change']),
}).refine(c => c.end > c.start && Array.from(c.quote).length === c.end - c.start, 'Invalid code-point citation')

export const factV3Schema = z.strictObject({ ...classificationShape,
  fact_contract_version: z.literal(3), provenance_version: z.literal(3),
  id, project_id: id, session_id: id, statement: z.string(),
  status: z.enum(['pending', 'user_confirmed', 'evidence_supported', 'rejected']), version: integer,
  created_at: date, updated_at: date, origin: z.enum(['manual', 'ai_extracted']),
  memory_state: z.enum(['unspecified', 'certain', 'approximate', 'needs_check']), ai_run_id: id.nullable(), evidence_id: id.nullable(),
  original_source_turn_ids: z.array(id), current_statement_source_turn_ids: z.array(id),
  current_statement_citations: z.array(citationSchema), classification_citations: z.array(citationSchema).max(0),
  classification_basis_status: z.enum(['legacy_unclassified', 'not_recorded']),
  source_kind: z.enum(['conversation_turns', 'user_edit']), source_change_id: id.nullable(),
}).refine(validPair, 'Unsupported classification pair').refine(f => f.classification_basis_status === (f.classification_contract === 'legacy-v0' ? 'legacy_unclassified' : 'not_recorded'), 'Unknown classification evidence')
  .refine(f => f.status !== 'evidence_supported' || f.evidence_id !== null, 'Missing evidence')

type Fact = z.infer<typeof factV3Schema>
const reviewed = (f: Fact) => ['user_confirmed', 'evidence_supported'].includes(f.status)
const eligible = (f: Fact) => reviewed(f) && (f.classification_contract === 'legacy-v0' || (f.classification_contract === 'explicit-typed-v1' && f.fact_kind === 'personal_action' && f.progress_stage === 'completed'))
function exclusion(f: Fact) {
  return f.classification_contract === 'unclassified-v1' ? 'classification_unreviewed' : ({ personal_action: 'action_in_progress', plan: 'plan_not_contribution', background: 'background_context', boundary: 'boundary_limitation' } as Record<string, string>)[f.fact_kind]
}
const excludedSchema = z.strictObject({ fact: factV3Schema, reason: z.enum(['classification_unreviewed', 'action_in_progress', 'plan_not_contribution', 'background_context', 'boundary_limitation']) })

export const summaryV2Schema = z.strictObject({ summary_contract_version: z.literal(2), project_id: id, context_revision: integer,
  confirmed: z.array(factV3Schema), pending: z.array(factV3Schema), reviewed_non_contributions: z.array(excludedSchema), text: z.string(), incomplete: z.boolean(),
}).superRefine((s, ctx) => {
  const all = [...s.confirmed, ...s.pending, ...s.reviewed_non_contributions.map(e => e.fact)]
  if (all.some(f => f.project_id !== s.project_id) || new Set(all.map(f => f.id)).size !== all.length ||
    s.confirmed.some(f => !eligible(f)) || s.pending.some(f => f.status !== 'pending') ||
    s.reviewed_non_contributions.some(e => !reviewed(e.fact) || eligible(e.fact) || e.reason !== exclusion(e.fact)) ||
    s.text !== s.confirmed.map(f => f.statement).join('\n') || s.incomplete !== (s.confirmed.length === 0)) {
    ctx.addIssue({ code: 'custom', message: 'Summary eligibility contract mismatch' })
  }
})

const jsonObject = z.record(z.string(), z.unknown())
const snapshotClassification = z.strictObject({ ...classificationShape, interpretation: z.enum(['legacy_missing_keys', 'explicit_fields']) }).refine(validPair)
const history = z.strictObject({ id, session_id: id, fact_id: id,
  action: z.enum(['created', 'edited', 'status_changed', 'memory_changed']), actor: z.enum(['user', 'system']),
  before: jsonObject.nullable(), after: jsonObject, before_classification: snapshotClassification.nullable(),
  after_classification: snapshotClassification, created_at: date,
}).superRefine((h, ctx) => {
  for (const [raw, classification] of [[h.before, h.before_classification], [h.after, h.after_classification]] as const) {
    if (raw === null) { if (classification !== null) ctx.addIssue({ code: 'custom', message: 'Missing snapshot' }); continue }
    if (!classification || !integer.safeParse(raw.version).success) { ctx.addIssue({ code: 'custom', message: 'Invalid snapshot' }); continue }
    const keys = Object.keys(classificationShape)
    const present = keys.filter(k => Object.hasOwn(raw, k))
    if (present.length === 0 ? classification.interpretation !== 'legacy_missing_keys' || classification.classification_contract !== 'legacy-v0' :
      present.length !== 3 || classification.interpretation !== 'explicit_fields' || keys.some(k => raw[k] !== classification[k as keyof Classification])) ctx.addIssue({ code: 'custom', message: 'Classification interpretation mismatch' })
  }
})
const originalCitation = z.strictObject({ turn_id: id, start: z.number().int().nonnegative(), end: integer, quote: z.string() })
const factSource = z.strictObject({ fact_id: id, turn_id: id, session_id: id, citations: z.array(originalCitation).nullable() })
const fcs = z.strictObject({ id, operation_id: id, effect_slot: integer.max(5), change_id: id, fact_id: id, session_id: id, turn_id: id,
  source_role: z.enum(['statement', 'intent']), reason: z.enum(['addition', 'explicit_correction', 'explicit_withdrawal']),
  start_cp: z.number().int().nonnegative(), end_cp: integer, quote: z.string(), before_version: integer.nullable(), after_version: integer, created_at: date })
const operation = z.strictObject({ id, contract_version: z.union([z.literal(1), z.literal(2)]), state: z.enum(['applied', 'needs_clarification']),
  session_id: id, input_turn_id: id, kind: z.enum(['root', 'resolution']), action: z.enum(['append', 'correct', 'withdraw', 'disambiguate']),
  parent_operation_id: id.nullable(), proposed_action: z.string().nullable(), proposal_spans: z.array(jsonObject), progress_stage: z.null(),
  base_revision: integer, result_revision: integer, target_fact_id: id.nullable(), target_version: integer.nullable(), effect_count: z.number().int().min(0).max(5),
  outcome_code: z.string(), decision_contract: z.enum(['explicit-target-v1', 'append-batch-v1']), created_at: date, expires_at: date, completed_at: date,
}).refine(o => o.decision_contract === (o.contract_version === 1 ? 'explicit-target-v1' : 'append-batch-v1'))
const answer = z.strictObject({ question_id: id, question_version: integer })
const project = z.strictObject({ id, session_id: id, raw_input: z.string(), title: z.string().nullable(), created_at: date })
const turn = z.strictObject({ id, session_id: id, role: z.enum(['user', 'assistant']), content: z.string(), created_at: date, answered_questions: z.array(answer) })
const evidence = z.strictObject({ id, fact_id: id, material_reference: z.string(), basis: z.string(), reviewer: z.literal('user'), created_at: date, verification_label: z.string() })
const run = z.strictObject({ id, session_id: id, project_id: id, input_turn_id: id, base_revision: integer, reserved_revision: integer,
  state: z.enum(['reserved', 'running', 'completed', 'failed', 'unknown', 'stale']), lease_until: date, error_code: z.string().nullable(), retry_of: id.nullable(),
  provider: z.literal('scripted'), prompt_version: z.string(), tokens_in: z.number().int().nonnegative(), tokens_out: z.number().int().nonnegative(), assistant_turn_id: id.nullable(), created_at: date })
const question = z.strictObject({ id, session_id: id, run_id: id, content: z.string().nullable(), state: z.enum(['active', 'skipped', 'corrected', 'hidden', 'deleted']), version: integer, created_at: date })
export const exportV2Schema = z.strictObject({ format_version: z.literal(2), exported_at: date, data: z.strictObject({
  id, status: z.enum(['active', 'ended']), created_at: date, updated_at: date, context_revision: integer, mining_status: z.enum(['not_started', 'active', 'stopped']),
  projects: z.array(project), turns: z.array(turn), facts: z.array(factV3Schema), evidence: z.array(evidence), history: z.array(history),
  fact_sources: z.array(factSource), fact_change_sources: z.array(fcs), conversation_operations: z.array(operation), mining_runs: z.array(run), mining_questions: z.array(question),
  answer_questions: z.array(z.strictObject({ turn_id: id, question_id: id, session_id: id, question_version: integer, slot: z.union([z.literal(1), z.literal(2)]) })),
}) })

export type ExperienceSummaryV2 = z.infer<typeof summaryV2Schema>
export type ExperienceExportV2 = z.infer<typeof exportV2Schema>

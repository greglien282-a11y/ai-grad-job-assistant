import { describe, expect, it } from 'vitest'
import fixtures from '../test/experience-read-fixtures.json'
import { exportV2Schema, factV3Schema, summaryV2Schema } from './experience-read-contract'

// Generated once from real HTTP GETs using a SELECT-only LOGIN and a synthetic
// random PostgreSQL schema. CI never regenerates/blesses these expected DTOs.
const summary = () => summaryV2Schema.parse(structuredClone(fixtures.summary))
const backup = () => structuredClone(fixtures.export)
const completed = () => summary().confirmed.find(f => f.fact_kind === 'personal_action')!

describe('explicit read candidates, independent of the legacy React consumer', () => {
  it('parses actual summary HTTP DTOs without stripping new semantics', () => {
    expect(summaryV2Schema.parse(summary())).toEqual(fixtures.summary)
    expect(fixtures.summary.confirmed.some(f => f.classification_contract === 'legacy-v0')).toBe(true)
    expect(fixtures.summary.reviewed_non_contributions[0].reason).toBe('plan_not_contribution')
  })
  it('parses a full actual HTTP backup and preserves raw legacy snapshots', () => {
    expect(exportV2Schema.parse(backup())).toEqual(fixtures.export)
    const data = fixtures.export.data
    expect(data.fact_change_sources).toHaveLength(5)
    expect(data.conversation_operations).toHaveLength(2)
    expect(data.facts.some(f => f.status === 'pending')).toBe(true)
    expect(data.facts.some(f => f.status === 'rejected')).toBe(true)
    expect(data.history.some(c => !('fact_kind' in c.after) && c.after_classification.interpretation === 'legacy_missing_keys')).toBe(true)
    expect(data.mining_runs).toHaveLength(1)
    expect(data.mining_questions).toHaveLength(1)
    expect(data.answer_questions).toHaveLength(1)
  })

  it.each([
    ['fact_contract_version', 2], ['provenance_version', 2], ['version', '3'], ['version', true],
    ['fact_kind', 'achievement'], ['progress_stage', 'planned'], ['classification_contract', 'legacy-v0'],
    ['classification_contract', 'explicit-typed-v2'], ['status', 'confirmed'], ['origin', 'user_edit'],
    ['memory_state', 'completed'], ['classification_basis_status', 'verified'], ['source_kind', 'classification'],
  ])('rejects unsupported or coerced Fact v3 %s=%s', (field, value) => {
    const fact: Record<string, unknown> = completed()
    fact[field as string] = value
    expect(factV3Schema.safeParse(fact).success).toBe(false)
  })
  it.each(['fact_kind', 'progress_stage', 'classification_contract', 'fact_contract_version', 'classification_citations'])('never defaults a missing %s', field => {
    const fact: Record<string, unknown> = completed()
    delete fact[field]
    expect(factV3Schema.safeParse(fact).success).toBe(false)
  })
  it('cannot promote an excluded confirmed plan into contribution text', () => {
    const s = summary()
    const plan = s.reviewed_non_contributions.pop()!.fact
    s.confirmed.push(plan)
    s.text = s.confirmed.map(f => f.statement).join('\n')
    expect(summaryV2Schema.safeParse(s).success).toBe(false)
  })
  it('rejects a wrong reviewed exclusion reason', () => {
    const s = summary()
    s.reviewed_non_contributions[0].reason = 'action_in_progress'
    expect(summaryV2Schema.safeParse(s).success).toBe(false)
  })
  it.each(['pending', 'rejected'] as const)('cannot include %s in confirmed', status => {
    const s = summary()
    s.confirmed[0].status = status
    expect(summaryV2Schema.safeParse(s).success).toBe(false)
  })
  it('rejects incorrect incomplete/text and duplicate fact membership', () => {
    const s = summary()
    s.incomplete = true
    expect(summaryV2Schema.safeParse(s).success).toBe(false)
    s.incomplete = false
    s.text += '模型润色。'
    expect(summaryV2Schema.safeParse(s).success).toBe(false)
    s.text = fixtures.summary.text
    s.pending.push(s.confirmed[0])
    expect(summaryV2Schema.safeParse(s).success).toBe(false)
  })
  it('does not silently strip unknown top-level or fact fields', () => {
    expect(summaryV2Schema.safeParse({ ...summary(), response_contract_version: 3 }).success).toBe(false)
    expect(factV3Schema.safeParse({ ...completed(), related_plan: 'unreviewed' }).success).toBe(false)
  })
  it('does not manufacture classification evidence from original citations', () => {
    const f = completed()
    expect(f.current_statement_citations.length).toBeGreaterThan(0)
    f.classification_citations = f.current_statement_citations
    expect(factV3Schema.safeParse(f).success).toBe(false)
  })
  it('does not accept material support without a material pointer', () => {
    const f = completed()
    expect(f.status).toBe('evidence_supported')
    f.evidence_id = null
    expect(factV3Schema.safeParse(f).success).toBe(false)
  })
  it('uses Unicode code-point lengths, not UTF-16 offsets', () => {
    const f = completed()
    const c = f.current_statement_citations[0]
    expect(c.quote).toContain('🧪')
    c.end = c.start + c.quote.length
    expect(factV3Schema.safeParse(f).success).toBe(false)
  })
  it('rejects legacy or unknown export versions without fallback', () => {
    for (const version of [1, 3, '2', null]) expect(exportV2Schema.safeParse({ ...backup(), format_version: version }).success).toBe(false)
  })
  it('rejects unrecognized persistent operation versions and credentials', () => {
    const b = backup()
    b.data.conversation_operations[0].contract_version = 9
    expect(exportV2Schema.safeParse(b).success).toBe(false)
    const valid = backup()
    Object.assign(valid.data.conversation_operations[0], { key_digest: 'not-for-export' })
    expect(exportV2Schema.safeParse(valid).success).toBe(false)
  })
  it('rejects missing snapshot keys masquerading as explicitly typed history', () => {
    const b = backup()
    const h = b.data.history.find(c => c.after_classification.classification_contract === 'explicit-typed-v1')!
    delete (h.after as Record<string, unknown>).classification_contract
    expect(exportV2Schema.safeParse(b).success).toBe(false)
  })
})

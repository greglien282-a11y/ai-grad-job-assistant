import { afterEach, expect, it, vi } from 'vitest'
import { addManual, importText } from '../resume-lab/import'
import { adjustRequirement, newDraft, printable, setJob, validate } from '../resume-lab/draft'
import { aiSuggestionLabEnabled, generateCandidates, keywordCandidates, mockCandidates, riskyMockCandidates } from './adapters'
import { applyCandidate, binding, candidateGate, decisionContext, parsePacket, parsePacketJSON } from './contract'

const role = 'synthetic-role'
const make = () => setJob(newDraft(addManual(importText('项目经历\r\n👩‍💻 é 我编写了Python脚本。\r\n\r\n团队负责，我计划学习部署。'), '我有Python课程练习。')), '后端实习\n必备：Python基础。\n加分：部署经验。')
afterEach(() => vi.unstubAllEnvs())
it('preserves exact source and JD CP quotes including CRLF, ZWJ, combining and distinct manual review offsets', () => {
  const d = make(), packet = mockCandidates(d, role), b = binding(d, role)
  expect(parsePacketJSON(JSON.stringify(packet), b)).toEqual(packet)
  for (const c of packet.suggestions) {
    expect(Array.from(b.source_snapshot.text).slice(c.source.start, c.source.end).join('')).toBe(c.source.quote)
    expect(Array.from(b.jd_snapshot.text).slice(c.jd.start, c.jd.end).join('')).toBe(c.jd.quote)
  }
  const manual = packet.suggestions.find(c => c.source.kind === 'user_manual_statement')!
  expect(manual.source.start).toBeGreaterThan(Array.from(d.workbench.source.text).length)
  expect(manual.source.source_id).toBe(`review:${d.workbench.source.id}:${role}`)
})
it('refuses unknown version/keys, missing keys and type coercion', () => {
  const packet = mockCandidates(make(), role)
  for (const mutation of [
    { ...packet, contract: 'local-suggestion-candidates-v2' }, { ...packet, verified: true }, { ...packet, role_id: undefined },
    { ...packet, suggestions: [{ ...packet.suggestions[0], priority: '1' }] },
    { ...packet, suggestions: [{ ...packet.suggestions[0], provenance: { ...packet.suggestions[0].provenance, paid: false } }] },
  ]) expect(() => parsePacket(mutation)).toThrow()
  expect(() => parsePacketJSON(JSON.stringify(packet).replace('"contract":', '"contract":"future","contract":'))).toThrow()
  expect(() => parsePacketJSON(' '.repeat(512 * 1024 + 1))).toThrow()
})
it('refuses cross-source, missing paragraphs, partial quotes, role/JD changes and altered original text', () => {
  const d = make(), p = mockCandidates(d, role), c = p.suggestions[0]
  for (const source of [{ ...c.source, source_id: 'foreign' }, { ...c.source, paragraph_id: 'foreign' }, { ...c.source, kind: 'user_manual_statement' }, { ...c.source, start: c.source.start + 1, quote: Array.from(c.source.quote).slice(1).join('') }, { ...c.source, end: 99999 }, { ...c.source, quote: c.source.quote.replace('Python', 'Docker') }]) {
    expect(() => parsePacket({ ...p, suggestions: [{ ...c, source }] }, binding(d, role))).toThrow()
  }
  expect(() => parsePacket(p, binding(d, 'different-role'))).toThrow()
  expect(() => parsePacket(p, binding(setJob(d, '另一岗位\nPython必备。'), role))).toThrow()
  const changed = structuredClone(p); changed.source_snapshot.text += '另一段'; expect(() => parsePacket(changed, binding(d, role))).toThrow()
})
it('refuses duplicate IDs and duplicate source requirement pair without silently deduplicating', () => {
  const p = mockCandidates(make(), role)
  expect(() => parsePacket({ ...p, suggestions: [p.suggestions[0], p.suggestions[0]] })).toThrow()
  expect(() => parsePacket({ ...p, suggestions: [p.suggestions[0], { ...p.suggestions[0], id: 'another' }] })).toThrow()
  expect(() => parsePacket({ ...p, source_snapshot: { ...p.source_snapshot, paragraphs: [p.source_snapshot.paragraphs[0], p.source_snapshot.paragraphs[0]] } })).toThrow()
})
it('Mock and keyword are controls, never claim real AI quality; real provider modes refuse before effects', () => {
  const d = make(), fetcher = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network forbidden'))
  const before = JSON.stringify(d)
  expect(keywordCandidates(d, role).suggestions[0].provenance.kind).toBe('deterministic_rule')
  expect(mockCandidates(d, role).suggestions[0].provenance.kind).toBe('offline_mock')
  for (const mode of ['provider', 'openai', 'remote', 'paid', 'https://example.invalid', '']) expect(() => generateCandidates(mode, d, role)).toThrow('disabled')
  expect(fetcher).not.toHaveBeenCalled(); expect(JSON.stringify(d)).toBe(before); fetcher.mockRestore()
})
it('accepts only exact original into unverified draft and rechecks gap, rejection, team and concurrent edits', () => {
  const d = make(), p = mockCandidates(d, role), c = p.suggestions[0], accepted = applyCandidate(d, role, p, c.id)
  expect(accepted.trust).toBe('user_draft_not_verified'); expect(printable(accepted)[0].text).toBe(c.source.quote)
  expect(accepted.workbench).toEqual(d.workbench); expect(d.entries.every(e => !e.selected)).toBe(true)
  const risk = riskyMockCandidates(d, role); expect(candidateGate(d, risk.suggestions[0]).status).toBe('requires_review')
  expect(() => applyCandidate(d, role, risk, risk.suggestions[0].id)).toThrow()
  const hidden = structuredClone(risk); hidden.suggestions[0].new_claims = []; hidden.suggestions[0].evidence_gap = null
  expect(() => applyCandidate(d, role, hidden, hidden.suggestions[0].id)).toThrow()
  const rejected = validate({ ...d, rejected_statements: [c.source.quote] })
  expect(() => applyCandidate(rejected, role, p, c.id)).toThrow()
  const gap = validate({ ...d, assessments: d.assessments.map(a => ({ ...a, state: 'gap' })) })
  expect(() => applyCandidate(gap, role, p, c.id)).toThrow()
  const team = p.suggestions.find(c => c.source.quote.includes('团队'))!
  expect(() => applyCandidate(d, role, p, team.id)).toThrow()
  const edited = validate({ ...d, entries: d.entries.map(e => e.id === c.source.paragraph_id ? { ...e, text: '我补写的说明。', state: 'user_edited' } : e) })
  expect(() => applyCandidate(edited, role, p, c.id)).toThrow()
})
it('appearance leaves decision basis intact but content and role changes invalidate candidates', () => {
  const d = make(), key = decisionContext(d, role)
  expect(decisionContext({ ...d, layout: 'compact' }, role)).toBe(key)
  expect(decisionContext({ ...d, entries: d.entries.map(e => ({ ...e, selected: true })) }, role)).not.toBe(key)
  expect(decisionContext(d, 'other-role')).not.toBe(key)
  const r = d.job!.requirements[0]
  expect(decisionContext(adjustRequirement(d, r.id, { text: '改为核对其他要求。' }), role)).not.toBe(key)
  expect(decisionContext(adjustRequirement(d, r.id, { priority: 'bonus' }), role)).not.toBe(key)
  vi.stubEnv('DEV', true); vi.stubEnv('VITE_PATHWISE_AI_SUGGESTIONS', ''); expect(aiSuggestionLabEnabled()).toBe(false)
  vi.stubEnv('VITE_PATHWISE_AI_SUGGESTIONS', 'offline-v1'); expect(aiSuggestionLabEnabled()).toBe(true)
  vi.stubEnv('DEV', false); expect(aiSuggestionLabEnabled()).toBe(false)
})

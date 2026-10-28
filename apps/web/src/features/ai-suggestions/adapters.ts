import { suggestions } from '../resume-lab/workspace'
import type { Draft } from '../resume-lab/draft'
import { binding, parsePacket, SUGGESTION_CONTRACT, type CandidatePacket } from './contract'

export type CandidateGenerator = (d: Draft, roleId: string) => CandidatePacket
export const aiSuggestionLabEnabled = () => import.meta.env.DEV && import.meta.env.VITE_PATHWISE_AI_SUGGESTIONS === 'offline-v1'

export const keywordCandidates: CandidateGenerator = (d, roleId) => {
  const b = binding(d, roleId), result: CandidatePacket['suggestions'] = []
  for (const s of suggestions(d)) for (const link of s.links) {
    if (result.length === 100) break
    const q = b.source_snapshot.paragraphs.find(q => q.id === s.entry.id)!, r = link.requirement
    result.push({ id: `keyword:${result.length + 1}`, source: { source_id: b.source_snapshot.id, paragraph_id: q.id, kind: q.kind, quote: q.quote, start: q.start, end: q.end },
      jd: { requirement_id: r.id, quote: r.quote, start: r.start, end: r.end }, priority: result.length + 1, rewrite_text: null,
      reason: `有限字面词：${link.words.join('、')}；${s.reason}`, new_claims: [], evidence_gap: s.eligible ? null : s.reason,
      provenance: { kind: 'deterministic_rule', id: 'm2-keyword-baseline', version: 'm2-literal-v1' } })
  }
  return parsePacket({ contract: SUGGESTION_CONTRACT, ...b, suggestions: result }, b)
}
export const mockCandidates: CandidateGenerator = (d, roleId) => {
  const p = keywordCandidates(d, roleId)
  return parsePacket({ ...p, suggestions: p.suggestions.map(c => ({ ...c, id: c.id.replace('keyword:', 'mock:'), reason: `离线Mock候选（不是模型输出）。${c.reason}`,
    provenance: { kind: 'offline_mock', id: 'local-review-fixture', version: 'mock-v1' } })) }, binding(d, roleId))
}
// Deliberately unsafe synthetic fixture: visible only in quarantine for testing
// whether users can notice unsupported assertions. It is never auto-applicable.
export const riskyMockCandidates: CandidateGenerator = (d, roleId) => {
  const p = mockCandidates(d, roleId), first = p.suggestions[0]
  if (!first) return p
  return parsePacket({ ...p, suggestions: [{ ...first, id: 'risk:unsupported', rewrite_text: '我独立部署了Docker服务，提升30%。', reason: '公开合成风险反例：新增的部署、个人职责和数字没有来源。',
    new_claims: ['独立部署Docker服务', '提升30%'], evidence_gap: '原始材料没有这些主张的证据。' }] }, binding(d, roleId))
}
export function generateCandidates(mode: string, d: Draft, roleId: string): CandidatePacket {
  // No SDK, key lookup, fetch, HTTP route or fallback to an external service.
  if (mode === 'keyword') return keywordCandidates(d, roleId)
  if (mode === 'mock') return mockCandidates(d, roleId)
  if (mode === 'risk_fixture') return riskyMockCandidates(d, roleId)
  throw new Error('External Provider is disabled; independent approval and implementation required')
}

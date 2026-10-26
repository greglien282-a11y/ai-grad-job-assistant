import { expect, it } from 'vitest'
import { analyzeJD } from './jd'
import { deduplicate, matchRequirements, printableText, qualify, reviewQuestions } from './policy'
import { sample, samples } from './fixtures'
it('uses unchanged FactV3 plus independent synthetic declaration, never fabricates classification citations', () => {
  const e = qualify(samples[0]); expect(e.bucket).toBe('usable'); expect(e.fact?.classification_citations).toEqual([])
  expect(e.fact?.classification_basis_status).toBe('not_recorded'); expect(e.declaration?.basis.status).toBe('user_declaration_recorded')
  expect(qualify(samples[1]).bucket).toBe('usable')
})
it.each(samples.slice(2).map((s, i) => [i + 3, s] as const))('keeps sample %s out of contribution preview', (_, s) => expect(qualify(s).bucket).not.toBe('usable'))
it.each(['我计划部署服务。', '我正在部署服务。', '我们部署了服务。', '我没有部署服务。', '如果我部署服务。', '我可能部署过服务。', '我不知道。', '我提升了99%。'])('does not turn a hazardous sentence into a completed contribution: %s', text => {
  expect(qualify(sample(44, text)).bucket).not.toBe('usable')
})
it.each(['fact_version', 'session_id', 'project_id', 'statement', 'status', 'progress_stage'])('rejects a declaration for a different %s', field => {
  const s = structuredClone(samples[0]); const d = s.declaration as { subject: Record<string, unknown> }
  d.subject[field] = field === 'fact_version' ? 2 : 'changed'
  expect(qualify(s).bucket).not.toBe('usable')
})
it('refuses unknown/old DTO versions and missing source, without partial unsafe text', () => {
  const bad = structuredClone(samples[0]); (bad.fact as Record<string, unknown>).fact_contract_version = 1
  expect(qualify(bad)).toMatchObject({ bucket: 'excluded', fact: null })
  const missing = structuredClone(samples[0]); (missing.fact as Record<string, unknown>).current_statement_citations = []
  expect(qualify(missing).bucket).not.toBe('usable')
  const wrong = structuredClone(samples[0]); (wrong.declaration as Record<string, unknown>).read_contract = 'future-v99'
  expect(qualify(wrong).bucket).not.toBe('usable')
})
it('never normalizes quotes or upgrades a missing declaration from literal source', () => {
  const e = sample(45, '我制作了é原型图。'); const d = e.declaration as { turns: { content: string }[] }
  d.turns[0].content = '我制作了é原型图。'; expect(qualify(e).bucket).not.toBe('usable')
  expect(qualify(sample(46, '我部署了服务。', 'personal_action', 'completed', 'user_confirmed', false)).bucket).toBe('review')
})
it('deduplicates by identity and exact text without modifying source inputs', () => {
  const before = JSON.stringify(samples); const all = deduplicate([...samples, structuredClone(samples[0]), sample(77, '我测试了3个导出按钮。')])
  expect(all.filter(e => e.bucket === 'usable')).toHaveLength(2); expect(JSON.stringify(samples)).toBe(before)
})
it('reports an evidence gap, never claims Python experience from a script or a match percentage', () => {
  const matches = matchRequirements(analyzeJD('必须掌握Python。测试经验优先。').requirements, deduplicate(samples))
  expect(matches[0].usable).toHaveLength(0); expect(matches[0].conclusion).toContain('缺少可展示证据')
  expect(matches[1].usable).toHaveLength(1)
})
it('treats any local rewrite as unverified, excluded from printable text and fact-based review', () => {
  expect(printableText('我部署了服务。', '我部署了100个服务，提升90%。')).toBeNull()
  expect(printableText('我部署了服务。', '我部署了服务。')).toBe('我部署了服务。')
})
it('builds exactly three attributed prompts without inventing personal answers, or none without facts', () => {
  const fs = deduplicate(samples).filter(e => e.bucket === 'usable').map(e => e.fact!)
  const rs = analyzeJD('必须具备测试经验。').requirements
  const qs = reviewQuestions(fs, rs); expect(qs).toHaveLength(3)
  expect(qs.every(q => fs.includes(q.fact) && rs.includes(q.requirement))).toBe(true)
  expect(reviewQuestions([], rs)).toEqual([])
})

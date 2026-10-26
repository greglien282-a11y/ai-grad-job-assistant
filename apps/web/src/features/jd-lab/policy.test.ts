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
it('fails closed for conflicting current rows with the same Fact identity in either input order', () => {
  const rejected = structuredClone(samples[0]); (rejected.fact as Record<string, unknown>).status = 'rejected'
  for (const order of [[samples[0], rejected], [rejected, samples[0]]]) expect(deduplicate(order).some(e => e.bucket === 'usable')).toBe(false)
})
it('does not resurrect an exactly rejected statement by giving it another Fact ID', () => {
  const rejected = sample(99, '我测试了3个导出按钮。', 'personal_action', 'completed', 'rejected')
  for (const order of [[samples[0], rejected], [rejected, samples[0]]]) expect(deduplicate(order).some(e => e.bucket === 'usable')).toBe(false)
})
it.each(['pending', 'rejected'] as const)('excludes the entire exact-text group for %s versus confirmed in both orders', status => {
  const confirmed = sample(80, '我测试了3个导出按钮。')
  const other = sample(81, '我测试了3个导出按钮。', 'personal_action', 'completed', status)
  for (const order of [[other, confirmed], [confirmed, other]]) {
    expect(deduplicate(order).map(e => e.bucket)).toEqual(['excluded', 'excluded'])
  }
})
it('excludes same-ID pending/confirmed conflicts in both orders even with different statements', () => {
  const confirmed = sample(80, '我测试了3个导出按钮。')
  const pending = sample(80, '我部署了服务。', 'personal_action', 'completed', 'pending')
  for (const order of [[pending, confirmed], [confirmed, pending]]) {
    expect(deduplicate(order).every(e => e.bucket === 'excluded')).toBe(true)
  }
})
it('does not let a matching valid duplicate hide another row with missing declaration sources', () => {
  const valid = sample(80, '我测试了3个导出按钮。')
  const missing = sample(81, '我测试了3个导出按钮。', 'personal_action', 'completed', 'user_confirmed', false)
  for (const order of [[valid, missing], [missing, valid]]) expect(deduplicate(order).some(e => e.bucket === 'usable')).toBe(false)
})
it('keeps a deterministic single qualified representative for lawful exact duplicates', () => {
  const first = sample(80, '我测试了3个导出按钮。'), second = sample(81, '我测试了3个导出按钮。')
  for (const order of [[second, first, structuredClone(first)], [first, structuredClone(first), second]]) {
    const admitted = deduplicate(order).filter(e => e.bucket === 'usable')
    expect(admitted).toHaveLength(1); expect(admitted[0].fact?.id).toBe((first.fact as { id: string }).id)
  }
})
it('preserves the input array, nested facts and declaration sources while resolving mixed-state duplicates', () => {
  const order = [sample(81, '我测试了3个导出按钮。', 'personal_action', 'completed', 'pending'), sample(80, '我测试了3个导出按钮。')]
  const before = structuredClone(order), refs = [...order]
  deduplicate(order)
  expect(order).toEqual(before); expect(order[0]).toBe(refs[0]); expect(order[1]).toBe(refs[1])
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

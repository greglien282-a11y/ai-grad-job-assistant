import { expect, it } from 'vitest'
import { addManual, excerpt, importText } from './import'
import { adjustRequirement, admission, DRAFT_CONTRACT, emptyReview, MAX_DRAFT_BYTES, newDraft, printable, provenance, questions, restoreDraft, saveDraft, setJob, strategies, validate, type Draft } from './draft'

const base = () => setJob(newDraft(importText('项目经历\r\n我编写了图像读取脚本。\r\n\r\n技能\r\nPython课程基础。')), '视觉算法实习\n必须掌握Python；图像处理加分。\n部署经验优先。')
it('round trips a real editable local document, selections, order, strategy, Unicode references and review', () => {
  let d = base(); d.entries.reverse(); d.entries[0].selected = true; d.layout = 'compact'; d.entries[0].text += '这是用户说明。'; d.entries[0].state = 'user_edited'
  d = adjustRequirement(d, d.job!.requirements[1].id, { priority: 'bonus', text: '人工核对的Python条件' })
  d.review = { step: 1, complete: false, answers: ['我需要核对细节。', '', ''] }
  expect(restoreDraft(saveDraft(d))).toEqual(d)
  expect(d.trust).toBe('user_draft_not_verified'); expect(DRAFT_CONTRACT).toBe('local-job-resume-draft-v1')
})
it.each(['contract', 'trust', 'extra', 'entries', 'source', 'quote', 'state', 'job', 'selection', 'assessment', 'review'] as const)('rejects damaged/unknown %s without a partial document', field => {
  const d = base(), bad = structuredClone(d) as unknown as Record<string, any>
  if (field === 'contract') bad.contract = 'v999'
  if (field === 'trust') bad.trust = 'platform_verified'
  if (field === 'extra') bad.actor = 'authenticated_user'
  if (field === 'entries') bad.entries.push(bad.entries[0])
  if (field === 'source') bad.entries[0].id = crypto.randomUUID()
  if (field === 'quote') bad.workbench.excerpts[0].quote = '我部署了28台服务。'
  if (field === 'state') bad.entries[0].text = '换了文字却伪报original'
  if (field === 'job') bad.job.requirements[0].quote = '伪造JD来源'
  if (field === 'selection') bad.entries[0].selected = 'true'
  if (field === 'assessment') bad.assessments[0].requirement_id = 'not-a-requirement'
  if (field === 'review') bad.review = { step: 0, complete: true, answers: ['', '', ''] }
  expect(() => restoreDraft(JSON.stringify(bad))).toThrow(); expect(base().entries.every(e => !e.selected)).toBe(true)
})
it('rejects duplicate JSON keys including escaped aliases, prototype fields, excessive nesting, size and credential text', () => {
  const raw = saveDraft(base())
  for (const bad of [raw.replace('"contract":', '"contract":"future-version", "contract":'), raw.replace('"contract":', '"\\u0063ontract":"future-version", "contract":'), raw.replace('{', '{"__proto__":{},'), '['.repeat(34) + '0' + ']'.repeat(34), ' '.repeat(MAX_DRAFT_BYTES + 1)]) expect(() => restoreDraft(bad)).toThrow()
  const d = base(); d.entries[0].text = 'Bearer syntheticsecret123456789'; d.entries[0].state = 'user_edited'; expect(() => saveDraft(d)).toThrow()
})
it('rejects missing entries, wrong source kind and unfinished review without selected sources', () => {
  const d = base()
  expect(() => validate({ ...d, entries: d.entries.slice(1) })).toThrow()
  expect(() => validate({ ...d, entries: d.entries.map(e => ({ ...e, source_kind: 'user_manual_statement' })) })).toThrow()
  expect(() => validate({ ...d, review: { ...emptyReview(), step: 1 } })).toThrow()
})
it('never infers missing skills or achievements from a literal term, or equates missing evidence with an actual gap', () => {
  const d = setJob(newDraft(importText('项目经历\n我编写了读取脚本。')), '必须掌握Python。')
  expect(strategies(d)[0].matches).toEqual([]); expect(strategies(d)[0].label).toContain('补充证据')
  d.assessments[0].state = 'can_explain'; expect(strategies(d)[0].label).toContain('补充证据')
  d.assessments[0].state = 'gap'; expect(strategies(d)[0].label).toContain('用户明确自评')
  expect(saveDraft(d)).not.toContain('提升99%')
})
it('shows can-explain only as explicit self-assessment with a literal safe original', () => {
  const d = base(), index = d.job!.requirements.findIndex(r => /必须掌握Python/.test(r.quote))
  d.assessments[index].state = 'can_explain'
  expect(strategies(d)[index].label).toContain('可以直接说明（用户自评')
  d.entries.find(e => e.original.includes('Python'))!.state = 'user_edited'
  expect(strategies(d)[index].label).toContain('补充证据')
})
it.each(['我计划部署服务。', '我正在部署服务。', '团队部署了服务，我只整理样例。', '我没有部署服务。', '我并非负责人。', '我不知道结果。'])('keeps risky source as context and blocks removing its qualifiers: %s', raw => {
  const d = newDraft(importText(raw)), e = d.entries[0]; e.selected = true
  expect(admission(d, e).kind).toBe('context')
  e.text = '我独立完成部署，提升99%。'; e.state = 'user_edited'
  expect(admission(d, e).kind).toBe('blocked'); expect(printable(d)).toEqual([])
})
it('a cropped quote cannot hide its paragraph qualifiers while unrelated paragraphs remain independently usable', () => {
  const w = importText('我计划部署服务。\n\n我编写了图像读取脚本。')
  const start = Array.from(w.source.text).indexOf('部')
  w.excerpts[0] = excerpt(w, start, 8, 'project', w.excerpts[0].id)
  const d = newDraft(w); expect(admission(d, d.entries[0]).kind).toBe('context'); expect(admission(d, d.entries[1]).kind).toBe('draft')
})
it('allows clearly unverified local edits but never changes their originals or formal trust', () => {
  const d = base(), before = d.entries[0].original
  d.entries[0].text = '用户自己编写的新简历草稿。'; d.entries[0].state = 'user_edited'; d.entries[0].selected = true
  expect(admission(d, d.entries[0]).kind).toBe('draft'); expect(printable(d)[0].original).toBe(before)
  expect(provenance(d, d.entries[0])).toContain('导入原文'); expect(restoreDraft(saveDraft(d)).trust).toBe('user_draft_not_verified')
  d.entries[0].text = ''; expect(admission(d, d.entries[0]).kind).toBe('blocked')
})
it('preserves precise rejected statements across different source IDs, document restoration and input orders', () => {
  const w = addManual(importText('我编写了脚本。'), '我编写了脚本。'), d = newDraft(w, ['我编写了脚本。'])
  d.entries.forEach(e => { e.selected = true })
  for (const entries of [d.entries, [...d.entries].reverse()]) expect(printable({ ...d, entries })).toEqual([])
  const clean = newDraft(importText('我编写了脚本。')); clean.entries[0].selected = true
  expect(printable(restoreDraft(saveDraft(clean), d.rejected_statements))).toEqual([])
  expect(restoreDraft(saveDraft(d)).rejected_statements).toEqual(d.rejected_statements)
})
it('same-text originals with different edit states are blocked in both orders; lawful duplicates print exactly once', () => {
  const d = newDraft(addManual(importText('我编写了脚本。'), '我编写了脚本。'))
  d.entries.forEach(e => { e.selected = true }); const before = structuredClone(d)
  expect(printable(d)).toHaveLength(1); expect(printable({ ...d, entries: [...d.entries].reverse() })[0].id).toBe(printable(d)[0].id)
  d.entries[1].text = '用户改写'; d.entries[1].state = 'user_edited'
  for (const entries of [d.entries, [...d.entries].reverse()]) expect(printable({ ...d, entries })).toEqual([])
  expect(before.entries[1].state).toBe('original')
})
it('retains JD references on manual edits, protects conflicts and binds three questions to printable source entries', () => {
  let d = setJob(newDraft(importText('Python课程基础。')), '必须掌握Python。无需Python。')
  d = adjustRequirement(d, d.job!.requirements[0].id, { priority: 'must', text: '用户补充条件' })
  expect(d.job!.requirements[0]).toMatchObject({ priority: 'uncertain', quote: '必须掌握Python。', adjusted: true })
  d.entries[0].selected = true
  const qs = questions(d); expect(qs).toHaveLength(3); expect(qs.every(q => d.entries.includes(q.entry) && d.job!.requirements.includes(q.requirement) && q.provenance.includes('导入原文'))).toBe(true)
  expect(questions(newDraft(importText('没有项目。')))).toEqual([])
})
it('does not normalize Unicode while restoring and rejects changed stored references', () => {
  const d = newDraft(importText('👩‍💻 é\r\n原文'))
  expect(restoreDraft(saveDraft(d)).workbench.source.text).toBe('👩‍💻 é\r\n原文')
  const bad = structuredClone(d); bad.workbench.source.text = bad.workbench.source.text.normalize('NFC')
  expect(() => restoreDraft(JSON.stringify(bad))).toThrow()
})
export type TestDraft = Draft

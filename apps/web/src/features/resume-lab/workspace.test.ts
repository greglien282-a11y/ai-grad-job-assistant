import { describe, expect, it } from 'vitest'
import { importText, workbenchSchema } from './import'
import { emptyReview, newDraft, printable, questions, saveDraft, setJob, validate } from './draft'
import { addRole, applySourceSuggestion, MAX_WORKSPACE_BYTES, mergeRejections, newWorkspace, readWorkspace, restoreWorkspace, roleDraft, rolePresets, saveWorkspace, suggestions, updateRole, validateWorkspace, WORKSPACE_CONTRACT } from './workspace'
const source = () => importText('教育经历\n合成学校课程。\n\n项目经历\n我编写了Python脚本。\n\n团队负责演示，我尚未部署服务。\n\n技能\n我计划学习OpenCV。')
const setup = () => newWorkspace(source())
describe('one local source, independent strict job drafts', () => {
  it('serializes the shared source exactly once, no automatic proof or classification', () => {
    const w = addRole(setup(), '后端', rolePresets.backend.jd), raw = saveWorkspace(w)
    expect(raw.split('local-resume-workbench-v1')).toHaveLength(2)
    expect(raw).not.toMatch(/user_confirmed|operation_key|classification_citations|truth_verified/)
    expect(restoreWorkspace(raw).workspace).toEqual(w)
  })
  it('isolates JD, editing, selection, ordering, condition judgment, template and review per role', () => {
    let w = setup(), a = w.active_role_id, d = setJob(roleDraft(w), rolePresets.vision.jd)
    d = validate({ ...d, entries: [...d.entries].reverse().map(e => ({ ...e, selected: true })), layout: 'compact' })
    d.review = { ...emptyReview(), step: 1, answers: ['A only', '', ''] }; w = updateRole(w, d)
    const originalA = roleDraft(w)
    w = addRole(w, '后端', rolePresets.backend.jd); expect(roleDraft(w).entries.every(e => !e.selected)).toBe(true)
    let b = roleDraft(w); b = validate({ ...b, entries: b.entries.map(e => ({ ...e, selected: true })) }); b.review = { ...emptyReview(), step: 1, answers: ['B only', '', ''] }; w = updateRole(w, b)
    expect(roleDraft(w, a)).toEqual(originalA); expect(roleDraft(w).review.answers[0]).toBe('B only'); expect(roleDraft(w, a).review.answers[0]).toBe('A only')
    const restored = restoreWorkspace(saveWorkspace(w)).workspace; expect(restored).toEqual(w); expect(restored.workbench).toEqual(w.workbench)
  })
  it('only explicit safe source suggestions select and move exact words, never create metrics', () => {
    let d = setJob(newDraft(source()), rolePresets.backend.jd), before = JSON.stringify(d)
    const candidate = suggestions(d).find(s => s.eligible)!; expect(candidate.requirements.length).toBeGreaterThan(0)
    const next = applySourceSuggestion(d, candidate.entry.id); expect(next.entries[0].text).toBe(candidate.entry.original); expect(next.entries[0].state).toBe('original'); expect(next.entries[0].selected).toBe(true)
    expect(JSON.stringify(d)).toBe(before); expect(JSON.stringify(next)).not.toContain('87%')
    for (const s of suggestions(d).filter(s => !s.eligible)) expect(() => applySourceSuggestion(d, s.entry.id)).toThrow()
  })
  it('rejections are shared across roles and retained restore, resetting stale review without unlocking', () => {
    let w = setup(), a = w.active_role_id; const old = saveWorkspace(w)
    w = addRole(w, '岗位B', rolePresets.backend.jd)
    const d = roleDraft(w), statement = d.entries[1].original
    w = updateRole(w, { ...d, rejected_statements: [statement] })
    for (const id of [a, w.active_role_id]) expect(printable({ ...roleDraft(w, id), entries: roleDraft(w, id).entries.map(e => ({ ...e, selected: true })) }).some(e => e.original === statement)).toBe(false)
    expect(restoreWorkspace(old, [statement]).workspace.rejected_statements).toEqual([statement])
  })
  it('migrates exact legacy v1 as one role without invented file hashes/profile/history', () => {
    const d = setJob(newDraft(source()), rolePresets.testing.jd), migrated = restoreWorkspace(saveDraft(d))
    expect(migrated.migrated).toBe(true); expect(migrated.workspace.roles).toHaveLength(1); expect(roleDraft(migrated.workspace)).toEqual(d)
    expect(migrated.workspace.profile.contact).toBe(''); expect(migrated.workspace.workbench.source).not.toHaveProperty('extraction')
  })
  it('migrates extracted v2 without rewriting snapshot or review declaration', async () => {
    const legacy = source(), { sha256 } = await import('./document-import')
    const w = workbenchSchema.parse({ ...legacy, contract: 'local-resume-workbench-v2', source: { ...legacy.source, origin: 'extracted_file', name: 'synthetic.pdf', review: 'user_checked_text', extraction: { contract: 'extracted-text-snapshot-v1', format: 'pdf', file_bytes: 123, file_sha256: 'a'.repeat(64), text_sha256: await sha256(new TextEncoder().encode(legacy.source.text)), parser: 'pdfjs-dist@6.4.299', pages: 1, warnings: ['layout'] } } })
    const d = newDraft(w), result = restoreWorkspace(saveDraft(d)); expect(roleDraft(result.workspace)).toEqual(d)
    const damaged = structuredClone(result.workspace)
    if (damaged.workbench.contract !== 'local-resume-workbench-v2') throw new Error('fixture')
    damaged.workbench.source.extraction.text_sha256 = '0'.repeat(64)
    const raw = JSON.stringify(damaged), bytes = new TextEncoder().encode(raw)
    await expect(readWorkspace({ name: 'bad.json', size: bytes.length, arrayBuffer: async () => bytes.buffer } as File, [])).rejects.toThrow('Snapshot')
  })
  it.each(['version', 'unknown', 'active', 'duplicate', 'missing', 'quote', 'status', 'source', 'profile', 'review'])('rejects corrupt %s with no fallback', kind => {
    const w: any = structuredClone(setup())
    if (kind === 'version') w.contract = 'local-job-resume-draft-v99'
    if (kind === 'unknown') w.verified = true
    if (kind === 'active') w.active_role_id = crypto.randomUUID()
    if (kind === 'duplicate') w.roles.push(w.roles[0])
    if (kind === 'missing') w.roles[0].content.entries.pop()
    if (kind === 'quote') w.workbench.excerpts[0].quote = 'fabricated'
    if (kind === 'status') w.roles[0].content.entries[0].status = 'user_confirmed'
    if (kind === 'source') w.roles[0].content.workbench = w.workbench
    if (kind === 'profile') w.profile.contact = 'Bearer syntheticsecret1234567890'
    if (kind === 'review') w.roles[0].content.review.step = 2
    expect(() => restoreWorkspace(JSON.stringify(w))).toThrow()
  })
  it('rejects duplicate/escaped keys, limits and extra old-contract fields', () => {
    const raw = saveWorkspace(setup())
    expect(() => restoreWorkspace(raw.replace('"contract":', '"contract":"future", "contract":'))).toThrow()
    expect(() => restoreWorkspace(raw.replace('"trust":', '"tr\\u0075st":"x", "trust":'))).toThrow()
    expect(() => restoreWorkspace(' '.repeat(MAX_WORKSPACE_BYTES + 1))).toThrow()
    expect(() => restoreWorkspace(JSON.stringify({ ...newDraft(source()), profile: {} }))).toThrow()
    let w = setup(); for (let n = 0; n < 4; n++) w = addRole(w, `role${n}`)
    expect(() => addRole(w, 'sixth')).toThrow(); expect(() => validateWorkspace({ ...w, active_role_id: 'bad' })).toThrow()
  })
  it('does not silently change shared source in a role update or certify restored declarations', () => {
    const w = setup(), before = JSON.stringify(w), d = roleDraft(w)
    expect(() => updateRole(w, validate({ ...d, workbench: source() }))).toThrow()
    expect(JSON.stringify(w)).toBe(before); expect(mergeRejections(w, []).contract).toBe(WORKSPACE_CONTRACT)
  })
  it('gap review asks for learning rather than inventing project experience', () => {
    let d = setJob(newDraft(source()), rolePresets.backend.jd)
    d = validate({ ...d, entries: d.entries.map(e => ({ ...e, selected: true })), assessments: d.assessments.map(a => ({ ...a, state: 'gap' })) })
    expect(questions(d)[2].prompt).toContain('不要把学习准备讲成已完成项目'); expect(questions(d)[2].requirement).toEqual(d.job!.requirements[0])
  })
})

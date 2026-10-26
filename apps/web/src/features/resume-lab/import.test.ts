import { expect, it, vi } from 'vitest'
import { addManual, checkText, decodeFile, excerpt, importText, MAX_BYTES, privacyWarnings, readFile, workbenchSchema } from './import'
import { graduateResume } from './fixtures'

it('segments education/projects/skills/internship with exact untouched CRLF code-point citations', () => {
  const w = importText(graduateResume)
  expect(w.source.text).toBe(graduateResume)
  expect(new Set(w.excerpts.map(e => e.section))).toEqual(new Set(['education', 'project', 'skill', 'internship', 'other']))
  for (const e of w.excerpts) expect(Array.from(graduateResume).slice(e.start, e.end).join('')).toBe(e.quote)
  expect(w.excerpts.find(e => e.quote.includes('团队'))?.quote).toContain('我只整理')
  expect(w.excerpts.find(e => e.quote.includes('计划'))?.quote).toContain('尚未部署')
  expect(w.source.trust).toBe('local_unverified'); expect(JSON.stringify(w)).not.toContain('user_confirmed')
})
it('preserves emoji, ZWJ, combining forms, BOM and cross-line quotations without normalization', () => {
  const raw = '\uFEFF项目经历\r\n👩‍💻 é\r\n第二行\r\n\r\n另一段'
  const w = decodeFile('resume.MD', new TextEncoder().encode(raw))
  expect(w.source.text).toBe(raw)
  const start = Array.from(raw).indexOf('👩')
  expect(excerpt(w, start, Array.from(raw).length).quote).toBe('👩‍💻 é\r\n第二行\r\n\r\n另一段')
  expect(workbenchSchema.safeParse({ ...w, excerpts: [{ ...w.excerpts[0], quote: w.excerpts[0].quote.normalize('NFC') }] }).success).toBe(false)
})
it.each(['', ' \r\n', 'a\u0000b', '\uD800', '\uDC00', '文字\u202E隐藏', '文字\u2066隐藏', 'a\u0007b', 'x'.repeat(20001)])('refuses invalid/empty/oversized source %#', raw => expect(() => checkText(raw)).toThrow())
it.each(['note.pdf', 'resume.docx', '../resume.txt', 'resume.exe.txt\u202E', 'resume.json'])('refuses invalid filenames %s', name => expect(() => decodeFile(name, new TextEncoder().encode('我的原文'))).toThrow())
it.each([new Uint8Array(), new Uint8Array(MAX_BYTES + 1), new Uint8Array([0xff, 0xfe, 65, 0]), new Uint8Array([0xc3, 0x28])])('rejects empty/oversize/invalid UTF-8 bytes %#', bytes => expect(() => decodeFile('resume.txt', bytes)).toThrow())
it.each(['-----BEGIN PRIVATE KEY-----\nsynthetic', 'Authorization: Bearer synthetictoken12345678', 'sk-syntheticsecret1234567890'])('refuses credential-like text %#', raw => expect(() => importText(raw)).toThrow())
it('allows contact text with a local privacy warning and treats markup as inert source text', () => {
  expect(privacyWarnings('graduate@example.invalid')).toHaveLength(1)
  const raw = '<script>fetch("https://example.invalid")</script>\n![image](https://example.invalid/x)'
  expect(importText(raw).source.text).toBe(raw)
})
it('allows manual structure changes and statements without mutating originals or inventing source trust', () => {
  const w = importText('教育背景\n原始教育\n\n项目经历\n原始项目'), before = structuredClone(w)
  const e = excerpt(w, 0, Array.from(w.source.text).length, 'other', w.excerpts[0].id, '人工分段')
  expect(e.quote).toBe(w.source.text)
  const next = addManual(w, '我不确定职责，需要核对。')
  expect(next.manual[0]).toMatchObject({ kind: 'user_manual_statement', trust: 'local_unverified' })
  expect(w).toEqual(before); expect(w.manual).toEqual([])
  expect(() => excerpt(w, -1, 3)).toThrow(); expect(() => excerpt(w, 4, 2)).toThrow()
})
it('rejects duplicate IDs, wrong source identity, fabricated quote and extra trust fields', () => {
  const w = importText('项目经历\n我写了脚本。'), e = w.excerpts[0]
  for (const changed of [{ ...w, excerpts: [e, e] }, { ...w, excerpts: [{ ...e, source_id: crypto.randomUUID() }] }, { ...w, excerpts: [{ ...e, quote: '我写了28条。' }] }, { ...w, actor: 'authenticated' }]) expect(workbenchSchema.safeParse(changed).success).toBe(false)
})
it('checks metadata before reading file bytes', async () => {
  const arrayBuffer = vi.fn()
  await expect(readFile({ name: 'bad.pdf', size: 10, arrayBuffer } as unknown as File)).rejects.toThrow()
  await expect(readFile({ name: 'a.txt', size: MAX_BYTES + 1, arrayBuffer } as unknown as File)).rejects.toThrow()
  expect(arrayBuffer).not.toHaveBeenCalled()
})

import { describe, it, expect, vi } from 'vitest'
import { strToU8, zipSync } from 'fflate'
import { boundedDocx } from './archive'
import { boundedTask, PARSE_DEADLINE, sha256 } from './document-import'
import { orderPage } from './pdf-layout'
import { importText, workbenchSchema, segment, isReviewed } from './import'
import { newDraft, restoreDraft, saveDraft } from './draft'
const zip = (extra: Record<string, Uint8Array> = {}) => zipSync({ '[Content_Types].xml': strToU8('<Types/>'), 'word/document.xml': strToU8('<w:document><w:tbl /></w:document>'), ...extra })
describe('bounded local document import', () => {
  it('reconstructs bounded DOCX without interpreting HTML or external relationships', () => { expect(boundedDocx(zip({ 'word/_rels/document.xml.rels': strToU8('<Relationships Target="https://example.invalid"/>') })).tables).toBe(true) })
  it.each(['../bad.xml', '/bad.xml', 'word/vbaProject.bin', 'word/embeddings/thing', 'a:b.xml'])('rejects unsupported archive path %s', name => { expect(() => boundedDocx(zip({ [name]: strToU8('x') }))).toThrow() })
  it('rejects XML entities, too many entries, truncated and decompression budgets', () => {
    expect(() => boundedDocx(zip({ 'evil.xml': strToU8('<!DOCTYPE x>') }))).toThrow()
    expect(() => boundedDocx(zip(Object.fromEntries(Array.from({ length: 257 }, (_, i) => [`${i}.xml`, strToU8('x')]))))).toThrow()
    expect(() => boundedDocx(zip().slice(0, 40))).toThrow()
    expect(() => boundedDocx(zip({ 'huge.xml': new Uint8Array(2 * 1024 * 1024 + 1) }))).toThrow()
  })
  it('orders column candidates without mutating input, never treats geometry as offsets', () => {
    const items = [{ str: 'R2', x: 330, y: 90, width: 40, height: 12 }, { str: 'L1', x: 20, y: 110, width: 40, height: 12 }, { str: 'R1', x: 330, y: 110, width: 40, height: 12 }, { str: 'L2', x: 20, y: 90, width: 40, height: 12 }], before = JSON.stringify(items)
    expect(orderPage(items, 600)).toEqual({ text: 'L1\n\nL2\n\nR1\n\nR2', columns: true }); expect(JSON.stringify(items)).toBe(before)
    expect(() => orderPage([{ ...items[0], x: NaN }], 600)).toThrow()
  })
  it('terminates resource tasks on deadline and cancellation, no late result', async () => {
    vi.useFakeTimers(); const cleanup = vi.fn(); const result = boundedTask<string>(() => cleanup); const rejected = expect(result).rejects.toThrow('15秒')
    await vi.advanceTimersByTimeAsync(PARSE_DEADLINE); await rejected; expect(cleanup).toHaveBeenCalledTimes(1); vi.useRealTimers()
    const c = new AbortController(), stop = vi.fn(), p = boundedTask<string>(() => stop, c.signal); c.abort(); await expect(p).rejects.toThrow('取消'); expect(stop).toHaveBeenCalledTimes(1)
  })
  it('keeps old v1 literal-compatible and rejects changing its source contract', () => {
    const d = newDraft(importText('项目\n我编写了Python脚本。')); expect(restoreDraft(saveDraft(d))).toEqual(d)
    expect(() => restoreDraft(JSON.stringify({ ...d, contract: 'local-job-resume-draft-v9' }))).toThrow()
  })
  it('extracted snapshots have exact code-point quotes and cannot masquerade as legacy or certified facts', async () => {
    const text = '项目\n👩‍💻 é 我没有部署服务。\r\n\r\nPython课程。', hash = await sha256(new TextEncoder().encode(text))
    const legacy = importText(text), w = workbenchSchema.parse({ ...legacy, contract: 'local-resume-workbench-v2', source: { ...legacy.source, origin: 'extracted_file', name: 'synthetic.pdf', review: 'needs_review', extraction: { contract: 'extracted-text-snapshot-v1', format: 'pdf', file_bytes: 100, file_sha256: 'a'.repeat(64), text_sha256: hash, parser: 'pdfjs-dist@6.4.299', pages: 1, warnings: ['layout'] } } })
    const full = workbenchSchema.parse({ ...w, excerpts: segment(w) }); expect(isReviewed(full)).toBe(false)
    for (const e of full.excerpts) expect(Array.from(text).slice(e.start, e.end).join('')).toBe(e.quote)
    const d = newDraft(full); expect(d.contract).toBe('local-job-resume-draft-v2'); expect(restoreDraft(saveDraft(d))).toEqual(d)
    expect(() => restoreDraft(JSON.stringify({ ...d, contract: 'local-job-resume-draft-v1' }))).toThrow()
    expect(() => workbenchSchema.parse({ ...full, verified: true })).toThrow()
    expect(() => workbenchSchema.parse({ ...full, excerpts: [{ ...full.excerpts[0], quote: '我完成了部署。' }] })).toThrow()
  })
})

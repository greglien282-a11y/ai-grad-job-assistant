import { checkText, segment, workbenchSchema, type Workbench, type extractionSchema } from './import'
import { orderPage } from './pdf-layout'
import type { z } from 'zod'
export const DOCUMENT_LIMIT = 5 * 1024 * 1024
export const PARSE_DEADLINE = 15000
export type Extraction = { text: string; pages: number | null; warnings: z.infer<typeof extractionSchema>['warnings'] }
export const sha256 = async (bytes: Uint8Array) => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes.slice().buffer))).map(b => b.toString(16).padStart(2, '0')).join('')
export function boundedTask<T>(start: (resolve: (value: T) => void, reject: (reason: Error) => void) => () => void, signal?: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    let cleanup = () => {}; let done = false
    const finish = (value?: T, error?: Error) => { if (done) return; done = true; clearTimeout(timer); signal?.removeEventListener('abort', abort); cleanup(); error ? reject(error) : resolve(value!) }
    const abort = () => finish(undefined, new Error('解析已取消，未导入。'))
    const timer = setTimeout(() => finish(undefined, new Error('解析超过15秒预算，请转为UTF-8文字。')), PARSE_DEADLINE)
    if (signal?.aborted) { abort(); return }
    signal?.addEventListener('abort', abort, { once: true })
    try { cleanup = start(v => finish(v), e => finish(undefined, e)); if (done) cleanup() } catch { finish(undefined, new Error('文件解析失败，未导入。')) }
  })
}
async function pdf(bytes: Uint8Array, signal?: AbortSignal): Promise<Extraction> {
  const lib = await import('pdfjs-dist')
  const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default
  lib.GlobalWorkerOptions.workerSrc = workerUrl
  return boundedTask<Extraction>((resolve, reject) => {
    const task = lib.getDocument({ data: bytes, disableFontFace: true, useSystemFonts: false, useWorkerFetch: false, useWasm: false, enableXfa: false, stopAtErrors: true, verbosity: 0, disableAutoFetch: true })
    void (async () => {
      try {
        const doc = await task.promise
        if (doc.numPages > 12) throw new Error('PDF超过12页，请缩减后重试。')
        const pages: string[] = []; let totalItems = 0; const warnings: Extraction['warnings'] = ['layout']
        for (let n = 1; n <= doc.numPages; n++) {
          const page = await doc.getPage(n), content = await page.getTextContent({ disableNormalization: true })
          totalItems += content.items.length
          if (totalItems > 30000) throw new Error('PDF文字结构过于复杂，请转为文字。')
          const fragments = content.items.filter(i => 'str' in i).map(i => ({ str: i.str, x: i.transform[4], y: i.transform[5], width: i.width, height: i.height }))
          const result = orderPage(fragments, page.getViewport({ scale: 1 }).width)
          if (!result.text.trim()) throw new Error('PDF含无可选文字页面，可能是扫描件；不支持OCR，请提供文字版。')
          if (result.columns && !warnings.includes('columns')) warnings.push('columns')
          pages.push(result.text); checkText(pages.join('\n\n')); page.cleanup()
        }
        resolve({ text: pages.join('\n\n'), pages: doc.numPages, warnings })
      } catch (error) { reject(new Error(error instanceof Error && error.name === 'PasswordException' ? '加密PDF不支持，请在本地解密后重试。' : error instanceof Error && /PDF|20,000/.test(error.message) ? error.message : 'PDF损坏或无法完整提取，请转为文字。')) }
    })()
    return () => { void task.destroy().catch(() => {}) }
  }, signal)
}
async function docx(bytes: Uint8Array, signal?: AbortSignal): Promise<Extraction> {
  return boundedTask<Extraction>((resolve, reject) => {
    const worker = new Worker(new URL('./docx.worker.ts', import.meta.url), { type: 'module' })
    worker.onmessage = e => e.data.error ? reject(new Error('DOCX损坏、含不支持内容或超过压缩预算；请另存为文字。')) : resolve(e.data)
    worker.onerror = () => reject(new Error('DOCX本地解析不可用，请另存为文字。'))
    worker.postMessage(bytes.buffer, [bytes.buffer]); return () => worker.terminate()
  }, signal)
}
export async function readDocument(file: File, signal?: AbortSignal): Promise<Workbench> {
  if (!/^[^\\/\x00-\x1f]{1,115}\.(pdf|docx)$/i.test(file.name) || !file.size || file.size > DOCUMENT_LIMIT) throw new Error('请选择非空、5 MiB以内的PDF或DOCX；旧DOC请先转换。')
  const bytes = new Uint8Array(await file.arrayBuffer()), file_sha256 = await sha256(bytes), format = file.name.toLowerCase().endsWith('.pdf') ? 'pdf' : 'docx'
  const result = await (format === 'pdf' ? pdf(bytes, signal) : docx(bytes, signal))
  checkText(result.text)
  const paragraphs = result.text.split(/\n\s*\n/).filter(p => p.trim())
  if (new Set(paragraphs).size < paragraphs.length) result.warnings.push('duplicates')
  const w: Workbench = workbenchSchema.parse({ contract: 'local-resume-workbench-v2', source: { id: crypto.randomUUID(), origin: 'extracted_file', name: file.name, text: result.text, trust: 'local_unverified', review: 'needs_review', extraction: { contract: 'extracted-text-snapshot-v1', format, file_bytes: file.size, file_sha256, text_sha256: await sha256(new TextEncoder().encode(result.text)), parser: format === 'pdf' ? 'pdfjs-dist@6.4.299' : 'mammoth@1.13.0', pages: result.pages, warnings: [...new Set(result.warnings)] } }, excerpts: [], manual: [] })
  return workbenchSchema.parse({ ...w, excerpts: segment(w) })
}
export const qualityLabels = { layout: '请逐字核对乱码、遗漏、标题与段落顺序；提取不保证版面保真。', columns: '检测到可能双栏；按左栏后右栏重排，跨栏标题须人工核对。', tables: '含表格；单元格按文档顺序展开，不能保证表格视觉关系。', omissions: '仅提取正文文本；页眉页脚、图形、文本框可能遗漏，请与原文件对照。', duplicates: '存在重复段落，保留原样；请核对重复是否必要。', parser_warning: '解析器报告不支持的结构，请特别检查遗漏。' }

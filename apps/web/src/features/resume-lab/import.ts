import { z } from 'zod'

export const MAX_BYTES = 128 * 1024
export const MAX_POINTS = 20000
export const sections = { education: '教育', project: '项目', skill: '技能', internship: '实习', other: '其他 / 待核对' } as const
export type Section = keyof typeof sections
const unsafe = /\0|[\u0001-\u0008\u000B\u000C\u000E-\u001F\u007F]|[\u202A-\u202E\u2066-\u2069]|[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u
const secret = /-----BEGIN [A-Z ]*PRIVATE KEY-----|\bBearer\s+[A-Za-z0-9._~-]{12,}|\bsk-[A-Za-z0-9_-]{16,}/i
export function checkText(text: string): string {
  if (!text.trim()) throw new Error('原文为空，请提供可核对的文字。')
  if (Array.from(text).length > MAX_POINTS || new TextEncoder().encode(text).length > MAX_BYTES) throw new Error('文字超过本地限制：20,000 code points /128 KiB。')
  if (unsafe.test(text)) throw new Error('文字包含无效 Unicode、隐藏方向控制或控制字符，已拒绝。')
  if (secret.test(text)) throw new Error('检测到疑似凭证或私钥，请先移除；内容未上传或保存。')
  return text
}
export const privacyWarnings = (text: string) => /[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b1[3-9]\d{9}\b/i.test(text)
  ? ['含疑似邮箱或电话。请检查隐私；仅在当前内存处理，不上传。'] : []
const filename = (name: string) => name.length <= 120 && !/[\\/]/.test(name) && !unsafe.test(name) && !secret.test(name) && /\.(txt|md)$/i.test(name)
const safeText = z.string().superRefine((value, ctx) => { try { checkText(value) } catch { ctx.addIssue({ code: 'custom', message: 'Invalid local text' }) } })
const sourceSchema = z.strictObject({ id: z.string().uuid(), origin: z.enum(['paste', 'file']), name: z.string().nullable(), text: safeText, trust: z.literal('local_unverified') })
  .refine(s => s.origin === 'file' ? s.name !== null && filename(s.name) : s.name === null)
export const excerptSchema = z.strictObject({ id: z.string().uuid(), kind: z.literal('resume_excerpt'), source_id: z.string().uuid(), section: z.enum(['education', 'project', 'skill', 'internship', 'other']), label: z.string().min(1).max(100), start: z.number().int().nonnegative(), end: z.number().int().positive(), quote: safeText })
const manualSchema = z.strictObject({ id: z.string().uuid(), kind: z.literal('user_manual_statement'), text: safeText, trust: z.literal('local_unverified') })
export const workbenchSchema = z.strictObject({ contract: z.literal('local-resume-workbench-v1'), source: sourceSchema, excerpts: z.array(excerptSchema).max(100), manual: z.array(manualSchema).max(50) })
  .superRefine((w, ctx) => {
    const points = Array.from(w.source.text), ids = [...w.excerpts, ...w.manual].map(e => e.id)
    if (new Set(ids).size !== ids.length || w.excerpts.some(e => e.source_id !== w.source.id || e.end <= e.start || e.end > points.length || points.slice(e.start, e.end).join('') !== e.quote)) ctx.addIssue({ code: 'custom', message: 'Broken local source relation' })
  })
export type Workbench = z.infer<typeof workbenchSchema>
export type Excerpt = z.infer<typeof excerptSchema>

export function excerpt(w: Workbench, start: number, end: number, section: Section = 'other', id: string = crypto.randomUUID(), label: string = sections[section]): Excerpt {
  const out = { id, kind: 'resume_excerpt' as const, source_id: w.source.id, section, label, start, end, quote: Array.from(w.source.text).slice(start, end).join('') }
  workbenchSchema.parse({ ...w, excerpts: [out], manual: [] })
  return out
}
function segment(w: Workbench): Excerpt[] {
  const points = Array.from(w.source.text), out: Excerpt[] = []
  let line = 0, begin: number | null = null, end = 0, section: Section = 'other'
  const flush = () => { if (begin !== null) out.push(excerpt(w, begin, end, section)); begin = null }
  for (let i = 0; i <= points.length; i++) {
    if (i < points.length && points[i] !== '\n') continue
    let a = line, b = i
    while (a < b && /\s/.test(points[a])) a++
    while (b > a && /\s/.test(points[b - 1])) b--
    const text = points.slice(a, b).join('')
    const heading = /^(?:#{1,6}\s*)?(教育(?:背景|经历)?|项目(?:经历|经验)?|技能(?:清单)?|专业技能|实习(?:经历|经验)?|其他)[：:\s]*$/.exec(text)
    if (!text || heading) {
      flush()
      if (heading) section = heading[1].startsWith('教育') ? 'education' : heading[1].startsWith('项目') ? 'project' : heading[1].startsWith('实习') ? 'internship' : heading[1] === '其他' ? 'other' : 'skill'
    } else { if (begin === null) begin = a; end = b }
    line = i + 1
  }
  flush()
  return out
}
export function importText(text: string, name: string | null = null): Workbench {
  checkText(text)
  if (name !== null && !filename(name)) throw new Error('仅支持本地 .txt / .md 文件名。')
  const w: Workbench = { contract: 'local-resume-workbench-v1', source: { id: crypto.randomUUID(), origin: name === null ? 'paste' : 'file', name, text, trust: 'local_unverified' }, excerpts: [], manual: [] }
  w.excerpts = segment(w)
  if (w.excerpts.length > 100) throw new Error('候选段落过多，请减少到100段以内。')
  return workbenchSchema.parse(w)
}
export function decodeFile(name: string, bytes: Uint8Array): Workbench {
  if (!filename(name)) throw new Error('仅支持本地 .txt / .md，不支持 PDF、Word 或可执行文件。')
  if (!bytes.length || bytes.length > MAX_BYTES) throw new Error('文件为空或超过128 KiB限制。')
  let text: string
  try { text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes) } catch { throw new Error('仅支持有效UTF-8文字，请另存为UTF-8后重试。') }
  return importText(text, name)
}
export async function readFile(file: File): Promise<Workbench> {
  if (!filename(file.name) || !file.size || file.size > MAX_BYTES) throw new Error('请选择非空、128 KiB以内的 .txt / .md UTF-8文件。')
  return decodeFile(file.name, new Uint8Array(await file.arrayBuffer()))
}
export function addManual(w: Workbench, text: string): Workbench {
  return workbenchSchema.parse({ ...w, manual: [...w.manual, { id: crypto.randomUUID(), kind: 'user_manual_statement', trust: 'local_unverified', text: checkText(text) }] })
}

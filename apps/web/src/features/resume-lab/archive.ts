import { Unzip, UnzipInflate, zipSync } from 'fflate'
export const ZIP_TOTAL = 8 * 1024 * 1024
// Bounded reconstruction prevents a second parser interpreting a different central directory.
export function boundedDocx(bytes: Uint8Array): { bytes: Uint8Array; tables: boolean } {
  if (!bytes.length || bytes.length > 5 * 1024 * 1024 || bytes[0] !== 80 || bytes[1] !== 75) throw new Error('archive')
  const entries: Record<string, Uint8Array> = Object.create(null), names = new Set<string>()
  let total = 0, completed = 0, tables = false
  const streams: { terminate: () => void }[] = []
  const unzip = new Unzip(file => {
    streams.push(file)
    if (names.has(file.name) || names.size >= 256 || file.name.length > 200 || /(^\/|\\|(^|\/)\.\.(\/|$)|:)/.test(file.name) || /vba|activex|embeddings/i.test(file.name) || ![0, 8].includes(file.compression) || (file.originalSize ?? 0) > 2 * 1024 * 1024) throw new Error('archive')
    names.add(file.name)
    const chunks: Uint8Array[] = []; let size = 0
    file.ondata = (error, data, final) => {
      if (error) throw new Error('archive')
      size += data.length; total += data.length
      if (size > 2 * 1024 * 1024 || total > ZIP_TOTAL || total > Math.max(1024 * 1024, bytes.length * 150)) throw new Error('archive budget')
      chunks.push(data)
      if (final) {
        completed++
        const content = new Uint8Array(size); let offset = 0
        for (const c of chunks) { content.set(c, offset); offset += c.length }
        if (/\.(xml|rels)$/i.test(file.name)) {
          const xml = new TextDecoder('utf-8', { fatal: true }).decode(content)
          if (/<!DOCTYPE|<!ENTITY/i.test(xml)) throw new Error('XML declarations')
          if (file.name === 'word/document.xml') tables = /<w:tbl[ >]/.test(xml)
        }
        entries[file.name] = content
      }
    }; file.start()
  }); unzip.register(UnzipInflate)
  try {
    for (let i = 0; i < bytes.length; i += 4096) unzip.push(bytes.subarray(i, i + 4096), i + 4096 >= bytes.length)
    if (completed !== names.size || !entries['[Content_Types].xml'] || !entries['word/document.xml']) throw new Error('Incomplete DOCX')
    return { bytes: zipSync(entries, { level: 0 }), tables }
  } finally { streams.forEach(s => s.terminate()) }
}

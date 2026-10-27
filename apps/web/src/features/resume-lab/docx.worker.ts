import mammoth from 'mammoth'
import { boundedDocx } from './archive'
// This worker has no network path. Raw text only; no HTML conversion or image callbacks.
Object.defineProperty(globalThis, 'fetch', { value: () => Promise.reject(new Error('network disabled')) })
Object.defineProperty(globalThis, 'XMLHttpRequest', { value: undefined })
Object.defineProperty(globalThis, 'WebSocket', { value: undefined })
self.onmessage = async (event: MessageEvent<ArrayBuffer>) => {
  try {
    const archive = boundedDocx(new Uint8Array(event.data))
    const result = await mammoth.extractRawText({ arrayBuffer: archive.bytes.buffer as ArrayBuffer })
    if (result.messages.some(m => m.type === 'error')) throw new Error('incomplete')
    if (Array.from(result.value).length > 20000) throw new Error('text budget')
    self.postMessage({ text: result.value, pages: null, warnings: ['layout', 'omissions', ...(archive.tables ? ['tables'] : []), ...(result.messages.length ? ['parser_warning'] : [])] })
  } catch { self.postMessage({ error: true }) }
}

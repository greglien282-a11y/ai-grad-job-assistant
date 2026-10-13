import { z } from 'zod'

export const PENDING_KEY = 'pathwise.development.pendingCreate'
const pendingSchema = z.object({ schemaVersion: z.literal(1), key: z.string().regex(/^v1\.[1-9][0-9]{9}\.[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/), token: z.string().regex(/^[A-Za-z0-9_-]{43}$/),
  bodyTag: z.string().regex(/^[a-f0-9]{64}$/), expiresAt: z.number().int().positive() }).strict()
export type PendingCreate = z.infer<typeof pendingSchema>
export type Operation = { key: string; bodyTag: string }
function cryptoApi() {
  if (!globalThis.crypto?.subtle || !globalThis.crypto.getRandomValues) throw new Error('安全随机数不可用，尚未发送创建请求。请使用受支持的浏览器。')
  return globalThis.crypto
}
function base64(bytes: Uint8Array) { return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '') }
export function randomSecret() { return base64(cryptoApi().getRandomValues(new Uint8Array(32))) }
export async function hmac(token: string, message: string) {
  const api = cryptoApi()
  const key = await api.subtle.importKey('raw', new TextEncoder().encode(token), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign'])
  return new Uint8Array(await api.subtle.sign('HMAC', key, new TextEncoder().encode(message)))
}
export async function bodyTag(token: string, kind: string, scope: string, body: Record<string, unknown>) {
  const canonical = JSON.stringify(Object.fromEntries(Object.keys(body).sort().map(key => [key, body[key]])))
  const bytes = await hmac(token, `${kind}\n${scope}\n${canonical}`)
  return [...bytes].map(byte => byte.toString(16).padStart(2, '0')).join('')
}
export async function operation(token: string, kind: string, scope: string, body: Record<string, unknown>): Promise<Operation> {
  const issued = Math.floor(Date.now() / 1000), nonce = randomSecret()
  const proof = base64(await hmac(token, `pathwise-idempotency-v1\n${kind}\n${scope}\n${issued}\n${nonce}`))
  return { key: `v1.${issued}.${nonce}.${proof}`, bodyTag: await bodyTag(token, kind, scope, body) }
}
export async function newPending(raw: string): Promise<PendingCreate> {
  const token = randomSecret(), op = await operation(token, 'create_session', 'global', { raw_input: raw })
  return { schemaVersion: 1, ...op, token, expiresAt: (Number(op.key.split('.')[1]) + 86400) * 1000 }
}
export function readPending(): { value: PendingCreate | null; error: string } {
  try {
    const text = sessionStorage.getItem(PENDING_KEY)
    if (!text) return { value: null, error: '' }
    const parsed = pendingSchema.safeParse(JSON.parse(text))
    if (!parsed.success || parsed.data.expiresAt !== (Number(parsed.data.key.split('.')[1]) + 86400) * 1000) return { value: null, error: '临时恢复记录异常，已停止创建。请核对当前标签页暂存；不要重复创建。' }
    if (Date.now() >= parsed.data.expiresAt) {
      sessionStorage.removeItem(PENDING_KEY)
      return { value: null, error: '24 小时临时恢复窗口已结束。之前可能已创建匿名会话，无法保证找回；没有自动创建新会话。' }
    }
    return { value: parsed.data, error: '' }
  } catch { return { value: null, error: '浏览器暂存不可用，已停止创建。请开启当前标签页暂存后重试。' } }
}
export function storePending(value: PendingCreate) {
  try {
    const serialized = JSON.stringify(pendingSchema.parse(value))
    sessionStorage.setItem(PENDING_KEY, serialized)
    if (sessionStorage.getItem(PENDING_KEY) !== serialized) throw new Error()
  } catch { throw new Error('浏览器暂存不可用，尚未发送创建请求。请开启当前标签页暂存后重试。') }
}
export function clearPending() { sessionStorage.removeItem(PENDING_KEY) }
export async function checkBody(value: PendingCreate, raw: string) {
  if (Date.now() >= value.expiresAt) throw new Error('24 小时临时恢复窗口已结束。请先核对之前的创建结果，不会自动新建。')
  if (await bodyTag(value.token, 'create_session', 'global', { raw_input: raw }) !== value.bodyTag) throw new Error('这次输入与先前提交不同。请恢复刚才的创建操作，或重新输入完全一致的原经历。')
}

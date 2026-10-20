import { z } from 'zod'
import { exportV2Schema, factV3Schema, summaryV2Schema } from './experience-read-contract'

export type ReadAccess = { sessionId: string; projectId: string; token: string }
export type FactV3 = z.infer<typeof factV3Schema>
export class ReadError extends Error {
  constructor(public kind: 'disabled' | 'auth' | 'missing' | 'conflict' | 'unavailable' | 'version' | 'contract' | 'network' | 'input') {
    super(({ disabled: '新版读取暂不可用。请等待服务开放。', auth: '需要有效的会话凭证，请核对后手动读取。',
      missing: '资料不存在或不属于当前会话。', conflict: '资料版本或状态已变化，请手动重新读取。',
      unavailable: '暂时无法安全读取完整资料，请稍后手动读取。', version: '服务返回了尚不支持的读取版本，已停止展示本次结果。', contract: '资料数据校验失败，已停止展示本次结果。',
      network: '网络连接中断，请检查连接后手动读取。', input: '请填写有效的会话 ID、项目 ID 和会话凭证。' })[kind])
  }
}
export function validateAccess(a: ReadAccess) {
  if (!z.strictObject({ sessionId: z.string().uuid(), projectId: z.string().uuid(), token: z.string().min(32).max(256) }).safeParse(a).success) throw new ReadError('input')
}
export function createReadApi(fetcher: typeof fetch = fetch) {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  async function get<T>(path: string, schema: z.ZodType<T>, a: ReadAccess, signal?: AbortSignal) {
    validateAccess(a)
    let r: Response
    try { r = await fetcher(`${base}/api/v2/experience${path}`, { method: 'GET', signal, cache: 'no-store', redirect: 'error',
      headers: { Authorization: `Bearer ${a.token}`, Accept: 'application/json' } }) }
    catch { throw new ReadError('network') }
    if (!r.ok) {
      // Never put server messages, URLs, rejected data or credentials in an Error.
      const body: unknown = await r.json().catch(() => null)
      const error = z.object({ error: z.object({ code: z.string() }) }).safeParse(body)
      throw new ReadError(r.status === 401 ? 'auth' : r.status === 404 ? 'missing' : r.status === 409 ? 'conflict' :
        r.status === 503 && error.success && error.data.error.code === 'experience_read_disabled' ? 'disabled' : 'unavailable')
    }
    let body: string
    try { body = await r.text() } catch { throw new ReadError('network') }
    let raw: unknown
    try { raw = JSON.parse(body) } catch { throw new ReadError('contract') }
    if (raw && typeof raw === 'object') {
      for (const [key, version] of Object.entries({ summary_contract_version: 2, format_version: 2, fact_contract_version: 3, provenance_version: 3 })) {
        if (Object.hasOwn(raw, key) && (raw as Record<string, unknown>)[key] !== version) throw new ReadError('version')
      }
    }
    const parsed = schema.safeParse(raw)
    if (!parsed.success) throw new ReadError('contract')
    return parsed.data
  }
  return {
    summary: async (a: ReadAccess, signal?: AbortSignal) => {
      const s = await get(`/projects/${a.projectId}/experience-summary`, summaryV2Schema, a, signal)
      if (s.project_id !== a.projectId || [...s.confirmed, ...s.pending, ...s.reviewed_non_contributions.map(e => e.fact)].some(f => f.session_id !== a.sessionId)) throw new ReadError('contract')
      return s
    },
    fact: async (a: ReadAccess, fid: string, signal?: AbortSignal) => {
      if (!z.string().uuid().safeParse(fid).success) throw new ReadError('input')
      const f = await get(`/sessions/${a.sessionId}/facts/${fid}`, factV3Schema, a, signal)
      if (f.id !== fid || f.session_id !== a.sessionId || f.project_id !== a.projectId) throw new ReadError('contract')
      return f
    },
    export: async (a: ReadAccess, signal?: AbortSignal) => {
      const out = await get(`/sessions/${a.sessionId}/export`, exportV2Schema, a, signal)
      if (out.data.id !== a.sessionId || !out.data.projects.some(p => p.id === a.projectId) ||
        out.data.facts.some(f => f.session_id !== a.sessionId)) throw new ReadError('contract')
      return out
    },
  }
}

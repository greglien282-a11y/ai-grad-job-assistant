import { z } from 'zod'

const id = z.string().uuid()
const timestamp = z.string().datetime({ offset: true })
export const factStatus = z.enum(['pending', 'user_confirmed', 'evidence_supported', 'rejected'])
export const factSchema = z.object({
  id, project_id: id, session_id: id, statement: z.string(), status: factStatus,
  version: z.number().int().positive(), created_at: timestamp, updated_at: timestamp,
  original_source_turn_ids: z.array(id), source_kind: z.enum(['conversation_turns', 'user_edit']),
  source_turn_ids: z.array(id), source_change_id: id.nullable(), evidence_id: id.nullable(),
}).refine(fact => fact.source_kind === 'user_edit'
  ? fact.source_change_id !== null && fact.source_turn_ids.length === 0
  : fact.source_change_id === null, 'Current provenance is inconsistent')
const projectSchema = z.object({ id, session_id: id, raw_input: z.string(), title: z.string().nullable(), created_at: timestamp })
export const turnSchema = z.object({ id, session_id: id, role: z.enum(['user', 'assistant']), content: z.string(), created_at: timestamp })
const historySnapshot = z.object({ statement: z.string(), status: factStatus, version: z.number().int().positive().optional() }).passthrough()
export const sessionSchema = z.object({
  id, status: z.enum(['active', 'ended']), created_at: timestamp, updated_at: timestamp,
  projects: z.array(projectSchema), turns: z.array(turnSchema), facts: z.array(factSchema),
  evidence: z.array(z.object({ id, fact_id: id, material_reference: z.string(), basis: z.string(), reviewer: z.literal('user'), created_at: timestamp, verification_label: z.string() })),
  history: z.array(z.object({ id, fact_id: id, action: z.string(), actor: z.enum(['user', 'system']), before: historySnapshot.nullable(), after: historySnapshot, created_at: timestamp })),
})
const createdSchema = z.object({ session_id: id, project_id: id, initial_turn_id: id, status: z.literal('active'), access_token: z.string().min(32).max(256) })
const exportSchema = z.object({ format_version: z.literal(1), exported_at: timestamp, data: sessionSchema })
export const credentialsSchema = z.object({ sessionId: id, token: z.string().min(32).max(256) }).strict()
export type Credentials = z.infer<typeof credentialsSchema>
export type ExperienceSession = z.infer<typeof sessionSchema>
export type Fact = z.infer<typeof factSchema>
export type Mutation = { action: 'edit'; statement: string; expected_version: number }
  | { action: 'confirm' | 'reject'; expected_version: number }
  | { action: 'verify_material'; expected_version: number; material_reference: string; basis: string }

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(({ 401: '会话凭证无效，请检查当前会话。', 404: '会话不存在或无法访问。',
      409: '资料已变化或当前状态不允许此操作。', 422: '请检查输入内容与事实来源。',
      413: '输入过长，请缩短后重试。', 503: '数据库暂时不可用，请稍后重新读取。' } as Record<number, string>)[status] ?? '请求未完成，请稍后重试。')
  }
}

export function createExperienceApi(fetcher: typeof fetch = fetch) {
  const base = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
  async function request<T>(path: string, schema: z.ZodType<T> | null, credentials?: Credentials, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
    let response: Response
    try {
      response = await fetcher(`${base}/api/v1/experience${path}`, { method, signal, cache: 'no-store',
        headers: { Accept: 'application/json', ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
          ...(credentials ? { Authorization: `Bearer ${credentials.token}` } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      })
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') throw error
      throw new Error('暂时无法连接服务。输入已保留，请检查 API 后重试。')
    }
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null)
      const parsed = z.object({ error: z.object({ code: z.string() }) }).safeParse(payload)
      throw new ApiError(response.status, parsed.success ? parsed.data.error.code : 'request_failed')
    }
    if (schema === null) return undefined as T
    const parsed = schema.safeParse(await response.json().catch(() => null))
    if (!parsed.success) throw new Error('服务返回的资料格式异常，请重新读取。')
    return parsed.data
  }
  return {
    create: (raw_input: string) => request('/sessions', createdSchema, undefined, 'POST', { raw_input }),
    read: (c: Credentials, signal?: AbortSignal) => request(`/sessions/${c.sessionId}`, sessionSchema, c, 'GET', undefined, signal),
    turn: (c: Credentials, content: string) => request(`/sessions/${c.sessionId}/turns`, turnSchema, c, 'POST', { content }),
    add: (c: Credentials, projectId: string, statement: string, sourceId: string) => request(`/projects/${projectId}/facts`, factSchema, c, 'POST', { statement, source_turn_ids: [sourceId] }),
    mutate: (c: Credentials, factId: string, body: Mutation) => request(`/facts/${factId}`, factSchema, c, 'PATCH', body),
    end: (c: Credentials) => request(`/sessions/${c.sessionId}/end`, sessionSchema, c, 'POST'),
    remove: (c: Credentials) => request<void>(`/sessions/${c.sessionId}`, null, c, 'DELETE'),
    export: (c: Credentials) => request(`/sessions/${c.sessionId}/export`, exportSchema, c),
  }
}
export type ExperienceApi = ReturnType<typeof createExperienceApi>
export const SESSION_KEY = 'pathwise.development.session'
export function readCredentials(): Credentials | null {
  try { return credentialsSchema.parse(JSON.parse(sessionStorage.getItem(SESSION_KEY) ?? 'null')) } catch { return null }
}
export function saveCredentials(c: Credentials) { sessionStorage.setItem(SESSION_KEY, JSON.stringify(c)) }
export function downloadJson(value: unknown, filename: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

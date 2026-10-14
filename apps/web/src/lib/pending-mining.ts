import { z } from 'zod'
import { bodyTag, operation } from './idempotency'
import type { MiningBody } from './mining-contract'
import type { Credentials } from './experience'
export const MINING_KEY = 'pathwise.development.pendingMining'
const id = z.string().uuid()
const schema = z.object({ schemaVersion: z.literal(1), sessionId: id, key: z.string().regex(/^v1\.[1-9][0-9]{9}\.[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$/), bodyTag: z.string().regex(/^[a-f0-9]{64}$/),
  expiresAt: z.number().int().positive(), project_id: id, base_revision: z.number().int().positive(), input_turn_id: id.nullable(), retry_of: id.nullable(),
  confirm_retry: z.boolean(), answered_question_ids: z.array(id).max(2).optional(), mode: z.enum(['initial', 'answer', 'retry']) }).strict()
export type PendingMining = z.infer<typeof schema>
export function readMining(): { value: PendingMining | null; error: string } {
  try {
    const value = sessionStorage.getItem(MINING_KEY)
    if (!value) return { value: null, error: '' }
    const parsed = schema.parse(JSON.parse(value))
    if (parsed.expiresAt !== (Number(parsed.key.split('.')[1]) + 86400) * 1000) throw new Error()
    return { value: parsed, error: Date.now() >= parsed.expiresAt ? '临时操作窗口已过期，请先核对已保存回答，不会自动重建。' : '' }
  } catch { return { value: null, error: '操作暂存无法读取。已停止写入，请检查当前标签页暂存。' } }
}
export async function newMining(c: Credentials, body: MiningBody): Promise<PendingMining> {
  const op = await operation(c.token, 'mining_run', `session:${c.sessionId}`, body)
  const { content: _content, ...metadata } = body
  return { schemaVersion: 1, sessionId: c.sessionId, ...op, ...metadata, mode: body.retry_of ? 'retry' : body.input_turn_id ? 'initial' : 'answer', expiresAt: (Number(op.key.split('.')[1]) + 86400) * 1000 }
}
export function storeMining(value: PendingMining) {
  const serialized = JSON.stringify(schema.parse(value))
  sessionStorage.setItem(MINING_KEY, serialized)
  if (sessionStorage.getItem(MINING_KEY) !== serialized) throw new Error('操作键暂存失败，尚未发送请求。')
}
export function clearMining() { sessionStorage.removeItem(MINING_KEY) }
export function originalBody(p: PendingMining, content = ''): MiningBody {
  return { project_id: p.project_id, base_revision: p.base_revision, content: p.mode === 'answer' ? content : null,
    input_turn_id: p.input_turn_id, retry_of: p.retry_of, confirm_retry: p.confirm_retry,
    ...(p.answered_question_ids?.length ? { answered_question_ids: p.answered_question_ids } : {}) }
}
export async function verifyMining(c: Credentials, p: PendingMining, body: MiningBody) {
  if (c.sessionId !== p.sessionId || Date.now() >= p.expiresAt) throw new Error('操作记录与会话不匹配或已过期，已停止发送。')
  if (await bodyTag(c.token, 'mining_run', `session:${c.sessionId}`, body) !== p.bodyTag) throw new Error('请重新输入完全一致的原回答，保留原问题关联；不会换键发送。')
}

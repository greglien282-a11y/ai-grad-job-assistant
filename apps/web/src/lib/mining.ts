import { z } from 'zod'
import { factSchema, type Credentials, type ExperienceApi } from './experience'
import { miningRunSchema, questionSchema, type MiningBody, type QuestionAction } from './mining-contract'
const summarySchema = z.object({ project_id: z.string().uuid(), context_revision: z.number().int().positive(),
  confirmed: z.array(factSchema), pending: z.array(factSchema), text: z.string(), incomplete: z.boolean() }).refine(data =>
  data.confirmed.every(f => ['user_confirmed', 'evidence_supported'].includes(f.status)) && data.pending.every(f => f.status === 'pending') &&
  data.text === data.confirmed.map(f => f.statement).join('\n'), 'Summary must use only confirmed facts')
export type Summary = z.infer<typeof summarySchema>
export function createMiningApi(api: ExperienceApi) {
  const base = (c: Credentials) => `/sessions/${c.sessionId}`
  return {
    start: (c: Credentials, body: MiningBody, key: string) => api.request(`${base(c)}/mining-runs`, miningRunSchema, c, 'POST', body, AbortSignal.timeout(60000), key),
    recover: (c: Credentials, key: string) => api.request(`${base(c)}/mining-runs/recovery`, miningRunSchema, c, 'GET', undefined, AbortSignal.timeout(10000), key),
    summary: (c: Credentials, project: string) => api.request(`/projects/${project}/experience-summary`, summarySchema, c, 'GET', undefined, AbortSignal.timeout(10000)),
    stop: (c: Credentials, revision: number) => api.request(`${base(c)}/mining-stop`, z.object({ mining_status: z.literal('stopped'), context_revision: z.number().int() }), c, 'POST', { base_revision: revision }),
    question: (c: Credentials, id: string, revision: number, version: number, action: QuestionAction, content?: string) => api.request(`${base(c)}/mining-questions/${id}`, questionSchema.extend({ context_revision: z.number().int() }), c, 'PATCH', { base_revision: revision, expected_version: version, action, ...(content === undefined ? {} : { content }) }),
  }
}
export type MiningApi = ReturnType<typeof createMiningApi>

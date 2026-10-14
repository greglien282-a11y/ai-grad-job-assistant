import { z } from 'zod'
const id = z.string().uuid()
export const answerLinkSchema = z.object({ question_id: id, question_version: z.number().int().positive() })
export const questionSchema = z.object({ id, state: z.enum(['active', 'skipped', 'corrected', 'hidden', 'deleted']), version: z.number().int().positive(), content: z.string().nullable() })
export const miningRunSchema = z.object({ id, session_id: id, project_id: id, input_turn_id: id,
  base_revision: z.number().int().positive(), reserved_revision: z.number().int().positive(),
  state: z.enum(['reserved', 'running', 'completed', 'failed', 'unknown', 'stale']), lease_until: z.string().datetime({ offset: true }),
  error_code: z.string().nullable(), retry_of: id.nullable(), provider: z.literal('scripted'), synthetic: z.literal(true),
  questions: z.array(questionSchema).max(2), candidate_fact_ids: z.array(id), answered_questions: z.array(answerLinkSchema).max(2),
})
export type MiningRun = z.infer<typeof miningRunSchema>
export type Question = z.infer<typeof questionSchema>
export type MiningBody = { project_id: string; base_revision: number; content: string | null; input_turn_id: string | null; retry_of: string | null; confirm_retry: boolean; answered_question_ids?: string[] }
export type QuestionAction = 'skip' | 'correct' | 'hide' | 'delete'

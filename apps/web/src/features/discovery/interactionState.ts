import type { ExperienceSession } from '../../lib/experience'

export type RequestPhase = 'idle' | 'reading' | 'submitting' | 'recovering'
export type InteractionInput = {
  session: ExperienceSession | null; hasCredentials: boolean; busy: boolean; phase: RequestPhase;
  needsReload: boolean; storageError: boolean; pending: boolean; notFound: boolean; failureCode: string | null
}

/** Presentation only: no provider, timers, requests, inferred model text or state writes. */
export function interactionState(i: InteractionInput) {
  const s = i.session, run = s?.mining_runs?.at(-1)
  const answered = new Set(s?.turns.flatMap(t => t.answered_questions?.map(q => q.question_id) ?? []))
  const questions = run?.questions.filter(q => ['active', 'corrected'].includes(q.state) && !answered.has(q.id)) ?? []
  const ids = new Set(run?.candidate_fact_ids)
  const candidates = s?.facts.filter(f => ids.has(f.id)) ?? []
  const pendingCount = candidates.filter(f => f.status === 'pending').length
  function state(key: string, title: string, description: string, next: string, pauseMining = false, recoverOnly = false, query = false) {
    return { key, title, description, next, pauseMining, recoverOnly, query,
      candidateCount: candidates.length, pendingCount, questionCount: questions.length }
  }
  if (i.needsReload || i.storageError) return state(
    ['context_conflict', 'version_conflict'].includes(i.failureCode ?? '') ? 'conflict' : 'recovery_required',
    '先核对最新资料', '读取失败、暂存异常或版本冲突时，旧资料不能作为本次成功结果。',
    '先只读恢复；草稿保留，不会覆盖或自动重发。', true, true, true)
  if (i.phase === 'submitting') return state('submitting', '正在提交并进行合成整理',
    '这是用户明确提交后的请求，尚未确认保存或整理结果。', '请勿重复提交；不会自动发起第二次推理。', true)
  if (i.phase === 'recovering') return state('reading', '正在只读查询整理结果',
    '此处只查询已提交操作，不保存回答，也不触发推理。', '等待本次查询返回。', true)
  if (i.busy) return state('reading', '正在读取或处理资料',
    '资料操作不代表模型正在思考；尚未确认本次操作的最终结果。', '请等待资料核对完成。', true)
  if (!s) return state(i.hasCredentials || i.pending ? 'recovery_required' : 'describe',
    i.hasCredentials || i.pending ? '先恢复已有操作' : '先描述一段合成经历',
    '当前仅启用零费用合成测试，真实 AI 尚未启用。',
    i.hasCredentials || i.pending ? '只读查询原结果，不会自动创建或推理。' : '由你明确提交后，才开始整理。', true, i.hasCredentials, i.hasCredentials)
  if (s.status === 'ended') return state('ended', '会话已结束 · 只读',
    '不会再保存回答或编辑事实。', '可以阅读已确认整理稿及查看来源。', true)
  if (run?.state === 'unknown') return state('unknown', '本轮结果不确定',
    '超时或未知提交结果不能当作失败后可直接重试。', '只读查询本轮状态；不自动重发，也不开放重新推理。', true, true, true)
  if (run?.state === 'reserved' || run?.state === 'running') return state(run.state,
    run.state === 'reserved' ? '合成整理已预留' : '服务端记录合成整理进行中',
    '状态来自已保存的运行记录，不是模型自然语言回复。', '手动只读查询；本页不自动轮询。', true, true, true)
  if (s.mining_status === 'stopped') return state('stopped', '追问已停止 · 仍可核对事实',
    '服务端记录已停止；当前合同不提供具体停止原因。', '审核已有事实，或前往 03 阅读已确认的原文整理。', true)
  if (['mining_round_limit', 'mining_attempt_limit'].includes(i.failureCode ?? '')) return state('limit',
    '已达到本次整理限制', '服务端拒绝了进一步整理；这不表示经历已完整。', '可审核已有事实、阅读 03 或明确停止追问。', true)
  if (i.pending && !i.notFound) return state('unknown', '上一条提交尚待核对',
    '本地仍有未恢复的操作记录，不能用旧轮次宣称本轮已完成。', '先只读查询原操作结果。', true, true, true)
  if (i.pending && i.notFound) return state('not_found', '已明确未找到原操作',
    '没有自动更换操作键或重复保存回答。', '按恢复面板要求输入完全一致的原回答，显式同键重试。')
  if (!run) return state('not_started', '等待首次合成整理',
    '原始描述已保存，尚无已完成的整理记录。', '点击下方开始按钮，明确启动本次整理。')
  if (run.state === 'failed') return state('failed',
    run.error_code === 'provider_output_invalid' ? '本轮输出未通过校验' : '本轮整理明确失败',
    run.error_code === 'provider_output_invalid' ? '未通过来源或输出校验的内容不能成为候选事实。' : '不能把失败记录当作有效提取结果；失败原因以服务端记录为准。',
    '可先重新读取；再次整理已保存回答必须单独确认。', true, false, true)
  if (run.state === 'stale') return state('stale', '本轮上下文已过期',
    '迟到结果不能覆盖更新后的资料，新回答提交已暂停。',
    '先只读核对当前资料；重新整理仍须明确确认。', true, false, true)
  if (candidates.length !== ids.size) return state('recovery_required', '本轮候选资料尚不完整',
    '运行记录与当前事实无法完整对应，不能报告提取成功。', '先只读重新获取资料。', true, true, true)
  if (!pendingCount && questions.length && candidates.length) return state('awaiting_answer', '等待你回答当前问题',
    '本轮候选已审核，问题与用户回答仍按显式关联记录。', '选择“回答这题”、勾选两题或自由补充；也可阅读 03。')
  return candidates.length ? state('completed', pendingCount ? `本轮有 ${pendingCount} 条候选事实待确认` : '本轮候选事实已审核',
    `本轮当前共有 ${candidates.length} 条候选；待确认 ${pendingCount} 条。数量来自服务端当前事实。`,
    pendingCount ? '可回答当前问题或对照原文审核；只有确认后的事实才进入 03。' : '可继续回答问题，或阅读已确认的整理稿。')
    : state('no_new_facts', '本轮没有新增候选事实', '不能将零条候选描述为提取成功。',
      questions.length ? '仍有已保存的合法追问，可以继续澄清。' : '暂无可回答追问，可自由补充、审核旧事实或明确停止。')
}

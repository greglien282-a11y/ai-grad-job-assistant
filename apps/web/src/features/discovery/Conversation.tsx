import type { ExperienceSession } from '../../lib/experience'
import type { Question, QuestionAction } from '../../lib/mining-contract'
import { QuestionCard } from './QuestionCard'
export function Conversation({ session, selected, disabled, onSelect, onAnswer, onQuestion }: {
  session: ExperienceSession; selected: string[]; disabled: boolean; onSelect: (id: string) => void;
  onAnswer: (id: string) => void;
  onQuestion: (q: Question, action: QuestionAction, content?: string) => Promise<boolean>
}) {
  const runs = session.mining_runs ?? []
  const latest = [...runs].reverse().find(r => r.state === 'completed')
  const questions = new Map(runs.flatMap(r => r.questions.map(q => [q.id, q] as const)))
  const latestTurn = session.turns.filter(t => t.role === 'user').at(-1)?.id
  return <div className="chat-timeline" aria-label="经历对话">
    {session.turns.filter(turn => turn.role === 'user').map((turn, index) => <details className="saved-turn" key={turn.id} open={turn.id === latestTurn || turn.id === latest?.input_turn_id}>
      <summary>{turn.id === latestTurn ? '本轮已保存的描述' : `历史描述与回答 ${index + 1}`}</summary><article className="message user-message">
      <div className="message-author">你的经历 <span>已保存</span></div><details className="saved-description"><summary>查看已保存原文</summary><p>{turn.content}</p></details>
      {!!turn.answered_questions?.length && <div className="answer-trace">已关联 {turn.answered_questions.length} 个问题{turn.answered_questions.map(link => <details key={link.question_id}><summary>作答时问题版本 {link.question_version}</summary>{questions.get(link.question_id)?.state === 'deleted' ? <p>对应问题已删除，原回答仍保留。</p> : <p>{questions.get(link.question_id)?.content ?? '对应问题待重新读取'}{questions.get(link.question_id)?.version !== link.question_version && '（这是后续修订的问题，原回答关联未被改写。）'}</p>}</details>)}</div>}
    </article>{runs.filter(r => r.input_turn_id === turn.id && r.state === 'completed').map(r => <section className="message assistant-message" key={r.id}>
      <div className="message-author">Pathwise <span>合成流程记录 · 不是模型回复</span></div><p>以下是已保存的问题及回答来源记录；候选数量与本轮状态以服务端资料为准。</p>
      <details className="past-questions" data-current={r.id === latest?.id} open={r.id === latest?.id}><summary>{r.id === latest?.id ? '当前追问' : '已保存的历史追问'} · {r.questions.length} 题</summary>
        {r.id === latest?.id && <p className="question-guidance">点击“回答这题”关联并跳转；也可勾选两题一起回答。不选即自由补充。</p>}
        {r.questions.map(q => <QuestionCard key={q.id} question={q} current={r.id === latest?.id && session.mining_status === 'active'} selected={selected.includes(q.id)} disabled={disabled} onSelect={() => onSelect(q.id)} onAnswer={() => onAnswer(q.id)} onAction={(action, content) => onQuestion(q, action, content)} />)}</details>
    </section>)}</details>)}
  </div>
}

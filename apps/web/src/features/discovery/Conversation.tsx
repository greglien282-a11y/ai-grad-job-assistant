import type { ExperienceSession } from '../../lib/experience'
import type { Question, QuestionAction } from '../../lib/mining-contract'
import { QuestionCard } from './QuestionCard'
export function Conversation({ session, selected, disabled, onSelect, onQuestion }: {
  session: ExperienceSession; selected: string[]; disabled: boolean; onSelect: (id: string) => void;
  onQuestion: (q: Question, action: QuestionAction, content?: string) => Promise<boolean>
}) {
  const runs = session.mining_runs ?? []
  const latest = [...runs].reverse().find(r => r.state === 'completed')
  const questions = new Map(runs.flatMap(r => r.questions.map(q => [q.id, q] as const)))
  return <div className="chat-timeline" aria-label="经历对话">
    {session.turns.filter(turn => turn.role === 'user').map(turn => <div key={turn.id}><article className="message user-message">
      <div className="message-author">你的经历 <span>已保存</span></div><p>{turn.content}</p>
      {!!turn.answered_questions?.length && <div className="answer-trace">已关联 {turn.answered_questions.length} 个问题{turn.answered_questions.map(link => <details key={link.question_id}><summary>作答时问题版本 {link.question_version}</summary>{questions.get(link.question_id)?.state === 'deleted' ? <p>对应问题已删除，原回答仍保留。</p> : <p>{questions.get(link.question_id)?.content ?? '对应问题待重新读取'}{questions.get(link.question_id)?.version !== link.question_version && '（这是后续修订的问题，原回答关联未被改写。）'}</p>}</details>)}</div>}
    </article>{runs.filter(r => r.input_turn_id === turn.id && r.state === 'completed').map(r => <section className="message assistant-message" key={r.id}>
      <div className="message-author">Pathwise <span>合成测试 · 固定开放问题</span></div><p>已按你的原文整理候选。先回答你记得的部分，事实由你决定是否确认。</p>
      <details className="past-questions" open={r.id === latest?.id}><summary>{r.id === latest?.id ? '本轮合成追问' : '已保存的历史追问'} · {r.questions.length} 题</summary>{r.questions.map(q => <QuestionCard key={q.id} question={q} current={r.id === latest?.id && session.mining_status === 'active'} selected={selected.includes(q.id)} disabled={disabled} onSelect={() => onSelect(q.id)} onAction={(action, content) => onQuestion(q, action, content)} />)}</details>
    </section>)}</div>)}
  </div>
}

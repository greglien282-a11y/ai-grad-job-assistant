import { factV3Schema } from '../../lib/experience-read-contract'
import { parse as parseDeclaration } from '../../../../../research/declaration_read/web/contract'
import type { Envelope } from '../../../../../research/declaration_read/web/contract'
import { keywords } from './jd'
import type { Requirement } from './jd'
import type { z } from 'zod'

export type Fact = z.infer<typeof factV3Schema>
export type LabInput = { fact: unknown; declaration: unknown }
export type Evidence = { fact: Fact | null; declaration: Envelope | null; bucket: 'usable' | 'review' | 'excluded'; reason: string }
// This adapter accepts synthetic read candidates only. Never a database trust grant.
export function qualify(input: LabInput): Evidence {
  const parsed = factV3Schema.safeParse(input.fact)
  if (!parsed.success) return { fact: null, declaration: null, bucket: 'excluded', reason: '未知或损坏的事实合同，停止展示。' }
  const f = parsed.data, basis = parseDeclaration(input.declaration)
  const reject = (reason: string, bucket: Evidence['bucket'] = 'excluded'): Evidence => ({ fact: f, declaration: null, bucket, reason })
  if (f.status === 'rejected') return reject('已拒绝，不能重新作为贡献。')
  if (f.classification_contract === 'legacy-v0') return reject('legacy 未分类；不推断已完成。', 'review')
  if (f.classification_contract === 'unclassified-v1') return reject('尚未完成分类审核。', 'review')
  if (f.fact_kind !== 'personal_action' || f.progress_stage !== 'completed') return reject('计划、进行中、背景和限制不属于已完成个人贡献。')
  if (f.status === 'pending') return reject('待审核，不进入简历预览正文。', 'review')
  // Defensive refusal only, not a general classifier or proof of semantic independence.
  if (!/^我[^们]/.test(f.statement) || /计划|正在|如果|可能|没有|不确定|不知道|团队|我们|%|％|提升率/.test(f.statement)) return reject('原文含责任、进度或不确定性风险，需人工核对。', 'review')
  if (basis.status !== 'parsed_candidate' || !basis.view || basis.view.basis.status !== 'user_declaration_recorded') return reject('暂无可核对的分类声明依据。', 'review')
  const d = basis.view, s = d.subject
  if (s.fact_id !== f.id || s.session_id !== f.session_id || s.project_id !== f.project_id || s.fact_version !== f.version || s.statement !== f.statement || s.status !== f.status ||
    s.fact_kind !== f.fact_kind || s.progress_stage !== f.progress_stage || s.classification_contract !== f.classification_contract) return reject('分类声明与当前事实/版本不一致。')
  const citations = f.current_statement_citations
  if (!citations.length || new Set(citations.map(c => c.turn_id)).size !== f.current_statement_source_turn_ids.length ||
    citations.some(c => !f.current_statement_source_turn_ids.includes(c.turn_id) || c.fact_version > f.version || c.quote !== f.statement ||
      !d.text_provenance.current.citations.some(source => source.turn_id === c.turn_id && source.start === c.start && source.end === c.end && source.quote === c.quote)) ||
    d.text_provenance.current.citations.length !== citations.length ||
    new Set(d.text_provenance.original.turn_ids).size !== f.original_source_turn_ids.length || d.text_provenance.original.turn_ids.some(id => !f.original_source_turn_ids.includes(id))) return reject('当前文字或原始来源不完整，不使用。')
  return { fact: f, declaration: d, bucket: 'usable', reason: '合成已审核个人完成动作，原文及独立分类声明可核对；不代表平台独立认证。' }
}
export function deduplicate(inputs: LabInput[]): Evidence[] {
  const seen = new Set<string>(), statements = new Set<string>()
  return inputs.map(input => {
    const e = qualify(input), f = e.fact
    if (!f) return e
    if (seen.has(f.id) || statements.has(f.statement)) return { ...e, bucket: 'excluded', reason: '重复经历，只展示一次，不能重复计算。' }
    seen.add(f.id); statements.add(f.statement); return e
  })
}
export function matchRequirements(requirements: Requirement[], evidence: Evidence[]) {
  return requirements.map(requirement => {
    const terms = keywords(requirement.text)
    const relevant = evidence.filter(e => e.fact && terms.some(term => keywords(e.fact!.statement).includes(term)))
    const usable = relevant.filter(e => e.bucket === 'usable')
    return { requirement, usable, review: relevant.filter(e => e.bucket === 'review'), excluded: relevant.filter(e => e.bucket === 'excluded'),
      conclusion: requirement.priority === 'uncertain' || requirement.conflict ? '待人工判断；不作满足结论' : usable.length ? '存在字面相关合成经历；不代表完全满足岗位条件' : '缺少可展示证据；不等于已经证明没有能力' }
  })
}
export function reviewQuestions(facts: Fact[], requirements: Requirement[]) {
  if (!facts.length || !requirements.length) return []
  return ['请解释你实际做了什么，并划清个人职责与团队工作。', '请回忆如何检查结果；没有记录的数字请明确说不知道。', '面试追问边界：哪些相关技术尚未做过，下一步如何准备？'].map((prompt, i) => {
    const fact = facts[i % facts.length]
    const requirement = requirements.find(r => keywords(r.text).some(k => keywords(fact.statement).includes(k))) ?? requirements[0]
    return { id: i + 1, fact, requirement, prompt }
  })
}
export const printableText = (original: string, draft: string) => draft === original ? original : null

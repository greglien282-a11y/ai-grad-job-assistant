import { DECLARATION_CONTRACT, READ_CONTRACT, declarationText } from '../../../../../research/declaration_read/web/contract'
import type { Classification, Envelope } from '../../../../../research/declaration_read/web/contract'
import type { Fact, LabInput } from './policy'
const uuid = (n: number) => `00000000-0000-4000-8000-${n.toString().padStart(12, '0')}`
// Public synthetic fixtures only; no credentials, storage, HTTP or real data adapter.
export function sample(n: number, statement: string, kind: Classification['fact_kind'] = 'personal_action', progress: Classification['progress_stage'] = 'completed', status: Fact['status'] = 'user_confirmed', recorded = true): LabInput {
  const classification: Classification = { fact_kind: kind, progress_stage: progress, classification_contract: kind === 'legacy_unspecified' ? 'legacy-v0' : 'explicit-typed-v1' }
  const fid = uuid(n), tid = uuid(n + 100), did = uuid(n + 200), sid = uuid(900), pid = uuid(901)
  const citation = { turn_id: tid, start: 0, end: Array.from(statement).length, quote: statement }
  const choice = declarationText(classification)
  const basis: Envelope = { read_contract: READ_CONTRACT, synthetic: true,
    subject: { ...classification, fact_id: fid, session_id: sid, project_id: pid, fact_version: 1, statement, status },
    turns: [{ id: tid, session_id: sid, role: 'user', content: statement }],
    text_provenance: { original: { availability: 'exact_quotes', turn_ids: [tid], citations: [citation] }, current: { availability: 'exact_quotes', turn_ids: [tid], citations: [citation] } },
    basis: { status: kind === 'legacy_unspecified' ? 'legacy_unclassified' : 'not_recorded', declaration: null } }
  if (recorded && kind !== 'legacy_unspecified') {
    basis.turns.push({ id: did, session_id: sid, role: 'user', content: choice })
    basis.basis = { status: 'user_declaration_recorded', declaration: { declaration_contract: DECLARATION_CONTRACT, declaration_id: uuid(n + 300), record_type: 'explicit_user_choice', actor: 'user', fact_id: fid, fact_version: 1, session_id: sid, project_id: pid, classification,
      statement_citations: [citation], declaration_source: { turn_id: did, start: 0, end: Array.from(choice).length, quote: choice },
      recorded_at: '2026-10-26T00:00:00Z', recorded_validation: { contract: 'typed-semantic-spike-v1', status: 'eligible_candidate', code: 'finite_rule_match' } } }
  }
  const fact: Fact = { ...classification, fact_contract_version: 3, provenance_version: 3, id: fid, session_id: sid, project_id: pid, statement, version: 1, status,
    created_at: '2026-10-26T00:00:00Z', updated_at: '2026-10-26T00:00:00Z', origin: 'manual', memory_state: 'unspecified', ai_run_id: null, evidence_id: status === 'evidence_supported' ? uuid(n + 400) : null,
    original_source_turn_ids: [tid], current_statement_source_turn_ids: [tid], current_statement_citations: [{ ...citation, change_id: uuid(n + 500), fact_version: 1, source_kind: 'original_source' }],
    classification_citations: [], classification_basis_status: kind === 'legacy_unspecified' ? 'legacy_unclassified' : 'not_recorded', source_kind: 'conversation_turns', source_change_id: null }
  return { fact, declaration: basis }
}
export const exampleJD = '软件测试实习生\n必须具备测试经验；掌握脚本编写。\n本科及以上，计算机相关专业。\n有服务部署经历优先。\nPython 为加分项；有一年实习经验优先。\n善于协作。'
export const samples: LabInput[] = [
  sample(1, '我测试了3个导出按钮。'), sample(2, '我编写了清洗脚本。', 'personal_action', 'completed', 'evidence_supported'),
  sample(3, '我部署了服务。', 'personal_action', 'completed', 'pending'), sample(4, '我计划部署服务。', 'plan', 'planned'),
  sample(5, '我正在测试导出按钮。', 'personal_action', 'in_progress'), sample(6, '团队部署了服务。', 'background', 'not_applicable'),
  sample(7, '我不知道。', 'boundary', 'not_applicable'), sample(8, '我验证了3个导出按钮。', 'personal_action', 'completed', 'rejected'),
  sample(9, '我编写了脚本。', 'legacy_unspecified', 'legacy_unknown'), sample(10, '我部署了推荐服务。', 'personal_action', 'completed', 'user_confirmed', false),
]

import { parseBatch } from '../../../g3_choice_protocol/web/contract'
export const blocks = ['STRICT_COMMIT_DEADLINE_BLOCK','R03_NOT_PROVEN','SHARED_LEGACY_CO_DOMAIN_BLOCK','PRODUCTION_ADMISSION_BLOCK'] as const
export type SourceReceipt = { receipt_contract: 'g4-source-audit-read-ref-v1'; operation_id: string; origin_nonce: string; source_body_sha256: string; selection_ids: string[]; expires_epoch: number; ingress_binding: 'exact_candidate_request'; retention_policy: 'DISPOSABLE_ONLY_UNAPPROVED'; semantic_independence: 'NOT_PROVEN' }
const id = (v: unknown) => typeof v === 'string' && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v)
const exact = (v: unknown, keys: string[]): v is Record<string,unknown> => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).sort().join('|') === [...keys].sort().join('|')
export function decodeSource(value: unknown) {
  if (!exact(value,['demo_contract','scope','operation_id','result','truth_verified','persistence_authorized','facts','source_receipt','blocks']) || value.demo_contract !== 'g4-source-bound-disposable-read-v1' || value.scope !== 'DISPOSABLE_RESEARCH_DATABASE' || value.result !== 'committed_pending_review' || value.truth_verified !== false || value.persistence_authorized !== false || !id(value.operation_id) || JSON.stringify(value.blocks) !== JSON.stringify(blocks)) throw Error('unsafe_contract')
  const parsed = parseBatch(value.facts)
  if (parsed.status !== 'parsed_candidate' || !parsed.view || parsed.view.some(f => f.subject.status !== 'pending' || f.subject.fact_version !== 1 || f.subject.classification_contract !== 'explicit-typed-v1' || f.basis.status !== 'event_recorded' || !f.basis.event || f.basis.event.operation_id !== value.operation_id)) throw Error('unsafe_contract')
  const r = value.source_receipt
  if (!exact(r,['receipt_contract','operation_id','origin_nonce','source_body_sha256','selection_ids','expires_epoch','ingress_binding','retention_policy','semantic_independence']) || r.receipt_contract !== 'g4-source-audit-read-ref-v1' || r.operation_id !== value.operation_id || !id(r.origin_nonce) || typeof r.source_body_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(r.source_body_sha256) || !Array.isArray(r.selection_ids) || r.selection_ids.length !== parsed.view.length || r.selection_ids.some((s,i) => !id(s) || s !== parsed.view![i].basis.event?.selection.id) || !Number.isSafeInteger(r.expires_epoch) || Number(r.expires_epoch) <= 0 || r.ingress_binding !== 'exact_candidate_request' || r.retention_policy !== 'DISPOSABLE_ONLY_UNAPPROVED' || r.semantic_independence !== 'NOT_PROVEN') throw Error('unsafe_source_audit')
  // A committed historical receipt can be read after its signing TTL. This
  // parser never re-authorizes a new write or calls a signer during recovery.
  return { views: parsed.view, receipt: r as SourceReceipt }
}

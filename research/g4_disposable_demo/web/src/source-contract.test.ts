import { expect, it } from 'vitest'
import corpus from '../../../g3_choice_protocol/read_cases.json'
import { blocks, decodeSource } from './source-contract'

function valid() {
  const fact=structuredClone(corpus.base)
  // The shared standalone fixture contains an intentionally unquoted prefix.
  // A source-bound batch must cover the whole Turn; make this synthetic input
  // complete rather than weakening parseBatch's source-completeness contract.
  fact.turns[0].content=fact.subject.statement
  for(const c of [...fact.text_provenance.original,...fact.text_provenance.current,...fact.basis.event!.statement_citations]) { c.start=0; c.end=Array.from(fact.subject.statement).length }
  return {demo_contract:'g4-source-bound-disposable-read-v1',scope:'DISPOSABLE_RESEARCH_DATABASE',operation_id:fact.basis.event!.operation_id,result:'committed_pending_review',truth_verified:false,persistence_authorized:false,facts:[fact],blocks:[...blocks],source_receipt:{receipt_contract:'g4-source-audit-read-ref-v1',operation_id:fact.basis.event!.operation_id,origin_nonce:'00000000-0000-4000-8000-000000000999',source_body_sha256:'a'.repeat(64),selection_ids:[fact.basis.event!.selection.id],expires_epoch:1,ingress_binding:'exact_candidate_request',retention_policy:'DISPOSABLE_ONLY_UNAPPROVED',semantic_independence:'NOT_PROVEN'}}
}
it('strictly reads pending source-bound historical receipt even after signing TTL without reauthorizing',()=>{
  const result=decodeSource(valid()); expect(result.views).toHaveLength(1); expect(result.receipt.semantic_independence).toBe('NOT_PROVEN')
})
it.each(['demo_contract','scope','operation_id','truth_verified','persistence_authorized','blocks'])('refuses changed outer contract %s without legacy fallback',field=>{
  const data:Record<string,unknown>=valid(); data[field]=field==='truth_verified'||field==='persistence_authorized'?true:'unknown'; expect(()=>decodeSource(data)).toThrow()
})
it.each(['receipt_contract','operation_id','origin_nonce','source_body_sha256','selection_ids','expires_epoch','ingress_binding','retention_policy','semantic_independence'])('refuses unknown or mismatched source receipt %s',field=>{
  const data=valid(); (data.source_receipt as Record<string,unknown>)[field]=field==='expires_epoch'?false:'unknown'; expect(()=>decodeSource(data)).toThrow()
})
it('does not accept a missing unsigned sidecar or an extra success flag',()=>{
  const data:Record<string,unknown>=valid(); delete data.source_receipt; expect(()=>decodeSource(data)).toThrow()
  expect(()=>decodeSource({...valid(),history_safe:true})).toThrow()
})

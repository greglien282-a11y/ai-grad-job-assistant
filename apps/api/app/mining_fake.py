"""Opt-in synthetic v2 fixture provider; never selected by production configuration.

Exercises the contract, not real model quality. Deliberately small deterministic
Chinese/English patterns: no network, keys, pricing, or adaptive AI claims.
"""
from app.mining_provider import AtomicCandidate, AtomicCitation, MiningOutputV2, ScriptedProvider, SuggestedQuestion
from app.mining_validation import PRIVATE, atomic, sentence_spans
from app.mining_context import question_fingerprint


class ContextFakeProvider(ScriptedProvider):
    output_contract_version = 2
    async def mine(self, context):
        snapshot = context.context
        if snapshot is None: raise ValueError('Missing bounded context')
        current = next(t for t in snapshot.user_turns if t.turn_id == context.turn_id)
        candidates = [AtomicCandidate(citation=AtomicCitation(turn_id=current.turn_id, quote=text, start=start, end=end))
            for start, end, text in sentence_spans(current.content) if atomic(text) and not PRIVATE.search(text) and '█' not in text][:5]
        previous = {q.dedup_fingerprint for q in snapshot.questions if q.dedup_fingerprint}
        options = [('contribution', '这段经历里你本人实际完成了哪一步？'),
                   ('detail', '你还记得这一步采用的技术或操作吗？不记得可以跳过。'),
                   ('verification', '有没有可以自行核对这段经历的材料？没有也可以结束。')]
        if '记不清' in current.content or '忘记' in current.content:
            options = [('uncertainty', '是否先保留记不清的部分并结束追问？')]
        questions = [SuggestedQuestion(text=text, purpose=purpose, source_turn_ids=[current.turn_id])
                     for purpose, text in options if question_fingerprint(text) not in previous][:2]
        stop = not questions or snapshot.stop.round_count >= snapshot.stop.maximum_rounds or any(q.state == 'deleted' for q in snapshot.questions)
        return MiningOutputV2(candidates=candidates, questions=[] if stop else questions,
            stop=stop, stop_reason='no_new_information' if stop else None)

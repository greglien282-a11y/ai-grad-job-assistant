# Typed Writer Contract Candidate — M1

Evidence class: **NOT_IMPLEMENTED / candidate specification**. No route, migration, writer, role or policy is enabled by this document. Baseline main: `17a35e9cf23d4d9f11b757a426793e575f861223`. c3b [Draft PR #44](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/44), HEAD `2020eaa9d3e2852671519f08894870cead7f3108`, is a reviewed-input dependency, not merged code in this branch.

## 1. Candidate is not admission

c3a only checks explicit declarations against exact, finite sentence templates. c3b additionally binds quotes to an authenticated saved user Turn on a repeatable read snapshot and reports precise history risk. Both always deny truth verification and persistence authorization. A future writer must repeat identity, version, source, integrity and history checks in its own transaction; a prior result is not a capability, lease, receipt or exemption.

Every DTO, code, route, state transition and schema addition below is a **candidate requiring review**. In particular CO3 is not a third spelling of CO2. No semantic independence oracle currently exists; clean exact comparisons alone cannot authorize reassertion. The reference model may simulate this restrictive candidate policy, never claim database enforcement.

## 2. One proposed command, no generic negotiation

Candidate route: `POST /api/v3/experience/sessions/{sid}/conversation-appends`. Fixed `contract_version=3`, `decision_contract=append-typed-candidate-v1`. The final name and version are REQUIRES_USER_APPROVAL; the earlier design's append-typed-v1 is a proposal, not a registered protocol. No Accept/query fallback or reuse of old DTOs.

Candidate request fields, all extra fields forbidden:

- contract_version (strict integer 3), decision_contract (fixed literal).
- base_revision (strict positive integer), project_id (UUID bound to Session).
- input.content (exact original user text, 1–10000 code points).
- items (1–5): fact_kind, progress_stage, classification_contract, quote, start, end. quote is one complete original sentence, 1–500 code points. Ordered nonoverlapping half-open CP intervals cover all non-ASCII-whitespace text. No rewriting, normalization or numeric substitution.

No Fact/status/evidence/actor/origin/run IDs supplied by the caller; no force, history_safe, related_plan, classify or automatic downgrade. Semantic contract version is server-pinned, not chosen by a client seeking a weaker validator. Production candidate approval must explicitly decide whether the c3a vocabulary/coverage is sufficient; this document does not expand it.

### Fresh Turn and saved-source separation

The candidate append creates a **fresh user Turn and all effects in the same transaction**, preserving input.content exactly. Validation can run before INSERT against that exact immutable command value; the newly saved Turn is checked again before commit. Rejected commands roll back the Turn too, leaving no fake clarification receipt.

c3b intentionally reads a *previously saved* Turn. That research interface does not authorize adopting, moving or consuming old Turns in append; 0013/0014 source/xmin rules and the all-new invariant remain relevant. Any future extraction-from-saved-Turn command needs a distinct reviewed DTO, consumed-source audit, version/idempotency rules and source immutability proof. It is REQUIRES_USER_APPROVAL, outside this candidate append.

An eventual schema must prevent ordinary UPDATE/DELETE of source content, source relocation, quote drift and history rewrites, while preserving approved whole-session deletion. Source immutability must be proven with real restricted SQL, concurrent writers and deferred checks; declaring a field immutable in a DTO is insufficient.

## 3. Classification, progress and trust are independent

Use the existing 0015 matrix, without inferring legacy text:

- personal_action → in_progress or completed; explicit-typed-v1.
- plan → planned or in_progress; explicit-typed-v1.
- background / boundary → not_applicable; explicit-typed-v1.
- legacy_unspecified / legacy_unknown → legacy-v0 or unclassified-v1 remains historical compatibility, not a new typed append option.

All newly created candidate Facts are pending, version 1, origin manual, ai_run_id NULL, memory_state unspecified and evidence_id NULL. A completed declaration is not user confirmation or evidence_supported; in_progress is not a trust level. A user's confirmation is not platform independent certification. No classifier infers any axis from memory_state.

Plans and later completed actions have separate complete sources and separate Facts; the later one does not inherit the prior plan's confirmation, materials, destination or metrics. No related_plan/FactProgressLink is provided. Background, boundary, plan and in_progress never become completed personal contributions merely because reviewed. Existing legacy-v0 summary compatibility still may contain plans: stopping that globally needs another approved policy.

## 4. Classification basis is a blocking design gap

Current read_contract.FactV3 deliberately has classification_citations with max_length=0 and basis_status only legacy_unclassified/not_recorded. Existing FCS source_role and action constraints also do not implement a classification declaration audit. A writer cannot silently fill that field, reuse building provenance as independent classification evidence, or label a finite rule match as verification.

Two candidate choices need separate approval:

1. Preserve not_recorded for synthetic typed data, **keep formal typed writer closed**. This is the current safe boundary.
2. Add a versioned, immutable declaration/basis record linking the explicit user's kind/stage declaration, validator contract, exact full quote/CP range, newly created Turn, Fact version, FC and CO3. New source role/table/constraints and read projection semantics require a forward migration candidate plus read/UI review. Source proves what was declared, not truth or independent certification.

Recommended next design: choice 2 reviewed together with a new basis-aware source contract. Never reinterpret original_source/current_statement citations as later classification proof. Missing basis does not get an invented citation or a default verified status. Production implementation remains REQUIRES_USER_APPROVAL.

## 5. Atomic graph and database proof obligations

For N items, exactly one fresh user Turn, N distinct new pending/v1 Facts, N created/system FCs with before NULL, N original FS anchors and N statement FCS slots, and one CO3 receipt. The classification-basis edge, if approved, must be accounted for separately and cannot defeat the N-item bijection by double-counting FCS rows. No no_new_fact, partial success, item omission, inherited source or silent deduplication.

Each initial snapshot must match statement, status, version, origin, memory_state, ai_run_id, evidence_id, classification triple and exact source metadata with JSON types intact. Historical snapshots never rewritten or backfilled. The unique created snapshot has version 1/pending and before NULL; all same-version snapshots must agree. Any missing/extra/moved source or slot aborts the entire transaction.

Candidate forward migration (number only after topology review) would need CO3 identity/decision constraints, version-specific deferred graph/basis checks, source immutability, safe definer ownership/ACL and nonempty dangerous-downgrade protection. **No migration file is authorized tonight; 0001–0015 remain untouched.** A PostgreSQL proof cannot be inferred from an in-memory atomic swap.

## 6. Authentication, key and transaction ordering

Candidate new-command sequence:

1. Strict envelope and Bearer-bound key proof, no unauthenticated typed/history detail.
2. Key advisory lock; locate receipt in the same collision domain as old CO contracts. Existing legitimate replay is considered before new-command history/typed cutoff gates. Preserve the reviewed old v1/v2 availability/auth ordering; do not rewrite old paths for cosmetic consistency.
3. Authenticate Session/Project ownership, bind receipt ownership if present, then explicit route/contract matching and canonical payload equality. An existing other-contract key is a conflict, never an invitation to create a new operation.
4. For a new command only, lock Session, enforce state and unresolved-run gates, validate base_revision, complete current/history/source/basis integrity and reviewed policy. Later Fact/relationship locks only if separately approved; no funding lock or provider.
5. Validate every item and history risk; stage the exact graph; recheck graph, key expiry and versions at commit. One top-level transaction. All-new or rollback, never SAVEPOINT partial success.

Candidate status mapping (all NOT_IMPLEMENTED for CO3): 401 invalid credential/proof; 404 unavailable foreign resource; 409 context_conflict/contract_mismatch/payload_mismatch/exact reuse or history_requires_review; 410 expired/deleted receipt; 422 unsupported structure/classification/quote; 503 schema/ACL/integrity/runtime unavailable. Reject responses have no operation_id and do not pretend an unsaved clarification is a persisted receipt.

Key kind/scope/proof/canonical body must preserve cross-contract collision detection with CO1/CO2. Prefer retaining the existing maintenance key domain and explicit version/decision in body/HMAC, subject to security review. Do not choose a new namespace that makes the same logical key fresh on another route. Do not re-sign, extend expiry, purge or change old receipts.

## 7. Replay, recovery and historical typed gates

- First success and receipt commit are atomic. Same authenticated key + same canonical body returns the immutable effect graph without repeating any write; later context/rejected/typed changes do not cause replay to execute afresh.
- Same key + other body conflicts; other key + already-used exact text/source rejects as a new command. Neither rule proves semantic independence.
- Route versions remain explicit in both directions. v1 cannot read CO3; v2 cannot read CO3; CO3 cannot misproject CO1/CO2, including valid historical v1 append prototypes and resolution receipts.
- Candidate GET-only recovery uses one REPEATABLE READ READ ONLY connection, original key/expiry/auth checks, complete validated immutable snapshots and current-version information explicitly separated. No lock, cleanup, key registration, provider, resend, repair or receipt mutation.
- Current or historical typed data continues to block fresh old fact commands under existing require_legacy semantics. This is distinct from legal old receipt replay, Session end/delete and worker finalization. New CO3 cannot retrofit a typed label into old snapshots or use changed current labels to erase typed history.
- Fact.version remains per-fact history sequence; context_revision is the aggregate concurrency barrier. Neither is reset, inferred from classification nor substituted for operation contract version.

## 8. R03 and clarification policy

Mandatory exact checks cover current/history statements and original/current/history source identity. Numeric spellings, synonyms and a new Turn are never proof of a new contribution. Under the minimal conservative candidate, any current/ever rejected Fact makes a **new** append requires_review, even when the language rule matches and the new contribution appears unrelated. It produces zero effects and no persisted clarification.

This over-blocks legitimate unrelated work; M2 must quantify the synthetic cost. It is not a final semantic solution or permission to tighten all existing writers. A future human decision protocol must identify disputed claims, preserve the full evidence and rejected history, define explicit user responsibility and atomic/idem semantics; a checkbox saying “new fact” is not proof. No such write protocol is implemented tonight.

Even without a rejected record, exact non-reuse is INDEPENDENCE_NOT_PROVEN. The finite model can demonstrate a declared restrictive policy, not prove general semantics. R03 across manual, mining and append remains a production BLOCK.

## 9. Crash, concurrency, deletion and worker boundaries

- Before commit crash: durable graph/receipt absent; all staged pieces rolled back. After commit/response loss: GET recovers original graph; never re-execute based on a network failure or missing local response.
- Two connections same key: serialize and one graph; same key/other body conflicts. Different keys competing on one revision: at most one commit; retry requires explicit fresh review, not automatic key replacement.
- Deleted/unreadable source and broken current/history classification/unknown schema/ACL must fail closed. No partial backup/receipt projection or fallback legacy interpretation of explicit typed corruption.
- Whole-session deletion remains its own approved existing capability. Candidate CO3 tombstones must retain the minimum original digest/version/state/expiry needed to prevent replay, without retaining sensitive content; never delete audit alone. Foreign callers must not learn typed/deleted state. Expiry is not permission to erase live audit.
- In-flight worker complete/stale/fail/unknown and ledger effects are distinct from new Fact creation. Existing semantics remain unchanged. A typed cutoff cannot freeze necessary finalization or turn an uncertain run into success. Claim/context/complete races need actual restricted PG/process tests before enabling any writer.

## 10. Policy A and approval register

Policy A is a design assumption only: pure legacy sessions remain under existing contract; current/history typed blocks fresh old Fact commands; future typed sessions need explicit born-contract/create protocol **after** full writer/read/UI/recovery review. Old receipt replay, end/delete and worker drain remain separate capabilities. Legacy creation/append/mining can still create legacy-v0; no global “plans can never appear in confirmed text” claim is valid.

REQUIRES_USER_APPROVAL:

- D4 finite language/type/stage coverage, personal responsibility and plan semantics; relationship is deferred.
- D5 classification basis/declaration protocol, classify and typed edit/downgrade semantics; none enabled.
- D6 basis-aware read/source/UI and complete old/new writer/recovery compatibility; existing typed read-only success is insufficient.
- R03 independence/clarification policy and acceptable unrelated-contribution blocking; no generic semantic oracle assumed.
- Session born-contract/create version, policy A/B, grandfather/cutoff, rollout date/cohort and rollback policy.
- Candidate CO3 route/DTO/key domain/expiry/tombstone behavior and forward DB constraints.
- D8 production LOGIN/owner/ACL, runtime wiring, real provider/budget and deployment, all closed.

M1 completion means these candidate boundaries and proof obligations are specified, **not** that any decision has been approved or implemented.

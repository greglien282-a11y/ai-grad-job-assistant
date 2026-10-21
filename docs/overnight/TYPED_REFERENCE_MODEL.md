# Typed Reference Model — M4

Evidence class: **SIMULATED**, test-only immutable Python values. This is not an HTTP API, PostgreSQL writer, cryptographic proof, transaction manager or production policy. Source/schema/read/API choices in [M1 #45](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45) remain candidates requiring approval.

BASE_BRANCH=`codex/overnight-r03-research`; BASE_SHA=`fc9286e8f1b8e0e62f6d59d2821584391d03fd88`; DEPENDS_ON_PR=[#46](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46). This PR includes M3 and M4 increments, and actually imports M2's test-only r03 evaluator. It has no code dependency on unmerged c3b #44. It is not independent main verification; full integrated results include #46's parent.

## Executable scope

Files: `apps/api/tests/overnight_research/typed_model.py` and `apps/api/tests/test_overnight_typed_model.py`.

The model creates Python dataclasses only: State, SimSession, SimTurn, SimFact, SimChange, SimSource, SimAudit, SimBasis and SimReceipt. Everything is frozen/tuple-based. No app file imports the package. There is no DB/network/provider/filesystem/clock/secret/role/factory access, no route or background job, and no production table/migration. Importing existing strict Classification and unchanged c3a validator reuses structure/language rules without expanding vocabulary or copying a classifier.

Every Outcome has evidence_class=SIMULATED, source_binding=SIMULATED_ONLY, semantic_independence=NOT_PROVEN, transaction_review_required=true, truth_verified=false and persistence_authorized=false. simulated_applied means **a new mathematical State value**, not a saved Fact, FactV3, accepted operation or real receipt. Unknown general semantics remain unproven even if a finite model transition succeeds.

## Transition and graph

`submit(state, command, principal, now=..., fault=...)` returns a new State only after complete validation; refusals return the exact original State object. A fresh simulated user Turn preserves content byte-for-code-point; each 1–5 item gets an independent pending/v1/no-evidence/manual/no-run Fact, created/system/before-NULL Change, original Source, audit slot, declaration-only Basis and a shared simulated receipt. All items or none, no silent deduplication/partial result/rewrite/confirmation.

The model **does not adopt saved Turns**. Existing c3b advisory source checks do not authorize such an append. Full quote coverage/order/CP boundaries and finite language are delegated to c3a. Type/progress/trust stay independent; plan/background/boundary/in_progress can be represented as pending candidate values and never receive automatic confirmed or material-supported status.

SimBasis explores M1's proposed future declaration edge. It binds the explicit classification triple, validator version, exact source, operation/slot and initial Change. It is labeled SIMULATED_DECLARATION_ONLY, not classification verification or a real classification_citations object. The actual FactV3 contract cannot yet express such recorded basis; no production serialization/migration is provided. Approval and real database/source/read enforcement remain necessary.

Graph checks include exact N bijection, unique created history/version sequence, current snapshot equality, before/after continuity, immutable trust/origin metadata, exact original source ranges, audit/basis equality, fixed versions and receipt ownership. No extra Turn or orphan fact/source/audit/basis is accepted. Status-only review states are **arranged fixtures**, not a new review/classify command.

The reference is intentionally narrower than real historical contracts: one Change per version, no historical edited text/classify/material writer, no assistant Turns and no real evidence-supported graph. It does not declare those valid old behaviors illegal. Old CO1/CO2 rows are explicitly **opaque synthetic receipt fixtures** used only to model version/collision separation, not a second old receipt projector.

## Keys, replay, recovery and lifecycle

Toy principal/key symbols are not Bearer authentication or HMAC. Digests are deterministic identity handles for this model only; no real keys/credentials are accepted or created. Synthetic `now` is an integer counter, not server clock/expiry proof. Aggregate revision advances one abstract epoch per batch; that is not a prediction of real database trigger increments.

- Authenticate the model principal before state/history detail; match the receipt's scope/principal and explicit contract. Preserve one shared key collision domain across opaque CO1/CO2 and candidate CO3.
- Exact same key/body replays the original IDs/revision with no new State, even after later review/rejected/context/ended state. Different body includes classification/quote/source offsets/revision/project and conflicts. Issue metadata cannot renew old expiry.
- Different key + exact existing claim refuses. Finite M2 suspected families require review; current/ever rejected history conservatively refuses even unrelated work. These hints do not solve general semantic identity, and clean matches still have no persistence authority.
- `recover` is a pure GET-like model projection. It never calls submit, registers a key, cleans expiry or mutates State. Version mismatches cannot be re-executed through a different contract.
- Ended Session, unresolved reserved/running/unknown worker, mismatched revision/project and legacy-mode creation assumptions reject new candidate commands. Mode is a model assumption, not an actual Session born-contract field or approved creation policy.
- `legacy_capability` distinguishes fresh fact commands from recovery/end/delete/worker_finalize, returning separate-existing-capability-not-implemented for the latter. It does not implement or disable any existing behavior.
- `delete_session` is a pure **simulation**: clear local graph and sensitive receipt fields, retain minimal hashed scope/principal/key/version/expiry tombstone, preserve other sessions. Actual DELETE rules/permissions are unchanged; toy identity hashes are not a production privacy/security design.

## Failure injection and concurrency limits

Eight explicit model points: before Turn, after Turn/Fact/Change/Source/Receipt, before commit and after commit. Before the abstract boundary, SimulatedCrash exposes only the original State; after it, the complete new State can be recovered and replayed. This is a Python exception, **not** a real killed process, durable log or PostgreSQL rollback proof.

Both serial orders of same-key/same-body, same-key/different-body and different-key/same-revision commands are enumerated. At most one graph appears and the second result is replay/payload-conflict/context-conflict. Enumerating serial schedules is **not** testing real lock acquisition, write skew, isolation, process concurrency or commit acknowledgement. Existing CO1/CO2 real process tests and M3 real read concurrency stay separate evidence classes.

The model contains no dynamic SELECT/ACL/schema flags or history_safe escape parameter to manufacture trust. Actual PostgreSQL/role/source integrity is tested by M3 on existing readers; future writer constraints still need their own reviewed migration and real limited SQL/process tests.

## Executed tests and discovered bug

`python -m pytest -q -ra tests/test_overnight_typed_model.py`: **100 passed**, 0.29s locally, no database required. Tests cover graph size 1–5, type/stage/trust separation, all fault boundaries, every payload field, version isolation, serial orders, review/rejected history, source/language rejection, corruption, tombstone privacy, expiry, capability distinctions and import isolation.

Actual initial model defect: Python/dataclass equality aliases current Snapshot.version=True with 1. A red test reproduced acceptance in that case (1 failed, 86 passed), so the model was corrected with strict integer checks and type-preserving canonical comparisons across snapshots/sources. Additional bool slot/source, missing tag/digest, unknown worker state and tombstone corruption regressions were added; no production constraint or old test changed.

An additional audit counterexample deliberately passes both finite rules and misses the family hint: “我部署了服务。” then “我部署了推荐服务。” with no rejected history. The model can produce two candidate values but cannot determine if they describe the same service. Every result explicitly retains NOT_PROVEN / transaction_review_required / no persistence authority. This is evidence of the remaining semantic limit, not a positive independence result or a reason to enable a writer.

The model reuses existing Classification/c3a functions by identity; tests check all 75 kind/stage/contract combinations against the existing finite matrix. This does not replace the real database CHECK tests in the full suite. No modified frozen expectations, skip/xfail, retries, sleeps or timeout increases.

## Still NOT_IMPLEMENTED / REQUIRES_USER_APPROVAL

Real typed writer/CO3, fresh/saved Turn ingestion protocol, semantic independence/clarification, actual auth/HMAC/expiry, production basis/source contract, locks/constraints/atomicity/crash recovery, born-contract/cutoff, material/classify/edit/related_plan and production wiring. D4/D5/D6 remaining/D8, R03 and provider/paid/deployment gates stay BLOCK.

M4 completion is an executable reference for candidate invariants and counterexamples. It cannot be promoted to a factory, imported by app, or cited as a database guarantee without new approval and implementation.

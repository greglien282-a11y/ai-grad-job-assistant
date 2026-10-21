# Typed Failure Model — M3

This is a **NOT_IMPLEMENTED CO3 specification**, plus **EXECUTABLE_ISOLATED_TEST** observations of existing read-only contracts. No future typed writer guarantee is inferred from CO1/CO2 success or an in-memory model.

BASE_BRANCH=`codex/overnight-r03-research`; BASE_SHA=`fc9286e8f1b8e0e62f6d59d2821584391d03fd88`; DEPENDS_ON_PR=[#46](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46). This stacked branch intentionally includes #46's test-only research package; incremental PR diff excludes it. M1 design is [#45](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45). c3b #44 is context only and is not in this branch.

## Failure requirements and actual evidence boundaries

1. **First success / same-key replay.** Future CO3 must commit one exact graph/receipt, then replay without new effects or renewed expiry. Existing CO2 evidence: test_append_api::test_A01_bijection_and_get_only_recovery; typed implementation NOT_IMPLEMENTED. M4 may simulate the invariant.
2. **Lost response.** Future GET-only recovery returns the original committed graph; absence/transport failure never authorizes automatic POST/key replacement. Existing real process evidence: test_append_api::test_A08_real_process_crash_new_process_get_only and test_maintenance_api::test_real_process_exit_and_new_process_get_only_recovery. These exercise CO2/CO1, not CO3.
3. **Same key / other payload.** Future conflict has no extra graph. Existing c2e test_co_receipts_survive_typed_and_cross_contract_keys_do_not_execute covers literal payload/route collisions; future canonical typed declarations must include kind/stage/basis/version in the tag.
4. **Different keys / duplicate text or source.** Future all-new command must reject exact reuse; semantic reformulation remains unproven. M2 real observations show different legacy entries have different protections. No universal semantic duplicate guarantee exists.
5. **CO1/CO2/CO3 isolation.** Existing CO1/CO2 conflict/recovery tests remain actual; CO3 is NOT_IMPLEMENTED. A toy model can demonstrate a shared key domain, never register a real CO3 identity or silently adopt old receipts.
6. **Wrong bearer / Session / Project / Fact.** Authenticate before typed/history disclosure; preserve original receipt proof/expiry ordering. New M3 real reads test foreign bearer on all corrupted-session paths. No prototype bearer is a substitute for server identity.
7. **Revision changes.** Future writer rechecks in its transaction, under reviewed locks. New real two-connection M3 test proves old read snapshot is internally consistent while a later read sees changed revision/rejection; it deliberately does not treat old results as admission.
8. **Crash before commit.** Future durable graph/receipt absent; retries require original proof and explicit user action. Existing real process tests remain CO1/CO2 evidence. M4 exception/fault injection is SIMULATED, not a PostgreSQL crash.
9. **Commit then response loss.** Future receipt survives and GET causes zero writes. Typed durable commit boundary is NOT_IMPLEMENTED; model can keep a committed state before raising a simulated loss signal.
10. **Deleted/unreadable Turn.** Reader cannot DELETE a source Turn (real SQL 42501). Removed FS, corrupt range and revoked source/Turn SELECT fail closed in all three read projections. Actual whole-session deletion uses existing approved capability, not a partial Turn-delete permission.
11. **Current/history classification mismatch.** New M3 fault tests wash current typed labels to legacy or corrupt snapshot version: all Fact/summary/export reads reject, including a request for a good legacy sibling. No partial projection or silent legacy fallback.
12. **Unknown Schema / permission / missing created history.** New M3 real tests reject marker99, missing SELECT and removed created rows; all-table digests unchanged. Owner arranges faults outside requests and restores triggers before actual reader calls. No admission bypass is added.
13. **DELETE / tombstones.** Existing c2e::test_whole_session_delete_is_authenticated_privileged_existing_exception proves current authenticated ACL boundary, graph deletion and old receipt tombstones. Candidate CO3 tombstone and privacy constraints require forward schema review; NOT_IMPLEMENTED.
14. **Worker finalization.** Existing c2e::test_worker_finalization_has_distinct_existing_effects proves fail/stale/unknown/empty complete can have legitimate effects while candidate Fact completion is separately rejected. No new writer cutoff may freeze drain or erase ledger uncertainty. No worker behavior modified.
15. **Legacy/typed birth isolation.** Existing require_legacy gates current/history typed for fresh old Fact commands, but legal receipts/delete/end/drain are distinct. Born-contract/create version/cutoff policy is NOT_IMPLEMENTED and REQUIRES_USER_APPROVAL.
16. **Classification basis.** Existing FactV3 must keep [] / not_recorded for synthetic typed fixtures; new M3 positive read tests prove no forged basis. A formal recorded declaration/basis edge, writer constraints and read protocol remain NOT_IMPLEMENTED.
17. **Owner / ACL / runtime closure.** Existing read_permissions admission and new restricted runtime DELETE failure prove SELECT-only boundaries. Default get_read_factory still raises experience_read_disabled. Production roles/factories/ACL remain closed; no test identity is a production entitlement.

## Explicit future verification matrix

Before any CO3 enablement, repeat all requirements with actual restricted PostgreSQL LOGINs, DB-enforced graph/basis constraints, two independent processes/connections, before/after commit process exit, same/different key races, old migration upgrade/history, nonempty downgrade, expiry/tombstone, in-flight worker and authenticated old/new client recovery. An executable model is not a replacement for that matrix.

M4 state-machine assertions will be labeled SIMULATED. Existing API/DB tests are OBSERVED_EXISTING_BEHAVIOR, and new read-only faults are EXECUTABLE_ISOLATED_TEST. None is a production policy approval or semantic/truth assessment.

## New M3 test scope

`apps/api/tests/test_overnight_failures.py`: eight faults × fact/summary/export; three honest basis/zero-effect reads; real SELECT-only source-delete rejection; default factory/import isolation; actual repeatable-read interleaving. All failed reads compare every business table, including revisions, history, receipts, Run and fee ledgers. The one deliberate external writer commit is explicitly excluded from a false zero-change claim; subsequent reads are zero-effect.

Executed: `python -m pytest -q -ra tests/test_overnight_failures.py` => **30 passed**, 18.05s locally; existing Starlette/httpx warning only. Initial 3 failures came from a new test's assumed generic schema error prefix. The final assertions match each fault's exact existing code, including fact_classification_schema_unavailable; production behavior and old tests were unchanged, and the assertion is more precise than the initial allowed-code set.

No migration, source rewrite, writer, DELETE capability, worker logic, production ACL, frozen language or provider change. Test fault injection is owner-only synthetic arrangement and never used as normal reader identity. Full commands/counts/CI are appended to the master handoff and this PR after execution.

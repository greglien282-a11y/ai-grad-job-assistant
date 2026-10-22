# Pathwise Overnight Handoff

Started: **2026-10-22 00:46 Asia/Shanghai** (2026-10-21 16:46 UTC). Source authorization: user's attached Overnight Autonomous Development instructions, read in full. This log contains only synthetic summaries and public commit/PR identifiers; no Bearer, secret, raw operation key, password or private DSN.

## Startup / immutable boundaries

- Remote main and fetched origin/main: `17a35e9cf23d4d9f11b757a426793e575f861223`; worktree clean before branch creation.
- c3b [Draft PR #44](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/44), HEAD `2020eaa9d3e2852671519f08894870cead7f3108`, open/draft, not merged. [CI 39633793288](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39633793288) completed/success at that exact HEAD. Local 2158 backend; CI 2157 + 1 existing Windows-only skip; React 158; real Chromium 59; migrations/12/48/quality/Mock passed. Its four-file scope and remaining risk are in that PR.
- No pending user edits were overwritten, stashed, reset or deleted. c3b test cluster had been stopped and temporary resources cleared.
- No production data/credentials/provider/fees, migrations, writer/API/DELETE/worker behavior, runtime factory/ACL or frozen evaluation changes authorized. No Ready/Merge/Deploy/main push.
- M1–M5 are new design/research authority, not production policy approval. R03, D4/D5, D6 remaining and D8 remain BLOCK.

## Branch plan and dependencies

Keep increments reviewable, not one large PR:

1. `codex/overnight-typed-contract`, base main above: M1 contract and this continuously updated master handoff. Documentation only; source analysis of c3b #44 is explicit and does not import its unmerged code.
2. Independent main branch for M2 adversarial corpus/research and actual existing-behavior tests. No c3b runtime dependency. Design dependency on the M1 candidate is documented by PR link.
3. A branch stacked on M2 only where M3/M4 actually reuse its research evaluator/corpus; parent SHA/base/PR and incremental diff will be stated. M5 integrates the two research increments and consolidates this log.

All PRs stay Draft. Every milestone gets a meaningful commit and a handoff checkpoint. Exact SHAs/URLs are appended after commits; this avoids claiming a document knows its own future hash.

## M1 — contract candidate

Status: **COMPLETE (NOT_IMPLEMENTED specification)**.

Files: `docs/overnight/TYPED_WRITER_CONTRACT_CANDIDATE.md`, this handoff.

Code inspected: c3a, c3b #44, experience_read/read_api/read_contract/read_permissions, fact_classification, fact_append, fact_maintenance, maintenance_guard, idempotency and c2e evidence.

Concrete findings/decisions:

- Candidate fresh-Turn atomic append is distinct from c3b saved-Turn preflight; no permission to adopt old sources.
- Explicit current/history classification and trust metadata; pending/v1/no evidence, no inferred completion or confirmation.
- Classification basis is a **real blocking gap**: FactV3 limits classification_citations to empty and basis_status to legacy_unclassified/not_recorded. A basis-aware writer requires separately reviewed schema/source/read contract; it cannot silently reuse current statement provenance.
- CO3 cross-contract collisions/replay/GET recovery, aggregate revision, minimal role, graph bijection, crash/tombstone and policy A boundaries specified as candidates.
- R03 blanket history refusal retains availability cost; no semantic guarantee claimed.

Validation: documentation/source audit and `git diff --check`; no runtime change or database request. Ordinary design alternatives were decided within research scope; all production decisions remain REQUIRES_USER_APPROVAL in the contract's approval register.

Content commit: `05264aba90cf3795f0e9510a87e61972a27576d9`; [Draft PR #45](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45). Base main `17a35e9...`, documentation only. GitHub connector briefly failed before creation; public read-only listing proved no PR existed before the successful create, avoiding duplicates. No application CI is expected for docs-only paths.

## M2 — R03 adversarial research

Status: **COMPLETE (SIMULATED + OBSERVED_EXISTING_BEHAVIOR)**.

Independent branch `codex/overnight-r03-research`, base main `17a35e9cf23d4d9f11b757a426793e575f861223`; content/final HEAD `fc9286e8f1b8e0e62f6d59d2821584391d03fd88`; [Draft PR #46](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/46). No c3b or #45 code dependency. M1 policy is an explicit design reference only.

Files: `apps/api/tests/overnight_research/__init__.py`, `r03.py`, `r03_cases.json`; `apps/api/tests/test_overnight_r03.py`; `docs/overnight/R03_ADVERSARIAL_REVIEW.md`.

Command: `python -m pytest -q -ra tests/test_overnight_r03.py` in apps/api using explicit loopback15487 synthetic database => **42 passed**, 7.70s, existing Starlette/httpx warning. Log `.e2e/overnight-m2-targeted.log`. No new skip/xfail/retry/timeout changes.

24 corpus cases distinguish all six requested diagnostic classes. These are finite risk hints, not semantic equivalence or c3a grammar expansion. All assessments deny truth and persistence permission. Unrelated controls with rejected history: **5/5 blocked**; clean comparison still lacks independence proof.

12 real restricted PostgreSQL/HTTP observations reproduce: manual/mining spelling/synonym/unrelated additions allowed vs append D3 refused with all-table zero effects; shared guard history-only gap for pending/confirmed; legacy Turn can remain after a separate exact Fact rejection. Existing accepted behavior is asserted honestly, not silently tightened. Scripted calls are synthetic; paid_calls=0.

CI for #46 exact HEAD: [39639366346](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39639366346) **completed/success**; workflow and three jobs successful. Linux backend **2128 passed, 1 existing Windows-only skip**, 1138.95s; migrations/12/48/DRAFT quality/Mock also passed. React/Chromium jobs successful; their actual counts/logs will be archived at M5. No future model result is claimed as independent evidence for #46.

## M3 — failure model and real read-only evidence

Status: **COMPLETE (NOT_IMPLEMENTED future CO3 specification + EXECUTABLE_ISOLATED_TEST reads)**.

Branch `codex/overnight-typed-model`; BASE_BRANCH=codex/overnight-r03-research; BASE_SHA=`fc9286e8f1b8e0e62f6d59d2821584391d03fd88`; DEPENDS_ON_PR=#46. M3 content commit `23d6e1295a64971c4eae9e117f06ae58ce07d5d9`. PR will be created after the related M4 increment stabilizes; no upstream result is mislabeled independent.

Files: `apps/api/tests/test_overnight_failures.py`, `docs/overnight/TYPED_FAILURE_MODEL.md`.

Command: `python -m pytest -q -ra tests/test_overnight_failures.py` => **30 passed**, 18.05s, existing warning. Log `.e2e/overnight-m3-targeted.log`. Initial 3 failures were incorrect new-test assumptions about generic error prefix; final assertions use exact per-fault existing codes. No production behavior or old assertion changed.

Real restricted LOGIN covers eight faults across all three read projections, auth-before-disclosure, honest missing classification basis, source DELETE privilege failure, default closed factory and real two-connection RR snapshot behavior. Failure comparisons cover all tables. The intentional external writer commit is not counted as a reader effect.

Future CO3 first success/replay/response loss/key conflicts/version boundaries, crash/rollback, typed history, tombstone, legacy birth and worker drain obligations are explicitly NOT_IMPLEMENTED. Existing CO1/CO2 real process, delete and worker tests are cited by exact names and will run in full regression; they are not CO3 guarantees.

## M4 — strictly isolated reference model

Status: **COMPLETE (SIMULATED only)**.

Files: `apps/api/tests/overnight_research/typed_model.py`; `apps/api/tests/test_overnight_typed_model.py`; `docs/overnight/TYPED_REFERENCE_MODEL.md`.

Content commit `3b27a96c72ea903a4984e85ac5d654d6ed7bcec8`, explicit-uncertainty checkpoint `ec0c961b5cb6944472cf60f5b0298c7642bcff3f`, M5 integrity correction/final HEAD **`afe82bb10c3dff0eaacfba22406675d1d31b66c3`**. [Draft PR #47](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/47), base #46 branch/HEAD above. Incremental diff is 5 files (M3+M4), not the inherited M2 code. #44 is not imported.

Command: `python -m pytest -q -ra tests/test_overnight_typed_model.py` => checkpoint100 passed; **final102 passed**, 0.27s, no DB. Final log `.e2e/overnight-m4-final-targeted.log`.

Model supports immutable candidate graph/initial pending-v1/declaration edge, atomic all-or-none state replacement, payload/key/version isolation, GET-like replay, abstract pre/post commit faults, serial schedules, revision/history gates, tombstone and capability distinctions. It uses existing Classification and unchanged c3a plus M2 risk diagnostics. Toy keys/principals and revision epochs are not real crypto/auth/DB semantics.

Actual model defect found/fixed: True equaled version 1 through dataclass equality; strict integer/type-preserving snapshot/source checks and bool-slot/tombstone regressions now reject corruption. No production or old-test change. An explicit service/recommendation-service counterexample demonstrates missing general semantic identity even when the toy transition succeeds. Every outcome retains SIMULATED_ONLY, NOT_PROVEN, transaction_review_required=true, truth_verified=false and persistence_authorized=false.

M4's declaration basis is hypothetical, not a real classification_citations field or approved migration. No routes/factories/DB/Provider/paid calls; no persisted typed writer. Real process/concurrency/SQL enforcement is still NOT_IMPLEMENTED for CO3.

## M5 — integrated audit and final evidence

Status: **COMPLETE (research/evidence delivery only)**, final report below and in `OVERNIGHT_REPORT.md`. Final acceptance uses #47 afe82bb..., not the earlier checkpoint. No product/production BLOCK is closed.

Deep audit found two additional real **model** gaps at ec0c961: unquoted trailing Turn text and a nonempty but drifted receipt tag could pass recovery/state checks. Command `python -m pytest -q tests/test_overnight_typed_model.py -k 'turn_unquoted_tail or receipt_tag_drift'` => **2 failed, 100 deselected**. Log `.e2e/overnight-m5-red.log`. Fix afe82bb reconstructs the body from graph edges, reruns unchanged c3a full sentence coverage and verifies the canonical fingerprint. Both cases now pass; no production/old-test changes.

The old full collection at ec0c961 completed2259 passed921.92s but is **SUPERSEDED**, not final evidence. The causal new defect justified a new exact-head full run; no failure was retried without a code/test cause or hidden by relaxing assertions. Earlier CI39643557810 is also superseded for final acceptance.

Final #47 local backend: `python -m pytest -q -ra` => **2261 passed**, 906.99s, existing Starlette/httpx warning only; log `.e2e/overnight-final-backend.log`. This integrates main + #46 + #47, **not** unmerged c3b #44. New overnight test cases:42+30+102=174; old tests unchanged.

Other executed local commands (apps/web or apps/api respectively):

- `npm run test -- --reporter=dot`: **158 passed**; `.e2e/overnight-react.log`.
- `npm run build`; `npm run test:e2e:types`: passed; `.e2e/overnight-build.log`, `.e2e/overnight-e2e-types.log`.
- `PATHWISE_E2E_CHANNEL=msedge npm run test:e2e`: **59 passed**, 3.0m, actual Edge Chromium kernel/HTTP/PostgreSQL; `.e2e/overnight-e2e.log`. CI uses bundled Chromium. Original timeout/retries retained.
- `python ../../scripts/check_isolated_migrations.py`: passed, no new upgrade operations, existing cleanup smoke; static head0015_fact_classification. `.e2e/overnight-migrations.log`.
- `python ../../scripts/check_m12c2_contracts.py`: **12/12**; `python ../../scripts/check_s03b_output_contract.py`: **48/48**; corresponding contract12/contract48 logs. Existing S02 diagnostic and TOKENIZER_NOT_PROVIDED retained.
- `python ../../scripts/evaluate_mining_quality.py --outputs ../../docs/evaluation/quality-v1/oracle.outputs.json --output-dir ../../.e2e/overnight-quality`: passed, DRAFT/human unreviewed/real quality null/provider_requests0; `.e2e/overnight-quality.log`.
- `python ../../scripts/run_offline_evaluation.py --profile 0 --output ../../.e2e/overnight-mock.json`: passed, real requests0/actual cost0, quality/latency null; `.e2e/overnight-mock.log`.

The local nonbackend components completed before the test-model-only afe correction; `git diff --exit-code ec0c961..afe82bb -- apps/api/app apps/api/alembic apps/web scripts .github docs/evaluation` proves their runtime/frozen component trees identical. Final CI reruns every component on exact afe. No stale full result is used for changed model behavior.

Isolation audit: all #46/#47 changes are added test/research/docs files; zero diff under production app, frontend, migrations, scripts, workflow and frozen evaluation. App import scans forbid overnight_research. Existing role/owner/ACL/source immutability, legacy JSON and writer semantics unchanged. Matrix reused from actual Classification/c3a; no source consistency/finite match is described as truth or semantic independence. No cross-PR dependency is hidden.

Cleanup after both local full processes were terminal: both synthetic databases have **temporary_schemas=0, temporary_roles=0** (all non-system namespaces plus UUID-suffix/known test-role patterns checked). Dedicated15487 cluster stopped;15487/15173/18000 have no listeners. No unknown directory/schema/role deletion was needed. Worktree clean before final docs edits.

## Verification ledger

M2 targeted42, M3 targeted30, M4 final102 passed; final integrated backend2261 passed. #46 exact-head independent CI success as above, React158/build and Chromium59/types verified in job logs. #47 final [CI39644769165](https://github.com/greglien282-a11y/ai-grad-job-assistant/actions/runs/39644769165), head_sha **afe82bb10c3dff0eaacfba22406675d1d31b66c3**, is **completed/success**, workflow and all three jobs:

- Linux backend **2260 passed, 1 existing platform skip**,1371.16s. `tests/test_probe_secret_safety.py:195`: PowerShell5.1 Fake Native harness requires Windows; that existing case passes in local Windows2261. No new skip/xfail/timeout change.
- React **158 passed** plus TypeScript/Vite build; real bundled Chromium **59 passed** plus E2E types.
- Isolated migrations,12/48,DRAFT quality and Mock passed; real requests/fees0, actual real quality remains null.

#45 is documentation-only and does not match application workflow paths; not falsely called a new green full run. c3b's earlier results remain evidence for #44 only. Brief GitHub TLS/connector transport errors did not cause CI reruns or false terminal claims; document checkpoint1337af0 was retried as a fast-forward push after connectivity recovered.

## Risks / next resumption

Confirmed existing risks: old manual/mining reworded rejected claims can create new legacy pending facts; legacy confirmed can contain plan text; source-basis projection cannot yet express recorded classification evidence. Future semantic independence and writer atomicity remain unimplemented.

Completion artifact: `OVERNIGHT_REPORT.md` records all13 new files, exact content commits/PRs, full commands/results, evidence classes, known/possible/unresolved risks and seven REQUIRES_USER_APPROVAL groups. Source audit found zero production/frozen/old-test changes; no user edits were overwritten or removed. Latest remote main rechecked as17a35e9... before final documentation. Final docs own SHA is reported by #45/current Git HEAD rather than self-invented in its content.

Stop after final push/PR-state audit: preserve #44/#45/#46/#47 Draft. No Ready/Merge/Deploy/typed writer/production role/provider/paid operation. R03/D4/D5/D6 remaining/D8 and basis/born-contract/cutoff/CO3 real transaction/HMAC/permissions all remain BLOCK/REQUIRES_USER_APPROVAL. Test cluster stopped/resources clear; no restart. Full raw logs stay ignored; no credential/diagnostic upload.

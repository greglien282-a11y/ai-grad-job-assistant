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

Commit / Draft PR: pending first checkpoint.

## M2–M5

- M2 adversarial corpus and real compatibility observations: NOT_STARTED.
- M3 future failure specification and real read-only failure evidence: NOT_STARTED.
- M4 isolated in-memory reference model: NOT_STARTED; conditional on M1–M3 bounds.
- M5 integration audit, full regressions, cleanup and final report: NOT_STARTED.

## Verification ledger

New overnight tests: NOT_RUN yet. c3b's prior results above are evidence for #44 only, not proof that later branches pass. Each branch/CI will be bound to an exact SHA. No branch dependency will be reported as independent main verification.

## Risks / next resumption

Confirmed existing risks: old manual/mining reworded rejected claims can create new legacy pending facts; legacy confirmed can contain plan text; source-basis projection cannot yet express recorded classification evidence. Future semantic independence and writer atomicity remain unimplemented.

Resume M2 on stable main, preserve #44 Draft, do not implement any production fix. Update this handoff after each milestone and record exact evidence/approval dependencies. Local long logs belong only in ignored `.e2e/overnight-*` paths and must not be uploaded with credentials or raw diagnostics.

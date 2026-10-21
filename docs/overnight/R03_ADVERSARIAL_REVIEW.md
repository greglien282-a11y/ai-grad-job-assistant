# R03 Adversarial Review — M2

BASE_BRANCH=main; BASE_SHA=`17a35e9cf23d4d9f11b757a426793e575f861223`. No c3b code dependency: #44 is unmerged context only. Design reference: [M1 Draft PR #45](https://github.com/greglien282-a11y/ai-grad-job-assistant/pull/45). Every diagnostic here is a research candidate, not an API, writer admission, classification or semantic-proof contract.

## Artifacts and evidence classes

- `apps/api/tests/overnight_research/r03.py`: **SIMULATED** pure immutable risk diagnostics over caller-arranged synthetic history. No database, saved-source verification, network or provider. Nothing in app imports it.
- `apps/api/tests/overnight_research/r03_cases.json`: **SIMULATED** 24 public synthetic adversarial cases, separate from frozen quality-v1.
- `apps/api/tests/test_overnight_r03.py`: **EXECUTABLE_ISOLATED_TEST**, combining the pure corpus assertions and real PostgreSQL/HTTP restricted-identity observations.
- Existing writer outcomes below: **OBSERVED_EXISTING_BEHAVIOR**, not future security requirements. A permissive observed path is intentionally asserted as permissive; no false claim it is blocked.
- General semantic independence and a production remedy: **NOT_IMPLEMENTED**.

## Six diagnostics, no accepted fact

The diagnostics always include INDEPENDENCE_NOT_PROVEN and always keep truth_verified=false / persistence_authorized=false / source_binding=NOT_CHECKED. Source coordinates in the pure corpus are arranged inputs, not proof of a saved quotation. Real saved-source integrity is the separate c3b/read-projection responsibility.

- EXACT_REUSE: current or historical statement equals the candidate literally.
- SOURCE_REUSE: same synthetic Turn with overlapping known CP intervals, or same Turn with missing interval information. Known disjoint intervals are reported separately as same_turn_disjoint; they still do not prove independent claims. The real legacy guard remains whole-Turn conservative.
- HISTORY_RISK: current rejected or any arranged historical rejected snapshot, independent of current status.
- SEMANTICALLY_SUSPECTED: a finite **published adversarial family hint** contains old and new expressions. It never means equal claims, safe normalization, general synonym recognition, truth or independence. In particular 3/4 and 27/28 are not equated as quantities; they raise review risk because the contribution family is potentially related.
- NEEDS_HUMAN_DECISION: one of those precise/hinted risks exists. This is not a persisted clarification command or an override mechanism.
- INDEPENDENCE_NOT_PROVEN: present even when nothing matched. Unknown language and clean exact comparisons never establish independent work.

The finite family lists include subject, plan/completion, negation, quantity and omitted qualifier attacks. They do **not** expand c3a's actions/objects, accepted grammar or frozen expectations. Each corpus row separately invokes unchanged c3a; the same finite language may pass even when history remains risky. Positive personal grammar cannot prove the user really performed the work.

## Adversarial coverage

The 24 cases explicitly cover:

1. Rejected original text on a new Turn, and historical exact text after a changed current statement.
2. 3/三个, 测试/验证, 3/4 and 27/28 changes, without treating any number or synonym substitution as independence proof.
3. Current rejected and historical rejection followed by pending or user_confirmed.
4. Same source overlap, same Turn disjoint slices, missing original interval and different Turn.
5. Unrelated deployment/script/prototype contributions, including Unicode emoji.
6. Team→personal, plan→completed, removing negation, uncertainty or “不是独立完成” qualifiers.
7. New candidate still containing team/plan/uncertainty, where c3a reports clarification rather than completed eligibility.
8. No-rejection synonym and unrelated controls; unsupported text remains unsupported and independent semantics remain unknown.

Availability cost: six cases are marked unrelated; five have rejected history, and **all five are conservatively blocked**. The sixth has no rejected history and is not blanket-blocked, but remains INDEPENDENCE_NOT_PROVEN with no persistence permission. These are 5/5 synthetic rejected-history false blocks, not a population false-positive rate or model accuracy metric. Blanket refusal is an explicit temporary policy with real usability cost, not a solution to R03.

## Real PostgreSQL observations

Tests use random migrated Schemas and the existing c2e temporary restricted LOGIN. Owner only seeds synthetic historical states and reads all-table digests outside requests. No production ACL or writer behavior changes; no real provider/paid request.

Nine HTTP observations: 3 new utterances × manual / scripted mining / append:

- New utterances: 三个 spelling, 验证 synonym, and unrelated deployment.
- Manual Turn→Fact returns 201 then 201, creates pending legacy-v0 Fact and keeps rejected original; Provider calls=0.
- Mining returns completed/201 with one **synthetic Scripted** call, creates pending legacy-v0 Fact and keeps rejected original; paid_calls=0. This is not a real model quality result.
- Append returns 409 append_requires_clarification, all-table digest unchanged and Provider calls=0, including unrelated deployment.

Two historical-only observations: the trusted legacy fixture arranges rejected→pending/confirmed history without editing production code. The runtime restricted legacy domain can add the **exact current text** of that old restored fact, because shared rejected_contribution queries only **currently** rejected rows. The append history gate still rejects unrelated new input with all tables unchanged. This reproduces an existing gap, not a new grant or a proposal to allow it.

One exact-rejection observation: old manual add_turn succeeds before a separate add_fact returns 409 fact_rejected_immutable. The second request is all-table zero-effect, but the Turn from the first HTTP request remains. Thus “Fact rejection is zero effect” must be scoped to the failing request; it cannot be broadened into atomicity across old Turn→Fact requests. A future atomic writer must prove its own graph, not rewrite this compatibility assertion.

Paid ledger rows remain zero. Existing successful behavior may legitimately change revision/Turn/Fact/Run rows; tests do not falsely demand whole-database immutability for those cases. Refused append and refused add_fact compare all business tables, including revision/history/receipts/fees.

## Executed verification

`python -m pytest -q -ra tests/test_overnight_r03.py`: **42 passed**, 7.70s locally, one existing Starlette/httpx deprecation warning. 24 corpus rows + cost/invalid-input/isolation assertions and 12 actual legacy behavior cases. No skip/xfail, timeout/retry changes or production edits.

The full backend, React/build/types, real Chromium, migrations, 12/48, quality scaffold and Mock will be bound to this PR's exact HEAD and recorded in its description/master handoff. Results on a stacked later branch will be reported as integrated results, not independent evidence for a different head. Pure corpus statistics are never reported as real semantic quality.

## Recommendations and approvals

Retain all present production BLOCKs. Propose separate review of rejected identity across **all** entrypoints and all historical states, immutable saved sources, exact reuse and conservative semantic fallback. Before any tightening, explicitly decide how to handle unrelated legitimate work, old successful receipt replay, manual multi-request drafts, in-flight mining and whole-session deletion.

Do not broaden the shared guard tonight. A user checkbox, new Turn/key, number spelling or family heuristic cannot prove independence. R03 clarification policy, D4/D5 classification/basis, D6 remaining and D8 all remain REQUIRES_USER_APPROVAL. No formal writer, automatic classification, provider/Prompt/MiningContext change, migration or cutoff is enabled.

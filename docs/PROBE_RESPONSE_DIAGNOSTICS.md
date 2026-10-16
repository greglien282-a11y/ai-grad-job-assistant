# Controlled probe response diagnostics (offline repair)

## What can and cannot be concluded

The operator reports that the first fixed S03/b request was billed and manually
reconciled. Its response body was deliberately not retained. Neither this repair
nor its tests read that ledger, bill, Windows credentials or approval files.
There is no second vendor request.

Source-proven defects in the previous code:

1. `validate_response()` collapsed envelope, model, usage, output JSON, business
   schema, source and preview failures into `controlled_response_invalid`.
2. Live HTTP validated inside `_post_once()` while the secret was in scope.
   A failure there prevented the outer `status, raw = await ...` assignment.
   Consequently an observed HTTP 200 was persisted as null. The old record does
   not prove either an HTTP failure or business success.
3. A stream timeout/disconnect after receiving headers also discarded the
   observed status. Failures before headers still have no known HTTP status.

Offline fixtures reproduce those failure paths and prove the new diagnostics.
They do **not** reconstruct the first vendor response. Its 71 output tokens do
not establish `finish_reason=length`: the tests accept a valid stop response
with 624 input / 71 output tokens and reject an explicit length response.

## Validation and compatibility policy

The unchanged fixed request uses JSON object mode, which does not by itself
guarantee `MiningOutputV2`. The response must still contain exactly the five wire
keys: `schema_version`, `candidates`, `questions`, `stop`, `stop_reason`. Duplicate
keys, non-finite numbers, fenced JSON and repair attempts are rejected. Model
authored usage/status fields remain forbidden. Runtime token metadata comes from
the validated HTTP envelope, not the model's JSON.

`system_fingerprint` currently remains a required string in both the controlled
probe and C-0 decoder. Missing/null/wrong-type fixtures reproduce rejection at
the envelope boundary; this offline-only change does not claim that the real
supplier returned any of those shapes or that optional/null variants are proven
legal by newly verified official evidence. No protocol acceptance rule is relaxed
without such evidence. Fingerprints never prove immutable model weights.

Usage still requires five nonnegative, non-boolean integer counts; prompt cache
hit plus miss must equal prompt count, and prompt plus completion must equal
total. Completion must not exceed 256. Optional detail objects may be absent;
if provided they must have the expected shape and agree with cache/reasoning
counts. Null/malformed detail objects are rejected, not silently converted into
zero usage. Only zero reasoning is accepted in the fixed non-thinking mode.
The model allowlist and assistant/single-choice/non-tool requirements remain.

The source validator is unchanged: same-context legal user turns, Unicode
code-point offsets, exact full-sentence citations, conservative atomicity,
negation/uncertainty and duplicate-question checks. No model output is confirmed,
verified, or written into the user's experience library by the probe.

## Fixed safe diagnostics

| Boundary | Code |
| --- | --- |
| HTTP JSON/envelope/metadata shape | `controlled_envelope_invalid` |
| Fixed model allowlist | `controlled_model_mismatch` |
| Token fields, counts, cap and details | `controlled_usage_invalid` |
| Explicit length finish reason | `controlled_output_truncated` |
| Explicit refusal/filter | `controlled_output_refused` |
| Other finish reason, tools or reasoning | `controlled_output_mode_invalid` |
| Output JSON syntax/encoding/duplicates | `controlled_output_json_invalid` |
| MiningOutputV2 keys and Pydantic schema | `controlled_output_schema_invalid` |
| Snapshot sources and factual constraints | `controlled_facts_invalid` |
| Safe preview content/local retention | `controlled_preview_invalid` |

Codes are selected by local code, never copied from provider strings. The shared
output parser adds `AdapterError` subclasses while preserving its legacy
`output_invalid` string, keeping C-0 and offline adapters compatible.

An HTTP 200 is recorded only after headers were observed. Response validation
failures carry it across the inner live-validation boundary; mock HTTP now uses
that same validation path. Network errors after headers preserve the observed
status; failures before headers retain null. A cancellation without a returned
status still has null; no guessed status is fabricated. Success is still a
separate `validated=true` decision requiring every validation stage.

No raw response, headers, request body, exception detail or free-text model output
is added to the database/logs. Failure diagnostics contain only the existing
`http_status`, `validated=false`, and fixed `safe_code` fields. Failed output has
no safe preview. Previously validated output may still be shown locally if only
its local retention fails, as required by the prior preview contract.

## Database upgrade and safety

`0010_response_diagnostics` extends only the safe-code list in the existing
`controlled_runtime(text,text,text,jsonb)` function. `CREATE OR REPLACE` preserves
its OID, owner, SECURITY DEFINER, search_path, and restricted EXECUTE grants.
There are no table/data updates, grants, new approvals or modified transition
rules. Migration tests compare the entire old/new function definition after
removing the added list and check ledger/experiment rows remain identical.

Existing `0009` databases require a separately reviewed migration before using
the new diagnostic codes; this task never migrates the actual probe or daily DB.
Historical generic diagnostics stay intact. Downgrade refuses when a record
uses a new code; the existing nonempty-ledger downgrade guard remains in force.

After a send, any validation/network/refusal/truncation failure remains unknown,
holds the reservation and keeps funding frozen. No retries, new operation keys,
alternate models or suppliers are introduced. Reconciled records cannot regain
an approved/reserved/sent state through these code paths. A DB send permit is
still not a guarantee of supplier-side exactly-once execution.

## Offline verification

New tests use synthetic packets and `httpx.MockTransport`, including real
restricted runtime SQL in random schemas of a disposable `pathwise_test` cluster.
They cover phase classification, 200 business rejection, header/body failures,
usage optional/malformed variants, fingerprint variants, model mismatch,
fabricated/offset/self-confirmed facts, preview rejection, no retry, whitelist
ACL/definition preservation, downgrade safety and reconciled-state protection.
Existing HTTP 401/429/500/503, cancellation, crash, invoice and permit tests remain.

Local commands (with TEST_DATABASE_URL pointing **only** to the disposable test
cluster; never obtain a local private credential or use pathwise_probe/dev):

```powershell
# Run from apps/api
python -m pytest -q -ra
python ../../scripts/check_m12c2_contracts.py
python ../../scripts/check_isolated_migrations.py
python ../../scripts/run_offline_evaluation.py --profile 0 --output ../../.e2e/mock-response-evaluation.json
```

The first response's exact failure reason remains unknown. Real provider
compatibility, quality and latency are not remeasured by these mock tests.

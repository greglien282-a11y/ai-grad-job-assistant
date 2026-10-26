# M2 G — one local source, multiple job resumes

## Exact dependency

Main verified `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`. This candidate is based on F/Draft #66 `99b95886e4a22b3cb536f6090ce26d4f38555c8c`, which depends on #65→#64→#61. No existing PR, production writer, migration, role, approved DTO or frozen model is changed. All remain Draft; no merge/deployment authorization inferred.

## User journey and actual product value

Open /resume-lab using the explicit local DEV gate (instructions in M2_PDF_DOCX_LOCAL_IMPORT.md). Import paste/TXT/MD/PDF/DOCX, check extracted source and candidate order, then create up to5 independent job drafts over a single source. Start with your own JD or explicit visual-algorithm/Python-backend/testing preset. Roles preserve their own JD, adjusted conditions, user capability assessment, selected/hidden items, order, exact edits, density, template, page goal and three-question answers. Shared original text does not change on a role switch. Basic name/contact/location/headline are user-entered, shared and unverified. No account/database is required.

Suggestions display exact original text, snapshot citations and JD quotes/intervals. Literal overlap is not semantic matching or skill proficiency. Explicit application selects the exact original and moves it first, resets that role's review; no invented rewrite, number, qualification or certification. Team/plan/negation/conflict entries are not eligible for positive contribution suggestions. They remain context under existing admission rules. User-authored editing remains possible and explicitly unverified; unchanged original and edited draft are visible together. Rejected exact originals stay blocked across roles, undo and retained in-memory restores. A new rejection resets potentially stale review in all roles. This is local exact-text protection, not R03 semantic resolution; editable JSON/reload cannot prove complete rejection history.

The printable self-authored resume supports two real layouts: classic ruled section headings and minimal centered profile. Education/projects/internships/skills/other use source structure; section order follows first selected appearance, items inside each section follow edited order. Context/plan/limits are separately labeled and never combined into completed personal achievements. Profile, original comparison, source labels and unverified footer stay visible. One-page goal is guidance only; estimate is approximate. No clipping/automatic summarization/shrinking to hide content. Long paragraphs break across A4 pages; short entries stay together. Native browser print/PDF, not a new server.

Three questions are recomputed from current role's selected admissible draft and JD citations. Answers are role-local and restored as user recollections, never proof. User-declared skill gaps ask about learning/preparation without pretending the technology was used in a project. Switching roles cannot show another role's old answer.

## Local v3 contract and migration

`local-job-resume-draft-v3` serializes shared workbench once, profile,1–5 role records, active role ID and shared exact rejection set. Strict role content reuses existing single-draft schemas/validation, not a second provenance/admission implementation. Role records cannot override the shared source. Every role must cover the full source-entry bijection, valid JD references/assessments and valid review state. Unknown/extra fields, duplicate JSON keys (including escaped keys), duplicate/missing IDs, broken quotes, unknown active role, invented status and unknown versions reject the whole file. Source fingerprint/quote relationships from F stay intact; extracted snapshot hash is checked before restore applies.

Old v1/v2 single drafts must pass their original schema and512KiB budget, then explicitly migrate to exactly one v3 role. Source/JD/text/state/review retained; blank profile and layout defaults are transparent; no fabricated file hash, historical review event or classification basis. New v3 supports2MiB, retains UTF-8/file validation and bounded JSON nesting. No unknown-version downgrade. Failed restore clears prior views; no partial stale resume. Restored flags are user-editable declarations, not signed audit evidence or authenticated natural-person actions.

Download includes COMPLETE source text, fingerprint metadata (not binary original), contacts, every job draft and review answers. The UI warns before the explicit download action. No localStorage/sessionStorage/IndexedDB/remote sync/autosave. Refresh leaves an empty workbench until manual JSON import. No API, Provider, paid call, upload or formal write. Source structural changes intentionally reset dependent role drafts (UI explains this); merely acknowledging unchanged extraction text preserves roles. Per-role undo cannot remove retained rejection records.

## Actual validation commands

From apps/web:

- `npm test -- --reporter=dot`:302 pass (280 from F +19 workspace/model +3 component tests).
- `npm run build`: pass; local studio lazy50.49kB/gzip18.38; parser chunks unchanged from F.
- `npx tsc -p tsconfig.resume-lab.json --noEmit`; `npx tsc -p tsconfig.jd-lab.json --noEmit`: pass.
- `PATHWISE_PROTOTYPE_CHANNEL=chrome npx playwright test --config resume-lab/playwright.config.ts`:18 pass (14 F/prior +4 new journeys).
- Equivalent jd-lab config:5 pass.
- `git diff --check`: pass.

New actual browser journeys: independent2-role creation/edit/selection/template/questions→download→refresh→restore→both roles verified→nativePDF; explicit old-v1 migration/corrupt-v3 refusal; shared rejection across roles/suggestions/undo; long CJK/English paragraph preserved across multiple native print pages and mobile width. Existing unsafe rewrite/duplicate/admission tests remain. The old downloaded-shape assertions now explicitly inspect v3 shared source and per-role content; original v1 parser tests remain, plus migration tests. Oversized-v3 refusal now tests2MiB+1 (the old512KiB cap still applies to migrated v1/v2). No deleted/skip/xfail/timeout relaxation. Browser screenshots use public synthetic materials only. Complete backend/formalChromium/migrations/offline12/48/quality/Mock are required by exact-HEAD application CI; final run URLs/results attached to Draft PR.

Native PDF inspection also exposed a blank trailing page on short resumes caused by screen min-height entering print. Scoped print min-height reset fixes it; real PDF assertions now require the short draft to be exactly one page and long content to span multiple pages without clipping. Whitespace-normalized text extraction of the long PDF retained all140 repeated synthetic course phrases.

Development caught and fixed a source-input remount that cleared pasted text, and a test selector ambiguity introduced by an extra note role. Both are recorded honestly; no failing result relabeled passed. Existing Zod/build warnings and inherited development dependency audit advisories remain as documented in F.

## Still blocked / unavailable

No real AI semantic matching, database-backed experience adaptation, formal fact authentication, G4 trusted persistence, typed writer/CO3/classify/related_plan, production account or deploy. All T2/T3/shared-key/G4, R03, D4/D5, remaining D6, D8 remain BLOCK. Client-supplied resume content is not proven true. Complex PDF/DOCX extraction still requires human checking; no OCR or arbitrary layout guarantee. Source and contact privacy remain user's responsibility; no perfect DLP claim.

# M2 F — browser-local PDF / DOCX import

## Baseline and delivery boundary

Verified main `e1eff78fd43e424ab22996b182e0e5f4d6bd609c`; #61 `e36499c5d9e01aacb4754c62d520ee02b28d91e4`, #64 `f52126ddcd88b07d542bb11fdfed044e19a12419`, #65 `667a4279b6d733b934e97fde63adf085d6863897` remain unmerged Drafts. This branch starts at exact #65 and is reviewed against `codex/m2-local-resume-studio`. No previous PR is rewritten, retargeted or merged.

Run from apps/web: `npm ci`, then PowerShell `$env:VITE_PATHWISE_JD_LAB='synthetic-v1'; npm run dev -- --host 127.0.0.1`. Open /resume-lab. Production build remains closed even when preview-server environment supplies the gate.

## Implemented journey

Select TXT/MD, PDF or DOCX; full extracted text and quality warnings appear first. PDF/DOCX cannot reach job analysis or download until the user explicitly reviews the text, order and omissions. Category, quote boundary and paragraph order remain editable; structural changes reset review and downstream draft. User review means local textual checking, never authenticated classification, true completion or platform verification.

PDF uses selectable text only. A bounded geometric heuristic detects some columns, orders left then right, and warns. Spanning headings, arbitrary multi-column typography, complex tables, rotations, missing fonts and reading order are not guaranteed. DOCX extracts main-body plain text and table cells in document order; headers/footers/textboxes/images may be omitted, with explicit warning. All text is inert React text. No rich HTML conversion, viewer scripting, macros, external relationships/images or OCR execution.

Encrypted PDFs, any textless PDF page, >12 pages, corrupted/unsupported files and oversized input reject the entire result. Legacy DOC must be converted locally. PDF/DOCX <=5 MiB, text <=20,000 code points /128 KiB, PDF <=10,000 text items/page and 30,000/document, parser deadline 15 seconds. DOCX dedicated terminable worker: <=256 ZIP entries, <=2 MiB/entry, <=8 MiB expanded total, <=max(1 MiB,150x input), input fed in 4 KiB chunks. Duplicate/traversing/unsupported archive paths, macros/embedded objects and XML entity declarations reject. Bounded entries are reconstructed before Mammoth to avoid a second parser selecting another central-directory body. These are admission/resource limits, not an OS-enforced memory quota. PDF.js work is destroyed on timeout/cancellation; no unlimited recovery retries.

## Forward local contracts

Existing `local-resume-workbench-v1` and `local-job-resume-draft-v1` remain exact for TXT/MD/paste. PDF/DOCX use workbench v2 and single draft v2. Strict schemas reject extra/unknown versions and broken quote/entry graphs. Metadata distinguishes original filename/bytes/SHA-256, immutable extraction text/SHA-256, pinned parser, page count, warnings and local review status. All Unicode offsets refer ONLY to extracted text, never PDF coordinates or file bytes. Reordering candidates leaves snapshot unchanged. Download includes snapshot + file fingerprint, NOT original file bytes. Restoration verifies extracted snapshot hash before applying. A hash detects mismatched bytes, not authenticity; a user-editable JSON is neither a signed receipt nor tamper-proof audit history. Old missing file metadata is never fabricated.

All input stays in current browser memory unless user explicitly downloads a JSON. No automatic storage, API, Provider, telemetry or upload. Refresh clears. Contacts remain user-controlled and downloads contain sensitive source content. Existing trusted FactV3/G2.1 print admission is unchanged; local self-authored resume remains unverified.

## Dependencies and build evidence (2026-10-26)

Exact lock: pdfjs-dist 6.4.299 (Apache-2.0; package unpacked 34,913,648 bytes), mammoth 1.13.0 (BSD-2-Clause;1,671,388), fflate 0.8.3 (MIT;796,742). docx 9.14.0 (MIT; dev-only) generates public synthetic test documents. npm audit --omit=dev: 0. Full audit: 2 moderate/1 high in existing Vitest/mocker and jsdom→undici tooling, not introduced parser production paths; not silently relabeled safe.

PDF.js official release and security advisory checked: https://github.com/mozilla/pdf.js/releases and https://github.com/mozilla/pdf.js/security/advisories/GHSA-hq66-cqwq-w95j (patched6.2.108, chosen6.4.299). Text APIs only, no viewer/ScriptingManager, XFA disabled, worker fetch/font loading/wasm disabled. Current PDF.js does not expose the old isEvalSupported option; this implementation does not claim an unsupported option protects it. Mammoth documents no HTML sanitization: https://github.com/mwilliamson/mammoth.js ; only extractRawText is used, its browser external-file reader rejects linked reads and the worker independently denies network APIs. ZIP limits use https://github.com/101arrowz/fflate . No dependency or parser is a full document malware scanner.

Build: PDF lazy chunk437.62kB/gzip131.39; fixed local PDF worker1,264.34kB; DOCX worker327.17kB; local studio38.57kB/gzip14.72. Packages are not loaded from CDN. Vite prebundles lazy parser dependencies upfront to prevent first DOCX selection causing a development optimizer reload; browser config forces a fresh optimization to exercise cold startup. Existing Zod PURE annotation warnings remain, plus a harmless mixed static/dynamic import report for the fingerprint helper.

## Actual local validation

- `npm test -- --reporter=dot`: 280 pass (269 inherited +11 parser tests).
- `npm run build`: pass.
- `npx tsc -p tsconfig.resume-lab.json --noEmit` and tsconfig.jd-lab.json: pass.
- `PATHWISE_PROTOTYPE_CHANNEL=chrome npx playwright test --config resume-lab/playwright.config.ts`:14 pass (11 inherited +3 actual document journeys); no retries, unchanged timeout.
- Equivalent jd-lab config:5 pass.
- `git diff --check`: pass.

First full browser run exposed a development dependency-optimization reload, fixed by explicit prebundling; cold optimization rerun passed14/14. No sleep/timeout increase/skip added. Real synthetic PDF produced by Chromium and DOCX by docx-js; encrypted synthetic fixture generation documented beside fixture. Screenshots `resume_pdf_review.png` / `resume_docx_review.png` produced from actual browser. Main application CI additionally runs complete backend, isolated migrations, formal Chromium/PostgreSQL, offline12/48, quality scaffold and zero-cost Mock CLI; exact run links/results are attached to the Draft PR after completion.

R03, G4/T2/T3/shared-key, D4/D5, remaining D6 and D8 remain BLOCK. No formal writer, migration, role, DTO, frozen model or production behavior changed.

# Development validation and release gates — internal, 2026-11-07

## Outcome

The PDF-first development product is buildable and its controlled Chrome MV3 flow
works. **It is not a production-validated AI detector.** No requested-ensemble AI
weights, labeled ensemble-score dataset, production authorship head or independent
accuracy evidence was supplied. Missing models/calibration produce unavailable
results, never random or synthetic predictions. Historical code/data were retained
and excluded from the new product dependency/build boundary.

## Executed checks

- `npm run build`: Chrome and Firefox-compatible outputs; explicit first-party
  allowlist. Unexpected distribution files now fail the build rather than being
  deleted or silently packaged. No internal docs/upstream identities in the build.
- `npm test`: 7 JavaScript tests passed, including PDF detection, Unicode ranges,
  stale-result rejection, safe rendering, both highlight colors, exports and build
  boundaries. The dual AI/source-color test uses a protocol fixture, not real AI.
- Python suite: 24 tests passed; primary real PDF parsing; no-text/size failures; domain gating;
  word-weighted coverage; offline no-web behavior; cancellation; source failures;
  authenticated helper endpoints; public-IP policy; genuine tiny-head fitting and
  leakage/release gates; digest-pinned local asset verification and result expiry.
- `npm run demo`: actual MV3 extension + local authenticated helper. Real PDF byte
  acquisition and parser, two embedded PDF selection, source evidence, JSON/text
  exports, consent invalidation/removal of old highlights, offline scan, visible
  website Unicode/editor exclusion, clear, navigation invalidation and image-only
  safe failure passed. No AI scores were mocked.

Browser smoke substitutions are explicit: a regular extension tab emulates
side-panel active-tab semantics; a test-only loopback-origin grant replaces browser
permission chrome; source retrieval uses a first-party controlled reference. This
does not validate toolbar prompts, store installation, live recall or AI accuracy.

## Evidence and calibration

`internal/demo/screenshots/source-review.png` and `fixture-report.json` show two
matched sentences, 60.377% word-weighted similarity on 80.303% search coverage,
with authorship unavailable. `website-report.txt` and `browser-validation.json`
record the expanded smoke. These are first-party fixtures, not benchmarks.

`internal/retraining/controlled-calibration.json` contains an actually fitted
logistic copying head on controlled grouped pairs. It is bundled inactive with
`production_approved: false`; its template-domain metrics cannot support real-web
confidence or a production model/fine-tuning claim. AI calibration is absent.

Live-web smoke initially stalled in browser page cleanup and was interrupted.
Cleanup/query deadlines and stricter navigation-only routing were added. The
bounded retry completed (`screenshots/live-report.json`) but retrieved no verified
comparison evidence: source status was partial/unavailable, 0% coverage, with a
**null**, not 0%, plagiarism result. This validates fail-closed behavior only;
successful live search/source recall remains unvalidated. Controlled sources are
never substituted into live mode.

A separate real `fetch_public("https://example.org/")` smoke succeeded through the
validated pinned-IP path (577 HTML bytes). This confirms basic public HTTPS fetch,
not successful search-provider parsing or plagiarism-source discovery.

## Remaining release gates

1. Obtain permitted, exact requested-model snapshots; verify complete asset hashes,
   loading architecture, label mapping, optional dependencies and actual execution.
   Keep assets immutable during the helper lifetime; config changes invalidate
   calibration signatures. Large causal models need deliberate memory provisioning.
2. Acquire licensed independent labeled segment data; train matching heads; measure
   held-out calibration, human false positives, subgroup robustness, paraphrases,
   mixed authorship and source recall. Approve artifacts only after documented review.
3. Manual Chrome/Edge/Firefox acceptance: real toolbar/permission flows, native
   viewers, file URLs, authenticated/redirected PDFs, offline cached viewers, complex
   layouts, multi-page/code documents, switch-tabs/cancellation and installation.
4. Runtime security/resource review: DNS/HTTP/native calls are not forcibly
   preemptible; use OS-level isolation for hostile documents/sources. Private IPs,
   unsafe redirects, frames/subresources and unexpected navigation are rejected.
5. Search-provider access/robots/terms review; no claim of whole-web comparison.
6. Any future redistributed runtime/weights/browser bundle must ship applicable
   license/NOTICE texts. Internal credits do not replace redistribution obligations.

No commits or pushes were made; this workspace has no Git repository.

## Desktop-installer follow-up

The macOS one-click installer adds automatic runtime provisioning, stable extension
identity, browser-native pairing, on-demand startup and idle shutdown. See
`internal/desktop_distribution.md`. It does not change model/calibration limits.

- Final installer `.app`/ZIP build, shell syntax and bundle plist checks passed.
- Final suites: **34 Python tests** and **10 JavaScript tests** passed. The earlier
  24/7 counts above describe the pre-installer baseline.
- A clean sandbox installer retry downloaded/verified standalone Python 3.11.18,
  installed runtime packages/headless browser, and registered only sandbox hosts.
- Actual Chromium MV3 native messaging against that installed runtime passed with
  **no native API shim or token entry**: startup, PDF extraction, offline review,
  repeat-token preservation, automatic restart before read and on panel reopen.
  The final run exited normally and stopped its helper/browser. See
  `internal/demo/screenshots/desktop-validation.json` and `automatic-companion.png`.
- The expanded controlled `npm run demo` passed again after the final build.

The native smoke still substitutes an explicit sandbox profile/installed manifest,
side-panel active-tab semantics and loopback document permissions. Public macOS
distribution remains blocked on signing/notarization, reviewed hosting and license
acceptance. Intel, Firefox and real Chrome/Edge toolbar/default-profile flows remain
unvalidated. Linux installation is not implemented. Windows now has the separate
development implementation described below. AI weights and approved calibration
remain unavailable.

## Windows-installer follow-up

Added a Windows 10/11 x64 GUI `.exe` installer with private per-user runtime setup,
HKCU native registration in both registry views, and the shared automatic
pairing/start/restart protocol. See `internal/windows_distribution.md`.

- Cross-build produced `product/dist/installer/windows/VeritySetup.exe` and
  `Verity-Windows.zip`; no end-user compiler, Python setup, terminal or PowerShell
  policy change is required by the implemented flow.
- Static checks verified the actual AMD64 GUI PE, embedded `asInvoker` resource,
  exact source/payload/archive hashes and retained compiler licensing. Artifact
  report: `internal/demo/screenshots/windows-package-validation.json`.
- Downloaded the digest-pinned Windows Python archive and passed its actual
  extraction logic on macOS without executing its binaries.
- Current checks passed: **39 Python tests**, **11 JavaScript tests**, and **7
  portable installer test groups**, including registry/upgrade/rollback and
  controlled staged install/failure cases. The existing MV3 fixture demo passed.
- **No real Windows execution** was available: installer UI, DACL enforcement,
  dependency/runtime execution, native-host stdio/discovery, Windows browser/PDF
  flows and cancellation UX remain unvalidated. Registry tests are explicit fakes.
  The `.exe` is unsigned; Authenticode signing and reviewed distribution are still
  required. Native Windows ARM64 and 32-bit installers are not implemented.

Model, calibration, live-source discovery and accuracy gates are unchanged.

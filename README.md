# Verity — Local Desktop Review

A **Python-only desktop app** with **Review, Results, Models and Settings** tabs.
Open PDFs or paste text/code, inspect extraction and source evidence, cancel work,
and export JSON/text reports. No extension, pairing token, server, manual helper,
terminal commands or user-managed Python installation is required.

**[Download website](https://veritylocal.github.io/)** ·
**[Standard development release](https://github.com/VerityLocal/Main/releases/tag/v0.3.0-dev.1)**

## Standard bundle

Platform ZIPs contain the application, Python/Tcl/Tk, dependencies, actual pinned
**Desklib + BGE-small weights and tokenizers**, configuration and license notices.
First launch and local inference need no internet or additional downloads.
Web-source comparison is optional, disabled by default and consented per scan.

- **macOS Apple Silicon:** extract `Verity-Standard-macOS-arm64.zip`, then open
  **Verity.app**. You can move it to Applications; keep the app bundle intact.
- **Windows x64:** extract `Verity-Standard-Windows-x64.zip`, then open **Verity.exe**
  inside the Verity folder. Keep `_internal` and its model files alongside it.
- Use only the assets actually listed on the release page. Native Windows
  acceptance is a publication gate; Intel macOS, Windows ARM64 and Linux are not
  offered by this release.

**Unsigned development build:** macOS uses ad-hoc signing, not Developer ID or
notarization; Windows has no Authenticode signature. OS security may block these
apps. Do not disable security protections. This is not a production accuracy claim.

## Review

1. In **Review**, open a text-layer PDF or paste text/code. Correct extraction if needed.
2. Click **Analyze locally**. The window stays responsive; **Cancel & revoke consent**
   stops the owned worker and discards the interrupted result.
3. Inspect **Results**: segment statuses, coverage, text highlights and source excerpts.
   Yellow marks source evidence; grey marks unscored text, not human/original text.
4. Export JSON/text only when you choose. Editing invalidates old results.
5. In **Models**, verify all bundled file hashes. In **Settings**, optionally allow
   web comparison, then grant consent separately for each scan in Review.

Limits: 16 MiB PDF, 200 pages, 200,000 text characters and 1,500 segments. No OCR.
Documents/preferences stay in memory; exit or Clear releases them. Originals are
never modified. Explicit exports contain document text and should be kept private.

## Honest limitations

- **AI-written percentages are unavailable until independently calibrated.**
  `calibration_required` means a genuine local feature was computed, not a verdict.
- Desklib is an English prose signal; BGE supports semantic source comparison.
  Standard excludes Falcon/Binoculars, GPTSniffer and a production code corpus.
  Code is reviewable/source-comparable, but has no bundled authorship detector.
- Desklib cold-loading gates: 8 GiB physical / 3 GiB available RAM. BGE: 4 GiB /
  0.5 GiB. These are conservative gates, not guarantees against memory exhaustion.
- Source similarity is evidence, not proof of plagiarism. Search coverage is limited;
  unavailable or unchecked text is never counted as original. Up to 24 eligible
  segments are searched per consented scan.

## Source and development

- `product/desktop/` — native UI, worker ownership and exports.
- `product/engine/` — reused local analysis engine.
- `product/packaging/` — native frozen-app assembly and release checks.
- `product/tests/`, `product/tools/`, `docs/` — tests, calibration tools and guidance.

See [development](docs/DEVELOPMENT.md), [distribution](docs/DISTRIBUTION.md),
[models](docs/MODELS.md) and [privacy](docs/SECURITY.md).
Old extension/companion releases and Git history remain intact; they are not this
Python-only application. Private originals, model assets, environments and generated
ZIPs are excluded from Git source.

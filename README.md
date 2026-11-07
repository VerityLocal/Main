# Verity — PDF & Website Review

A browser extension for reviewing the **active PDF or website** with **our
in-house detection engine**. It displays source-overlap percentages, estimated
AI authorship, sentence/block evidence, attributed source links and export.

## Install for normal use (macOS 14+)

1. Open **Verity Installer.app** from the download and click **Install**.
2. Load the `chrome-extension` folder shown in Finder into Chrome or Edge.
3. Open a PDF and click the extension. Its desktop companion starts and pairs
   automatically—no terminal commands, Python installation or pairing token.

First installation needs internet to download the local runtime. Subsequent
connections start the installed helper on demand; it stops after 30 idle minutes.
Documents still stay local for authorship analysis. AI weights are not included.
The current installer is a **development build**; publicly downloaded macOS apps
require signing and notarization before distribution. Do not disable OS security.
Linux one-click installation is not yet available.

## Windows installer (10/11 x64 — development)

Open **VeritySetup.exe** and approve installation, then load the `chrome-extension`
folder shown in Explorer into Chrome or Edge. Runtime provisioning, pairing,
startup and restart are automatic; no terminal, Python setup or pairing token.

Download archive: `product/dist/installer/windows/Verity-Windows.zip`.
First installation requires internet. This is an **unsigned development build**:
Windows execution/browser acceptance testing and code signing are still required
before public distribution. Do not disable Windows security. Native ARM64 and
32-bit Windows are not supported. AI model/calibration limitations are unchanged.

## Build for development

With Node.js 20 or newer, build the extension or an installer:

```sh
npm run build
npm run build:installer
npm run build:installer:windows
```

In Chrome or Edge, enable Developer mode on the extensions page, choose **Load
unpacked**, and select `product/dist/chrome`. A Firefox-compatible popup build is
at `product/dist/firefox`; install its manifest temporarily for development.
Firefox PDF-viewer access varies by browser permissions and remains experimental.
The macOS installer archive is `product/dist/installer/macos/Verity-macOS.zip`.
Windows installer builds additionally need the maintainer toolchain described in
`internal/windows_distribution.md`; normal users need no build tools.

## Manual developer helper (optional)

Python 3.11 or newer is required for the local helper. Provision its runtime using
the maintained internal setup instructions. No document is sent to a cloud AI
service. From the project root:

```sh
python -m product.engine.server --init
python -m product.engine.server --allow-origin chrome-extension://YOUR_EXTENSION_ID
python -m product.engine.server
```

The initializer creates `product/.local/helper.json` without overwriting existing
settings. Enter its private `token` in the extension’s **Settings**. Pair the exact
origin shown under **Advanced development connection** (including the
browser-generated origin for Firefox). Normal installer users skip these steps.

**Current release limitation:** no production AI model/calibration is provisioned
by the build command. Until configured, authorship results show **Unavailable**,
not a fabricated percentage. PDF extraction and web source comparison also require
the provisioned local runtime. This is a development release, not a validated
accuracy guarantee or an assertion of completed in-house model fine-tuning.

## Review a document

1. Open a PDF or website and click the toolbar icon.
2. Click **Read active document**. Grant access to that PDF’s origin if prompted.
   For an embedded PDF, its text takes precedence over the surrounding website;
   choose the document if several PDFs are embedded.
3. Review the extracted text. Enable **Compare against web sources** to consent to
   sharing short excerpts with search services for source comparison.
4. Click **Scan document**. Source overlap is amber; AI-suspected text is blue.
   A segment can show both colors. Hover, click or keyboard-focus it for evidence.
5. Export a JSON or text report. **Clear** removes text/results from the panel.

File PDFs require the browser’s **Allow access to file URLs** setting. Protected,
image-only PDFs, inaccessible frames and unusual layouts may be unsupported.
Open an inaccessible embedded PDF in its own tab. Native viewer access may re-read
the active PDF from its original URL; redirects are rejected. Already-open cached
viewer bytes are used where available. Limits: 16 MB, 200 pages, 200,000 text
characters, 1,500 segments. Website extraction includes visible read-only text,
not editors, hidden content or unrendered pages.

## What scores mean

- **Plagiarism / source overlap %** is word-weighted matched similarity on checked
  passages, not proof of copying or misconduct. Quotations and citations need review.
- **AI-written %** is a word-weighted probability estimate on scored passages,
  not a measurement of how many words were written by AI or authorship proof.
- Coverage is always shown. Unchecked text, search failures, short passages and
  unavailable models are **not** counted as original/human. Web comparison checks
  up to 24 sufficiently long segments per scan by default; it cannot search the
  entire web or establish that unmatched text is original.
- Confidence is separate from source similarity. No calibrated confidence is
  shown when a matching fitted calibration head is unavailable.

Authorship checks work offline **after** local provisioning. Web source comparison
needs internet access and explicit consent. Acquiring an active remote PDF may
need its original site; that is document acquisition, not a cloud AI check.
Only the pairing token is persisted by the extension. Helper scan results stay in
memory for up to 30 minutes while it is running, with a bounded queue; exported
reports contain document text and should be handled as private data.

Sample PDFs are in `internal/demo/pdfs`. Maintainer setup, model provenance,
calibration, tests and demo instructions are internal and never copied into the
distributed extension. Historical research trees are not part of this product.

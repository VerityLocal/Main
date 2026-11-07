# Verity — PDF & Website Review

A browser extension and local desktop companion for reviewing the **active PDF or
website**, with source-overlap evidence, highlights, coverage, attributed links
and export. Authorship analysis stays local when approved models are provisioned.

**[Download website](https://veritylocal.github.io/)** ·
**[Development release](https://github.com/VerityLocal/Main/releases/tag/v0.2.0-dev.1)**

## Download for macOS or Windows

| Platform | Requirements | Download |
| --- | --- | --- |
| macOS | 14+, Intel or Apple Silicon | [Verity-macOS.zip](https://github.com/VerityLocal/Main/releases/download/v0.2.0-dev.1/Verity-macOS.zip) |
| Windows | 10/11 x64 | [Verity-Windows.zip](https://github.com/VerityLocal/Main/releases/download/v0.2.0-dev.1/Verity-Windows.zip) |

**[Download the browser extension ZIP](https://github.com/VerityLocal/Main/releases/download/v0.2.0-dev.1/Verity-Extension.zip)**
— the same Chrome/Edge extension for both platforms. It still requires the matching
desktop companion for PDF extraction and analysis. Companion installers already
include the extension; use this ZIP to load or update it separately.

**Unsigned development builds:** operating systems may warn or block installation.
Do not disable security protections. Windows installation/browser integration and
Intel macOS execution are not yet tested. Signed production builds are unavailable.
AI estimates currently show **Unavailable**; no model weights or approved
calibration are included. See [release limitations](docs/DISTRIBUTION.md).

1. Extract the ZIP. Open **Verity Installer.app** on macOS or **VeritySetup.exe**
   on Windows and approve installation if permitted by the operating system.
2. In Chrome or Edge, enable Developer mode and **Load unpacked** using the
   `chrome-extension` folder shown in Finder or Explorer.
3. Open a PDF and click the extension. Pairing, runtime setup and helper
   startup/restart are automatic—no terminal, Python setup or pairing token.

First installation needs internet. The helper stops after 30 idle minutes. Linux,
native Windows ARM64, 32-bit Windows, Safari and mobile are not supported.

## Build for development

With Node.js 20 or newer, build the extension or an installer:

```sh
npm run build
npm run build:extension
npm run build:installer
npm run build:installer:windows
```

In Chrome or Edge, enable Developer mode on the extensions page, choose **Load
unpacked**, and select `product/dist/chrome`. A Firefox-compatible popup build is
at `product/dist/firefox`; install its manifest temporarily for development.
Firefox PDF-viewer access varies by browser permissions and remains experimental.
The macOS installer archive is `product/dist/installer/macos/Verity-macOS.zip`.
Windows installer builds additionally need the maintainer toolchain described in
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md); normal users need no build tools.

## Manual developer helper (optional)

Python 3.11 is recommended for the local helper. Provision its runtime using
the [development setup](docs/DEVELOPMENT.md). No document is sent to a cloud AI
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

## Repository layout

- `product/extension` — browser UI, document capture and connection.
- `product/engine` and `product/installer` — local analysis and desktop provisioning.
- `product/tests` and `product/tools` — required tests, fixture generators and asset/calibration tools.
- `docs` — development, distribution, security and model guidance.

Generated installers are distributed through GitHub Releases, not committed.
Internal reports, historical research, credentials and model assets are excluded.

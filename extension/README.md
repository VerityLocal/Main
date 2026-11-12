# Verity Local browser extension

Manifest V3 extension for Chrome/Edge. Uses your local models and locally bundled
PDF.js. Detector signals are **not evidence of AI authorship**; neither detector
is validated for university submissions.

Version 0.4 adds a **small toolbar popup**. It analyzes the current PDF without
opening a review tab. Detailed evidence opens only when you request it.

**[Illustrated setup guide](../docs/SETUP.md)** · **[Ready-to-load download](https://github.com/VerityLocal/Main/releases/download/v0.4.0/Verity-Local-Extension-v0.4.0.zip)** · **[Website](https://veritylocal.github.io/)**

Install the Python dependencies and model weights using the project setup guide
before starting the backend. Release ZIPs include the PDF.js bundle; Git clones
need the build step below (Node.js 22.13+).

## Open it in your normal browser

1. From this directory run `npm ci --ignore-scripts` then `npm run build`.
2. Open `chrome://extensions` (Edge: `edge://extensions`). Enable Developer mode.
3. Click **Load unpacked** and select this `extension/` folder.
4. Copy the extension ID shown on the extension card.
5. From the project root start the backend:

   ```sh
   source .venv/bin/activate
   python -B -m backend.scripts.run_local --extension-id YOUR_EXTENSION_ID
   ```

6. Open the extension's **Settings**. Use `http://127.0.0.1:8000` and copy the
   token from `.local/backend-token` into the password field. Save and test.
7. Open a PDF in a browser tab and click the extension toolbar button. The popup
   starts analysis when access is available; otherwise click **Allow this site &
   analyze** or **Choose PDF instead**.
8. Read separate **AI-text flag rate** and **AI-code flag rate** percentages.
   Click **View detailed results** for the existing evidence-review tab.

After updating an unpacked installation, click **Reload** on its extension card.
Chrome 116+ (or compatible Edge) is required for offscreen document APIs.

The launcher uses installed `.venv-extraction/` and `.tools-ocr/` automatically.
Without that launcher, configure parser paths and bearer token explicitly.
The browser-test scripts expect a separately started backend on **port 8765**.

## Review

- The popup stays small; opening or closing it does not open a detailed tab.
- Analysis continues after the popup closes. Reopening on the same PDF resumes
  the same session, without submitting a duplicate job. **Re-analyze** explicitly
  submits a new job using the retained bytes.
- The detailed tab receives the same PDF and completed analysis through trusted
  extension messaging/a temporary Blob URL. No second download or model run.
- Popup percentages mean **share of analyzed content flagged**, separately for
  text and code. Missing/unsupported content is **Not scored**, not 0%.
- **Open manual PDF/source review** retains the original `.pdf`, `.py`, `.js`, and
  `.txt` upload workflow and configurable threshold. The popup uses threshold 0.5.
- Prose and code have separate detector-signal summaries.
- Review **all analyzed**, **flagged**, **unscored**, and **excluded/uncertain**
  passages. Missing scores are not zero scores or proof of human authorship.
- **View location** highlights original source ranges or extracted PDF line boxes.
- File upload limit: 50 MiB. Original-tab PDF capture: 8 MiB. The toolbar click's
  temporary active-tab access may suffice; request only that site's permission
  when needed. Login/viewer pages and redirects fall back to explicit upload.
- Local `file://` PDFs require **Allow access to file URLs** in extension details
  and file-origin permission. The popup explains this; **Choose PDF instead**
  works without it. Embedded/`blob:`/protected browser viewers are not injected
  into or bypassed.
- When using the popup's file picker, keep the popup open while it reads/transfers
  the file. After submission, analysis survives closing the popup. An abandoned
  partial file transfer is discarded within 60 seconds.
- Temporary sessions retain at most three PDFs / 64 MiB of document bytes. Oldest
  sessions may be evicted; finished sessions expire within 15 minutes. Reloading
  the extension/browser, navigating the original tab, or closing it discards its
  session. A detailed tab already displaying a document keeps its own in-memory
  copy until cleared or closed.
- **Clear review** removes this tab's document/results. It does not cancel an
  already submitted backend job; backend results expire from memory. Clearing a
  popup-origin detailed review also releases its shared extension session.

## Privacy and security

No content scripts, CDN scripts, or document syncing. The bearer token is stored
in trusted extension storage and sent only to the configured loopback backend.
Student document bytes/results remain in tab/offscreen/backend memory, not browser
storage; backend parser files are temporary. Empty offscreen documents close
automatically. Runtime messages are restricted to trusted extension pages and
the service worker. The API requires a bearer token and the exact configured
extension origin. Remote tab capture never includes the backend token.

Docling layout assets have not been downloaded or approved; the current backend
uses native PyMuPDF/pdfplumber and local Tesseract. OCR code is withheld by default.
Parser isolation is a bounded subprocess, **not a hardened OS sandbox**.

## Testing

Backend (from project root):

```sh
PDF_AI_RUN_MODEL_TESTS=1 PDF_AI_RUN_LOCAL_TOOLS=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  python3 -B -m unittest discover -s backend/tests -v
```

The actual-browser test script uses a visible, isolated Chromium test profile
with this unpacked extension and a loopback DevTools port 9223:

```sh
cd extension
npm test
```

From the project root:

```sh
node extension/scripts/browser-smoke.mjs
node extension/scripts/browser-popup.mjs
```

The first checks manual PDF/source review. The second opens **actual Chrome
toolbar popups**, verifies close/reopen continuation and same-result detail
handoff, and runs a temporary loopback-only PDF fixture server. It also checks
viewer/login, redirect, size-limit, manual-upload, and local-file-access states.
Unit tests cover denied permissions, trusted-message boundaries, byte limits,
session expiry/eviction, and navigation/clear races. Native permission dialogs
are not silently approved or bypassed by the tests.

Results/screenshots are written to `.local/browser-tests/`. Test screenshots may
contain the selected PDF's passage text: treat them as private local artifacts.
The JSON report records status/coverage, not student passage text or credentials.

# Development

The maintained product is entirely in `product/`. Historical research, private
assets and generated outputs are not repository inputs.

## Extension

Node.js 20+ is required; the build and JavaScript tests have no npm dependencies.

```sh
npm run build
npm run build:extension
npm test
```

Load `product/dist/chrome` through Chrome/Edge's **Load unpacked** control.
`product/dist/downloads/Verity-Extension.zip` is the same extension package for
macOS and Windows. It still requires the matching desktop companion for analysis.
`product/dist/firefox` is an experimental temporary-install build.

## Local helper and Python tests

Use Python 3.11 and a dedicated development environment:

```sh
python3.11 -m venv product/.runtime
product/.runtime/bin/python -m pip install -r product/runtime-requirements.txt
product/.runtime/bin/python -m playwright install chromium --only-shell
product/.runtime/bin/python -m unittest discover -s product/tests -p 'test_*.py'
product/.runtime/bin/python -m product.engine.server --init
```

To enable the reviewed local model profile explicitly (about 1.9 GB on an 8 GiB+
machine, with ~29 GB additional Falcon downloads only on 64 GiB+ machines):

```sh
product/.runtime/bin/python -m pip install --only-binary=:all: -r product/model-requirements.txt
product/.runtime/bin/python -m product.engine.model_setup --root product/.local --pins product/model-pins.json --config product/.local/helper.json
```

This is a setup-only network operation; analysis never calls the downloader.
The command preserves private pairing/custom settings. Code assets and independent
calibration are not invented by setup. Read [model availability](MODELS.md) before
running it on a large-memory workstation; it can download the full Falcon pair.

On Windows use `product\.runtime\Scripts\python.exe` in place of the macOS/Linux
interpreter path. Pair the extension's exact origin with `--allow-origin`, start
`python -m product.engine.server` with that interpreter, and enter the generated
private token under **Advanced development connection**. Installer users do not
need these steps. Do not commit `product/.local/helper.json`.

## Browser acceptance fixtures

```sh
npm run build
npm run demo
product/.runtime/bin/python -m product.tests.browser.run
```

PDFs are generated automatically from first-party text. Only source retrieval is
controlled; parsing, segmentation, browser APIs and export are real. AI predictions
are not mocked. The ordinary panel tab substitutes side-panel active-tab semantics
and loopback document permissions, so production toolbar prompts are not proven.
Generated PDFs, screenshots and reports are ignored by Git.

`python -m product.tests.browser.model_run --profile product/.local/models-profile.json`
performs genuine offline Desklib/BGE inference, verifies asset hashes and resource
abstention, and asserts that uncalibrated document percentages stay unavailable.
It is a functional smoke test, not an independent accuracy benchmark.

`product.tests.browser.desktop_run` tests actual native messaging against an
explicit sandbox macOS installation using `--install-root` and `--browser-home`.
Add `--require-models` for a model-enabled installation to verify genuine prose
inference in exported segments, safe short-text abstention and setup-status labels.
Never point it at an unrelated installation. Windows package structure is checked
with `python -m product.tests.browser.windows_package`; this does not execute
Windows or prove its browser integration.

## Desktop installers

```sh
npm run build:installer
npm run build:installer:windows
```

The macOS archive must be packaged on macOS. Windows cross-builds additionally need
Go 1.22+ on the maintainer machine; set `VERITY_GO` if it is not on PATH. End users
need neither Go nor Python. Portable archive/provisioning tests run with `go test`
in `product/installer/windows` on macOS/Linux. Set
`VERITY_WINDOWS_RUNTIME_ARCHIVE` to the pinned archive to test real extraction.

See [distribution](DISTRIBUTION.md) for release gates and [models](MODELS.md) for
explicit local asset provisioning and calibration.

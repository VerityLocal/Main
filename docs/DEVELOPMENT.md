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

`product.tests.browser.desktop_run` tests actual native messaging against an
explicit sandbox macOS installation using `--install-root` and `--browser-home`.
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

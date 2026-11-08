# Python desktop development

Normal users extract and open the platform app ZIP. Commands here are only for
maintainers. Build **natively** on macOS Apple Silicon or Windows x64 with CPython
3.11 and working Tcl/Tk (macOS build: 3.11.12; Windows CI: 3.11.9).
No Node.js, Go, extension or web server is used.

## Runtime and model staging

Create a dedicated environment; install `product/desktop-requirements.txt` and
`product/build-requirements.txt` with binary wheels. On Windows use the official
PyTorch CPU wheel (`torch==2.7.0+cpu`) from `https://download.pytorch.org/whl/cpu`
before installing the other requirements. On macOS use the regular arm64 wheel.

```sh
python -m pip install --only-binary=:all: -r product/desktop-lock.txt -r product/build-requirements.txt
python -m playwright install chromium --only-shell
python -m product.packaging.prepare --output product/.local/desktop-bundle --browsers PATH_TO_PLAYWRIGHT_CACHE
python -m product.desktop.main
```

`prepare` intentionally downloads only reviewed Desklib/BGE snapshots, using exact
revisions, byte counts and SHA-256 pins. Add `--models PATH_TO_EXISTING_MODELS` to
copy already-verified snapshots without downloading. Original files are never
changed. Always choose a **new** output directory. This build-time acquisition
is never called by the desktop app. Keep model assets and browser caches ignored.

## Tests and frozen app

```sh
python -m unittest discover -s product/tests -p 'test_*.py'
python -m product.packaging.build --bundle product/.local/desktop-bundle --output product/dist/standard-native
```

Run the resulting **actual executable** with `--acceptance-output NEW_FOLDER`.
On macOS it is `Verity.app/Contents/MacOS/Verity`; on Windows it is
`Verity/Verity.exe`. Assert the resulting `acceptance.json` has `passed: true` and
`frozen: true`. The ordinary app needs no arguments.

Acceptance exercises all four real Tk tabs, complete model integrity, PDF parsing,
genuine Desklib/BGE inference with Python outbound networking blocked, a real
bundled browser with in-memory routed content, coverage, unavailable AI percentages,
selection/highlights, explicit exports, edit invalidation, hard cancellation,
consent revocation and memory clearing. First-party text is a **functional fixture**,
not independently labeled evaluation data. It does not prove live-search recall,
OS signing, clean-machine compatibility or detector accuracy.

Chromium is copied after freezing to preserve its own native binary layout and
notices. macOS output receives an ad-hoc signature, not notarization. Do not inject
signing credentials into source. `product/packaging/verity.spec` excludes obsolete
server/native-host code and excluded model dependencies.

Archive and verify the ZIP, then extract it into a new directory and run acceptance
again. Measure the final ZIP and enforce GitHub's **under 2 GiB per asset** limit.
Windows CI must build and execute its actual native app; cross-build metadata is
not acceptance. See [distribution](DISTRIBUTION.md).

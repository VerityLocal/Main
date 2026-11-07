# Windows desktop distribution — development build

## Normal-user flow

Double-click `VeritySetup.exe`, approve installation, and load the extension folder
shown in Explorer into Chrome or Edge. No terminal, Python installation, pairing
token, PowerShell script or execution-policy change is needed. Opening the panel
starts/pairs the installed helper; future reads and panel reopens restart it as
needed. PDF-origin permissions remain ordinary browser permissions.

Target: **Windows 10/11 x64**, per-user installation. Native ARM64 and 32-bit builds
are not implemented. The installer explicitly requests `asInvoker`, not administrator
elevation. First installation requires internet; it does not upload documents,
download AI checkpoints or create an always-running/login service.

Outputs:

- `product/dist/installer/windows/VeritySetup.exe`
- `product/dist/installer/windows/Verity-Windows.zip` (executable, checksum and notices)

These are unsigned **development artifacts**, not a Windows-validated public release.

## Maintainer build

Install Node.js 20+ and Go 1.22+ on the build machine, then:

```sh
npm run build:installer:windows
```

Set `VERITY_GO` to the Go executable if it is not on PATH. No Go compiler is shipped
or downloaded for end users. The build cross-compiles on macOS/Linux/Windows using
only the Go standard library and no Windows SDK, resource compiler or third-party
module downloads. A first-party COFF resource embeds the non-admin manifest.

`npm run build:installer` retains the macOS-only build and does not acquire a Go
dependency. Both builds include the new portable OS boundary in the Python engine.

## Installation and native bridge

- Installs in `%LOCALAPPDATA%\Verity\versions\<unique-release>` with a progress
  window and cancellation. A protected inherited DACL grants access only to the
  current user and SYSTEM. Reparse points/junctions are rejected at the private
  installation boundary. Settings persist under `%LOCALAPPDATA%\Verity`.
- The GUI executable embeds only allowlisted first-party payloads and compiler
  licensing. Every embedded file is bound to its SHA-256 manifest; extra, changed
  or missing files fail extraction. Runtime archive paths, special files, links,
  reserved Windows device names, ADS paths and traversal are rejected; extraction
  and download sizes are bounded.
- Downloads standalone Python 3.11.18 from the same release as macOS, using an
  independently pinned Windows x64 digest. Verifies it before extraction. Installs
  binary runtime wheels and the headless source-retrieval browser separately from
  their official endpoints. Transitive dependency locks/license approval remain
  release gates. No model downloads occur.
- Copies the executable as `native-host.exe` into the promoted private release.
  Native mode forwards binary stdin/stdout to the fixed isolated Python entrypoint
  without invoking a shell. Browser messages cannot choose commands or paths.
  Caller-origin validation, bearer authentication, narrow pairing/lifecycle APIs,
  saved-token preservation and idle shutdown are shared with macOS.
- Registers **HKCU only**, in both 32-bit and 64-bit registry views, under
  `Software\Google\Chrome\NativeMessagingHosts`,
  `Software\Microsoft\Edge\NativeMessagingHosts`,
  `Software\Chromium\NativeMessagingHosts`, and
  `Software\Mozilla\NativeMessagingHosts`. The default value points to the private
  Chrome/Firefox manifest; permissions bind to the same stable extension identities.
  No HKLM writes or administrator commands are used.
- Every existing registration is checked before pairing/writes. Unrelated pointers
  are preserved; failed registration rolls back only default values this invocation
  changed. Active runtime/settings are not overwritten or deleted. Failed staging
  cleanup is limited to this installer's unique temporary directory; a promoted
  release is retained on later failure.
- Windows uses byte-range bootstrap locking, binary native stdio and hidden
  new-process-group helper startup. Cancellation targets only the dependency child
  tree created by the installer. Install logs contain component diagnostics, not
  tokens or document text. Normal operations do not print secrets in command lines.

## Validation boundary

The build was produced on macOS using a digest-verified build-only compiler. The
downloaded Windows Python archive was also digest-verified and extracted by the
installer's real archive logic **without executing Windows binaries**.

Run portable checks:

```sh
go test -v ./...
```

from `product/installer/windows`. Set `VERITY_WINDOWS_RUNTIME_ARCHIVE` to the pinned
download to include real-archive extraction; otherwise that test explicitly skips.
The other tests use controlled payload/runtime/process fixtures, not a Windows
installation or model prediction.

Additional checks:

```sh
npm test
product/.runtime/bin/python -m unittest discover -s product/tests -p 'test_*.py' -v
product/.runtime/bin/python -m internal.demo.windows_package
```

Windows Python paths differ on a Windows development host; the commands above
describe this macOS build environment. Registry unit tests use an explicit in-memory
HKCU/view fixture, never the maintainer's actual registry. Package validation reads
the real PE resource tree and embedded ZIP: AMD64 GUI subsystem, `asInvoker`, exact
source hashes, approved identities, archive checksum and retained licensing. Its
report is `internal/demo/screenshots/windows-package-validation.json`.

Executed checks on 2026-11-07:

- Windows `.exe` and download ZIP cross-build passed; the real PE manifest/resource
  and embedded payload/archive validation passed. The executable is **unsigned**.
- **39 Python tests**, **11 JavaScript tests**, and **7 portable installer test
  groups** passed. These include actual pinned Windows archive extraction, controlled
  install promotion/failure cleanup, HKCU registry collision/rollback/reinstall,
  private-path rejection and cross-platform native process policy.
- The existing MV3 PDF/source/export/invalidation fixture demo passed after the
  portable engine changes. Its browser and helper execute on macOS, not Windows.
- No Windows binaries, real Windows registry writes, Windows GUI/ACL operations or
  Windows browser native messaging were executed. The corresponding acceptance
  gates below remain open; no Windows functionality/accuracy validation is implied.

## Before public release

1. Execute the installer on clean Windows 10/11 x64 machines: downloads/dependency
   installation, actual DACLs, cancellation/repair/reinstall, relocation, Unicode
   and spaced usernames, no-admin operation, native launch, no console flashes,
   no manual token, PDF extraction, offline scan and automatic restart/idle exit.
2. Test real Chrome/Edge default-profile and toolbar/native-host discovery, both
   registry views, Firefox's UUID/caller arguments and PDF viewers. Portable tests
   and the macOS native smoke do **not** establish these Windows outcomes.
3. Authenticode-sign the executable using the owner's credentials, repack the ZIP
   and checksum, and review download hosting and SmartScreen behavior. No credentials,
   security bypass, release upload or Windows VM was supplied/attempted here.
4. Bind to reviewed store identities and fulfill runtime/browser/compiler license
   and dependency supply-chain obligations. Notices are retained; internal credits
   alone are never sufficient for redistribution.
5. AI weights/approved calibration and live-source/accuracy validation remain
   separate gates. The installer does not supply unavailable predictions.

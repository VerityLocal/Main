# One-click desktop distribution — macOS development build

## What a normal user does

Open `Verity Installer.app`, approve **Install**, and load the extension folder
shown in Finder. There is no Python/terminal/pairing-token setup. The browser then
uses the installed native messaging host to pair and start the local helper on
demand. A stopped idle helper is restarted automatically before a read/scan.

Build the app and ZIP with `npm run build:installer`. Output:
`product/dist/installer/macos/Verity-macOS.zip`. The script-based app supports Intel
and Apple Silicon Macs on macOS 14+; first installation requires internet. It does not request
administrator access, install a login agent, change historical project environments
or download any AI checkpoints. A Windows 10/11 x64 development installer is now
implemented separately; see `internal/windows_distribution.md`. Linux installer
support is not implemented.

## Runtime and security boundary

- Installs in `~/Library/Application Support/Verity/versions/<unique-release>`.
  A digest-pinned standalone Python archive is verified before extraction. Runtime
  packages and browser components are installed separately from their official
  registries/distribution endpoints. Their package metadata/licenses are retained.
- The engine/calibration and extension are first-party allowlisted payloads. Each
  runtime release is immutable by convention; reinstalls do not overwrite an active
  runtime, secrets, model configuration or unrelated native-host registrations.
- `helper.json` is generated automatically with a private token and paired origin.
  Atomic owner-only configuration writes and a native bootstrap lock preserve the
  token across simultaneous opens and reinstalls. Installer logs never print it.
- Per-user native host `local.verity.helper` is registered for Chrome, Edge,
  Chromium and Firefox on macOS. Chromium's allowed origin is derived from the
  extension's stable public manifest key; Firefox uses `verity@local.invalid`.
- Native input is bounded length-prefixed JSON, supporting only the `bootstrap`
  operation. The JSON origin must match the browser-supplied caller arguments and
  the approved extension identity. No file paths, text, models or shell commands
  can be supplied by the browser message.
- The native host starts an isolated installed Python entrypoint, checks the
  authenticated helper identity/version, and pairs the running origin. No token
  is placed in URLs, command-line arguments or logs. Only trusted extension
  contexts store the returned token.
- Helper lifecycle/pairing endpoints require the private bearer token and reject
  web-origin requests. A conflicting service is not terminated. An authenticated
  older installation can be gracefully replaced; no arbitrary process is killed.
- The helper stops after 30 idle minutes when no scan is active. Existing manual
  developer setups keep their original lifetime policy. No document is uploaded
  during install/bootstrap; source search still needs explicit consent.

## Development validation

Unit tests cover framing, caller impersonation, port conflict, preserved settings,
registration scope/collision, symlink/path-traversal rejection, installer payload
guards, native API validation, and authenticated pairing.
A real isolated native subprocess test starts the helper and extracts a PDF through
it. The existing MV3 fixture test exercises the explicit **advanced developer**
connection, so it does not by itself validate OS native-host discovery.

For a clean installation smoke without touching the maintainer's actual browser:

```sh
VERITY_INSTALL_ROOT="/approved/sandbox/home/Library/Application Support/Verity" \
VERITY_BROWSER_HOME="/approved/sandbox/home" \
zsh "product/dist/installer/macos/Verity Installer.app/Contents/Resources/install-macos.sh" --headless
```

These overrides are test-only; normal users double-click the app. Verify installed
runtime relocation, real Chrome/Edge native-host discovery, restart/reinstall,
Firefox UUID pairing, UI dialogs, slow/download failure, and user cancellation.
The Intel download is pinned but must be executed on an Intel acceptance machine.

The headless installer completed on this Apple Silicon development Mac in an
isolated browser home. It downloaded and digest-verified standalone Python
3.11.18, installed binary runtime packages and headless browser components, and
registered the native host without touching the maintainer's actual registrations.
An initial configuration-write error was corrected and the installer was rebuilt
before the successful retry. This tests provisioning, not Finder dialogs or a
quarantined public download.

For an actual MV3/native smoke against that sandbox:

```sh
product/.runtime/bin/python -m internal.demo.desktop_run \
  --install-root "/approved/sandbox/home/Library/Application Support/Verity" \
  --browser-home "/approved/sandbox/home"
```

The test copies the installer's real native manifest into its explicit Chromium
user-data directory. Native APIs and the installed helper are not mocked; only
the side-panel active-tab semantics and loopback document permission are fixtures.
Do not run this concurrently with other tests/demos using helper port 8790.

Final development checks on 2026-11-07:

- `npm run build:installer` rebuilt the unsigned `.app`/ZIP from the final
  allowlisted sources; shell syntax and bundle property-list checks passed.
- **34 Python tests** and **10 JavaScript tests** passed, including rejection of
  unrelated registrations, escaped host paths and unexpected/symlinked payloads.
- The actual MV3/native smoke **passed and exited cleanly**. It started the installed
  standalone helper, paired without token entry, extracted a real PDF, ran an
  offline review, preserved the token on repeat bootstrap, and automatically
  restarted before a read and after reopening the panel. No **Connect** click or
  advanced pairing was needed. Evidence is in
  `internal/demo/screenshots/desktop-validation.json` and `automatic-companion.png`.
- The first corrected native smoke completed its assertions but timed out during
  teardown. The test now stops its sandbox helper before bounded browser cleanup
  and uses daemon fixture-server threads. The subsequent full run exited normally.
- `npm run demo` also passed the existing PDF/source-evidence/export/invalidation
  fixture flow after the final installer build. Neither smoke supplies AI scores.

These checks do not validate default-profile Chrome/Edge toolbar installation,
Firefox native messaging/viewers, Intel execution, Finder installer dialogs,
installer cancellation/failure UX, or signed/quarantined downloads. Those remain
acceptance gates; no production AI or live-source accuracy claim follows from them.

## Public release gates

1. **Sign and notarize the macOS app/ZIP** using the owner's Apple Developer
   credentials, then test a quarantined download. This repository's generated app
   is unsigned. Do not use Gatekeeper bypasses or tell users to disable security.
2. Publish the signed download through a reviewed distribution channel. No hosting,
   signing credentials or release upload has been configured by this change.
3. Bind native manifests to the actual store extension identity before a store
   release. The stable unpacked key is a development identity, not a store signing
   key; no private signing key was generated or retained.
4. Review standalone Python, native parser, browser binary and transitive notices,
   distribution/download terms, dependency locks and supply-chain acceptance.
   Internal attribution alone never substitutes for required LICENSE/NOTICE files.
5. AI model/license/calibration gates remain unchanged. This installer makes the
   current local engine easy to start; it does not create unavailable model weights,
   trained AI probabilities, detection accuracy or a production fine-tuning claim.

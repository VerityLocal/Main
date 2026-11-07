# Desktop distribution

Downloads: https://veritylocal.github.io/ ·
Development release: https://github.com/VerityLocal/Main/releases/tag/v0.2.0-dev.1

`Verity-Extension.zip` is one Chrome/Edge package shared across macOS and Windows.
It does not replace the local companion: install the matching desktop companion
for PDF extraction and analysis. Companion installers already include this extension.

## Current status

The macOS and Windows downloads are **unsigned development builds**, not signed,
production-validated installers. macOS may block the app; Windows may warn or block
the executable. Do not disable operating-system security to run them. Signed
installers are not yet available.

| Platform | Target | Validation boundary |
| --- | --- | --- |
| macOS | 14+, Intel / Apple Silicon | Apple Silicon sandbox installation and actual Chromium native messaging passed; Intel and normal toolbar/profile flows remain untested. |
| Windows | 10/11 x64 | Cross-build, PE manifest, archive integrity and portable provisioning checks passed; real Windows installation, DACLs and browser integration are not tested. |

Linux, native Windows ARM64, 32-bit Windows, Safari and mobile installation are not
supported. Chrome/Edge unpacked installation is manual; this is not a store listing.
Firefox compatibility is experimental. Weights are not bundled; installers acquire
reviewed models where hardware permits. No independently approved calibration ships.

## What installers do

- Download and verify digest-pinned standalone Python, then separately install
  runtime wheels and the headless retrieval browser. First install needs internet.
- Install direct-pinned ML dependencies and acquire per-file hash-pinned Desklib
  and BGE-small snapshots (~1.9 GB on 8 GiB+ machines, plus runtime/dependencies).
  The Falcon pair adds ~29 GB only on 64 GiB+ machines. Available-RAM gates also
  apply at inference. GPTSniffer and production code-corpus setup remain blocked;
  AI percentages stay unavailable until independently calibrated. See [MODELS.md](MODELS.md).
- Install per-user, without administrator setup. macOS uses
  `~/Library/Application Support/Verity`; Windows uses `%LOCALAPPDATA%\Verity`.
- Register a narrowly permissioned native host for the fixed extension identities.
  Windows uses HKCU in both registry views and an `asInvoker` GUI executable.
- Preserve pairing/settings across upgrades, start/restart the authenticated helper
  on demand, and stop it after 30 idle minutes. No login service is installed.
- Keep local environments, model checkpoints and private documents out of the
  downloadable payload. Adapter notices remain in both installers; Windows ZIPs
  also retain compiler licensing. Downloaded runtimes keep their own notices.

## Release requirements

Development downloads are explicitly labeled as prereleases. Before a production
release: test clean installation, repair/reinstall, cancellation, automatic native
startup/restart and PDFs on every supported platform/browser; complete dependency,
license and network-policy reviews; lock transitive dependencies; sign/notarize
macOS output and Authenticode-sign Windows output. Recompute checksums after signing.

Signing credentials are never committed. Package notices must be retained; making
source available does not grant permission to redistribute restricted model assets.
AI accuracy, independent calibration and live source recall are separate validation
gates, not consequences of successfully building an installer.

Release assets live on GitHub Releases, not in the source tree. `SHA256SUMS.txt`
identifies the exact extension and installer ZIPs; checksums detect accidental changes, not
publisher identity or operating-system signing.

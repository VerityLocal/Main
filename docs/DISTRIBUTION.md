# Standard desktop distribution

Release: https://github.com/VerityLocal/Main/releases/tag/v0.3.0-dev.1
Website: https://veritylocal.github.io/

The Standard ZIP contains one native frozen Python app, all dependencies,
Desklib/BGE weights and tokenizers, immutable configuration and license notices.
There is no installation downloader, extension registration, listener port, helper
service, startup item or pairing token. Local first launch/inference works offline.

| Platform | Asset | Validation gate |
| --- | --- | --- |
| macOS Apple Silicon | `Verity-Standard-macOS-arm64.zip` | Actual native frozen-app and re-extracted ZIP acceptance on Apple Silicon. Other macOS versions need separate testing. |
| Windows x64 | `Verity-Standard-Windows-x64.zip` | Build and execute on a native Windows runner; publish only after its frozen-app and re-extracted ZIP reports pass. |

Only accepted assets are published. Intel macOS, Windows ARM64, 32-bit Windows,
Linux and mobile are not offered. Keep the `.app` intact on macOS and the complete
Verity folder intact on Windows. No user Python installation is required.

## Development limitations

Unsigned development prerelease. macOS has only an ad-hoc signature, no Developer
ID/notarization; Windows is not Authenticode-signed. OS security may block launch.
Never advise disabling OS protections. Signing and independently calibrated AI
percentages remain unavailable. Functional inference is not detector accuracy.

The exact ZIP sizes and SHA-256 digests belong to the release metadata and
`SHA256SUMS.txt`; never describe the raw 1.9 GB model size as the whole app ZIP.
Each ZIP must be **smaller than 2,147,483,648 bytes**. Checksums detect changes,
not publisher identity or signing trust.

## Publication gate

1. Test unit/controller/GUI cases and the genuine native packaged app.
2. Check all pinned model files, licenses, Python/Tcl/Tk, dependencies and retrieval
   browser. Ensure no credentials, private input, profiles, source environments or
   obsolete extension/installer payloads are included.
3. Archive without breaking app symlinks/executable modes. Verify contents, byte
   size and hash; re-extract and re-run actual executable acceptance offline.
4. Record tested OS/architecture and the validation boundary. Live web recall,
   broader clean-machine acceptance, vulnerability review, signing and independent
   calibration are separate production gates.
5. Push accepted source and create a **new prerelease**. Never replace prior
   downloads. Update website/profile links only to published accepted assets.

Previous `v0.2.0-dev.1` assets are the retired extension/companion architecture and
remain preserved. The prior source is in Git history and a local ignored archive.

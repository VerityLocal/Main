# Maintainer runtime setup — internal

Normal macOS and Windows users use the generated desktop installers, not the commands below.
See `internal/desktop_distribution.md` for installer builds, automatic native
pairing/startup and signing/distribution gates. Windows build/runtime acceptance
is documented in `internal/windows_distribution.md`. Manual setup remains optional
for development and other platforms.

Do not replace/delete the historical `.venv`, `.env`, models or databases. The new
runtime is independent, on port 8790; the old service used 8787.

```sh
python3.11 -m venv product/.runtime
product/.runtime/bin/python -m pip install -r internal/runtime-requirements.txt
product/.runtime/bin/python -m playwright install chromium
npm run build
product/.runtime/bin/python -m product.engine.server --init
```

Windows: use `product\.runtime\Scripts\python.exe` instead of `bin/python`.
Pair using the installed extension origin, enter the token from
`product/.local/helper.json`, then run `python -m product.engine.server` with the
runtime interpreter. Neither the token nor document text is printed in API logs.
The helper accepts only its fixed loopback Host, exact paired origins and bearer
authentication; mutation requests require JSON/auth preflight. No websites receive
credentials. PDF endpoint accepts bytes only, never file paths/remote URLs.

`internal/runtime_config.example.json` documents optional signal configuration.
Acquire model snapshots **explicitly**, under reviewed license terms and exact
revisions. Install optional compatible ML dependencies in a separate reviewed
environment (see requirement comments); these are not installed automatically.
Register local paths/checksum manifest, confirm classifier AI-label mapping, set
license approval, train an exact-signature calibration head using real data and
merge approved heads into the extension artifact. Desklib needs its explicit
mean-pooling wrapper; a generic classification pipeline is not equivalent.
GPTSniffer cannot be assumed licensed or trained by a base CodeBERT download.
SameCode needs a provenance-bearing known-AI code corpus; similarity alone is not
AI probability. Binoculars is very memory-intensive. Do not enable blindly.

For each intentionally provisioned model/corpus, copy it into a dedicated immutable
directory (no symlinks) and inventory it before training:

```sh
python -m internal.retraining.hash_assets --config product/.local/helper.json --signal text --output private/manifests/text.json
```

Set the printed `asset_manifest` and `asset_manifest_sha256` in that signal's
configuration; repeat for `ratio`, `code`, `code_match` and optional `semantic`.
The loader checks the manifest digest and every file, including added/missing files,
before initial loading. Keep assets read-only during the process lifetime and
restart/recalibrate after updates. This protects accidental drift, not a hostile
local operator who can change both config and assets. Missing/invalid integrity
metadata abstains; a `snapshot_id` label alone cannot enable inference.

Model scoring has no hard native-call preemption: cancellation is cooperative
between segments; a currently executing native model/parser operation can finish.
Search uses a bounded top-3 candidate policy and 24-query default. Search challenge,
missing browser or inaccessible pages produce unavailable/partial coverage.
Each query is capped at 90 seconds; page/runtime cleanup has separate five-second
deadlines. Retrieval allows only the expected top-level navigation: frames,
subresources and unexpected refresh navigation are blocked. DNS/native HTTP calls
are not hard-preempted by async cancellation; deployment still needs OS-level
resource isolation and network/security acceptance.
Private-address DNS results and redirects are rejected; HTTPS connections are
pinned to validated public IPs. No subresource/script browsing is allowed. This
will miss JavaScript-only sources, authentication-gated pages and some search
providers; do not present failures as 0% plagiarism.

Release checklist: tests; model/data/license provenance; browser lifecycle across
Chrome/Edge/Firefox; independent calibration/false-positive evaluation; search
terms/robots/access policies; SSRF and local helper security review. Required
redistribution notices must ship in any future vendored helper/model distribution.

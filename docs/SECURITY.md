# Privacy and security

Verity is a native Python desktop application with an automatically owned worker
process. It opens no listener port, starts no HTTP server, registers no native
messaging host and creates no pairing token or login service. Documents,
preferences and results stay in memory; only explicit JSON/text exports are saved.
Original PDFs are read only. Exports contain document text: treat them as private.

Local model inference is offline from first launch. Hugging Face/Transformers
offline flags, telemetry suppression, local-only loaders, safetensors and disabled
remote code apply before lazy ML imports. Complete asset manifests are checked
against application-bound pins before cold loading. A hostile local user able to
rewrite the executable itself is outside this integrity boundary.

Optional web comparison is disabled by default. Enabling it in Settings does not
grant scan consent: Review requires a fresh per-scan checkbox. Short excerpts go
to public search, then public source pages are fetched; no full-document upload or
cloud AI analysis occurs. Disabling comparison, editing input or cancelling revokes
consent. An in-flight consented request may already have sent an excerpt before
cancellation; cancellation cannot undo remote receipt.

Source retrieval rejects private-address DNS results and redirects, pins outbound
connections to validated public IPs, disables scripts/cookies/service workers and
blocks frames, subresources and unexpected navigation. Deadlines/input bounds apply.
Protected/JavaScript-only sites or search challenges can fail. Unavailable searches
are not zero overlap or proof of originality. Opening a source in the user's
browser is a separately confirmed external navigation.

Inference/PDF extraction stay off the Tk UI thread. Cancel kills the owned worker
and retrieval-browser descendants rather than waiting for native model/parser
code to return. macOS owns a process group; Windows owns a kill-on-close Job
Object, including descendant processes. This is process isolation, not a hardened
OS sandbox. Resource gates do not guarantee against OOM or native parser vulnerabilities.

Build-time preparation contacts model, package and browser distribution hosts;
no user document is involved. Runtime never starts that downloader. Retain all
license notices; keep credentials, personal files, environments, models and
generated assets out of Git. Development builds are not Developer ID/notarized or
Authenticode-signed. Checksums do not replace signing. Website/GitHub downloads
receive ordinary network metadata such as IP addresses.

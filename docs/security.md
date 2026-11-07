# Privacy and local API security

## Implemented foundation controls

- CLI accepts only loopback bind addresses; default `127.0.0.1:8787`.
- Exact Host validation (`127.0.0.1`, `localhost`, `::1`) and allowed port.
- Exact Origin allowlist with no wildcard, no `null`, no arbitrary web origins.
  Requests without Origin are allowed only with the token (local CLI clients).
- Two independently generated secrets: `X-Local-Token` on every API request;
  `X-CSRF-Token` additionally on unsafe methods. Constant-time comparisons.
- Trusted-origin preflight supports only approved methods and headers.
  Credentials/cookies are not used. CORS is not authentication.
- JSON-only mutation bodies, advertised and actual streaming request-size caps,
  body-read deadlines, a token-bucket request limiter, concurrency cap, and
  request execution timeout. One shared local rate bucket intentionally prevents
  spoofed forwarding/IP headers from creating unlimited buckets.
- Pydantic strict validation, extra-field rejection, checked offsets,
  immutable documents, stale-revision rejection and metadata hashes.
- Safe, fixed error messages; server-generated request IDs; access logging
  disabled; ordinary logs contain no submitted document, URL, token or headers.
- Revision registry stores only document IDs, revisions and SHA-256 digests,
  is bounded and TTL-expiring, and is cleared on process shutdown/restart.
- No automatic downloads or external retrieval without policy and request consent.

Secrets are generated into a git-ignored `.env`, with creation failing if the
file already exists. On Windows, the file inherits directory ACLs; this does
not protect against another process running as the same user. Keep it private,
use BitLocker/appropriate user permissions as needed, and never commit it.
The helper prints the path, not the secrets. `.env.example` is deliberately
not a working credential configuration.

## Deployment boundary

Run one worker. The application is local tooling, not an Internet-facing
service. The CLI refuses non-loopback binding, but a person launching uvicorn
directly can bypass that CLI check; Host checks are not a substitute for a
loopback socket. Do not use `--host 0.0.0.0`, a reverse proxy, or forwarded
headers. TLS between loopback processes is not implemented.

This threat model blocks ordinary malicious websites, DNS rebinding Hosts,
cross-origin requests, oversized requests, and accidental stale application.
It does not protect against administrator-level compromise, stolen secrets,
untrusted code running under the same account, or local denial of service.
Dependency versions are pinned for reproducibility, not a completed security
audit. Audit/update deliberately and regenerate the lock before deployment.

## Extension and external evidence

Start with `activeTab`, `scripting`, and minimal storage permission; request
loopback/website permissions only as needed. No unnecessary `<all_urls>`.
Persist settings/request cursors, not full documents by default. Do not analyze
passwords; configurable domain exclusions apply before extraction. Use the
isolated content-script world and safe text rendering. MAIN-world integration
needs a documented, tested boundary and is not the default.

Exact `chrome-extension://<id>` must be added to the backend allowlist before
an extension can connect. Never discover/accept arbitrary extension origins.
The side panel consumes authenticated fetch-based SSE; EventSource
cannot set the authentication headers used by this API.

External search is disabled by default. Both policy settings and request consent
must permit it. Wikipedia receives up to three sentence queries, each capped at
256 characters, through fixed HTTPS endpoints with no redirects/proxy environment,
three-second timeouts and at most two attempts. Sources retain nullable publication
date and retrieval timestamps; Wikipedia is unrated, not automatically trusted.
Evidence is untrusted data, never executable instructions. No search result
does not establish falsehood, nor does an NLI score establish source authority.

The manifest uses `activeTab`, `scripting`, `storage`, `sidePanel`, and only the
fixed loopback host permission. Local corpus and replay contain private source
text/evidence. Their SQLite files are plaintext under `%LOCALAPPDATA%\VerityLocal\data`
by default; removal is not encryption or secure erasure. Full submitted documents
are not persisted in extension storage; tokens/settings and request/cursors are.
Same-user malware can read these. The current workspace is under OneDrive:
exclude/move secrets, datasets and checkpoints out of synced folders. Git-ignore
is not a cloud-sync policy.

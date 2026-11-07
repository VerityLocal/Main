# Privacy and security

Authorship inference runs locally when explicitly provisioned. The extension does
not send documents to a cloud AI service. Web source comparison is off until the
user consents: short text excerpts go to search services and candidate public
sources are retrieved. Opening a remote PDF can contact its original site.

The desktop helper binds to `127.0.0.1:8790`, requires a bearer token and exact paired
browser origins, bounds request/concurrency/document sizes, and expires in-memory
terminal results after 30 minutes. Native startup validates browser caller identity;
pairing/shutdown requests require authentication. Installer/native-host permissions
are per-user, not system-wide.

Public-source retrieval rejects private-address DNS results and redirects, pins
connections to validated public IPs, blocks unexpected navigation, frames and
subresources, and imposes deadlines. It intentionally misses some protected or
JavaScript-only sources. Missing search results are not proof of originality.

Model loading is local-only with remote code disabled. Optional assets require
reviewed licenses, exact snapshots and a SHA-256-pinned complete file manifest.
Changed, missing, extra or linked assets cause abstention. This protects drift, not
a hostile local user able to rewrite configuration and assets together.

Cancellation is cooperative between segments; an executing native parser/model
operation may finish before cancellation takes effect. OS resource isolation and
platform/browser security acceptance remain production gates.

Only the pairing token is persisted by the extension. Exported reports include
document text: treat them as private. Never commit tokens, signing credentials,
personal PDFs, model weights or user profiles. The download website has no
analytics, forms, cookies or third-party scripts; GitHub hosting/downloads receive
ordinary network metadata such as IP addresses.

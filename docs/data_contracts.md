# Shared contracts

Contract version: `1.0.0`. JSON Schema dialect: 2020-12. Executable definitions
live in `backend/app/schemas/`; generated schemas in `shared/schemas/` are
checked against their source by regression tests. Extra keys are rejected.

## Canonical document

Required fields: `document_id`, `revision`, `language`, `blocks`,
`extracted_text`, `offset_unit`, `extraction_metadata`, `contract_version`.
Language is a BCP-47-shaped tag, or `und`; tag registration and actual language
identification are not claimed. All browser offsets are half-open UTF-16 units.

Each block contains `block_id`, `original_text`, `start_offset`, `end_offset`,
`adapter_ref`, `text_revision`, and `normalization`. IDs are unique within a
document. A block text revision cannot exceed the document revision.
`adapter_ref` is data (surface type and opaque locator), never executable code
or a serialized DOM node. An adapter must retain its own node/editor mapping.

The document's text must exactly equal the block texts joined with `\n\n`.
Every block boundary and map boundary must land on a Unicode scalar boundary.
The two-unit separators belong to the document, not the individual blocks.
Empty blocks and empty documents are rejected in v1. Block IDs must be reused
by the caller across revisions; the manual builder generates fresh UUIDs when
none are supplied and cannot infer cross-revision identity.

`extraction_metadata.scope`: `full_document`, `rendered_content`, `selection`,
or `manual`. This is not evidence that an adapter is supported. Source URLs
are optional provenance and never fetched by this layer. Normalization includes
the normalized text, code-point-indexed original UTF-16 start/end arrays,
algorithm/version information, and original length. Maps are block-local;
add `block.start_offset` to convert to document coordinates.

## Findings

`Finding` carries identity, document/revision, UTF-16 span, category, score,
optional calibrated confidence, confidence interpretation, and diagnostics.
A non-null confidence requires `probability_calibrated` and a calibration
artifact ID. Similarity and retrieval scores belong to `score`, not confidence.
The score's method/scale must be specified in diagnostics by each engine.

Similarity matches additionally require source ID and source offsets, category
(`EXACT_OVERLAP`, `REORDERED_TEXT`, `SEMANTIC_PARAPHRASE`), similarity score,
verification score, and retrieval method. Claim outputs carry claims,
evidence citations, provenance, NLI scores, aggregation rules, and the four
final states. `Claim` and `SimilarityMatch` base contracts exist; rich engine
payloads also carry source/evidence fields in JSON dictionaries. Comprehensive
typed rich-result schemas remain a hardening gate; do not validate those extended
payloads directly against the narrow generic `Finding` schema.

The finding model validates internal span ordering. Validation against an
actual document is separately required: `validate_against(document)` rejects
wrong IDs, stale revisions, out-of-bounds or surrogate-splitting spans.

## SSE envelope and persistent replay

Event names: `analysis.started`, `ai_detection.completed`,
`plagiarism.completed`, `claim_verification.partial`,
`claim_verification.completed`, `analysis.completed`, `analysis.error`.

The JSON object in `data` contains `request_id`, `document_id`,
`document_revision`, `sequence` (positive integer), `offset_unit`, `timestamp`
(timezone-aware), `payload`, `diagnostics`, and `contract_version`.
Payload and diagnostics are JSON values, not arbitrary Python objects.
The wire formatter uses `id: <sequence>`, `event: <event_name>`, a JSON `data:`
line, and a blank line. Routes provide streaming and SQLite-backed replay.

Replay uses numeric Last-Event-ID and bounded request-scoped history. Evicted
requests return 410; ahead-of-history cursors return 409. Clients persist
request/revision/cursor identity; sequence gaps and mismatches are rejected and
duplicates ignored. Restart terminates unfinished work, not its replay history.
Runtime integration and SSE parser fixtures exercise these boundaries; actual
MV3 installation/lifecycle behavior remains a separate browser acceptance gate.

## Safe API errors

Errors use `{"error":{"code":...,"message":...},"request_id":...}`.
No submitted text, token, exception string, or Pydantic input value is reflected
in error bodies or ordinary logs. Request IDs are server-generated UUIDs.

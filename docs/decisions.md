# Decision log

## Current baseline decisions

- Executable implementations now span all phases; see `implementation_status.md`.
- CPU-only torch wheel, serial inference, pinned explicit local downloads.
- Model/tokenizer SHAs and declared upstream licenses are recorded in configuration;
  these are not a substitute for deployment legal review.
- Rule sentence claims and optional FLAN-T5 decomposition remain unvalidated.
- SQLite replay is bounded, persistent and terminates lost requests on restart.
- Runtime private databases default outside the OneDrive workspace; source/event
  plaintext storage and synced credentials remain operational privacy considerations.
- MV3 side panel and rendered adapters are built/tested with fixtures, not real
  editor document-model integration. Optional Wikipedia requires policy plus consent.

The following Phase 0 decisions/acceptance list is historical context. Its unresolved
dataset, model-quality, editor and performance gates remain applicable; implementation
availability is described by the current status document rather than the old list.

## Selected Phase 0 decisions

- Python 3.11 baseline; exact direct dependencies and uv lock, isolated venv.
- One canonical half-open UTF-16 coordinate system and strict document schemas.
- Blocks join with two LF characters; original text retained alongside
  grapheme-local normalization provenance and pinned Unicode metadata.
- Loopback-only CLI, token authentication, independent CSRF secret, exact
  origins/hosts, bounded JSON requests, one-worker in-memory revision registry.
- CPU-only foundation; optional PyTorch/driver profiling without model downloads.
- No mock detector or placeholder engine exposed as real inference.
- Proposed MV3 side panel streaming context; worker state must be persisted.

## Decisions required before later phases

1. Actual target GPU (4/6 GB), supported PyTorch/CUDA build and pinned wheel
   source, usable CPU/RAM, power mode, and measured safe configurations.
2. Approved datasets/licenses, annotation schemas, grouping rules, split sizes,
   language scope, generators/domains, and calibrated decision thresholds.
3. Exact model/tokenizer commit SHAs and reviewed licenses. The stated
   DeBERTa/BGE/Qwen candidates are retained, not silently substituted.
4. POS artifact and language resources; freeze the proposed minimum sample
   rules, lexical tokenizer, sentence segmenter, full/light feature profiles.
5. Atomic-claim model with demonstrated atomicity and offset provenance;
   suitable NLI model with inspected id2label mapping; reranking/verification
   models and local source/evidence corpus policy.
6. Optional external provider and explicit consent UX/privacy policy. No
   document text leaves the machine in this increment.
7. Event retention/persistence and request-cache invalidation; cancellation
   checkpoints, replay eviction, timeout policy, extension lifecycle tests.
8. Editor-specific public integration boundaries and realistic fixture coverage;
   geometry tolerance measured at supported browser zooms.
9. Precision/ONNX decisions only after correctness and provider-placement
   benchmarks. Optional DoRA, checkpointing, paged optimizers, contrastive or
   late-interaction models require cost/benefit experiments.

These do not block the Phase 0 foundation. They block credible model accuracy,
production-readiness, GPU-fit, or website-support claims.

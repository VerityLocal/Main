# Cross-language contracts

Six generated JSON Schemas in `../schemas/` are language-neutral
artifacts. Their source is `backend/app/schemas/` plus the normalization map.
Regenerate with `python -m backend.scripts.export_schemas`; use `--check` in CI.

JSON Schema covers structural constraints. Canonical concatenation, original
normalization provenance, surrogate boundaries, calibrated confidence policy,
and revision identity also require semantic checks. The JavaScript extension
validates spans/event identity; the backend validates canonical normalization.
Schema acceptance alone is not sufficient.

# Dataset registry

Recommended starting data: the English portion of LLMTrace Detection. See
the [source-backed comparison and pinned revisions](../../docs/dataset_recommendation.md).

The English LLMTrace pilot has been imported into local application storage and
registered in `registry.yaml`. Raw records and converted data are outside source
control. See [import measurements](../../artifacts/llmtrace_import_validation_2026-11-05.md)
for the actual checksums, grouping audit, labels and split counts.

Required fields per dataset: name, version, source, license, language,
record_count, label_schema, collection_method, preprocessing, limitations,
checksums, split_manifest, grouping_keys. Store private records and weights
outside source control. See `docs/evaluation.md`.

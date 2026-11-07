# Internal calibration / retraining

The distributed artifact has no AI head. Do **not** claim it is a
production fine-tuned AI model. A controlled development copying head is provided
in `controlled-calibration.json` and bundled **inactive**; its template-domain
test performance is not web accuracy. `production_approved: false` prevents its
use for user-facing probabilities. Tests alone can explicitly enable development
heads; there is no such switch in the extension or production helper API.
This is calibration-head training, not backbone fine-tuning or upstream ownership.

## Real authorship data

Use independently annotated human/AI **segments**, with author/source/topic and
near-duplicate groups separated across train, validation and final test. Mixed
segments need an explicit binary-label policy; scores do not identify each token's
author. Include multiple generators, domains, paraphrase attacks and sufficient
human examples to measure false positives. English prose and code need separate
heads. Licensing/provenance is mandatory. Do not use fabricated detector scores.

Input JSONL: `id`, `group`, `split` (`train`, `validation`, `test`), `text`, `kind`
(`text`/`code`), `label` (0 human/1 AI), `provenance`.

```sh
python -m internal.retraining.extract_scores --data private/labels.jsonl --output private/scores.jsonl
python -m internal.retraining.train --data private/scores.jsonl --output private/calibration.json
```

The extractor uses configured, licensed, local snapshot adapters only. The trainer
requires at least 10 rows/both classes in each split (a smoke-test minimum, **not**
statistical acceptance). It rejects group leakage, mismatched signal sets,
nonfinite/out-of-range values, duplicate IDs and output overwrite. All signal
scores plus their weighted mean are logistic inputs. Missing upstream signals
change the signature and cause abstention, not zero-filled probabilities.

For plagiarism, create labeled query/source pairs, record lexical + semantic
signals with exactly the runtime signature, and use task `plagiarism`.
Development fixture workflow:

```sh
python -m internal.retraining.controlled_pairs --output private/pairs.jsonl
python -m internal.retraining.train --data private/pairs.jsonl --output private/copy-calibration.json
```

Review held-out Brier score, human false-positive rate, subgroup results, independent
domain tests and source recall. The artifact records train count, validation and
untouched final-test metrics plus dataset digest. `production_approved` and `claim_allowed` stay false
pending a documented release review. Merge approved heads into
`product/extension/calibration.json` (via an intentional reviewed edit), rebuild,
restart the helper. Helper and extension read the same bundled artifact. Calibration
signatures include snapshot IDs/configuration and the checksum-manifest digest;
changing paths or weights requires a reviewed new calibration. Run `hash_assets`
as documented in `internal/SETUP.md` before score extraction. Runtime verifies all
listed files and refuses symlinks/unlisted files before loading. Keep provisioned
assets immutable for the process lifetime; merely setting `snapshot_id` cannot
enable inference.

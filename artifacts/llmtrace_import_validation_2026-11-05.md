# LLMTrace English pilot import — 2026-11-05

## Provenance and integrity

- Repository: `iitolstykh/LLMTrace_detection`.
- Immutable revision: `332053804f8798177ff2ecb1148e1839ed429ba3`.
- All three original files matched the advertised SHA-256 hashes and byte sizes
  recorded in [the dataset registry](../backend/datasets/registry.yaml).
- Download size: 269,243,165 JSONL bytes. The release contains **79,342** rows,
  of which **40,317** are English (27,766 train; 5,536 valid; 7,015 test).
- The dataset card declares Apache-2.0. Original source/author identities and
  source-specific terms are not fully supplied by this release; the registry
  records that scope rather than inventing provenance.
- Storage: `%LOCALAPPDATA%\VerityLocal\datasets\llmtrace_detection`.
  Original text is preserved; raw records and model inputs are not published.

Converted file: `pilot_v1/english_pilot.jsonl`.
Its SHA-256 is
`e61b73e851e2a3359ce64955d773c633e7be5ad25b91beb7161dff0613f36b67`.
The adjacent `english_pilot.manifest.json` records complete statistics and
conversion/sampling policies. Training checks this manifest against the data bytes.

## Annotation definition

Document labels use **`contains_annotated_ai_v1`**:

- 0: human / no annotated AI content.
- 1: contains annotated AI content, including mixed documents.

This is a presence classifier, not a percentage of words written by AI or a
claim that a mixed document is wholly generated. Sentence labels come directly
from the released half-open character intervals, converted from code points to
original half-open UTF-16 offsets. Fully covered non-whitespace sentence content
is labeled AI; zero overlap is human; partial coverage is masked. Document
labels are never broadcast to sentence labels.

Seventeen English records have invalid code-point intervals (12 train, 2 valid,
3 test) and were excluded. Inputs above 512 tokenizer tokens, 128 sentence
candidates or 20,000 code points are excluded with separate counts. They are
not truncated or relabeled.

## Leakage audit before sampling

All 40,317 English texts participated in grouping, including texts later
excluded for length. Grouping uses:

1. Original `topic_id` source/derivative families: **15,459** groups.
2. Normalized exact-text equality (case-folded, whitespace collapsed).
3. NFKC/case-folded Unicode word five-grams, 64-bit BLAKE2b hashes and a
   deterministic prefix-filtered Jaccard join at **0.85**, with exact candidate
   verification in the hashed-shingle space.

The near-duplicate join merged **32** previously separate components; the result
contains **15,427** components, largest size 66. It is not probabilistic LSH
candidate sampling. Unit fixtures compare the join against exhaustive pairwise
Jaccard grouping at multiple thresholds. Hash collisions and low-overlap semantic
paraphrases remain explicit limitations.

Although upstream topic IDs did not cross partitions, **four merged components
did**. To keep evaluation isolated, **91 development records** were excluded:

- 68 training rows belonging to reserved test components.
- 11 training rows belonging to reserved validation components.
- 12 validation rows belonging to reserved test components.

Original test components are never moved into training. Remaining original
validation components are assigned by a seeded, stable group hash to either
validation or calibration. Independent loader checks confirmed no selected
group or normalized exact-text overlap across the four splits.

## Actual pilot

| Split | Documents | Groups | Human documents | AI/mixed documents | Human sentences | AI sentences | Masked sentences |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Train | 4,096 | 3,589 | 1,365 | 2,731 | 15,674 | 15,965 | 382 |
| Validation | 768 | 607 | 305 | 463 | 3,512 | 2,162 | 40 |
| Calibration | 768 | 578 | 282 | 486 | 3,136 | 2,335 | 48 |
| Final test | 1,536 | 1,227 | 592 | 944 | 7,138 | 4,561 | 100 |

Training sampling is nested: source label (human/AI/mixed), then domain, then
generator/length. It includes 1,366 fully AI and 1,365 mixed documents across all
nine domains and 18 named generators. Evaluation samples use label-independent
stable ID hashes within their reserved splits; they are bounded samples, not the
complete upstream benchmark. The seed is 42.

These are corpus/conversion measurements, not model accuracy results. The test
sample's 592 human records do not establish a 0.1% false-positive operating point.
Training and held-out evaluation results are recorded separately when completed.

## Reproduce with a new output path

```powershell
.\.venv-cuda\Scripts\python.exe -m backend.scripts.prepare_llmtrace --download --output "$env:LOCALAPPDATA\VerityLocal\datasets\llmtrace_detection\reproduced\english_pilot.jsonl"
```

`--download` explicitly enables network access for the pinned public files.
Omit it when using the already downloaded raw snapshot. Existing outputs are
preserved; the command requires new JSONL/manifest paths.

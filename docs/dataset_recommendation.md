# AI detector dataset recommendation

Research date: **2026-11-05**. This is a source-backed selection for this app;
no detector accuracy is inferred from another project's benchmark results.

Import update: all pinned Detection files have now been downloaded and verified.
A grouped English pilot is prepared; see the
[actual import and leakage audit](../artifacts/llmtrace_import_validation_2026-11-05.md).

## Recommended starting point

Use the **English portion of
[LLMTrace Detection](https://huggingface.co/datasets/iitolstykh/LLMTrace_detection)**.
It best matches the current combination of document scoring, sentence highlights,
and original-text offsets among the publicly accessible resources reviewed.

- Published labels distinguish **human, AI, and mixed** texts, with explicit
  `ai_char_intervals` for AI-generated regions.
- Mixed examples include multiple gap-filled regions, continuations, and human
  edits of AI text, rather than only a single human-to-AI boundary.
- The English data covers nine domains, including news, reviews, questions,
  short-form writing, stories, factual text, and scientific abstracts.
- The paper reports **40,317 English records**: 27,766 train, 5,536 validation,
  7,015 test. The complete English/Russian detection release has **79,342** rows.
- All three original JSONL files together total **269,243,165 bytes** (about
  269 MB); this is the bilingual download size, not an English-only estimate.
- `topic_id` groups a source and its derivatives, providing a useful starting
  point for leakage control.
- The current dataset card declares **Apache-2.0** and downloads are ungated.

The [paper](https://arxiv.org/html/2509.21269v1) reports 31 generators in the
detection corpus, across both languages. Its gap-filling component uses a smaller
set, including Gemini 2.5 Flash and GPT-4/4o/o1 families. Do not claim every model
occurs in every language, domain, or editing scenario.

## Companion datasets

| Dataset | Recommended role | Important distinction |
| --- | --- | --- |
| [OpAI-Bench](https://huggingface.co/datasets/OpAI-Bench1/OpAI-Bench) | Newer-generator and repeated-editing evaluation; later training augmentation after fixing label semantics | Sentence, token and span annotations; four domains; GPT-5.4, GPT-5.4-nano, Gemini 2.5 Flash, and held-out Qwen3-8B. Labels mark **AI-edited sentences**, including retained words inside them. |
| [LLMTrace Classification](https://huggingface.co/datasets/iitolstykh/LLMTrace_classification) | Later document-head training expansion | 589,086 bilingual records; about 249k English per the paper. No sentence-span field. Shares source material with Detection, so cross-corpus grouping is required. |
| [RAID](https://huggingface.co/datasets/liamdugan/raid) | Independent adversarial/document-level evaluation | Diverse decoding settings, paraphrases, spelling and Unicode perturbations. The official test labels are hidden; use a reserved labeled subset for local metrics or the official evaluation service. |

OpAI-Bench's [construction paper](https://arxiv.org/html/2606.06481) defines an
AI-edited sentence by whether it was selected for rewriting. Its token/span
labels are projected from those sentence regions. That differs from attribution
of individual inserted or retained words, so the datasets must not be pooled
under an unspecified common label definition.

The working OpAI-Bench repository is **`OpAI-Bench1/OpAI-Bench`**, linked from
the [official code](https://github.com/VILA-Lab/OpAI-Bench). An older search result
uses `OpAI-Bench/OpAI-Bench`, which returned HTTP 401 during this review.
The current viewer reports 281,178 main rows and 37,071 ablation rows; the code
README reports 279,794 versioned main samples. Count the pinned imported files
and record that count instead of treating those differently scoped totals as
interchangeable.

RAID's card declares MIT; both LLMTrace cards and OpAI-Bench declare Apache-2.0.
These are release-level declarations. LLMTrace's source list includes Wikipedia,
news, forum and other third-party corpora, whose underlying terms/provenance
are not replaced by a dataset-card license badge. A per-source reuse audit was
not completed in this research step.

## Why the older alternatives are secondary

- [MAGE](https://github.com/yafuly/MAGE) offers 447,674 texts and 27 generators,
  but its distributed binary data lacks the span supervision required here.
  It also uses the opposite numeric label direction: 0=machine, 1=human.
  Its GitHub README badge says CC BY 4.0 while its HF card says Apache-2.0.
- [SeqXGPT](https://github.com/Jihuai-wpy/SeqXGPT/tree/main/SeqXGPT) supplies
  `prompt_len` boundary supervision, but mainly older generators and a single
  human-prefix/AI-suffix structure. It is useful as an additional boundary test.
- [HACo-Det](https://aclanthology.org/2025.acl-long.1069/) is relevant to
  word-level coauthoring; its lexical-retention attribution policy differs from
  whole-sentence AI-edit labels and requires an explicit conversion policy.
- [AITDNA](https://huggingface.co/datasets/UKPLab/AITDNA) provides realistic
  human-AI edit histories, but only 362 texts. It is an evaluation candidate,
  not the main training corpus. Its card metadata says CC BY-SA 4.0 while the
  body says GPL-2.0; that discrepancy needs resolving before adoption.

## Required conversion for this trainer

The downloaded JSONL is not directly compatible with
[`train_ai_detector.py`](../backend/scripts/train_ai_detector.py).

1. Retain `lang == "eng"` and map it to `language: "en"`. Preserve the exact
   text, original label, generator, domain, topic and dataset revision.
2. Validate every original character interval and convert its code-point
   positions into half-open UTF-16 positions with `Utf16Index`. Segmentation
   must use this project's pinned `sentence_spans` implementation.
3. Derive sentence supervision from the supplied intervals. A conservative
   initial policy labels fully covered non-whitespace sentence content AI,
   non-overlapping content human, and masks partially covered sentences. Record
   the coverage/masking counts. Never broadcast the document label to sentences.
4. Freeze the document-label definition for `mixed` records. The current trainer
   accepts only 0/1. An explicit **contains annotated AI content** policy is
   possible, but it must be recorded in the artifact and reflected in output
   interpretation; `mixed` must not silently mean fully AI-generated.
5. Keep topic families, authors/sources where known, and near-duplicate clusters
   together. Check both exact and near-duplicate overlap across all corpora.
   An existing upstream split is not proof that this app's leakage checks pass.
6. Keep the upstream test partition untouched for final evaluation. Reserve
   calibration groups from the remaining data independently of training and
   model selection. Include both document and sentence classes in calibration.
7. Begin with a bounded, stratified pilot and measure actual training memory and
   speed. The current loader materializes records/features, so scaling requires
   a memory-aware importer/training plan. Sampling must cover human, AI, mixed,
   domain, length and generator strata rather than taking the first N rows.
8. Evaluate low-FPR recall, false positives on human writing, sentence precision
   and recall, mixed-text coverage, unseen generators/domains, and calibration.
   Add deployment-like short and non-native English examples with provenance;
   the published corpora alone do not establish that coverage.

CUDA speeds up training; it does not resolve annotation or evaluation gaps.
See [training instructions](training.md) for the GPU execution profile.

## Revisions and download integrity

These immutable revisions were read from the authors' public Hugging Face APIs:

| Repository | Revision |
| --- | --- |
| `iitolstykh/LLMTrace_detection` | `332053804f8798177ff2ecb1148e1839ed429ba3` |
| `iitolstykh/LLMTrace_classification` | `252e21e3dca713bc82bc3c1ef73bf533d7c9fc7e` |
| `OpAI-Bench1/OpAI-Bench` | `072c03c7051409346aaba05168d183cf6d863ee9` |
| `liamdugan/raid` | `865cac74188466cb0c3b7574a10204007b57a459` |

LLMTrace Detection's advertised original-file SHA-256 values:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `train.jsonl` | 183111035 | `1bb15183e4156365cb67c870052730ea3691c30a6a975dfe3e25554688048b84` |
| `valid.jsonl` | 35713963 | `478c91dc43e07024388853e87cddac4e1cf347e3d93f4ade00f3b48c69d66910` |
| `test.jsonl` | 50418167 | `0b879a39d7a1c1147636f87e8f6a626a46c8e5cdf83a85d0c00a636c1c08e97e` |

The initial selection inspected author documentation, metadata and viewer
samples. The subsequent LLMTrace Detection import verified all three local files
against these hashes and registered a grouped pilot. Other companion corpora
have not been imported. See the linked import report for the exact scope.

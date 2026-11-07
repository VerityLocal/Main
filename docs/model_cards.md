# Pinned model candidates — no bundled weights

All entries in `configs/models.yaml` have exact model/tokenizer commit SHAs and
declared upstream licenses. The initial baseline shipped with all models disabled.
On 2026-11-05, this local installation enabled BGE, STSB, NLI and MS MARCO and
passed [small local smoke checks](../artifacts/model_setup_validation_2026-11-05.md).
The pinned AI backbone was subsequently downloaded and used for the completed
English LLMTrace detector pilot. Reference LM, POS and claim-decomposition
snapshots remain unavailable here. The semantic/evidence smoke checks establish
execution only; their task-specific quality evaluation remains outstanding.

| Component | Pinned candidate | Interpretation / outstanding gate |
|---|---|---|
| AI backbone | `microsoft/deberta-v3-small` | Encoder used by the local trained English detector; load the full detector checkpoint for analysis |
| Reference LM | `Qwen/Qwen2.5-0.5B` | CPU causal score/rank features; cost/quality unmeasured |
| Dense retrieval | `BAAI/bge-small-en-v1.5` | Normalized window-pooled embeddings; retrieval evaluation outstanding |
| POS | `spacy/en_core_web_sm` | English features; pinned artifact and installed spaCy resources |
| Similarity verifier | `cross-encoder/stsb-TinyBERT-L-4` | STS sigmoid scale, not calibrated paraphrase probability |
| Evidence reranker | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Raw relevance logits only; not a truth verifier |
| Claim decomposition | `google/flan-t5-base` | Instruction-model candidates; factual fidelity and atomicity unvalidated |
| NLI | `cross-encoder/nli-deberta-v3-small` | Three-way scores conditional on premise; thresholds/authority unvalidated |

The explicit downloader stores the pinned revision in a completion marker and
can enable only selected entries. Startup and analysis load local files only,
with remote-code trust disabled. Failed or missing snapshots do not become mock
predictions. The POS path uses spaCy artifact loading rather than a Transformers
tokenizer.

Each trained artifact must include intended use, licensed dataset provenance,
split identities, feature profile/normalizer, optimizer/seed/config, training logs,
hardware, domain/generator evaluation, calibration provenance, deployment precision
and known limitations. The local detector now has these artifacts and a
[measured pilot report](../artifacts/llmtrace_pilot_validation_2026-11-05.md).
Base DeBERTa is not an AI-authorship detector; dense similarity does not prove
paraphrase intent; NLI scores do not establish source authority or truth.

## Local detector: `llmtrace_detector_pilot_v1_retry1`

- English LLMTrace, pinned revision and Apache-2.0 dataset-card declaration;
  original-source terms and provenance limitations are recorded in the import audit.
- DeBERTa-v3-small with `light_v1` 24-feature fusion/missingness and two heads.
  Three CUDA BF16 epochs completed; validation loss selected epoch 1.
- Intended use: local experimental detection of annotated AI-content presence,
  including mixed documents, up to 512 tokenizer tokens and 128 sentences.
- Calibrated and deployed in FP32 CPU using `.venv-cuda`; live HTTP/SSE, UTF-16,
  revisions and input-boundary checks passed.
- Final-test documents: accuracy **79.82%**, macro-F1 **0.790061**, ROC-AUC
  **0.874420**, human false-positive rate **21.96% at 0.5**. Mixed recall:
  **71.25%**; fully AI recall: **95.95%**.
- Final-test sentence macro-F1 **0.808299**, ECE **0.167215**. Temperature fitting
  increased sentence ECE on the calibration split. The pilot has material
  false-positive, mixed-content and subgroup-calibration limitations.
- Test scope: 1,536 documents from the reserved same-corpus test partition,
  including 592 human documents. Independent-corpus generalization and a low-FPR
  deployment threshold are not established.

The [pilot report](../artifacts/llmtrace_pilot_validation_2026-11-05.md) contains
epoch logs, provenance, GPU measurements, calibration temperatures, domain
strata and SHA-256 hashes. Weights are private local files, not extension assets.

## STS score-activation check

The pinned [STSB model card](https://huggingface.co/cross-encoder/stsb-TinyBERT-L-4/blob/1f478482145797a0cac02d6b9ab3c65c9d25fb1e/README.md)
specifies a score between zero and one. Its pinned config has one output label
and no activation override. Installed Sentence Transformers 4.1.0
`CrossEncoder.get_default_activation_fn()` selects `torch.nn.Sigmoid` for one
label. The direct-Transformers runtime explicitly reproduces that activation;
synthetic regression tests separately preserve raw MS MARCO ranking logits.

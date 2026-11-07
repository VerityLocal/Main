# AI baseline tensor contract

Backbone: `microsoft/deberta-v3-small`, exact revision in `configs/models.yaml`.
Derive H from `AutoConfig.hidden_size`; derive C from the label schema
(initial binary human/AI task, not an assertion that mixed text is binary).
L includes special tokens and must not exceed 512 or the actual model limit.

| Tensor | Shape | Meaning |
|---|---|---|
| input_ids / attention_mask | [B,L] | Non-padding contextual input |
| token_states | [B,L,H] | DeBERTa output |
| sentence_token_mask | [B,S,L] | Real, overlapping sentence tokens only |
| sentence_valid_mask | [B,S] | Sentence has at least one valid token |
| mean_pool / max_pool | [B,S,H] | Masked span reduction; invalid spans zeroed |
| contextual_span | [B,S,2H] | Concatenated mean and max |
| features / feature_valid_mask | [B,S,24] | Normalized measurements and missingness |
| projected_context | [B,S,D] | Linear projection from 2H |
| projected_style | [B,S,D] | Linear projection of [features, mask], dimension 48 |
| fused | [B,S,D] | Learned linear projection of concatenation, with activation |
| sentence_logits | [B,S,C] | Independent sentence head |
| document_embedding | [B,D] | Masked aggregate of valid sentence embeddings |
| document_logits | [B,C] | Independent document head |

D is a configurable fusion dimension to benchmark, not a backbone constant.
Max pooling must mask excluded tokens before reduction and explicitly handle
empty spans. The sentence validity mask applies to both classification losses
and document aggregation. A token may contribute to a sentence only when its
source offset intersects the sentence; special/padding tokens never do.

## Windows and objectives

Implemented tokenizer windows use 512 tokens and 96-token overlap. Sentence masks
preserve original boundaries, but windows may split sentences. Aggregate representations
across windows using coverage weights, so the same original token is not
implicitly counted multiple times. Long-sentence partial spans expose truncation
diagnostics and a documented aggregation policy. Aggregate unique sentence
representations for document prediction, weighting by unique covered UTF-16 token length
(zero-length invalid spans excluded). No TextCNN/BiGRU/contrastive objective in
the baseline. Tiny neural/overflow fixtures exercise it; real model/resource and
quality evaluation remains required.

Loss: `lambda_doc * CE(document_logits, document_labels) +
lambda_sent * masked_CE(sentence_logits, sentence_labels)` with training-only
class weights. Missing sentence labels are masked, not inferred from document
labels. Tune loss weights on validation data. LoRA baseline rank=8, alpha=16,
configurable dropout; choose target modules by inspecting the actual model.
Training supports CPU FP32 or CUDA autocast (BF16 when supported; otherwise FP16
with gradient scaling). CUDA enables non-reentrant gradient checkpointing and
defaults to one window per document; gradient accumulation groups documents
without retaining their computation graphs. Window inputs, coverage weights,
class weights and labels are placed on the model's device. Deployment and
calibration use merged FP32 CPU weights. See [training](training.md) for the
memory ceiling and environment requirements. Calibrate each head separately on
a dedicated calibration split. DoRA and paged optimizers remain future experiments.

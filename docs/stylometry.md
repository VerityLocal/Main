# Exact 24-feature specification

The extractor is executable. `light_v1` keeps F21–F24 missing; `full_v1` requires
the pinned reference LM. POS use and model/resource revisions are persisted and
checked at inference. Floors/formulas are fixed baseline policies, not validated
statistical-reliability claims. No trained detector is bundled.

Let lexical words be Unicode letter runs with optional internal apostrophes or
hyphens (proposed English-oriented rule). Case-fold word types. Let N be their
count, V their distinct count, V_i the number of types occurring i times,
p(t) the empirical type frequency, and `nc` the non-whitespace code-point count.
`W` denotes the original sentence, `D` the document/analysis window. Entropy
uses base-2 logs; distributional variances below are population variances.

| ID | Definition | Unit | Scope | Invalid/missing policy |
|---|---|---|---|---|
| F1 | Count non-special, non-padding tokens from the pinned detector tokenizer | tokens | W | Missing without pinned tokenizer |
| F2 | Count Unicode code points for which `isspace()` is false | characters | W | Valid, including zero |
| F3 | `sum(word code-point lengths)/N` | characters/word | W | Missing if N=0 |
| F4 | N in the sentence | words | W | Valid, including zero |
| F5 | `-sum_t p(t)*log2(p(t))` | bits | D | Missing if N<2 |
| F6 | Mean distinct-type count/50 over all overlapping 50-word windows | ratio | D | Missing if N<50; never shrink window |
| F7 | `10000*(sum_i i*i*V_i-N)/(N*N)` | scaled inverse concentration | D | Missing if N<50 (proposed reliability floor) |
| F8 | `100*ln(N)/(1-V_1/V)` | scaled logarithmic richness | D | Missing if N<50, V=0, or V_1=V |
| F9 | `population_std(sentence_word_counts)/mean(counts)` | ratio | D | Missing with <2 sentences or zero mean |
| F10 | Unicode general-category P* count/nc | ratio | W | Missing if nc=0 |
| F11 | Unicode `isdigit()` count/nc | ratio | W | Missing if nc=0 |
| F12 | Uppercase alphabetic count/alphabetic count | ratio | W | Missing with no alphabetic characters |
| F13 | Pinned language stopword matches/N | ratio | W | Missing if N=0 or language list unavailable |
| F14 | Distinct function-word types/function-word count | ratio | W | Missing if no function words or pinned list unavailable |
| F15 | `H(next_UPOS | current belongs to G1)` | bits | D | Missing with <2 qualifying transitions |
| F16 | Same for G2 | bits | D | Same |
| F17 | Same for G3 | bits | D | Same |
| F18 | Same for G4 | bits | D | Same |
| F19 | Same for G5 | bits | D | Same |
| F20 | Same for G6 | bits | D | Same |
| F21 | Mean `ln P(x_t | context, x_<t)` over eligible observed tokens | nats | W with preceding context | Missing without reference LM or <1 score |
| F22 | Population variance of F21 token log probabilities | nats² | W with context | Missing with <2 scores |
| F23 | Mean `ln(rank(x_t))` | log-rank | W with context | Missing without LM or <1 rank |
| F24 | Mean `abs(lr[t+1]-2*lr[t]+lr[t-1])` | log-rank | W with context | Missing with <3 ranks |

F15–F20 groups are disjoint: G1={NOUN,PROPN}, G2={VERB,AUX},
G3={ADJ,ADV}, G4={PRON,DET}, G5={ADP,CCONJ,SCONJ},
G6={NUM,PART,INTJ,SYM,X}. Remove PUNCT and SPACE tokens before transitions;
do not join transitions across sentence boundaries. For each group, collect
next-tag counts, normalize them, and calculate their entropy. This measures
the distribution of *next UPOS tags*, not the entropy of the six groups.
Record transition sample counts for reliability diagnostics.

English stopword/function-word lists and the UPOS artifact must be pinned with
license, version, checksum. Unsupported languages get missing masks, not
English-derived measurements presented as valid. F1 depends on the detector
tokenizer; F21–F24 depend on the reference tokenizer; never conflate them.

The reference candidate is `Qwen/Qwen2.5-0.5B`, CPU initially. Implemented scoring:
up to 511 prior tokens plus the observed token in a 512-token call,
causal shifted logits, no padding/special observed tokens. Pin exact revision
before use. Rank is one plus the number of larger logits plus tied-logit
tokens with smaller vocabulary ID (deterministic ID-ascending tie break).
Overlapping windows score each eligible observed token once. Context-free
first tokens lacking a causal prediction are missing, not scored as zero.

## Missingness and normalization

Return `features[24]` and `feature_valid_mask[24]`. Serialized invalid values
are JSON null; tensor preparation sets invalid entries to zero **after**
normalization and passes the explicit mask to fusion. Z-scores use only valid
training-split entries: `(x-mean_train)/std_train`. Constant training features
use scale 1; absent training features require a profile decision, not fabricated
statistics. Save counts, means, scales, schema, resources, and versions.

All 24 scalars use this normalization policy. Document-context values are
explicitly broadcast to sentence representations. A separately trained
lightweight profile may disable F21–F24 with a different persisted profile ID;
runtime must reject mismatched feature profiles rather than silently omitting
features trained as present. Reliability floors and scope choices are proposals
to validate before freezing the training pipeline.

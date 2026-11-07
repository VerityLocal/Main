"""Source-grounded candidates with optional instruction-model decomposition."""

import re

from backend.app.document.chunking import sentence_spans
from backend.app.schemas.analysis import Claim


def extract_claims(text, models, limit=48, check=lambda: None):
    output = []
    spans = sentence_spans(text)
    oversized_inputs = generation_limit_hits = omitted_propositions = 0
    for sentence in spans[:limit]:
        check()
        propositions = [sentence.text]
        method = "rule_sentence_candidate_not_atomic_model"
        if models.available("claim_extractor"):
            import torch

            with models.lease("claim_extractor") as bundle:
                prompt = (
                    "Split the following text into atomic factual propositions, one per line. "
                    "Preserve names, dates, numbers, negation and uncertainty. Do not add facts. "
                    "If there is no factual proposition, output NONE. Text: " + sentence.text
                )
                inputs = bundle.tokenizer(prompt, truncation=False, return_tensors="pt")
                if inputs["input_ids"].shape[-1] > 512:
                    oversized_inputs += 1
                    method = "rule_sentence_candidate_model_input_over_token_budget"
                else:
                    with torch.inference_mode():
                        generated_tokens = bundle.model.generate(
                            **inputs, max_new_tokens=160, do_sample=False
                        )[0]
                    if len(generated_tokens) >= 160 and int(generated_tokens[-1]) != (
                        bundle.tokenizer.eos_token_id
                    ):
                        generation_limit_hits += 1
                        # Do not verify a possibly incomplete generated proposition.
                        method = "rule_sentence_candidate_model_output_over_token_budget"
                    else:
                        decoded = bundle.tokenizer.decode(
                            generated_tokens, skip_special_tokens=True
                        )
                        if decoded.strip().upper() == "NONE":
                            continue
                        generated = [
                            strip_list_marker(part)
                            for part in decoded.splitlines()
                            if strip_list_marker(part)
                        ]
                        if generated:
                            omitted_propositions += max(0, len(generated) - 4)
                            propositions = generated[:4]
                            method = "flan_t5_decomposition_candidate_unvalidated"
        for proposition in propositions:
            output.append(
                Claim(
                    claim_id=f"claim_{len(output)}",
                    original_text=sentence.text,
                    normalized_claim=proposition,
                    start_offset=sentence.start_offset,
                    end_offset=sentence.end_offset,
                    entities=tuple(
                        re.findall(r"\b[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)*", sentence.text)
                    ),
                    temporal_expressions=tuple(
                        re.findall(r"\b(?:1[0-9]{3}|20[0-9]{2})(?:-\d\d-\d\d)?\b", sentence.text)
                    ),
                    quantities=tuple(re.findall(r"\b\d+(?:[.,]\d+)?(?:\s?%)?", sentence.text)),
                    extraction_method=method,
                )
            )
    return output, {
        "sentence_candidates": len(spans),
        "analyzed_sentences": min(limit, len(spans)),
        "complete_atomicity_not_established": True,
        "decomposition_inputs_over_token_budget": oversized_inputs,
        "decomposition_generation_limit_hits": generation_limit_hits,
        "decomposition_propositions_omitted": omitted_propositions,
        "coverage_limited": bool(
            len(spans) > limit or oversized_inputs or generation_limit_hits or omitted_propositions
        ),
    }


def strip_list_marker(text):
    # Only conventional markers, never dates, negative quantities or decimals.
    return re.sub(r"^\s*(?:[-•]\s+|\d{1,2}[.)]\s+)", "", text).strip()

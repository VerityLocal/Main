"""Evidence is premise, user claim is hypothesis; inspect the actual label map."""


def verify(models, premise, hypothesis):
    import torch

    with models.lease("nli_verifier") as bundle:
        mapping = {
            int(key): str(value).lower() for key, value in bundle.model.config.id2label.items()
        }
        if set(mapping.values()) != {"entailment", "contradiction", "neutral"}:
            raise ValueError("NLI checkpoint lacks a verified three-class label mapping")
        encoded = bundle.tokenizer(premise, hypothesis, truncation=False, return_tensors="pt")
        if encoded["input_ids"].shape[-1] > 512:
            return None  # No NLI decision from a silently truncated premise/claim.
        with torch.inference_mode():
            scores = bundle.model(**encoded).logits.softmax(-1)[0].tolist()
        return {mapping[index]: score for index, score in enumerate(scores)}

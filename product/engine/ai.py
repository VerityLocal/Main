"""Internal upstream adapters. Domain-gated, local-only, lazy loading, no remote code."""
import json
import math
from pathlib import Path

from .assets import ASSET_ROLES, fingerprint, verify_assets
from .calibration import sigmoid
from .resources import ResourceLimit, require_memory


class SequenceSignal:
    """GPTSniffer-compatible trained sequence classifier; only code paragraphs."""
    domain = "code"

    def __init__(self, config):
        self.config, self.bundle = config, None

    def score(self, text):
        if self.bundle is None:
            require_memory(max(4, self.config.get("min_ram_gib", 4)), 1)
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self.bundle is None:
            path = self.config["path"]
            tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            model, info = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True, trust_remote_code=False, use_safetensors=True, output_loading_info=True, low_cpu_mem_usage=True)
            if info["missing_keys"] or info["unexpected_keys"] or info.get("mismatched_keys"):
                raise ValueError("Incompatible local weights")
            model = model.cpu().eval()
            label = self.config.get("ai_label_index")
            if type(label) is not int or not 0 <= label < model.config.num_labels or model.config.num_labels < 2:
                raise ValueError("A verified AI label mapping is required")
            self.bundle = tokenizer, model
        tokenizer, model = self.bundle
        encoded = tokenizer(text, return_tensors="pt", truncation=False)
        if encoded["input_ids"].shape[1] > self.config.get("max_tokens", 512):
            return None
        with torch.inference_mode():
            return float(model(**encoded).logits.softmax(-1)[0, self.config["ai_label_index"]])


class TextSignal:
    """desklib/ai-text-detector-v1.01 mean pooling + single logit, English prose."""
    domain = "text"

    def __init__(self, config):
        self.config, self.bundle = config, None

    def score(self, text):
        if self.bundle is None:
            require_memory(max(8, self.config.get("min_ram_gib", 8)), 3)
        import torch
        from transformers import AutoConfig, AutoModel, AutoTokenizer, PreTrainedModel

        class LocalTextHead(PreTrainedModel):
            config_class = AutoConfig

            def __init__(self, config):
                super().__init__(config)
                self.model = AutoModel.from_config(config, trust_remote_code=False)
                self.classifier = torch.nn.Linear(config.hidden_size, 1)
                self.post_init()

            def forward(self, input_ids, attention_mask, **unused):
                hidden = self.model(input_ids=input_ids, attention_mask=attention_mask)[0]
                mask = attention_mask.unsqueeze(-1).float()
                pooled = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                return self.classifier(pooled)

        if self.bundle is None:
            path = self.config["path"]
            tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            model, info = LocalTextHead.from_pretrained(path, local_files_only=True, use_safetensors=True, output_loading_info=True, low_cpu_mem_usage=True)
            if info["missing_keys"] or info["unexpected_keys"] or info.get("mismatched_keys"):
                raise ValueError("Incompatible local weights")
            self.bundle = tokenizer, model.cpu().eval()
        tokenizer, model = self.bundle
        encoded = tokenizer(text, return_tensors="pt", truncation=False)
        if encoded["input_ids"].shape[1] > self.config.get("max_tokens", 768):
            return None
        with torch.inference_mode():
            return float(model(**encoded).sigmoid().item())


class RatioSignal:
    """Binoculars method; two pinned local models, no upstream remote-code loader."""
    domain = "text"

    def __init__(self, config):
        self.config, self.bundle = config, None

    def score(self, text):
        if self.bundle is None:
            # Gate before importing ML libraries or opening either multi-gigabyte checkpoint.
            require_memory(max(64, self.config.get("min_ram_gib", 64)), 56)
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        if self.bundle is None:
            paths = [self.config["observer"], self.config["performer"]]
            tokenizers = [AutoTokenizer.from_pretrained(p, local_files_only=True, trust_remote_code=False) for p in paths]
            if tokenizers[0].get_vocab() != tokenizers[1].get_vocab():
                raise ValueError("Tokenizers differ")
            models = []
            for path in paths:
                model, info = AutoModelForCausalLM.from_pretrained(path, local_files_only=True, trust_remote_code=False, use_safetensors=True, output_loading_info=True, torch_dtype=torch.float32, low_cpu_mem_usage=True)
                if info["missing_keys"] or info["unexpected_keys"] or info.get("mismatched_keys"):
                    raise ValueError("Incompatible local weights")
                models.append(model.cpu().float().eval())
            self.bundle = tokenizers[0], models
        tokenizer, models = self.bundle
        encoded = tokenizer(text, return_tensors="pt", truncation=False)
        length = encoded["input_ids"].shape[1]
        if not 2 <= length <= self.config.get("max_tokens", 512):
            return None
        with torch.inference_mode():
            observer, performer = [m(**encoded).logits.float() for m in models]
            # Cross entropy on the actual next token; cross-model entropy at every position.
            actual = torch.nn.functional.cross_entropy(performer[:, :-1].reshape(-1, performer.shape[-1]), encoded["input_ids"][:, 1:].reshape(-1))
            cross = -(observer.softmax(-1) * performer.log_softmax(-1)).sum(-1).mean()
            ratio = float(actual / cross)
        # Monotone normalized evidence, not calibrated probability. Mapping must be trained.
        return sigmoid((self.config.get("center", 0.9015310749276843) - ratio) / self.config.get("scale", 0.1))


class CodeMatchSignal:
    """ai-gen-code-search/SameCode offline known-AI corpus match; not prose inference."""
    domain = "code"

    def __init__(self, config):
        self.config, self.hashes = config, None

    def score(self, text):
        from samecode.halohash import BitAverageHaloHash

        def digest(value):
            return BitAverageHaloHash(value.encode().split(), size_in_bits=256)

        if self.hashes is None:
            corpus = Path(self.config["corpus"])
            if corpus.stat().st_size > 16 * 1024 * 1024:
                raise ValueError("Reference corpus exceeds limits")
            records = json.loads(corpus.read_text())
            if not isinstance(records, list) or not records or len(records) > 10_000 or any(not isinstance(r, dict) or r.get("label") != "known_ai" or not isinstance(r.get("provenance"), str) or not r["provenance"].strip() or not isinstance(r.get("text"), str) or not 1 <= len(r["text"]) <= 20_000 for r in records):
                raise ValueError("Invalid reference provenance")
            self.hashes = [digest(row["text"]) for row in records]
        current = digest(text)
        return max(1 - current.distance(other) / 256 for other in self.hashes)


class AIClassifier:
    """Single domain-aware interface; weighted mean is an input to a fitted head."""
    TYPES = {"text": TextSignal, "ratio": RatioSignal, "code": SequenceSignal, "code_match": CodeMatchSignal}

    def __init__(self, config, calibration):
        self.calibration = calibration
        self.signals = []
        self.verified = set()
        self.failure_observer = None  # Explicit developer diagnostics only; never a user result.
        self.states = {name: "not_configured" for name in self.TYPES}
        for name, value in config.items():
            if name in self.TYPES and value.get("enabled") and value.get("license_reviewed") and value.get("snapshot_id") and value.get("asset_manifest") and value.get("asset_manifest_sha256"):
                weight = value.get("weight", 1)
                if not math.isfinite(weight) or weight <= 0:
                    raise ValueError("Invalid signal weight")
                self.signals.append((name, self.TYPES[name](value), weight, fingerprint(value)))
                self.states[name] = "provisioned"

    def features(self, row):
        """Training-only raw features, never returned in user-facing results."""
        values, weights, identities = {}, [], []
        for name, adapter, weight, identity in self.signals:
            if adapter.domain != row["kind"]:
                continue
            try:
                if identity not in self.verified:
                    verify_assets(adapter.config, ASSET_ROLES[name])
                    self.verified.add(identity)
                score = adapter.score(row["text"])
                if score is not None and math.isfinite(score) and 0 <= score <= 1:
                    values[name] = score
                    weights.append((score, weight))
                    identities.append(f"{name}:{identity}")
                    self.states[name] = "feature_computed"
                else:
                    self.states[name] = "unsupported_length"
            except ResourceLimit:
                self.states[name] = "insufficient_memory"
            except Exception as error:
                # Upstream exceptions and identities never cross the product API boundary.
                self.states[name] = "unavailable"
                if self.failure_observer:
                    self.failure_observer(name, error)
                continue
        if not values:
            return {}, ""
        values["ensemble"] = sum(s * w for s, w in weights) / sum(w for _, w in weights)
        signature = "|".join(sorted(identities))
        return values, signature

    def score(self, row):
        if row["words"] < 12:
            return {"status": "insufficient_text", "score": None, "confidence": None}
        values, signature = self.features(row)
        if not values:
            return {"status": "unavailable", "score": None, "confidence": None}
        probability = self.calibration.predict(f"ai_{row['kind']}", values, signature)
        if probability is None:
            return {"status": "calibration_required", "score": None, "confidence": None}
        return {"status": "scored", "score": probability, "confidence": max(probability, 1 - probability), "label": "AI-suspected" if probability >= 0.5 else "Human-suspected"}

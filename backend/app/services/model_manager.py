"""Serialized CPU model leases. No automatic network access or GPU allocation."""

import gc
import importlib.util
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from backend.app.core.config import PlatformConfig, Settings


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class ModelBundle:
    model: object
    tokenizer: object | None = None


class ModelManager:
    def __init__(self, settings: Settings, config: PlatformConfig):
        self.settings, self.config = settings, config
        self.lock = threading.RLock()
        self.loaded_name = None
        self.loaded = None
        self.references = 0
        self.states = {key: "unloaded" for key in config.models.models}

    def path(self, name):
        spec = self.config.models.models[name]
        return self.settings.model_cache / name / str(spec.revision)

    def available(self, name):
        spec = self.config.models.models.get(name)
        if not spec or not spec.enabled:
            return False
        marker = self.path(name) / ".download-complete"
        try:
            pinned = marker.read_text(encoding="ascii").strip() == spec.revision
        except OSError:
            return False
        return bool(
            pinned
            and spec.tokenizer_revision == spec.revision
            and importlib.util.find_spec("torch")
        )

    def status(self):
        # Diagnostic snapshot must not wait for a long inference lease.
        states = self.states.copy()
        return {
            key: {
                "state": states[key],
                "available": self.available(key),
                "enabled": spec.enabled,
                "revision": spec.revision,
                "license": spec.license,
                "device": "cpu",
                "active_references": self.references if self.loaded_name == key else 0,
            }
            for key, spec in self.config.models.models.items()
        }

    def unload(self):
        with self.lock:
            if self.references:
                raise RuntimeError("Cannot unload an actively leased model")
            name = self.loaded_name
            self.loaded = None
            self.loaded_name = None
            if name:
                self.states[name] = "unloaded"
            gc.collect()

    def _load(self, name):
        if not self.available(name):
            raise ModelUnavailable(
                "Install ML dependencies, download the pinned model and enable it"
            )
        path = str(self.path(name))
        if name == "dense_retriever":
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(
                path, device="cpu", local_files_only=True, trust_remote_code=False
            )
            model.max_seq_length = self.config.retrieval.dense.max_tokens
            return ModelBundle(model)
        if name == "pos_tagger":
            import spacy

            return ModelBundle(spacy.load(path))
        from transformers import (
            AutoModelForCausalLM,
            AutoModelForSeq2SeqLM,
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        tokenizer = AutoTokenizer.from_pretrained(
            path, local_files_only=True, use_fast=True, trust_remote_code=False
        )
        factory = AutoModelForSequenceClassification
        if name == "claim_extractor":
            factory = AutoModelForSeq2SeqLM
        elif name == "reference_lm":
            factory = AutoModelForCausalLM
        model = (
            factory.from_pretrained(path, local_files_only=True, trust_remote_code=False)
            .cpu()
            .eval()
        )
        return ModelBundle(model, tokenizer)

    @contextmanager
    def lease(self, name):
        with self.lock:
            if self.loaded_name != name:
                self.unload()
                self.states[name] = "loading"
                try:
                    self.loaded = self._load(name)
                    self.loaded_name = name
                    self.states[name] = "ready"
                except Exception:
                    self.states[name] = "failed"
                    raise ModelUnavailable("Pinned local model could not be loaded") from None
            self.references += 1
            self.states[name] = "in_use"
            try:
                yield self.loaded
            finally:
                self.references -= 1
                self.states[name] = "ready"

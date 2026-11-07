import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from product.engine.ai import AIClassifier, CodeMatchSignal, RatioSignal
from product.engine.assets import file_digest, inventory, verify_assets
from product.engine.calibration import Calibration
from product.engine.model_setup import PROFILE, REPOSITORIES, ModelRedirects, apply_profile, setup_models, validate_pins
from product.engine.resources import ResourceLimit, model_setup_states, require_memory


def fixture_pins():
    data = b"Test-only download integrity fixture; never loaded as model weights."
    files = {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()} for name in ["README.md", "model.safetensors"]}
    return {"schema_version": 1, "models": {role: {"repository": repo, "revision": "a" * 40, "license": "MIT", "files": copy.deepcopy(files)} for role, repo in REPOSITORIES.items()}}, data


class SetupTests(unittest.TestCase):
    def test_16gb_setup_skips_large_pair_and_does_not_invent_code_assets(self):
        pins, data = fixture_pins()
        calls = []
        def download(model, name, pin, target):
            calls.append(model["repository"])
            target.write_bytes(data)
        with tempfile.TemporaryDirectory() as folder:
            profile = setup_models(Path(folder).resolve(), pins, downloader=download, memory=16 * 1024 ** 3)
            self.assertEqual(profile["states"], {"text": "provisioned", "semantic": "provisioned", "ratio": "insufficient_memory", "code": "checkpoint_required", "code_match": "corpus_required"})
            self.assertEqual(len(calls), 4)
            verify_assets(profile["signals"]["text"], ("path",))
            verify_assets(profile["semantic"], ("path",))
            setup_models(Path(folder).resolve(), pins, downloader=download, memory=16 * 1024 ** 3)
            self.assertEqual(len(calls), 4, "unchanged snapshots should not download again")

    def test_changed_snapshot_is_not_overwritten(self):
        pins, data = fixture_pins()
        with tempfile.TemporaryDirectory() as folder:
            profile = setup_models(Path(folder).resolve(), pins, downloader=lambda m, n, p, t: t.write_bytes(data), memory=16 * 1024 ** 3)
            changed = Path(profile["signals"]["text"]["path"]) / "model.safetensors"
            changed.write_bytes(b"unrelated changed content")
            with self.assertRaisesRegex(ValueError, "Changed model snapshot"):
                setup_models(Path(folder).resolve(), pins, memory=16 * 1024 ** 3)
            self.assertEqual(changed.read_bytes(), b"unrelated changed content")

    def test_bad_download_never_promotes_partial_model(self):
        pins, _ = fixture_pins()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                setup_models(Path(folder).resolve(), pins, downloader=lambda m, n, p, t: t.write_bytes(b"bad"), memory=16 * 1024 ** 3)
            self.assertFalse(any(p.name.startswith("text-") or p.name.startswith(".model-") for p in (Path(folder) / "models").iterdir()))

    def test_unapproved_repositories_formats_and_paths_are_rejected(self):
        pins, data = fixture_pins()
        for name in ["../file", "/file", "file.py", "weights.bin", "file.", "C:/file", "a\\file"]:
            value = copy.deepcopy(pins)
            value["models"]["text"]["files"][name] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            with self.assertRaises(ValueError):
                validate_pins(value)
        pins["models"]["text"]["repository"] = "unapproved/model"
        with self.assertRaises(ValueError):
            validate_pins(pins)

    def test_redirects_never_leave_approved_https_model_hosts(self):
        redirects = ModelRedirects()
        request = urllib.request.Request("https://huggingface.co/model")
        for url in ["http://huggingface.co/file", "https://evil.invalid/file", "https://127.0.0.1/file", "https://user:secret@huggingface.co/file"]:
            with self.assertRaises(ValueError):
                redirects.redirect_request(request, None, 302, "", {}, url)

    def test_custom_pairing_and_models_and_disabled_choices_are_preserved(self):
        config = {"token": "private-test-token", "origins": ["test-origin"], "signals": {"text": {"enabled": False, "path": "operator model"}, "ratio": {"enabled": False, "managed_profile": PROFILE}}}
        profile = {"signals": {"text": {"enabled": True, "path": "new"}, "ratio": {"enabled": True, "managed_profile": PROFILE, "path": "new"}}, "states": {}}
        updated = apply_profile(config, profile)
        self.assertEqual(updated["token"], config["token"])
        self.assertEqual(updated["origins"], config["origins"])
        self.assertEqual(updated["signals"]["text"], config["signals"]["text"])
        self.assertFalse(updated["signals"]["ratio"]["enabled"])
        self.assertNotIn("model_setup_states", config, "input configuration must not mutate")

    def test_status_does_not_claim_custom_disabled_or_stale_assets_are_ready(self):
        config = {"signals": {"text": {"enabled": False}, "ratio": {"enabled": True, "path": "custom"}}, "model_setup_states": {"text": "provisioned", "ratio": "provisioned", "semantic": "provisioned", "code": "checkpoint_required"}}
        states = model_setup_states(config)
        self.assertEqual(states["text"], "disabled")
        self.assertEqual(states["ratio"], "custom_configured")
        self.assertEqual(states["semantic"], "not_configured")
        self.assertEqual(states["code"], "checkpoint_required")

    def test_physical_and_available_memory_gates(self):
        with patch("product.engine.resources.physical_memory", return_value=16 * 1024 ** 3), patch("product.engine.resources.available_memory", return_value=8 * 1024 ** 3):
            require_memory(8, 3)
            with self.assertRaises(ResourceLimit):
                RatioSignal({"observer": "never opened", "performer": "never opened"}).score("test paragraph")
        with patch("product.engine.resources.physical_memory", return_value=128 * 1024 ** 3), patch("product.engine.resources.available_memory", return_value=4 * 1024 ** 3):
            with self.assertRaises(ResourceLimit):
                require_memory(64, 56)


@unittest.skipUnless(importlib.util.find_spec("samecode"), "install model-requirements.txt for genuine SameCode acceptance")
class RealCodeMatchTests(unittest.TestCase):
    def test_actual_samecode_match_is_evidence_not_authorship_probability(self):
        # This code is genuinely AI-authored for this development fixture, not an independent benchmark.
        text = "def count_words(document):\n    counts = {}\n    for word in document.split():\n        counts[word] = counts.get(word, 0) + 1\n    return counts\n"
        with tempfile.TemporaryDirectory() as folder:
            corpus = Path(folder) / "known-ai.json"
            corpus.write_text(json.dumps([{"text": text, "label": "known_ai", "provenance": "AI assistant-authored development fixture, 2026-11-08; not evaluation data"}]))
            manifest = Path(folder) / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "assets": {"corpus": inventory(corpus)}}))
            config = {"enabled": True, "corpus": str(corpus), "license_reviewed": True, "snapshot_id": "first-party-development-fixture", "asset_manifest": str(manifest), "asset_manifest_sha256": file_digest(manifest)}
            self.assertEqual(CodeMatchSignal(config).score(text), 1)
            classifier = AIClassifier({"code_match": config}, Calibration())
            result = classifier.score({"kind": "code", "text": text, "words": 20})
            self.assertEqual(result["status"], "calibration_required")
            self.assertIsNone(result["score"])
            self.assertEqual(classifier.states["code_match"], "feature_computed")


if __name__ == "__main__":
    unittest.main()

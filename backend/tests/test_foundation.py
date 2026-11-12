import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import torch
from torch import nn
from backend.tests.helpers import TestClient as FastAPITestClient, create_app

from backend.config import PROJECT_ROOT, Settings
from backend.detectors.artifacts import ModelLoadError, verify_artifacts
from backend.detectors.inference import LoadedDetector, masked_mean
from backend.detectors.loaders import build_classifier, load_detector, merge_code_adapter
from backend.detectors.runtime import ModelRuntime


def TestClient(app):
    return FastAPITestClient(app,base_url="http://localhost")


class ToyTokenizer:
    def __init__(self):
        self.inputs = None
        self.options = None

    def __call__(self, inputs, **kwargs):
        self.inputs, self.options = inputs, kwargs
        ids = [[1] + [2] * len(text) + [3] for text in inputs]
        return {"input_ids": ids, "attention_mask": [[1] * len(row) for row in ids]}

    def pad(self, rows, **kwargs):
        size = max(len(row["input_ids"]) for row in rows)
        return {key: torch.tensor([row[key] + [0] * (size - len(row[key])) for row in rows])
                for key in ("input_ids", "attention_mask")}


class ToyLogits(nn.Module):
    def __init__(self, value=0.0):
        super().__init__()
        self.value, self.batch_sizes = value, []

    def forward(self, input_ids, attention_mask):
        self.batch_sizes.append(len(input_ids))
        return torch.full((len(input_ids), 1), self.value)


class ToyBackbone(nn.Module):
    def __init__(self):
        super().__init__()
        self.config = SimpleNamespace(hidden_size=2)

    def forward(self, input_ids, attention_mask):
        return SimpleNamespace(last_hidden_state=input_ids.float().unsqueeze(-1).repeat(1, 1, 2))


def toy_code_adapter():
    backbone = ToyBackbone()
    backbone.encoder = nn.Module()
    backbone.encoder.layer = nn.ModuleList([nn.Module()])
    layer = backbone.encoder.layer[0]
    layer.attention = nn.Module()
    layer.attention.self = nn.Module()
    layer.attention.self.query = nn.Linear(2, 2)
    layer.attention.self.value = nn.Linear(2, 2)
    tensors = {"head.weight": torch.tensor([[0.1, 0.2]]), "head.bias": torch.tensor([0.3])}
    for name in ("query", "value"):
        prefix = f"lora.encoder.layer.0.attention.self.{name}"
        tensors[prefix + ".A"] = torch.tensor([[1.0, 2.0]])
        tensors[prefix + ".B"] = torch.tensor([[0.2], [0.3]])
    return backbone, tensors


class ConfigTests(unittest.TestCase):
    def test_defaults_do_not_depend_on_working_directory(self):
        settings = Settings.from_env({})
        self.assertEqual(settings.models_dir, PROJECT_ROOT / "models")
        self.assertEqual((settings.max_tokens, settings.batch_size, settings.threshold), (512, 4, 0.5))
        self.assertEqual(settings.device, "cpu")

    def test_environment_overrides(self):
        settings = Settings.from_env({"PDF_AI_MAX_TOKENS": "256", "PDF_AI_THRESHOLD": "0.7",
                                      "PDF_AI_BATCH_SIZE": "2", "PDF_AI_TORCH_THREADS": "1"})
        self.assertEqual((settings.max_tokens, settings.threshold, settings.batch_size, settings.torch_threads),
                         (256, 0.7, 2, 1))

    def test_invalid_configuration_is_not_silently_corrected(self):
        for kwargs in ({"max_tokens": 513}, {"max_tokens": 7}, {"batch_size": 0},
                       {"batch_size": True}, {"device": "auto"}, {"torch_threads": -1},
                       {"threshold": float("nan")}, {"threshold": float("inf")}, {"threshold": 1.1},
                       {"threshold": "0.5"}, {"threshold": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                Settings(**kwargs)
        with self.assertRaises(ValueError):
            Settings.from_env({"PDF_AI_BATCH_SIZE": "lots"})


class IntegrityTests(unittest.TestCase):
    def test_exact_match_then_tampering(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            artifact = directory / "weights.bin"
            artifact.write_bytes(b"verified checkpoint")
            expected = {artifact.name: hashlib.sha256(artifact.read_bytes()).hexdigest()}
            verify_artifacts(directory, expected)
            artifact.write_bytes(b"swapped checkpoint")
            with self.assertRaises(ModelLoadError) as error:
                verify_artifacts(directory, expected)
            self.assertEqual(error.exception.code, "artifact_mismatch")

    def test_missing_file_and_missing_directory(self):
        with TemporaryDirectory() as temp:
            for directory in (Path(temp), Path(temp) / "missing"):
                with self.subTest(directory=directory), self.assertRaises(ModelLoadError) as error:
                    verify_artifacts(directory, {"weights.bin": "0" * 64})
                self.assertEqual(error.exception.code, "files_missing")

    def test_uninspected_alternate_tokenizer_is_rejected(self):
        with TemporaryDirectory() as temp:
            (Path(temp) / "tokenizer.json").write_text("{}")
            with self.assertRaises(ModelLoadError) as error:
                verify_artifacts(Path(temp), {})
            self.assertEqual(error.exception.code, "unverified_artifacts")

    def test_loader_verifies_before_importing_or_allocating_weights(self):
        with TemporaryDirectory() as temp:
            with self.assertRaises(ModelLoadError) as error:
                load_detector("text", Settings(models_dir=Path(temp)))
            self.assertEqual(error.exception.code, "files_missing")
        with self.assertRaises(ValueError):
            load_detector("unknown", Settings())


class ModelMathTests(unittest.TestCase):
    def test_pooling_ignores_padding_including_large_values(self):
        hidden = torch.tensor([[[1.0, 2.0], [3.0, 4.0], [9000.0, -9000.0]]])
        mask = torch.tensor([[1, 1, 0]])
        torch.testing.assert_close(masked_mean(hidden, mask), torch.tensor([[2.0, 3.0]]))
        torch.testing.assert_close(masked_mean(hidden, torch.zeros_like(mask)), torch.zeros((1, 2)))

    def test_custom_head_uses_mean_not_cls_and_strict_weight_matching(self):
        model = build_classifier(ToyBackbone(), "model", "classifier")
        model.classifier.load_state_dict({"weight": torch.tensor([[1.0, 0.0]]), "bias": torch.zeros(1)}, strict=True)
        actual = model(input_ids=torch.tensor([[1, 3, 999]]), attention_mask=torch.tensor([[1, 1, 0]]))
        torch.testing.assert_close(actual, torch.tensor([[2.0]]))
        with self.assertRaises(RuntimeError):
            model.load_state_dict({"classifier.weight": torch.zeros(1, 2)}, strict=True)
        bad_state = dict(model.state_dict(), extra=torch.zeros(1))
        with self.assertRaises(RuntimeError):
            model.load_state_dict(bad_state, strict=True)

    def test_lora_merge_matches_original_forward_with_alpha_over_rank_two(self):
        backbone, tensors = toy_code_adapter()
        source = torch.tensor([[0.5, 0.2]])
        references = {}
        for name in ("query", "value"):
            prefix = f"lora.encoder.layer.0.attention.self.{name}"
            projection = getattr(backbone.encoder.layer[0].attention.self, name)
            references[name] = projection(source) + 2 * (source @ tensors[prefix + ".A"].T) @ tensors[prefix + ".B"].T
        head_state = merge_code_adapter(backbone, tensors, rank=1, alpha=2)
        for name, expected in references.items():
            torch.testing.assert_close(getattr(backbone.encoder.layer[0].attention.self, name)(source), expected)
        torch.testing.assert_close(head_state["weight"], tensors["head.weight"])

    def test_invalid_adapter_rejected_before_any_weight_is_mutated(self):
        for mutation in ("missing", "extra", "shape", "nonfinite"):
            with self.subTest(mutation=mutation):
                backbone, tensors = toy_code_adapter()
                original = backbone.encoder.layer[0].attention.self.query.weight.detach().clone()
                if mutation == "missing":
                    tensors.pop("head.bias")
                elif mutation == "extra":
                    tensors["unknown"] = torch.ones(1)
                elif mutation == "shape":
                    tensors["head.bias"] = torch.zeros(2)
                else:
                    tensors["head.bias"] = torch.tensor([float("nan")])
                with self.assertRaises(ModelLoadError):
                    merge_code_adapter(backbone, tensors, rank=1, alpha=2)
                torch.testing.assert_close(backbone.encoder.layer[0].attention.self.query.weight, original)


class InferenceTests(unittest.TestCase):
    def detector(self, value=0.0):
        return LoadedDetector("code", ToyTokenizer(), ToyLogits(value).eval(), "cpu", 32, 2)

    def test_formatting_is_preserved_and_batching_keeps_order(self):
        detector = self.detector()
        inputs = ["def f():\n    # comment\n    x=1", "x=2", "// Hi\nlet x = 3;"]
        scores = detector.predict_chunks(inputs)
        self.assertEqual(detector.tokenizer.inputs, inputs)
        self.assertFalse(detector.tokenizer.options["truncation"])
        self.assertEqual(detector.model.batch_sizes, [2, 1])
        self.assertEqual([score.input_tokens for score in scores], [len(text) + 2 for text in inputs])
        self.assertEqual([score.probability for score in scores], [0.5, 0.5, 0.5])

    def test_positive_logit_means_positive_label_probability(self):
        score = self.detector(2.0).predict_chunks(["x"])[0]
        self.assertAlmostEqual(score.probability, torch.sigmoid(torch.tensor(2.0)).item())
        self.assertGreater(score.probability, 0.5)

    def test_empty_inputs_have_no_invented_scores(self):
        detector = self.detector()
        self.assertEqual(detector.predict_chunks([]), [])
        for inputs in ([" "], ["x", "\n\t"], [None], "x", {"text": "x"}):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                detector.predict_chunks(inputs)
        self.assertEqual(detector.model.batch_sizes, [])

    def test_oversize_chunk_is_rejected_without_scoring_or_truncation(self):
        detector = self.detector()
        with self.assertRaisesRegex(ValueError, "split it first"):
            detector.predict_chunks(["x", "y" * 31])
        self.assertEqual(detector.model.batch_sizes, [])
        self.assertEqual(detector.predict_chunks(["x" * 30])[0].input_tokens, 32)

    def test_nonfinite_logits_and_wrong_output_shape_are_errors(self):
        for value in (float("inf"), float("nan")):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.detector(value).predict_chunks(["x"])
        detector = self.detector()
        detector.model = Mock(return_value=torch.ones(2))
        with self.assertRaises(RuntimeError):
            detector.predict_chunks(["x"])


class RuntimeHealthTests(unittest.TestCase):
    def test_single_initialization_even_with_concurrent_callers(self):
        loader = Mock(side_effect=lambda kind, settings: object())
        runtime = ModelRuntime(Settings(), loader)
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: runtime.initialize(), range(8)))
        self.assertEqual(loader.call_count, 2)
        self.assertTrue(runtime.health()["ready"])
        runtime.close()
        self.assertEqual(runtime.health()["status"], "stopped")
        with self.assertRaises(RuntimeError):
            runtime.get_detector("text")

    def test_loading_snapshot_does_not_block(self):
        observed = []
        runtime = ModelRuntime(Settings())
        def loader(kind, settings):
            observed.append(runtime.health())
            return object()
        runtime._loader = loader
        runtime.initialize()
        self.assertEqual([snapshot["status"] for snapshot in observed], ["starting", "starting"])
        self.assertEqual(observed[0]["models"]["text"]["status"], "loading")

    def test_health_before_startup_is_not_ready(self):
        app = create_app(Settings(), loader=Mock())
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
        # A client without a lifespan must not accidentally claim readiness.
        app = create_app(Settings(), loader=Mock())
        client = TestClient(app)
        response = client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "starting")
        client.close()

    def test_ready_health_loads_once_and_explains_experimental_code(self):
        loader = Mock(side_effect=lambda kind, settings: object())
        app = create_app(Settings(), loader=loader)
        with TestClient(app) as client:
            for _ in range(3):
                response = client.get("/health")
                self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(payload["status"], "ready")
            self.assertTrue(payload["analysis_available"])
            self.assertTrue(payload["models"]["code"]["experimental"])
            self.assertFalse(payload["models"]["text"]["experimental"])
            self.assertIn("synthetic", payload["models"]["code"]["positive_label"])
            self.assertIn("false positives", payload["disclaimer"])
            self.assertNotIn("probability", payload["models"]["code"])
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(client.post("/analyze", json={}).status_code, 415)
        self.assertEqual(app.state.runtime.health()["status"], "stopped")

    def test_one_failure_is_degraded_not_a_zero_score(self):
        def loader(kind, settings):
            if kind == "code":
                raise ModelLoadError("artifact_mismatch", "Inspected SHA-256 does not match: adapter.safetensors")
            return object()
        with self.assertLogs("backend.detectors.runtime", level="ERROR"):
            with TestClient(create_app(Settings(), loader=loader)) as client:
                response = client.get("/health")
                payload = response.json()
                self.assertEqual(response.status_code, 503)
                self.assertEqual(payload["status"], "degraded")
                self.assertEqual(payload["models"]["text"]["status"], "ready")
                self.assertEqual(payload["models"]["code"]["error"]["code"], "artifact_mismatch")
                self.assertFalse(payload["models"]["code"]["integrity_verified"])
                with self.assertRaises(RuntimeError):
                    client.app.state.runtime.get_detector("code")

    def test_both_failures_dependency_failure_and_unknown_errors(self):
        for exception, code in ((ImportError("missing dependency"), "dependency_missing"),
                                (RuntimeError("private filesystem details"), "load_failed")):
            with self.subTest(code=code), self.assertLogs("backend.detectors.runtime", level="ERROR"):
                loader = Mock(side_effect=exception)
                with TestClient(create_app(Settings(), loader=loader)) as client:
                    response = client.get("/health")
                    self.assertEqual(response.status_code, 503)
                    self.assertEqual(response.json()["status"], "unavailable")
                    for state in response.json()["models"].values():
                        self.assertEqual(state["error"]["code"], code)
                        self.assertNotIn("private filesystem", state["error"]["message"])
                    client.get("/health")
                    self.assertEqual(loader.call_count, 2)

    def test_none_returning_loader_is_unavailable(self):
        with self.assertLogs("backend.detectors.runtime", level="ERROR"):
            runtime = ModelRuntime(Settings(), loader=Mock(return_value=None))
            runtime.initialize()
        self.assertEqual(runtime.health()["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()

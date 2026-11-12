"""Offline smoke tests against the existing checkpoints, never downloads."""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

from backend.tests.helpers import TestClient, create_app

from backend.config import Settings
from backend.detectors.loaders import load_detector
from backend.detectors.runtime import ModelRuntime
from backend.analysis.pipeline import AnalysisPipeline


@unittest.skipUnless(os.environ.get("PDF_AI_RUN_MODEL_TESTS") == "1", "Opt in with PDF_AI_RUN_MODEL_TESTS=1")
class RealModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings = Settings()
        cls.loader = Mock(side_effect=load_detector)
        cls.runtime = ModelRuntime(cls.settings, loader=cls.loader)
        cls.runtime.initialize()
        cls.runtime.initialize()
        if not cls.runtime.health()["ready"]:
            raise RuntimeError(f"Real model initialization failed: {cls.runtime.health()}")

    @classmethod
    def tearDownClass(cls):
        cls.runtime.close()

    def test_models_are_strictly_loaded_once_and_in_evaluation_mode(self):
        self.assertEqual(self.loader.call_count, 2)
        for kind in ("text", "code"):
            detector = self.runtime.get_detector(kind)
            self.assertFalse(detector.model.training)
            self.assertTrue(all(not module.training for module in detector.model.modules()))
        text = self.runtime.get_detector("text").model
        code = self.runtime.get_detector("code").model
        self.assertEqual(tuple(text.classifier.weight.shape), (1, 1024))
        self.assertEqual(tuple(code.head.weight.shape), (1, 768))
        self.assertEqual(len(text.model.encoder.layer), 24)
        self.assertEqual(len(code.backbone.encoder.layer), 12)

    def test_raw_scores_are_finite_and_padding_invariant_for_both_models(self):
        samples = {
            "text": [
                "We measured the resistor voltage three times and recorded the values in our laboratory notebook.",
                "The purpose of this experiment was to compare the theoretical circuit response with measured data. "
                "We connected the components, checked the supply voltage, and repeated each measurement. "
                "Small differences may be caused by component tolerances and instrument resolution.",
            ],
            "code": [
                "def sum_items(items):\n    total = 0\n    for item in items:\n        total += item\n    return total\n",
                "function summarizeValues(values) {\n  // Keep only finite numbers before calculating their sum.\n"
                "  const validValues = values.filter(value => Number.isFinite(value));\n"
                "  return validValues.reduce((total, value) => total + value, 0);\n}\n",
            ],
        }
        for kind, inputs in samples.items():
            with self.subTest(kind=kind):
                detector = self.runtime.get_detector(kind)
                batch = detector.predict_chunks(inputs)
                self.assertEqual(len(batch), 2)
                for text, score in zip(inputs, batch):
                    self.assertTrue(0 <= score.probability <= 1)
                    self.assertGreater(score.input_tokens, 2)
                    single = detector.predict_chunks([text])[0]
                    self.assertAlmostEqual(single.probability, score.probability, delta=2e-5)
                    self.assertEqual(single.input_tokens, score.input_tokens)

    def test_512_token_forward_and_overlength_rejection(self):
        for kind in ("text", "code"):
            with self.subTest(kind=kind):
                detector = self.runtime.get_detector(kind)
                # Both inspected tokenizers encode each repeated x as one token.
                text = " ".join(["x"] * 510)
                self.assertEqual(len(detector.tokenizer(text)["input_ids"]), 512)
                score = detector.predict_chunks([text])[0]
                self.assertEqual(score.input_tokens, 512)
                self.assertTrue(0 <= score.probability <= 1)
                with self.assertRaises(ValueError):
                    detector.predict_chunks([text + " x"])

    def test_real_ready_health_with_no_additional_weight_loads(self):
        cached_loader = Mock(side_effect=lambda kind, settings: self.runtime.get_detector(kind))
        with TestClient(create_app(self.settings, loader=cached_loader),base_url="http://localhost") as client:
            response = client.get("/health")
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["ready"])
            self.assertTrue(all(state["integrity_verified"] for state in payload["models"].values()))
            self.assertEqual(payload["models"]["text"]["positive_label"], "AI-generated text")
            self.assertTrue(payload["models"]["code"]["experimental"])
        self.assertEqual(self.loader.call_count, 2)
        self.assertEqual(cached_loader.call_count, 2)

    def test_actual_pdf_extraction_through_both_real_detectors(self):
        from backend.tests.test_analysis import fixture_pdf
        with TemporaryDirectory(dir=self.settings.temp_dir) as directory:
            path=Path(directory)/"input.pdf"
            path.write_bytes(fixture_pdf())
            result=AnalysisPipeline(self.settings,self.runtime).run(path,.5)
        self.assertEqual(result["document"]["pages"],2)
        self.assertEqual(result["text"]["status"],"scored")
        self.assertEqual(result["code"]["status"],"scored")
        for kind in ("text","code"):
            self.assertTrue(0<=result[kind]["flagged_content_share"]<=1)
            self.assertTrue(0<=result[kind]["raw_mean_model_score"]<=1)
            self.assertTrue(all(chunk["input_tokens"]<=512 for chunk in result[kind]["chunk_scores"]))


if __name__ == "__main__":
    unittest.main()

import hashlib
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from product.desktop.config import offline_policy, standard_config
from product.desktop.controller import Controller, export_data, save_export
from product.desktop.fixtures import SOURCE_TEXT, pdf
from product.engine.assets import verify_assets
from product.engine.calibration import Calibration
from product.engine.detection import DetectionEngine
from product.engine.resources import ResourceLimit, require_memory
from product.packaging.prepare import check_pin


class ConfigurationTests(unittest.TestCase):
    def fixture(self, root):
        pins = {"schema_version": 1, "models": {}}
        for role in ("text", "semantic"):
            data = b"Integrity fixture only; never passed to a model loader."
            digest = hashlib.sha256(data).hexdigest()
            path = root / "models" / (role + "-" + "a" * 40)
            path.mkdir(parents=True)
            (path / "config.json").write_bytes(data)
            pins["models"][role] = {"revision": "a" * 40, "files": {"config.json": {"bytes": len(data), "sha256": digest}}}
            (root / "models" / (role + "-manifest.json")).write_text(json.dumps({"schema_version": 1, "assets": {"path": {"config.json": digest}}}))
        (root / "model-pins.json").write_text(json.dumps(pins))
        return hashlib.sha256(json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def test_relocatable_profile_enables_only_standard_models(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = self.fixture(root)
            with patch("product.desktop.config.APPROVED_PINS_SHA256", digest):
                config = standard_config(root)
            self.assertEqual(set(config["signals"]), {"text"})
            self.assertTrue(Path(config["signals"]["text"]["path"]).is_relative_to(root.resolve()))
            verify_assets(config["signals"]["text"], ("path",))
            (Path(config["signals"]["text"]["path"]) / "config.json").write_text("corrupted")
            with self.assertRaises(ValueError):
                verify_assets(config["signals"]["text"], ("path",))
            detector = DetectionEngine(config)
            result = detector.run(SOURCE_TEXT)
            self.assertIsNone(result["overall"]["ai"]["percent"])
            self.assertEqual(detector.ai.states["text"], "unavailable")

    def test_tampered_pins_cannot_reauthorize_weights(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            with self.assertRaisesRegex(ValueError, "approved application"):
                standard_config(root)

    def test_manifest_must_match_embedded_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            digest = self.fixture(root)
            (root / "models/text-manifest.json").write_text("{}")
            with patch("product.desktop.config.APPROVED_PINS_SHA256", digest), self.assertRaisesRegex(ValueError, "manifest differs"):
                standard_config(root)

    def test_offline_policy_precedes_loaders(self):
        with patch.dict(os.environ, {}, clear=True):
            offline_policy(Path("bundle"))
            for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY"):
                self.assertEqual(os.environ[key], "1")
            self.assertEqual(os.environ["PLAYWRIGHT_BROWSERS_PATH"], str(Path("bundle/browsers")))

    def test_no_fitted_heads_in_standard_calibration(self):
        self.assertEqual(Calibration().artifact["heads"], {})

    def test_resource_gates_abstain(self):
        with patch("product.engine.resources.physical_memory", return_value=4 * 1024 ** 3), patch("product.engine.resources.available_memory", return_value=1 * 1024 ** 3):
            with self.assertRaises(ResourceLimit):
                require_memory(8, 3)

    def test_pinned_paths_reject_traversal_and_executable_weights(self):
        pin = {"bytes": 5, "sha256": "a" * 64}
        for name in ("../config.json", "/config.json", "C:/config.json", "model.bin", "file.py", "x\\config.json"):
            with self.assertRaises(ValueError):
                check_pin(name, pin)

    def test_freezer_entry_does_not_shadow_packaging_dependency(self):
        spec = (Path(__file__).parents[1] / "packaging/verity.spec").read_text()
        self.assertIn("root / 'verity.py'", spec)
        self.assertNotIn("product/desktop_entry.py", spec)


class ControllerTests(unittest.TestCase):
    def wait(self, controller):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            for message in controller.poll():
                if message["type"] in {"completed", "error"}:
                    return message
            time.sleep(0.02)
        self.fail("Worker timeout")

    def test_real_owned_process_pdf_extraction_and_no_server_import(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / "input.pdf"
            path.write_bytes(pdf("Fixture", [SOURCE_TEXT]))
            controller = Controller(root)
            try:
                controller.submit("pdf", path=str(path), network_guard=True)
                with self.assertRaises(ValueError):
                    controller.submit("pdf", path=str(path))
                result = self.wait(controller)
                self.assertEqual(result["type"], "completed")
                self.assertIn(SOURCE_TEXT, result["result"]["text"])
            finally:
                controller.cancel()
            self.assertFalse(controller.busy)
            self.assertIsNone(controller.process)

    def test_worker_errors_do_not_leak_private_filename(self):
        with tempfile.TemporaryDirectory() as folder:
            controller = Controller(folder)
            try:
                controller.submit("pdf", path=str(Path(folder) / "private-person.pdf"))
                message = self.wait(controller)
                self.assertEqual(message["type"], "error")
                self.assertNotIn(folder, json.dumps(message))
                self.assertNotIn("private-person", json.dumps(message))
            finally:
                controller.cancel()

    def test_exports_preserve_document_and_exclude_configuration(self):
        result = DetectionEngine().run(SOURCE_TEXT)
        result.update(token="secret", config={"path": "/private/model"})
        exported = export_data(result)
        self.assertNotIn("token", exported)
        self.assertNotIn("config", exported)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "review.json"
            save_export(path, result, "json")
            self.assertEqual(json.loads(path.read_text())["text"], SOURCE_TEXT)
            destination = Path(folder) / "link.json"
            destination.symlink_to(path)
            with self.assertRaises(ValueError):
                save_export(destination, result, "json")


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from product.desktop.app import DesktopApp
        offline_policy(Path("bundle"))
        cls.app = DesktopApp(Path("bundle"))
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.app.close()

    def tearDown(self):
        self.app.clear()

    def test_unicode_segment_marks_are_exact_on_tk(self):
        text = "A fox 🦊 crossed the quiet garden path while the morning rain was falling.\n\nAnother sufficiently long sentence records the event without claiming any model accuracy."
        result = DetectionEngine().run(text)
        self.app.show_result(result)
        self.assertEqual(self.app.result_text.get("1.0", "end-1c"), text)
        for row in result["segments"]:
            self.assertEqual(self.app.result_text.get(row["id"] + "_start", row["id"] + "_end"), row["text"])

    def test_edit_revokes_consent_and_invalidates_exports(self):
        self.app.show_result(DetectionEngine().run(SOURCE_TEXT))
        self.app.consent.set(True)
        self.app.editor.insert("1.0", "Edited text")
        self.app.edited()
        self.assertIsNone(self.app.result)
        self.assertFalse(self.app.consent.get())
        self.assertEqual(str(self.app.export_json["state"]), "disabled")

    def test_source_evidence_is_visible_without_ai_probability(self):
        result = DetectionEngine().run(SOURCE_TEXT)
        row = result["segments"][0]
        row["plagiarism"].update(status="checked", match={"title": "First-party protocol fixture", "url": "https://example.org/fixture", "similarity": 0.9, "excerpt": "Visible evidence fixture"})
        self.app.show_result(result)
        self.app.rows.selection_set(row["id"])
        self.app.select_segment()
        self.assertIn("Visible evidence fixture", self.app.evidence.get())
        self.assertTrue(self.app.result_text.tag_ranges("evidence"))
        self.assertEqual(str(self.app.source_button["state"]), "normal")


if __name__ == "__main__":
    unittest.main()

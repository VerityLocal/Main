import base64
import io
import json
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from product.tests.browser.make_pdfs import SOURCE_TEXT, pdf
from product.engine.native_host import bootstrap, initialize_config, read_message, request_helper, validate_caller, write_message
from product.installer.provision import HOST, register

PRODUCT = Path(__file__).parents[1]
ORIGIN = "chrome-extension://" + "a" * 32
RELEASE = {"engine_version": "0.2.0", "chrome_origin": ORIGIN, "firefox_id": "verity@local.invalid"}
MESSAGE = {"type": "bootstrap", "protocol": 1, "origin": ORIGIN}


class NativeTests(unittest.TestCase):
    def test_native_framing_limits_and_partial_messages(self):
        stream = io.BytesIO()
        write_message(stream, MESSAGE)
        stream.seek(0)
        self.assertEqual(read_message(stream), MESSAGE)
        self.assertIsNone(read_message(io.BytesIO()))
        for data in [b"x", struct.pack("<I", 9000), struct.pack("<I", 5) + b"{}", struct.pack("<I", 2) + b"[]"]:
            with self.assertRaises(ValueError):
                read_message(io.BytesIO(data))

    def test_json_cannot_impersonate_the_browser_caller(self):
        self.assertEqual(validate_caller(MESSAGE, [ORIGIN + "/"], RELEASE), ORIGIN)
        for caller in [[], ["chrome-extension://" + "b" * 32 + "/"], [RELEASE["firefox_id"]]]:
            with self.assertRaises(ValueError):
                validate_caller(MESSAGE, caller, RELEASE)
        firefox = {**MESSAGE, "origin": "moz-extension://" + "c" * 36}
        self.assertEqual(validate_caller(firefox, ["/host/manifest.json", RELEASE["firefox_id"]], RELEASE), firefox["origin"])

    def test_existing_token_and_model_configuration_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            path = Path(folder) / "helper.json"
            initial = initialize_config(path, ORIGIN)
            initial["signals"] = {"text": {"enabled": False, "path": "private operator setting"}}
            path.write_text(json.dumps(initial))
            updated = initialize_config(path, "moz-extension://" + "c" * 36)
            self.assertEqual(initial["token"], updated["token"])
            self.assertEqual(initial["signals"], updated["signals"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_unknown_service_is_not_terminated_or_replaced(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            with patch("product.engine.native_host.request_helper", side_effect=ValueError("port_conflict")), patch("product.engine.native_host.subprocess.Popen") as spawn:
                with self.assertRaisesRegex(ValueError, "port_conflict"):
                    bootstrap(MESSAGE, [ORIGIN + "/"], RELEASE, Path(folder) / "helper.json", Path(folder) / "native_entry.py")
                spawn.assert_not_called()

    def test_real_native_subprocess_starts_pairs_and_extracts_pdf(self):
        with tempfile.TemporaryDirectory(prefix="verity-native-", dir=PRODUCT) as folder:
            root = Path(folder)
            (root / "product/engine").mkdir(parents=True)
            (root / "product/extension").mkdir(parents=True)
            for source in (PRODUCT / "engine").glob("*.py"):
                shutil.copyfile(source, root / "product/engine" / source.name)
            shutil.copyfile(PRODUCT / "extension/calibration.json", root / "product/extension/calibration.json")
            entry = root / "native_entry.py"
            shutil.copyfile(PRODUCT / "installer/native_entry.py", entry)
            release = root / "release.json"
            release.write_text(json.dumps(RELEASE))
            config = root / "helper.json"
            token = "t" * 43
            config.write_text(json.dumps({"token": token, "origins": [], "signals": {}, "idle_seconds": 2}))
            stream = io.BytesIO()
            write_message(stream, MESSAGE)
            try:
                completed = subprocess.run([sys.executable, "-I", str(entry), "native", "--release", str(release), "--config", str(config), "--entrypoint", str(entry), ORIGIN + "/"], input=stream.getvalue(), capture_output=True, timeout=25, check=True)
                response = read_message(io.BytesIO(completed.stdout))
                self.assertTrue(response["ready"], response)
                self.assertEqual(response["token"], token)
                self.assertEqual(completed.stderr, b"")
                self.assertTrue(request_helper(token)["ready"])
                result = request_helper(token, "/extract", {"data": base64.b64encode(pdf("Native fixture", [SOURCE_TEXT])).decode()})
                self.assertIn(SOURCE_TEXT, result["text"])
            finally:
                try:
                    request_helper(token, "/shutdown", {})
                except (OSError, ValueError):
                    pass
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        with socket.create_connection(("127.0.0.1", 8790), timeout=.2):
                            pass
                    except OSError:
                        break
                    time.sleep(.05)


class InstallerTests(unittest.TestCase):
    def make_release(self, root):
        root.mkdir(parents=True)
        (root / "release.json").write_text(json.dumps(RELEASE))

    def test_per_user_registration_and_reinstall_preserve_token(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            home = Path(folder) / "home"
            install = home / "Library/Application Support/Verity"
            root = install / "versions/test-release"
            self.make_release(root)
            register(root, install, home)
            original = json.loads((install / "helper.json").read_text())
            register(root, install, home)
            self.assertEqual(original["token"], json.loads((install / "helper.json").read_text())["token"])
            for browser in ["Google/Chrome", "Microsoft Edge", "Chromium"]:
                value = json.loads((home / "Library/Application Support" / browser / "NativeMessagingHosts" / (HOST + ".json")).read_text())
                self.assertEqual(value["allowed_origins"], [ORIGIN + "/"])
                self.assertEqual(value["path"], str(root / "native-host"))
            firefox = json.loads((home / "Library/Application Support/Mozilla/NativeMessagingHosts" / (HOST + ".json")).read_text())
            self.assertEqual(firefox["allowed_extensions"], [RELEASE["firefox_id"]])
            self.assertNotIn("allowed_origins", firefox)
            self.assertEqual((root / "native-host").stat().st_mode & 0o777, 0o700)

    def test_unrelated_registration_is_preserved_before_any_pairing(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            home = Path(folder) / "home"
            install = home / "Library/Application Support/Verity"
            root = install / "versions/test-release"
            self.make_release(root)
            path = home / "Library/Application Support/Microsoft Edge/NativeMessagingHosts" / (HOST + ".json")
            path.parent.mkdir(parents=True)
            existing = {"name": HOST, "path": "/unrelated/user/program"}
            path.write_text(json.dumps(existing))
            with self.assertRaises(ValueError):
                register(root, install, home)
            self.assertEqual(json.loads(path.read_text()), existing)
            self.assertFalse((install / "helper.json").exists())

    def test_registration_symlink_is_rejected_without_changing_its_target(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            home = Path(folder) / "home"
            install = home / "Library/Application Support/Verity"
            root = install / "versions/test-release"
            self.make_release(root)
            target = Path(folder) / "other-registration.json"
            target.write_text(json.dumps({"name": HOST, "path": str(root / "native-host")}))
            original = target.read_bytes()
            path = home / "Library/Application Support/Chromium/NativeMessagingHosts" / (HOST + ".json")
            path.parent.mkdir(parents=True)
            path.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                register(root, install, home)
            self.assertTrue(path.is_symlink())
            self.assertEqual(target.read_bytes(), original)
            self.assertFalse((install / "helper.json").exists())

    def test_registration_path_cannot_escape_versions_with_traversal_or_symlinks(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            home = Path(folder) / "home"
            install = home / "Library/Application Support/Verity"
            root = install / "versions/test-release"
            self.make_release(root)
            outside = Path(folder) / "unrelated"
            outside.mkdir()
            alias = install / "versions/alias"
            alias.symlink_to(outside, target_is_directory=True)
            path = home / "Library/Application Support/Chromium/NativeMessagingHosts" / (HOST + ".json")
            path.parent.mkdir(parents=True)
            for host in [install / "versions/../../unrelated/native-host", alias / "native-host"]:
                with self.subTest(host=host):
                    path.write_text(json.dumps({"name": HOST, "path": str(host)}))
                    original = path.read_bytes()
                    with self.assertRaisesRegex(ValueError, "unrelated"):
                        register(root, install, home)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertFalse((install / "helper.json").exists())


if __name__ == "__main__":
    unittest.main()

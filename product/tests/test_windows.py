import json
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from product.engine.local_os import helper_process_options, reject_link
from product.installer.provision_windows import HOST, REGISTRY_BASES, register

PRODUCT = Path(__file__).parents[1]
ORIGIN = "chrome-extension://" + "a" * 32
RELEASE = {"engine_version": "0.2.0", "chrome_origin": ORIGIN, "firefox_id": "verity@local.invalid"}


class RegistryKey:
    def __init__(self, registry, key, view):
        self.registry, self.key, self.view = registry, key, view

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class FakeRegistry:
    HKEY_CURRENT_USER = "current-user-only"
    KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 1
    KEY_WOW64_32KEY, KEY_WOW64_64KEY = 0x200, 0x100

    def __init__(self):
        self.values, self.writes = {}, []
        self.fail_once = False

    def OpenKey(self, hive, key, reserved, access):
        assert hive == self.HKEY_CURRENT_USER
        view = access & 0x300
        if (key, view) not in self.values:
            raise FileNotFoundError()
        return RegistryKey(self, key, view)

    def CreateKeyEx(self, hive, key, reserved, access):
        assert hive == self.HKEY_CURRENT_USER
        view = access & 0x300
        self.values.setdefault((key, view), None)
        return RegistryKey(self, key, view)

    def QueryValueEx(self, opened, name):
        assert name == ""
        value = self.values[opened.key, opened.view]
        if value is None:
            raise FileNotFoundError()
        return value

    def SetValueEx(self, opened, name, reserved, kind, value):
        assert name == ""
        if self.fail_once and "Mozilla" in opened.key:
            self.fail_once = False
            raise PermissionError("Controlled registry failure")
        self.values[opened.key, opened.view] = (value, kind)
        self.writes.append((opened.key, opened.view, value))

    def DeleteValue(self, opened, name):
        assert name == ""
        self.values[opened.key, opened.view] = None


class WindowsInstallerTests(unittest.TestCase):
    def make_release(self, root):
        (root / "python").mkdir(parents=True)
        (root / "python/python.exe").write_bytes(b"MZ fixture")
        (root / "native-host.exe").write_bytes(b"MZ fixture")
        (root / "release.json").write_text(json.dumps(RELEASE))

    def test_both_registry_views_pair_only_fixed_browser_identities(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            install = Path(folder) / "Verity"
            root = install / "versions/fixture"
            self.make_release(root)
            registry = FakeRegistry()
            register(root, install, registry)
            original = json.loads((install / "helper.json").read_text())
            register(root, install, registry)
            self.assertEqual(original["token"], json.loads((install / "helper.json").read_text())["token"])
            self.assertEqual(len(registry.values), 8)
            for (key, view), (path, kind) in registry.values.items():
                self.assertTrue(key.endswith("\\" + HOST))
                self.assertIn(view, [registry.KEY_WOW64_32KEY, registry.KEY_WOW64_64KEY])
                value = json.loads(Path(path).read_text())
                self.assertEqual(value["path"], str(root / "native-host.exe"))
                if "Mozilla" in key:
                    self.assertEqual(value["allowed_extensions"], [RELEASE["firefox_id"]])
                    self.assertNotIn("allowed_origins", value)
                else:
                    self.assertEqual(value["allowed_origins"], [ORIGIN + "/"])
            self.assertEqual(json.loads((install / "installed.json").read_text())["platform"], "windows")

    def test_registry_collision_changes_nothing_before_pairing(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            install = Path(folder) / "Verity"
            root = install / "versions/fixture"
            self.make_release(root)
            registry = FakeRegistry()
            key = REGISTRY_BASES[-1] + "\\" + HOST
            registry.values[key, registry.KEY_WOW64_64KEY] = (str(Path(folder) / "unrelated.json"), registry.REG_SZ)
            original = dict(registry.values)
            with self.assertRaisesRegex(ValueError, "unrelated"):
                register(root, install, registry)
            self.assertEqual(registry.values, original)
            self.assertFalse(registry.writes)
            self.assertFalse((install / "helper.json").exists())

    def test_upgrade_and_failed_registration_preserve_existing_release_and_token(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            install = Path(folder) / "Verity"
            old, new = install / "versions/old", install / "versions/new"
            self.make_release(old)
            self.make_release(new)
            registry = FakeRegistry()
            register(old, install, registry)
            previous_values = dict(registry.values)
            token = json.loads((install / "helper.json").read_text())["token"]
            registry.fail_once = True
            with self.assertRaises(PermissionError):
                register(new, install, registry)
            self.assertEqual(registry.values, previous_values)
            self.assertEqual(json.loads((install / "installed.json").read_text())["release_root"], str(old))
            register(new, install, registry)
            self.assertEqual(json.loads((install / "helper.json").read_text())["token"], token)
            self.assertEqual(json.loads((install / "installed.json").read_text())["release_root"], str(new))
            self.assertTrue((old / "native-host.exe").exists())

    def test_release_outside_installation_and_linked_executables_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=PRODUCT) as folder:
            install = Path(folder) / "Verity"
            outside = Path(folder) / "outside"
            self.make_release(outside)
            with self.assertRaises(ValueError):
                register(outside, install, FakeRegistry())
            root = install / "versions/fixture"
            self.make_release(root)
            (root / "native-host.exe").unlink()
            (root / "native-host.exe").symlink_to(outside / "native-host.exe")
            with self.assertRaises(ValueError):
                register(root, install, FakeRegistry())

    def test_reparse_points_and_windows_process_policy(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info):
            with self.assertRaisesRegex(ValueError, "reparse"):
                reject_link("fixture-junction")
        self.assertEqual(helper_process_options("win32"), {"creationflags": 0x08000200})
        self.assertEqual(helper_process_options("darwin"), {"start_new_session": True})


if __name__ == "__main__":
    unittest.main()

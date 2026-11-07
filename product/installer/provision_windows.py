"""Per-user Windows native registration; no system registry or administrator setup."""
import argparse
import json
from pathlib import Path

from product.engine.local_os import bootstrap_lock, reject_link
from product.engine.native_host import initialize_config, save_config

HOST = "local.verity.helper"
REGISTRY_BASES = [
    r"Software\Google\Chrome\NativeMessagingHosts",
    r"Software\Microsoft\Edge\NativeMessagingHosts",
    r"Software\Chromium\NativeMessagingHosts",
    r"Software\Mozilla\NativeMessagingHosts",
]


def existing_value(registry, key, view):
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, key, 0, registry.KEY_READ | view) as opened:
            value, kind = registry.QueryValueEx(opened, "")
            if kind != registry.REG_SZ or not isinstance(value, str):
                raise ValueError("Unsupported existing native-host registration")
            return value
    except FileNotFoundError:
        return None


def validate_existing(path, install_root):
    candidate = Path(path)
    reject_link(candidate)
    if not candidate.is_absolute() or not candidate.resolve().is_relative_to((install_root / "versions").resolve()):
        raise ValueError("An unrelated native-host registration already exists")
    manifest = json.loads(candidate.read_text(encoding="utf-8"))
    launcher = Path(manifest.get("path", ""))
    reject_link(launcher)
    if manifest.get("name") != HOST or launcher.name != "native-host.exe" or not launcher.resolve().is_relative_to((install_root / "versions").resolve()):
        raise ValueError("An unrelated native-host registration already exists")


def register(root, install_root, registry=None):
    if registry is None:
        import winreg as registry
    root, install_root = Path(root).resolve(), Path(install_root).resolve()
    if not root.is_relative_to(install_root / "versions"):
        raise ValueError("The release must be inside the private installation")
    for path in [root, root / "native-host.exe", root / "python/python.exe"]:
        reject_link(path)
        if not path.exists():
            raise ValueError("Installed runtime is incomplete")
    release = json.loads((root / "release.json").read_text(encoding="utf-8"))
    chrome = {"name": HOST, "description": "Verity local desktop companion", "path": str(root / "native-host.exe"), "type": "stdio", "allowed_origins": [release["chrome_origin"] + "/"]}
    firefox = {k: v for k, v in chrome.items() if k != "allowed_origins"}
    firefox["allowed_extensions"] = [release["firefox_id"]]
    paths = {"chrome": root / "chrome-native.json", "firefox": root / "firefox-native.json"}
    install_root.mkdir(parents=True, exist_ok=True)
    with bootstrap_lock(install_root / "helper.json.lock"):
        changes = []
        for base in REGISTRY_BASES:
            for view in [registry.KEY_WOW64_32KEY, registry.KEY_WOW64_64KEY]:
                key = base + "\\" + HOST
                original = existing_value(registry, key, view)
                if original is not None:
                    validate_existing(original, install_root)
                changes.append((key, view, original, str(paths["firefox" if "Mozilla" in base else "chrome"])))
        # Validate every collision before pairing or changing any registration.
        initialize_config(install_root / "helper.json", release["chrome_origin"])
        save_config(paths["chrome"], chrome)
        save_config(paths["firefox"], firefox)
        written = []
        try:
            for key, view, original, value in changes:
                with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, key, 0, registry.KEY_SET_VALUE | view) as opened:
                    registry.SetValueEx(opened, "", 0, registry.REG_SZ, value)
                written.append((key, view, original))
            save_config(install_root / "installed.json", {"version": release["engine_version"], "release_root": str(root), "platform": "windows"})
        except Exception:
            # Restore only the default values this invocation actually changed.
            for key, view, original in reversed(written):
                with registry.OpenKey(registry.HKEY_CURRENT_USER, key, 0, registry.KEY_SET_VALUE | view) as opened:
                    if original is None:
                        registry.DeleteValue(opened, "")
                    else:
                        registry.SetValueEx(opened, "", 0, registry.REG_SZ, original)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    args = parser.parse_args()
    register(args.root, args.install_root)
    print("Desktop companion installed and per-user browsers registered.")


if __name__ == "__main__":
    main()

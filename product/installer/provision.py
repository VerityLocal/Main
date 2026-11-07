"""Finish a staged install; register only the fixed extension IDs, per user."""
import argparse
import json
import os
import shlex
from pathlib import Path

from product.engine.native_host import initialize_config, save_config
from product.engine.model_setup import apply_profile

HOST = "local.verity.helper"


def register(root, install_root, browser_home):
    release = json.loads((root / "release.json").read_text())
    config = install_root / "helper.json"
    launcher = root / "native-host"
    command = [str(root / "python/bin/python3"), "-I", str(root / "native_entry.py"), "native", "--release", str(root / "release.json"), "--config", str(config), "--entrypoint", str(root / "native_entry.py")]
    launcher.write_text("#!/bin/sh\nexec " + " ".join(shlex.quote(value) for value in command) + ' "$@"\n')
    launcher.chmod(0o700)
    manifest = {"name": HOST, "description": "Verity local desktop companion", "path": str(launcher), "type": "stdio", "allowed_origins": [release["chrome_origin"] + "/"]}
    base = browser_home / "Library/Application Support"
    registrations = []
    for browser in ["Google/Chrome", "Microsoft Edge", "Chromium"]:
        path = base / browser / "NativeMessagingHosts" / (HOST + ".json")
        registrations.append((path, manifest))
    firefox = {k: v for k, v in manifest.items() if k != "allowed_origins"}
    firefox["allowed_extensions"] = [release["firefox_id"]]
    registrations.append((base / "Mozilla/NativeMessagingHosts" / (HOST + ".json"), firefox))
    for path, _ in registrations:
        validate_registration(path, install_root)
    value = initialize_config(config, release["chrome_origin"])
    profile = install_root / "models-profile.json"
    if profile.exists():
        if profile.is_symlink():
            raise ValueError("A model profile cannot be a symlink")
        save_config(config, apply_profile(value, json.loads(profile.read_text())))
    for path, value in registrations:
        save_config(path, value)
    save_config(install_root / "installed.json", {"version": release["engine_version"], "release_root": str(root)})


def validate_registration(path, install_root):
    # Do not overwrite a different application's existing registration.
    if path.is_symlink():
        raise ValueError("A native-host registration cannot be a symlink")
    if path.exists():
        existing = json.loads(path.read_text())
        if existing.get("name") != HOST or not Path(existing.get("path", "")).resolve().is_relative_to(install_root.resolve() / "versions"):
            raise ValueError("An unrelated native-host registration already exists")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--browser-home", type=Path, required=True)
    args = parser.parse_args()
    register(args.root.resolve(), args.install_root.resolve(), args.browser_home.resolve())
    print("Desktop companion installed and browser connection registered.")


if __name__ == "__main__":
    main()

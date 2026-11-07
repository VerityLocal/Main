"""Actual native messaging smoke using an installed sandbox companion, no API mock."""
import argparse
import asyncio
import functools
import json
import os
import shutil
import socket
import tempfile
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

from internal.demo.make_pdfs import BASE, SOURCE_TEXT
from product.engine.native_host import request_helper


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def stopped():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", 8790), timeout=.2):
                pass
        except OSError:
            return
        time.sleep(.05)
    raise AssertionError("The test companion did not stop")


def stop_companion(install):
    token = json.loads((install / "helper.json").read_text())["token"]
    try:
        request_helper(token, "/shutdown", {})
    except ConnectionRefusedError:
        return
    stopped()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install-root", type=Path, required=True)
    parser.add_argument("--browser-home", type=Path, required=True)
    args = parser.parse_args()
    install = args.install_root.resolve()
    home = args.browser_home.resolve()
    state = json.loads((install / "installed.json").read_text())
    root = Path(state["release_root"])
    release = json.loads((root / "release.json").read_text())
    screenshots = BASE / "screenshots"
    files = ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(QuietFiles, directory=str(BASE)))
    files.daemon_threads = True
    threading.Thread(target=files.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix="verity-desktop-browser-", dir=home) as temporary:
            extension = Path(temporary) / "extension"
            shutil.copytree(root / "chrome-extension", extension)
            manifest = json.loads((extension / "manifest.json").read_text())
            # Only browser-chrome document permission/side-panel semantics are fixtures.
            manifest["host_permissions"].append("http://127.0.0.1/*")
            (extension / "manifest.json").write_text(json.dumps(manifest))
            profile = Path(temporary) / "profile"
            hosts = profile / "NativeMessagingHosts"
            hosts.mkdir(parents=True)
            # Chromium resolves per-user hosts under its explicit --user-data-dir.
            # Copy the installer's actual manifest into this isolated test profile.
            shutil.copyfile(home / "Library/Application Support/Chromium/NativeMessagingHosts/local.verity.helper.json", hosts / "local.verity.helper.json")
            async with async_playwright() as runtime:
                print("Launching the isolated MV3/native smoke.", flush=True)
                context = await runtime.chromium.launch_persistent_context(str(profile), channel="chromium", headless=True, args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"], env={**os.environ, "HOME": str(home)}, viewport={"width": 440, "height": 1000})
                try:
                    worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
                    extension_id = worker.url.split("/")[2]
                    assert "chrome-extension://" + extension_id == release["chrome_origin"]
                    source = await context.new_page()
                    await source.goto("http://127.0.0.1:8765/embedded.html")
                    panel = await context.new_page()
                    await panel.add_init_script("""(() => {
                      const query = chrome.tabs.query.bind(chrome.tabs);
                      chrome.tabs.query = async () => (await query({})).filter(tab => tab.url?.startsWith('http://127.0.0.1:8765/')).slice(0, 1);
                      const activated = chrome.tabs.onActivated.addListener.bind(chrome.tabs.onActivated);
                      chrome.tabs.onActivated.addListener = callback => activated(async info => {
                        const tab = await chrome.tabs.get(info.tabId);
                        if (!tab.url?.startsWith('chrome-extension://')) callback(info);
                      });
                    })();""")
                    errors = []
                    panel.on("pageerror", lambda error: errors.append(str(error)))
                    await panel.goto(f"chrome-extension://{extension_id}/panel.html")
                    try:
                        await panel.locator("#connection-status").filter(has_text="Desktop companion ready").wait_for(state="attached", timeout=30_000)
                    except Exception as error:
                        status = await panel.locator("#connection-status").inner_text()
                        raise AssertionError("Actual native bootstrap failed: " + status) from error
                    print("Automatic native bootstrap passed.", flush=True)
                    assert await panel.locator("#advanced").get_attribute("open") is None
                    await panel.locator("#extract").click()
                    await panel.locator("#scan:not([disabled])").wait_for(timeout=20_000)
                    assert SOURCE_TEXT in await panel.locator("#reader").inner_text()
                    await panel.locator("#scan").click()
                    await panel.locator("#export:not([disabled])").wait_for(timeout=20_000)
                    assert await panel.locator("#ai-score").inner_text() == "Unavailable"
                    assert await panel.locator("#copy-score").inner_text() == "Not checked"
                    repeat = await panel.evaluate("""async () => {
                      const origin = chrome.runtime.getURL('').replace(/\/$/, '');
                      const stored = (await chrome.storage.local.get('pairingToken')).pairingToken;
                      const response = await chrome.runtime.sendNativeMessage('local.verity.helper', {type: 'bootstrap', protocol: 1, origin});
                      return {ready: response.ready, sameToken: response.token === stored, sameOrigin: response.origin === origin};
                    }""")
                    assert repeat == {"ready": True, "sameToken": True, "sameOrigin": True}, repeat
                    await panel.screenshot(path=str(screenshots / "automatic-companion.png"), full_page=True)
                    print("Installed PDF extraction, offline scan and preserved pairing passed.", flush=True)
                    # Reading restarts a stopped helper without opening Settings/Connect.
                    await asyncio.to_thread(stop_companion, install)
                    await panel.locator("#extract").click()
                    await panel.locator("#scan:not([disabled])").wait_for(timeout=20_000)
                    assert SOURCE_TEXT in await panel.locator("#reader").inner_text()
                    await asyncio.to_thread(stop_companion, install)
                    await panel.reload()
                    await panel.locator("#connection-status").filter(has_text="Desktop companion ready").wait_for(state="attached", timeout=30_000)
                    assert await panel.locator("#advanced").get_attribute("open") is None
                    assert not errors, errors
                    print("Automatic restart before read and on panel reopen passed.", flush=True)
                    result = {"installed_standalone_runtime": "passed", "actual_mv3_native_messaging": "passed; no native API shim", "automatic_pairing": "passed; no token entry", "helper_startup": "passed", "pdf_extraction": "passed with installed runtime", "offline_scan": "passed; AI unavailable, sources not checked", "repeat_bootstrap_preserves_token": "passed", "helper_restart": "passed automatically before read", "restart_on_panel_reopen": "passed with saved pairing; no Connect click", "test_only_substitutions": ["sandbox HOME/profile; installed native manifest copied to explicit user-data-dir", "side-panel active-tab semantics", "loopback document permission pregrant"], "screenshot": str(screenshots / "automatic-companion.png")}
                finally:
                    print("Stopping the sandbox helper and closing the browser.", flush=True)
                    await asyncio.to_thread(stop_companion, install)
                    await asyncio.wait_for(context.close(), timeout=15)
    finally:
        try:
            stop_companion(install)
        except (OSError, ValueError):
            pass
        files.shutdown()
        files.server_close()
    result["cleanup"] = "passed; sandbox helper and browser stopped"
    (screenshots / "desktop-validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())

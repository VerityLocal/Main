"""Real MV3 UI/byte extraction/helper smoke, with explicit test-only tab/retrieval fixtures."""
import asyncio
import functools
import json
import shutil
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.async_api import async_playwright

from product.tests.browser.make_pdfs import BASE, SOURCE_TEXT, main as make_fixtures
from product.tests.browser.run import FixtureSources
from product.engine.detection import DetectionEngine
from product.engine.server import make_server


class QuietFiles(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def wait_enabled(panel, selector, errors):
    try:
        await panel.locator(f"{selector}:not([disabled])").wait_for(timeout=20_000)
    except Exception as error:
        status = await panel.locator("#status").inner_text()
        controls = await panel.evaluate("({reader: document.querySelector('#reader').innerText, extractDisabled: document.querySelector('#extract').disabled, sources: [...document.querySelector('#source').options].map(o => o.value + ': ' + o.text)})")
        raise AssertionError(f"{selector} did not become ready: {status}; controls: {controls}; page errors: {errors}") from error


async def main():
    root = Path(__file__).parents[3]
    make_fixtures()
    screenshots = BASE / "screenshots"
    screenshots.mkdir(exist_ok=True)
    files = ThreadingHTTPServer(("127.0.0.1", 8765), functools.partial(QuietFiles, directory=str(BASE)))
    threading.Thread(target=files.serve_forever, daemon=True).start()
    helper = None
    try:
        with tempfile.TemporaryDirectory(prefix="verity-mv3-", dir=root / "product") as temporary:
            extension = Path(temporary) / "extension"
            shutil.copytree(root / "product/dist/chrome", extension)
            manifest = json.loads((extension / "manifest.json").read_text())
            # Test-only loopback-origin grant matches capture's origin-level request.
            # Permission prompts/browser chrome remain a separate manual acceptance gate.
            manifest["host_permissions"].append("http://127.0.0.1/*")
            (extension / "manifest.json").write_text(json.dumps(manifest))
            async with async_playwright() as runtime:
                context = await runtime.chromium.launch_persistent_context(str(Path(temporary) / "profile"), channel="chromium", headless=True, args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"], viewport={"width": 440, "height": 1000})
                try:
                    worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
                    extension_id = worker.url.split("/")[2]
                    token = "test-" + "t" * 40
                    helper = make_server({"token": token, "origins": ["chrome-extension://" + extension_id]}, engine=DetectionEngine(source_factory=FixtureSources))
                    threading.Thread(target=helper.serve_forever, daemon=True).start()
                    source = await context.new_page()
                    await source.goto("http://127.0.0.1:8765/embedded.html")
                    panel = await context.new_page()
                    # The ordinary test tab emulates side-panel active-tab semantics only.
                    # Tabs/scripting/storage and the MV3 runtime remain actual browser APIs.
                    await panel.add_init_script("""(() => {
                      const query = chrome.tabs.query.bind(chrome.tabs);
                      chrome.tabs.query = async opts => {
                        const values = await query({});
                        return values.filter(tab => tab.url?.startsWith('http://127.0.0.1:8765/')).slice(0, 1);
                      };
                      const activated = chrome.tabs.onActivated.addListener.bind(chrome.tabs.onActivated);
                      chrome.tabs.onActivated.addListener = callback => activated(async info => {
                        const tab = await chrome.tabs.get(info.tabId);
                        if (!tab.url?.startsWith('chrome-extension://')) callback(info);
                      });
                    })();""")
                    errors = []
                    panel.on("pageerror", lambda error: errors.append(str(error)))
                    await panel.goto(f"chrome-extension://{extension_id}/panel.html")
                    await panel.locator("#connection-status").filter(has_text="Install the Verity desktop companion once").wait_for()
                    await panel.locator("#advanced summary").click()
                    await panel.locator("#token").fill(token)
                    await panel.locator("#save").click()
                    await panel.locator("#status").filter(has_text="Local helper connected").wait_for()
                    await panel.locator("#extract").click()
                    await wait_enabled(panel, "#scan", errors)
                    reader = await panel.locator("#reader").inner_text()
                    assert SOURCE_TEXT in reader, reader
                    assert "Surrounding page must not be scanned" not in reader
                    assert await panel.locator("#source option").count() == 2
                    await panel.locator("#consent").check()
                    await panel.locator("#scan").click()
                    await wait_enabled(panel, "#export", errors)
                    assert await panel.locator(".segment.copied").count() == 2
                    assert await panel.locator("#ai-score").inner_text() == "Unavailable"
                    await panel.locator(".segment.copied").first.click()
                    assert "https://example.org/rain-garden-demo" in await panel.locator("#detail").inner_text()
                    async with panel.expect_download() as download:
                        await panel.locator("#export").click()
                    report = await download.value
                    await report.save_as(screenshots / "fixture-report.json")
                    await panel.screenshot(path=str(screenshots / "source-review.png"), full_page=True)
                    await panel.locator("#consent").uncheck()
                    assert await panel.locator(".segment").count() == 0
                    assert await panel.locator("#export").is_disabled()
                    await panel.locator("#scan").click()
                    await wait_enabled(panel, "#export", errors)
                    assert await panel.locator("#copy-score").inner_text() == "Not checked"
                    assert await panel.locator("#ai-score").inner_text() == "Unavailable"
                    assert await panel.locator(".segment.copied").count() == 0
                    await panel.locator("#source").select_option("1")
                    await panel.locator("#extract").click()
                    await wait_enabled(panel, "#scan", errors)
                    assert "Sustainable urban planning" in await panel.locator("#reader").inner_text()
                    assert SOURCE_TEXT not in await panel.locator("#reader").inner_text()
                    await source.goto("http://127.0.0.1:8765/reference.html")
                    await panel.locator("#status").filter(has_text="original tab navigated").wait_for(timeout=10_000)
                    assert await panel.locator("#scan").is_disabled()
                    assert await panel.locator("#export").is_disabled()
                    await source.goto("http://127.0.0.1:8765/website.html")
                    await panel.locator("#extract").click()
                    await wait_enabled(panel, "#scan", errors)
                    website = await panel.locator("#reader").inner_text()
                    assert "A fox 🦊" in website and "<script>not executable</script>" in website
                    assert "Excluded" not in website
                    await panel.locator("#scan").click()
                    await wait_enabled(panel, "#export", errors)
                    await panel.locator("#format").select_option("txt")
                    async with panel.expect_download() as download:
                        await panel.locator("#export").click()
                    report = await download.value
                    await report.save_as(screenshots / "website-report.txt")
                    await panel.locator("#clear").click()
                    assert await panel.locator(".segment").count() == 0
                    assert await panel.locator("#scan").is_disabled()
                    await source.goto("http://127.0.0.1:8765/pdfs/no-text.pdf")
                    await panel.locator("#extract").click()
                    await panel.locator("#status").filter(has_text="text layer").wait_for(timeout=20_000)
                    assert await panel.locator("#scan").is_disabled()
                    assert not errors, errors
                    outcome = {"mv3_ui": "passed", "pdf_extraction": "real primary parser", "active_tab": "test-only side-panel-semantics shim", "permissions": "test-only loopback-origin pregrant; toolbar prompts not automated", "plagiarism_retrieval": "controlled reference fixture", "ai": "unavailable; no mock predictions", "second_embedded_pdf": "passed", "offline_no_web": "passed", "consent_invalidation": "passed; old highlights removed", "website_unicode_editor_exclusion": "passed", "export": "JSON and text passed", "clear": "passed", "image_only_pdf": "safe failure passed", "navigation_invalidation": "passed", "screenshot": str(screenshots / "source-review.png")}
                    (screenshots / "browser-validation.json").write_text(json.dumps(outcome, indent=2) + "\n")
                    print(json.dumps(outcome, indent=2))
                finally:
                    await context.close()
    finally:
        files.shutdown()
        files.server_close()
        if helper:
            helper.shutdown()
            helper.server_close()
            helper.jobs.executor.shutdown(wait=True)


if __name__ == "__main__":
    asyncio.run(main())

"""Automatically owned analysis process; no sockets, server, or pairing token."""
import os


def serve(root, connection):
    if os.name == "posix":
        os.setsid()  # Cancel also stops any consented retrieval-browser descendants.
    from .config import offline_policy, standard_config
    offline_policy(root)
    from product.engine.detection import DetectionEngine
    from product.engine.assets import verify_assets
    from product.engine.pdf import MAX_PDF_BYTES, extract_pdf
    engine = None
    try:
        while True:
            request = connection.recv()
            operation = request["operation"]
            try:
                if request.get("network_guard"):
                    import socket
                    def denied(*args, **kwargs):
                        raise OSError("Acceptance forbids outbound Python network access")
                    socket.socket.connect = denied
                    socket.create_connection = denied
                if operation == "pdf":
                    # Bound reads before allocating or calling native PDF code.
                    with open(request["path"], "rb") as stream:
                        data = stream.read(MAX_PDF_BYTES + 1)
                    result = extract_pdf(data)
                elif operation == "verify":
                    config = standard_config(root)
                    result = {}
                    for name, value in (("text", config["signals"]["text"]), ("semantic", config["semantic"])):
                        connection.send({"type": "progress", "value": {"stage": "verify", "model": name}})
                        try:
                            verify_assets(value, ("path",))
                            result[name] = "integrity_verified"
                        except (OSError, ValueError):
                            result[name] = "integrity_failed"
                elif operation == "scan":
                    if engine is None:
                        engine = DetectionEngine(standard_config(root))
                    if request.get("diagnostics"):
                        import traceback
                        engine.ai.failure_observer = lambda name, error: connection.send({"type": "diagnostic", "message": "".join(traceback.format_exception(error))})
                    else:
                        engine.ai.failure_observer = None
                    result = engine.run(request["text"], consent=request["consent"], progress=lambda value: connection.send({"type": "progress", "value": value}))
                    result["model_states"] = dict(engine.ai.states)
                    result["model_states"]["semantic"] = "feature_computed" if engine.semantic.model is not None else "bundled_not_loaded"
                elif operation == "semantic_test":
                    # Explicit developer acceptance check, not a fabricated user result.
                    if engine is None:
                        engine = DetectionEngine(standard_config(root))
                    score = engine.semantic.score(request["left"], request["right"])
                    result = {"computed": score is not None, "bounded": score is not None and 0 <= score <= 1}
                elif operation == "browser_test":
                    import asyncio
                    from playwright.async_api import async_playwright
                    async def browser_test():
                        async with async_playwright() as runtime:
                            browser = await runtime.chromium.launch(headless=True)
                            try:
                                context = await browser.new_context(java_script_enabled=False, service_workers="block")
                                await context.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body="<html><body>Verity packaged browser fixture</body></html>"))
                                page = await context.new_page()
                                await page.goto("https://example.invalid/verity-acceptance")
                                return {"rendered": "packaged browser fixture" in await page.locator("body").inner_text()}
                            finally:
                                await browser.close()
                    result = asyncio.run(browser_test())
                else:
                    raise ValueError("Unsupported operation")
                connection.send({"type": "completed", "operation": operation, "result": result})
            except Exception as error:
                # Do not expose upstream traces, user paths, or configuration.
                message = "Unable to complete this operation. Check the Models tab and input limits."
                if operation == "pdf":
                    message = "PDF extraction failed. Use a text-layer PDF under 16 MiB and 200 pages, or paste its text."
                if isinstance(error, ValueError) and str(error).startswith(("Readable text", "This document exceeds", "Invalid text encoding")):
                    message = str(error)
                connection.send({"type": "error", "operation": operation, "message": message})
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()

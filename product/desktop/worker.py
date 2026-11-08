"""Automatically owned analysis process; no sockets, server, or pairing token."""
import os


def acceptance_network_guard():
    """Deny outbound test traffic, retaining Windows asyncio's local socket pair."""
    import ipaddress
    import socket
    original_connect = socket.socket.connect

    def guarded_connect(client, address):
        if client.family in (socket.AF_INET, socket.AF_INET6):
            try:
                if ipaddress.ip_address(address[0]).is_loopback:
                    return original_connect(client, address)
            except ValueError:
                pass
        raise OSError("Acceptance forbids outbound Python network access")

    def denied(*args, **kwargs):
        raise OSError("Acceptance forbids outbound Python network access")

    socket.socket.connect = guarded_connect
    socket.create_connection = denied


def serve(root, connection):
    if os.name == "posix":
        os.setsid()  # Cancel also stops any consented retrieval-browser descendants.
    from .config import offline_policy, standard_config
    offline_policy(root)
    from product.engine.detection import DetectionEngine
    from product.engine.assets import verify_assets
    from product.engine.pdf import MAX_PDF_BYTES, extract_pdf
    engine = None
    network_guard_installed = False
    try:
        while True:
            request = connection.recv()
            operation = request["operation"]
            try:
                if request.get("network_guard") and not network_guard_installed:
                    acceptance_network_guard()
                    network_guard_installed = True
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
                response = {"type": "error", "operation": operation, "message": message}
                if request.get("diagnostics"):
                    response["exception_type"] = type(error).__name__
                connection.send(response)
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()

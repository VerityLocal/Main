import asyncio
import http.client
import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from internal.demo.make_pdfs import AI_TEXT, ORIGINAL_TEXT, SOURCE_TEXT, pdf
from internal.retraining.controlled_pairs import records
from internal.retraining.train import read_data, train
from product.engine.ai import AIClassifier
from product.engine.assets import file_digest, fingerprint, inventory, verify_assets
from product.engine.calibration import Calibration
from product.engine.detection import Cancelled, DetectionEngine
from product.engine.pdf import extract_pdf
from product.engine.server import Jobs, make_server
from product.engine.similarity import Semantic, compare, lexical
from product.engine.text import Utf16Index, aggregate, segment
from product.engine.web import WebSources, public_target, source_url


class FixtureSources:
    calls = 0
    complete = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def search(self, query):
        type(self).calls += 1
        return [{"url": "https://example.org/reference", "title": "Reference", "text": SOURCE_TEXT}], self.complete


class FixtureAI:
    # Deterministic protocol fixture, never a production model or distributed artifact.
    def score(self, row):
        return {"score": .8, "confidence": .8, "status": "scored"}


class EngineTests(unittest.TestCase):
    def test_original_unicode_ranges(self):
        text = "Heading\n\nA fox 🦊 crossed the path. Another sentence!\n\n" + "longword " * 500
        rows = segment(text)
        index = Utf16Index(text)
        self.assertGreater(len(rows), 4)
        for row in rows:
            self.assertEqual(row["text"], index.slice(row["start"], row["end"]))
            self.assertLessEqual(len(row["text"]), 1600)
        with self.assertRaises(ValueError):
            Utf16Index("🦊").slice(1, 2)

    def test_pdf_primary_parser_and_headings(self):
        data = extract_pdf(pdf("Garden heading", [SOURCE_TEXT, ORIGINAL_TEXT]))
        self.assertEqual(data["blocks"][0]["text"], "Garden heading")
        self.assertIn(SOURCE_TEXT, data["text"])
        self.assertIn(ORIGINAL_TEXT, data["text"])
        self.assertEqual(data["empty_pages"], [])

    def test_pdf_failures(self):
        for data in [b"not PDF", pdf("", [], blank=True), b"%PDF-" + b"a" * (16 * 1024 * 1024)]:
            with self.assertRaises((ValueError, RuntimeError)):
                extract_pdf(data)

    def test_source_similarity_and_self_exclusion(self):
        sources = [{"url": "https://example.org/reference", "text": SOURCE_TEXT}]
        found = compare(SOURCE_TEXT, sources, Semantic({}), Calibration())
        self.assertEqual(found["similarity"], 1)
        self.assertIsNone(found["confidence"])
        self.assertIsNone(compare(SOURCE_TEXT, sources, Semantic({}), Calibration(), sources[0]["url"]))
        self.assertLess(lexical(ORIGINAL_TEXT, SOURCE_TEXT), .35)

    def test_offline_no_web_calls_and_no_fabricated_ai(self):
        FixtureSources.calls = 0
        result = DetectionEngine(source_factory=FixtureSources).run(SOURCE_TEXT, consent=False)
        self.assertEqual(FixtureSources.calls, 0)
        self.assertIsNone(result["overall"]["ai"]["percent"])
        self.assertEqual(result["overall"]["plagiarism"]["status"], "not_checked")

    def test_word_weighted_coverage_and_independent_engines(self):
        FixtureSources.complete = True
        result = DetectionEngine({"max_queries": 1}, classifier=FixtureAI(), source_factory=FixtureSources).run(SOURCE_TEXT + "\n\n" + ORIGINAL_TEXT, consent=True)
        self.assertAlmostEqual(result["overall"]["ai"]["percent"], 80)
        self.assertLess(result["overall"]["plagiarism"]["coverage"], 1)
        self.assertEqual(result["overall"]["plagiarism"]["status"], "partial")
        self.assertTrue(any(row["plagiarism"]["score"] is None for row in result["segments"]))

    def test_web_failure_is_not_zero(self):
        class Failed(FixtureSources):
            async def search(self, query):
                return [], False
        result = DetectionEngine(classifier=FixtureAI(), source_factory=Failed).run(AI_TEXT, consent=True)
        self.assertIsNone(result["overall"]["plagiarism"]["percent"])
        self.assertAlmostEqual(result["overall"]["ai"]["percent"], 80)

    def test_cancellation(self):
        with self.assertRaises(Cancelled):
            DetectionEngine(source_factory=FixtureSources).run(SOURCE_TEXT, consent=True, cancelled=lambda: True)

    def test_code_signals_do_not_score_prose(self):
        detector = AIClassifier({}, Calibration())
        class Code:
            domain = "code"
            def score(self, text):
                raise AssertionError("Code signal received prose")
        detector.signals = [("code", Code(), 1, "test")]
        self.assertEqual(detector.score({"text": SOURCE_TEXT, "kind": "text", "words": 30})["status"], "unavailable")

    def test_partial_aggregate(self):
        rows = [{"words": 10, "ai": {"score": .8}}, {"words": 30, "ai": {"score": .2}}, {"words": 10, "ai": {"score": None}}]
        result = aggregate(rows, "ai")
        self.assertAlmostEqual(result["percent"], 35)
        self.assertAlmostEqual(result["coverage"], .8)

    def test_terminal_results_expire_without_another_scan(self):
        jobs = Jobs(DetectionEngine())
        try:
            jobs.rows = {"old": {"state": "completed", "created": 0, "result": {"text": "private text"}}}
            self.assertIsNone(jobs.get("old"))
            self.assertEqual(jobs.rows, {})
        finally:
            jobs.executor.shutdown(wait=True)

    def test_public_destination_policy(self):
        def resolver(address):
            return lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
        for address in ["127.0.0.1", "169.254.169.254", "10.0.0.1", "::1", "192.168.1.2"]:
            with self.assertRaises(ValueError):
                public_target("https://example.org/", resolver(address))
        self.assertEqual(public_target("https://example.org/", resolver("8.8.8.8"))[1], "8.8.8.8")
        for url in ["file:///private/file", "https://user:secret@example.org", "http://example.org:8787"]:
            with self.assertRaises(ValueError):
                public_target(url, resolver("8.8.8.8"))
        self.assertEqual(source_url("https://example.org/page"), "https://example.org/page")

    def test_real_small_head_fitting_and_release_gate(self):
        data = records()
        artifact = train(data, steps=300)
        head = artifact["heads"]["plagiarism"]
        self.assertGreater(head["test"]["accuracy_at_0_5"], .9)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "head.json"
            path.write_text(json.dumps(artifact))
            features = {"lexical": 1.0, "semantic": 0.0, "ensemble": 1.0}
            self.assertIsNone(Calibration(path).predict("plagiarism", features, "lexical-v1"))
            self.assertGreater(Calibration(path, allow_development=True).predict("plagiarism", features, "lexical-v1"), .5)
            self.assertIsNone(Calibration(path, allow_development=True).predict("plagiarism", features, "changed-signals"))
            # Ensure leakage validation rejects cross-split topic identities.
            data[0]["group"] = data[-1]["group"]
            path.write_text("".join(json.dumps(row) + "\n" for row in data))
            with self.assertRaises(ValueError):
                read_data(path)


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_block_frames_subresources_and_unexpected_navigation(self):
        web = WebSources()
        page = object()
        web.allowed[page] = "https://example.org/source"
        for kind, parent, address in [("image", None, "https://example.org/source"), ("document", object(), "https://example.org/source"), ("document", None, "https://example.org/unexpected")]:
            route = SimpleNamespace(request=SimpleNamespace(resource_type=kind, method="GET", url=address, frame=SimpleNamespace(parent_frame=parent, page=page)), abort=AsyncMock(), fulfill=AsyncMock())
            with patch("product.engine.web.fetch_public") as fetch:
                await web._route(route)
                fetch.assert_not_called()
            route.abort.assert_awaited_once()
            route.fulfill.assert_not_awaited()

    async def test_allowed_document_uses_pinned_fetch(self):
        web = WebSources()
        page = object()
        address = "https://example.org/source"
        web.allowed[page] = address
        route = SimpleNamespace(request=SimpleNamespace(resource_type="document", method="GET", url=address, frame=SimpleNamespace(parent_frame=None, page=page)), abort=AsyncMock(), fulfill=AsyncMock())
        with patch("product.engine.web.fetch_public", return_value=(b"<p>controlled route fixture</p>", "text/html", address)) as fetch:
            await web._route(route)
            fetch.assert_called_once_with(address)
        route.fulfill.assert_awaited_once()
        route.abort.assert_not_awaited()

    async def test_undecodable_search_links_are_not_a_completed_zero(self):
        web = WebSources()
        locator = SimpleNamespace(evaluate_all=AsyncMock(return_value=["https://www.bing.com/ck/a?u=broken"]))
        page = SimpleNamespace(goto=AsyncMock(), locator=lambda _: locator, close=AsyncMock())
        # A hashable fake page matches the browser object's map semantics.
        class Page:
            goto = page.goto
            close = page.close
            def locator(self, _):
                return locator
        web.context = SimpleNamespace(new_page=AsyncMock(return_value=Page()))
        self.assertEqual(await web.search("controlled query"), ([], False))
        self.assertEqual(web.allowed, {})

    async def test_cleanup_errors_do_not_hide_unavailable_results(self):
        web = WebSources()
        web.browser = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("controlled close failure")))
        web.runtime = SimpleNamespace(stop=AsyncMock())
        await web.__aexit__(None, None, None)
        web.runtime.stop.assert_awaited_once()


class AssetTests(unittest.TestCase):
    def test_snapshot_integrity_and_manifest_binding(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot = root / "model"
            snapshot.mkdir()
            weights = snapshot / "weights.safetensors"
            weights.write_bytes(b"test-only bytes, never model predictions")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "assets": {"path": inventory(snapshot)}}))
            config = {"path": str(snapshot), "asset_manifest": str(manifest), "asset_manifest_sha256": file_digest(manifest)}
            verify_assets(config, ("path",))
            self.assertNotEqual(fingerprint(config), fingerprint({**config, "asset_manifest_sha256": "different"}))
            weights.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify_assets(config, ("path",))
            manifest.write_text("{}")
            with self.assertRaises(ValueError):
                verify_assets(config, ("path",))

    def test_missing_manifest_never_enables_a_signal(self):
        detector = AIClassifier({"text": {"enabled": True, "license_reviewed": True, "snapshot_id": "unverified", "path": "unused"}}, Calibration())
        self.assertEqual(detector.signals, [])

    def test_symlinks_and_unlisted_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            snapshot = root / "model"
            snapshot.mkdir()
            (snapshot / "config.json").write_text("{}")
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"schema_version": 1, "assets": {"path": inventory(snapshot)}}))
            config = {"path": str(snapshot), "asset_manifest": str(manifest), "asset_manifest_sha256": file_digest(manifest)}
            (snapshot / "extra.json").write_text("{}")
            with self.assertRaises(ValueError):
                verify_assets(config, ("path",))
            (snapshot / "link").symlink_to(manifest)
            with self.assertRaises(ValueError):
                inventory(snapshot)


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.token = "t" * 43
        cls.origin = "chrome-extension://" + "a" * 32
        cls.server = make_server({"token": cls.token, "origins": [cls.origin]}, engine=DetectionEngine(source_factory=FixtureSources))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server.jobs.executor.shutdown(wait=True)

    def request(self, method, path, data=None, token=None, origin=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", 8790, timeout=10)
        value = {"Authorization": "Bearer " + (token if token is not None else self.token)}
        if data is not None:
            value["Content-Type"] = "application/json"
        if origin:
            value["Origin"] = origin
        value.update(headers or {})
        connection.request(method, path, body=json.dumps(data) if data is not None else None, headers=value)
        response = connection.getresponse()
        output = response.read()
        connection.close()
        return response.status, output, response.headers

    def test_auth_origin_host_and_preflight(self):
        self.assertEqual(self.request("GET", "/health", token="bad")[0], 401)
        self.assertEqual(self.request("GET", "/health", origin="https://evil.invalid")[0], 403)
        self.assertEqual(self.request("GET", "/health", headers={"Host": "evil.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/health", origin=self.origin)[0], 200)
        self.assertEqual(self.request("OPTIONS", "/jobs", origin=self.origin, headers={"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})[0], 204)
        self.assertEqual(self.request("OPTIONS", "/jobs", origin=self.origin, headers={"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-untrusted"})[0], 403)

    def test_text_validation(self):
        self.assertEqual(self.request("POST", "/jobs", {"text": SOURCE_TEXT, "consent": "yes"})[0], 422)
        self.assertEqual(self.request("POST", "/jobs", {"text": ""})[0], 422)
        code, body, _ = self.request("POST", "/jobs", {"text": SOURCE_TEXT})
        self.assertEqual(code, 202)
        identifier = json.loads(body)["id"]
        self.assertEqual(self.request("POST", f"/jobs/{identifier}/cancel", {})[0], 200)

    def test_no_upstream_error_leak(self):
        import base64
        code, body, _ = self.request("POST", "/extract", {"data": base64.b64encode(b"bad").decode()})
        self.assertEqual(code, 422)
        self.assertNotIn(b"docling", body.lower())

    def test_pdf_bytes_through_authenticated_endpoint(self):
        import base64
        code, body, _ = self.request("POST", "/extract", {"data": base64.b64encode(pdf("Heading", [SOURCE_TEXT])).decode()}, origin=self.origin)
        self.assertEqual(code, 200)
        self.assertIn(SOURCE_TEXT, json.loads(body)["text"])

    def test_native_pairing_requires_auth_and_no_web_origin(self):
        origin = "moz-extension://" + "d" * 36
        self.assertEqual(self.request("POST", "/pair", {"origin": origin}, token="bad")[0], 401)
        self.assertEqual(self.request("POST", "/pair", {"origin": origin}, origin=self.origin)[0], 403)
        self.assertEqual(self.request("POST", "/pair", {"origin": "https://evil.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/pair", {"origin": origin})[0], 200)
        self.assertEqual(self.request("GET", "/health", origin=origin)[0], 200)


if __name__ == "__main__":
    unittest.main()

"""Small authenticated loopback helper, bounded in-memory jobs, no legacy dependencies."""
import argparse
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Set before lazy upstream imports. Only source comparison can make web requests.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
logging.disable(logging.CRITICAL)

from .detection import Cancelled, DetectionEngine
from .pdf import MAX_PDF_BYTES, extract_pdf
from .resources import model_setup_states

DEFAULT_CONFIG = Path(__file__).parents[1] / ".local/helper.json"
ORIGIN = re.compile(r"(?:chrome-extension://[a-p]{32}|moz-extension://[a-zA-Z0-9-]{20,80})$")
MAX_BODY = 23 * 1024 * 1024


class BoundedServer(ThreadingHTTPServer):
    def __init__(self, *args):
        self.connections = threading.BoundedSemaphore(12)
        super().__init__(*args)

    def process_request(self, request, address):
        if not self.connections.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.connections.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.connections.release()

    def service_actions(self):
        self.jobs.expire()
        with self.activity_lock:
            if self.idle_seconds and time.monotonic() - self.last_activity > self.idle_seconds and not self.stopping:
                with self.jobs.lock:
                    busy = self.active_operations or any(row["state"] in {"queued", "running"} for row in self.jobs.rows.values())
                if not busy:
                    self.stopping = True
                    threading.Thread(target=self.shutdown, daemon=True).start()


class Jobs:
    def __init__(self, engine):
        self.engine, self.lock = engine, threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.rows = {}

    def expire(self):
        with self.lock:
            self.rows = {k: v for k, v in self.rows.items() if not (v["state"] in {"completed", "cancelled", "error"} and time.monotonic() - v["created"] > 1800)}

    def submit(self, text, consent, url):
        self.expire()
        with self.lock:
            if len(self.rows) >= 8:
                # Evict the oldest terminal result, never an active job.
                terminal = [k for k, v in self.rows.items() if v["state"] in {"completed", "cancelled", "error"}]
                if not terminal:
                    raise ValueError("The local scan queue is full")
                del self.rows[terminal[0]]
            identifier = secrets.token_hex(16)
            self.rows[identifier] = {"state": "queued", "cancel": threading.Event(), "created": time.monotonic(), "progress": {}}

        def work():
            with self.lock:
                job = self.rows[identifier]
                job["state"] = "running"
            def progress(value):
                with self.lock:
                    job["progress"] = value
            try:
                result = self.engine.run(text, consent=consent, source_url=url, cancelled=job["cancel"].is_set, progress=progress)
                with self.lock:
                    if job["cancel"].is_set():
                        job["state"] = "cancelled"
                    else:
                        job.update(state="completed", result=result)
            except Cancelled:
                with self.lock:
                    job["state"] = "cancelled"
            except Exception:
                with self.lock:
                    job.update(state="error", message="The local scan could not be completed")
        self.executor.submit(work)
        return identifier

    def get(self, identifier):
        self.expire()
        with self.lock:
            job = self.rows.get(identifier)
            if job is None:
                return None
            return {k: v for k, v in job.items() if k not in {"cancel", "created"}}

    def cancel(self, identifier):
        with self.lock:
            job = self.rows.get(identifier)
            if job:
                job["cancel"].set()
                job.pop("result", None)
                if job["state"] == "completed":
                    job["state"] = "cancelled"


def make_server(config, port=8790, engine=None):
    if port != 8790 or not config.get("token") or len(config["token"]) < 32:
        raise ValueError("Invalid helper configuration")
    origins = config.get("origins", [])
    if any(not ORIGIN.fullmatch(value) for value in origins):
        raise ValueError("Invalid extension origin")
    jobs = Jobs(engine or DetectionEngine(config))
    slots = threading.BoundedSemaphore(4)
    parser_slot = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def reply(self, code, value):
            body = json.dumps(value, ensure_ascii=True, allow_nan=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            if self.headers.get("Origin") in origins:
                self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)
            self.close_connection = True

        def error(self, code, message):
            self.reply(code, {"error": message})

        def boundary(self, preflight=False):
            for header in ["Host", "Origin", "Authorization", "Content-Length", "Content-Type"]:
                if len(self.headers.get_all(header, [])) > 1:
                    self.error(400, "Duplicate request headers")
                    return False
            if self.headers.get("Host") != f"127.0.0.1:{port}":
                self.error(403, "The helper only accepts its local address")
                return False
            if self.headers.get("Origin") and self.headers["Origin"] not in origins:
                self.error(403, "Pair this extension with the local helper")
                return False
            if preflight:
                if self.headers.get("Origin") not in origins:
                    self.error(403, "Pair this extension with the local helper")
                    return False
                return True
            supplied = self.headers.get("Authorization", "").encode()
            if not hmac.compare_digest(supplied, ("Bearer " + config["token"]).encode()):
                self.error(401, "Enter a valid local pairing token")
                return False
            self.server.last_activity = time.monotonic()
            return True

        def do_OPTIONS(self):
            if not self.boundary(True):
                return
            requested = {h.strip().lower() for h in self.headers.get("Access-Control-Request-Headers", "").split(",") if h.strip()}
            if self.headers.get("Access-Control-Request-Method") not in {"GET", "POST"} or not requested <= {"authorization", "content-type"}:
                self.error(403, "Unsupported request")
                return
            self.send_response(204)
            for name, value in {"Access-Control-Allow-Origin": self.headers["Origin"], "Access-Control-Allow-Methods": "GET, POST", "Access-Control-Allow-Headers": "Authorization, Content-Type", "Content-Length": "0", "Connection": "close"}.items():
                self.send_header(name, value)
            self.end_headers()
            self.close_connection = True

        def do_GET(self):
            if not self.boundary():
                return
            if self.path == "/health":
                states = model_setup_states(config)
                self.reply(200, {"ready": True, "offline_ai": True, "version": "0.2.0", "installation_id": config.get("installation_id"), "model_setup": states, "calibration": "required"})
            elif re.fullmatch(r"/jobs/[a-f0-9]{32}", self.path):
                result = jobs.get(self.path.rsplit("/", 1)[1])
                self.reply(200, result) if result else self.error(404, "This scan is no longer available")
            else:
                self.error(404, "Unsupported operation")

        def do_POST(self):
            if not self.boundary():
                return
            if not slots.acquire(blocking=False):
                self.error(429, "The local helper is busy")
                return
            with self.server.activity_lock:
                self.server.active_operations += 1
            try:
                if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.error(415, "Unsupported request format")
                    return
                size = self.headers.get("Content-Length", "")
                if not size.isascii() or not size.isdecimal() or len(size) > 9 or not 0 < int(size) <= MAX_BODY:
                    self.error(413, "The document exceeds the request limit")
                    return
                raw = self.rfile.read(int(size))
                if len(raw) != int(size):
                    self.error(400, "Incomplete request")
                    return
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise ValueError()
                if self.path == "/shutdown":
                    if self.headers.get("Origin"):
                        self.error(403, "Unsupported lifecycle request")
                        return
                    self.reply(200, {"stopping": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                elif self.path == "/pair":
                    origin = value.get("origin")
                    if self.headers.get("Origin") or not isinstance(origin, str) or not ORIGIN.fullmatch(origin):
                        self.error(403, "Unsupported pairing request")
                        return
                    if origin not in origins:
                        origins.append(origin)
                    self.reply(200, {"paired": True})
                elif self.path == "/extract":
                    if not parser_slot.acquire(blocking=False):
                        self.error(429, "A PDF is already being extracted")
                        return
                    try:
                        data = base64.b64decode(value["data"], validate=True)
                        if len(data) > MAX_PDF_BYTES:
                            raise ValueError()
                        self.reply(200, extract_pdf(data))
                    finally:
                        parser_slot.release()
                elif self.path == "/jobs":
                    text, consent = value["text"], value.get("consent", False)
                    if not isinstance(text, str) or not text.strip() or len(text) > 200_000 or type(consent) is not bool:
                        raise ValueError()
                    url = value.get("source_url")
                    if url is not None and (not isinstance(url, str) or len(url) > 8192):
                        raise ValueError()
                    self.reply(202, {"id": jobs.submit(text, consent, url), "text_digest": hashlib.sha256(text.encode()).hexdigest()})
                elif re.fullmatch(r"/jobs/[a-f0-9]{32}/cancel", self.path):
                    jobs.cancel(self.path.split("/")[2])
                    self.reply(200, {"cancelled": True})
                else:
                    self.error(404, "Unsupported operation")
            except (ValueError, KeyError, TypeError):
                self.error(422, "The document could not be read. Check the text layer and size limits")
            except Exception:
                self.error(503, "The local operation is unavailable. Review your helper setup")
            finally:
                with self.server.activity_lock:
                    self.server.active_operations -= 1
                    self.server.last_activity = time.monotonic()
                slots.release()

    server = BoundedServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.jobs = jobs
    server.activity_lock = threading.Lock()
    server.active_operations = 0
    server.last_activity = time.monotonic()
    server.idle_seconds = max(0, min(86400, int(config.get("idle_seconds", 0))))
    server.stopping = False
    return server


def main():
    parser = argparse.ArgumentParser(description="Verity local helper")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--allow-origin")
    args = parser.parse_args()
    if args.init:
        args.config.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(args.config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump({"token": secrets.token_urlsafe(32), "origins": [], "signals": {}, "max_queries": 24}, stream, indent=2)
        except FileExistsError:
            raise SystemExit("Pairing configuration already exists; it was not overwritten") from None
        print(f"Pairing configuration created at {args.config}. Keep the token private.")
        return
    try:
        config = json.loads(args.config.read_text())
        if args.allow_origin:
            if not ORIGIN.fullmatch(args.allow_origin):
                raise ValueError()
            config["origins"] = list(dict.fromkeys(config.get("origins", []) + [args.allow_origin]))
            args.config.write_text(json.dumps(config, indent=2) + "\n")
            print("Extension origin paired. Restart the helper if already running.")
            return
        server = make_server(config)
    except (OSError, ValueError):
        raise SystemExit("Initialize and pair the local helper before starting it") from None
    print("Verity helper ready at http://127.0.0.1:8790. No cloud authorship calls.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for identifier in list(server.jobs.rows):
            server.jobs.cancel(identifier)
        server.server_close()
        server.jobs.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()

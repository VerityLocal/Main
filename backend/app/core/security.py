"""Pure ASGI security boundary with bounded body collection before JSON parsing."""

import asyncio
import hmac
import logging
import threading
import time
from collections.abc import Callable
from uuid import uuid4

from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.app.core.config import Settings

LOGGER = logging.getLogger("local_ai")
SAFE_METHODS = {"GET", "HEAD"}
ALLOWED_METHODS = {"GET", "HEAD", "POST", "OPTIONS"}
ALLOWED_HEADERS = {"content-type", "x-local-token", "x-csrf-token", "last-event-id"}


class TokenBucket:
    def __init__(
        self, per_minute: int, burst: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._rate = per_minute / 60
        self._burst = burst
        self._tokens = float(burst)
        self._clock = clock
        self._updated = clock()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            self._tokens = min(self._burst, self._tokens + (now - self._updated) * self._rate)
            self._updated = now
            if self._tokens < 1:
                return False
            self._tokens -= 1
            return True


def safe_error(status: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message}, "request_id": request_id},
    )


class LocalSecurityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.bucket = TokenBucket(settings.rate_limit_per_minute, settings.rate_limit_burst)
        self._active = 0

    def valid_host(self, host: str) -> bool:
        return host.lower() in {
            f"127.0.0.1:{self.settings.port}",
            f"localhost:{self.settings.port}",
            f"[::1]:{self.settings.port}",
        }

    @staticmethod
    def _matches(candidate: str, secret: str) -> bool:
        # Non-ASCII HTTP header values must not cause compare_digest to raise.
        return hmac.compare_digest(candidate.encode("utf-8"), secret.encode("ascii"))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        headers: dict[str, str] = {}
        duplicates = set()
        for key, value in scope.get("headers", []):
            name = key.decode("latin-1").lower()
            if name in headers:
                duplicates.add(name)
            headers[name] = value.decode("latin-1")
        origin = headers.get("origin")
        trusted_origin = origin is not None and origin in self.settings.allowed_origins
        response_started = False
        response_finished = False

        async def secure_send(message: Message) -> None:
            nonlocal response_started, response_finished
            if message["type"] == "http.response.start":
                response_started = True
                output_headers = list(message.get("headers", []))
                output_headers.extend(
                    [
                        (b"x-request-id", request_id.encode("ascii")),
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                    ]
                )
                if trusted_origin:
                    output_headers.extend(
                        [
                            (b"access-control-allow-origin", origin.encode("ascii")),
                            (b"vary", b"Origin"),
                            (b"access-control-expose-headers", b"X-Request-ID"),
                        ]
                    )
                message = {**message, "headers": output_headers}
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                response_finished = True
            await send(message)

        async def reject(status: int, code: str, message: str) -> None:
            await safe_error(status, code, message, request_id)(scope, receive, secure_send)

        sensitive_headers = {
            "host",
            "origin",
            "x-local-token",
            "x-csrf-token",
            "content-length",
            "content-type",
        }
        if duplicates & sensitive_headers:
            await reject(400, "invalid_headers", "Duplicate security headers are not permitted")
            return
        if not self.valid_host(headers.get("host", "")):
            await reject(400, "invalid_host", "Host is not an approved loopback endpoint")
            return
        if origin is not None and not trusted_origin:
            await reject(403, "invalid_origin", "Origin is not permitted")
            return
        if not self.bucket.allow():
            await reject(429, "rate_limited", "Local request rate limit reached")
            return
        method = scope["method"]
        if method not in ALLOWED_METHODS:
            await reject(405, "method_not_allowed", "Method is not permitted")
            return
        if method == "OPTIONS":
            requested_method = headers.get("access-control-request-method", "")
            requested_headers = {
                name.strip().lower()
                for name in headers.get("access-control-request-headers", "").split(",")
                if name.strip()
            }
            if (
                not trusted_origin
                or requested_method not in {"GET", "HEAD", "POST"}
                or not (requested_headers <= ALLOWED_HEADERS)
            ):
                await reject(403, "invalid_preflight", "Preflight request is not permitted")
                return
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Methods": "GET, HEAD, POST",
                    "Access-Control-Allow-Headers": ", ".join(sorted(ALLOWED_HEADERS)),
                    "Access-Control-Max-Age": "600",
                },
            )
            await response(scope, receive, secure_send)
            return
        if not self._matches(
            headers.get("x-local-token", ""), self.settings.auth_token.get_secret_value()
        ):
            await reject(401, "unauthorized", "A valid local authentication token is required")
            return
        if method not in SAFE_METHODS and not self._matches(
            headers.get("x-csrf-token", ""), self.settings.csrf_token.get_secret_value()
        ):
            await reject(403, "csrf_failed", "A valid CSRF token is required")
            return
        if self._active >= self.settings.max_concurrent_requests:
            await reject(503, "busy", "Local concurrent request limit reached")
            return
        if (
            method not in SAFE_METHODS
            and headers.get("content-type", "").split(";")[0].strip().lower() != "application/json"
        ):
            await reject(415, "json_required", "Mutation requests require application/json")
            return
        advertised = headers.get("content-length")
        if advertised is not None:
            if not advertised.isascii() or not advertised.isdecimal():
                await reject(400, "invalid_length", "Content-Length must be a nonnegative integer")
                return
            # Avoid huge integer conversion from attacker-controlled headers.
            if len(advertised) > 10 or int(advertised) > self.settings.max_request_bytes:
                await reject(413, "request_too_large", "Request body exceeds the configured limit")
                return
        self._active += 1
        try:
            chunks: list[bytes] = []
            size = 0

            async def collect_body() -> bool:
                nonlocal size
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        return False
                    chunk = message.get("body", b"")
                    size += len(chunk)
                    if size > self.settings.max_request_bytes:
                        return False
                    chunks.append(chunk)
                    if not message.get("more_body", False):
                        return True

            try:
                complete = await asyncio.wait_for(
                    collect_body(), timeout=self.settings.body_timeout_seconds
                )
            except TimeoutError:
                await reject(408, "body_timeout", "Request body read deadline exceeded")
                return
            if not complete:
                if size > self.settings.max_request_bytes:
                    await reject(
                        413, "request_too_large", "Request body exceeds the configured limit"
                    )
                return
            body = b"".join(chunks)
            delivered = False

            async def buffered_receive() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            try:
                await asyncio.wait_for(
                    self.app(scope, buffered_receive, secure_send),
                    timeout=self.settings.request_timeout_seconds,
                )
            except TimeoutError:
                if not response_started:
                    await reject(504, "request_timeout", "Request execution deadline exceeded")
                elif not response_finished:
                    await secure_send({"type": "http.response.body", "body": b""})
            except Exception:
                LOGGER.error("request_failed")
                if not response_started:
                    await reject(500, "internal_error", "The local request could not be completed")
                elif not response_finished:
                    await secure_send({"type": "http.response.body", "body": b""})
        finally:
            self._active -= 1

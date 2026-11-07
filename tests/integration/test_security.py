import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from backend.app.core.security import LocalSecurityMiddleware, TokenBucket
from backend.app.main import create_app


@pytest.mark.parametrize(
    "host",
    [
        "evil.example:8787",
        "localhost.evil.example:8787",
        "127.0.0.1:9000",
        "user@127.0.0.1:8787",
        "127.0.0.1:8787?",
        "127.0.0.1:8787#",
    ],
)
def test_host_rebinding_is_rejected(client, auth_headers, host):
    response = client.get("/api/v1/health", headers={**auth_headers, "Host": host})
    assert response.status_code == 400


@pytest.mark.parametrize(
    "origin", ["null", "https://evil.example", "chrome-extension://" + "b" * 32]
)
def test_unapproved_origins_are_rejected(client, auth_headers, origin):
    response = client.get("/api/v1/health", headers={**auth_headers, "Origin": origin})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers


def test_exact_origin_allowed_and_no_credentials(client, auth_headers, settings):
    origin = settings.allowed_origins[0]
    response = client.get("/api/v1/health", headers={**auth_headers, "Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin
    assert "access-control-allow-credentials" not in response.headers


def test_preflight_only_for_trusted_origin_and_headers(client, settings):
    headers = {
        "Origin": settings.allowed_origins[0],
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-local-token,x-csrf-token",
    }
    assert client.options("/api/v1/documents/register", headers=headers).status_code == 204
    assert (
        client.options(
            "/api/v1/documents/register",
            headers={**headers, "Access-Control-Request-Headers": "x-evil"},
        ).status_code
        == 403
    )
    assert (
        client.options(
            "/api/v1/documents/register", headers={**headers, "Origin": "https://evil.example"}
        ).status_code
        == 403
    )


def test_csrf_and_json_content_type(client, auth_headers, document):
    response = client.post(
        "/api/v1/documents/register",
        headers={"X-Local-Token": auth_headers["X-Local-Token"]},
        json=document.model_dump(mode="json"),
    )
    assert response.status_code == 403
    response = client.post(
        "/api/v1/documents/register", headers=auth_headers, content="private text"
    )
    assert response.status_code == 415


def test_advertised_size_is_rejected_before_parsing(client, auth_headers, settings):
    response = client.post(
        "/api/v1/documents/register",
        content="{}",
        headers={
            **auth_headers,
            "Content-Type": "application/json",
            "Content-Length": str(settings.max_request_bytes + 1),
        },
    )
    assert response.status_code == 413


def test_rate_limit_and_refill_without_timing_guesses():
    now = [0.0]
    bucket = TokenBucket(60, 2, clock=lambda: now[0])
    assert bucket.allow() and bucket.allow()
    assert not bucket.allow()
    now[0] = 1.0
    assert bucket.allow()
    assert not bucket.allow()


def test_api_rate_limit(settings_factory, hardware, auth_headers):
    app = create_app(settings_factory(rate_limit_burst=1), hardware_profiler=lambda _: hardware)
    with TestClient(app, base_url="http://127.0.0.1:8787") as instance:
        assert instance.get("/api/v1/health", headers=auth_headers).status_code == 200
        response = instance.get("/api/v1/health", headers=auth_headers)
        assert response.status_code == 429


async def success_app(scope, receive, send):
    await receive()
    await JSONResponse({"ok": True})(scope, receive, send)


def make_scope(auth_headers, *, method="POST", extra_headers=()):
    headers = [(b"host", b"127.0.0.1:8787"), (b"content-type", b"application/json")]
    headers.extend(
        (key.lower().encode("ascii"), value.encode("ascii")) for key, value in auth_headers.items()
    )
    headers.extend(extra_headers)
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": "/test",
        "raw_path": b"/test",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8787),
    }


async def invoke(middleware, scope, messages, *, body_delay=0):
    sent = []
    iterator = iter(messages)

    async def receive():
        if body_delay:
            await asyncio.sleep(body_delay)
        return next(iterator, {"type": "http.disconnect"})

    async def send(message):
        sent.append(message)

    await middleware(scope, receive, send)
    status = next(message["status"] for message in sent if message["type"] == "http.response.start")
    body = b"".join(
        message.get("body", b"") for message in sent if message["type"] == "http.response.body"
    )
    return status, json.loads(body) if body else None


def test_actual_chunked_body_limit(settings_factory, auth_headers):
    boundary = LocalSecurityMiddleware(success_app, settings_factory(max_request_bytes=1024))
    messages = [
        {"type": "http.request", "body": b"a" * 800, "more_body": True},
        {"type": "http.request", "body": b"b" * 800, "more_body": False},
    ]
    status, body = asyncio.run(invoke(boundary, make_scope(auth_headers), messages))
    assert status == 413 and body["error"]["code"] == "request_too_large"


@pytest.mark.parametrize("length", [b"-1", b"invalid", b"9" * 100])
def test_invalid_content_length(settings, auth_headers, length):
    boundary = LocalSecurityMiddleware(success_app, settings)
    status, _ = asyncio.run(
        invoke(boundary, make_scope(auth_headers, extra_headers=[(b"content-length", length)]), [])
    )
    assert status in {400, 413}


def test_duplicate_security_headers(settings, auth_headers):
    boundary = LocalSecurityMiddleware(success_app, settings)
    status, body = asyncio.run(
        invoke(boundary, make_scope(auth_headers, extra_headers=[(b"host", b"evil.example")]), [])
    )
    assert status == 400 and body["error"]["code"] == "invalid_headers"


def test_non_ascii_token_fails_safely(settings, auth_headers):
    boundary = LocalSecurityMiddleware(success_app, settings)
    scope = make_scope(
        {"X-CSRF-Token": auth_headers["X-CSRF-Token"]}, extra_headers=[(b"x-local-token", b"\xff")]
    )
    status, _ = asyncio.run(invoke(boundary, scope, []))
    assert status == 401


def test_body_read_timeout(settings_factory, auth_headers):
    boundary = LocalSecurityMiddleware(success_app, settings_factory(body_timeout_seconds=0.001))
    status, body = asyncio.run(invoke(boundary, make_scope(auth_headers), [], body_delay=0.05))
    assert status == 408 and body["error"]["code"] == "body_timeout"


def test_execution_timeout(settings_factory, auth_headers):
    async def slow_app(_scope, _receive, _send):
        await asyncio.sleep(0.05)

    boundary = LocalSecurityMiddleware(slow_app, settings_factory(request_timeout_seconds=0.001))
    status, body = asyncio.run(
        invoke(boundary, make_scope(auth_headers), [{"type": "http.request", "body": b"{}"}])
    )
    assert status == 504 and body["error"]["code"] == "request_timeout"
    assert boundary._active == 0


def test_concurrent_request_cap(settings_factory, auth_headers):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_app(scope, receive, send):
            entered.set()
            await release.wait()
            await success_app(scope, receive, send)

        boundary = LocalSecurityMiddleware(blocked_app, settings_factory(max_concurrent_requests=1))
        messages = [{"type": "http.request", "body": b"{}"}]
        first = asyncio.create_task(invoke(boundary, make_scope(auth_headers), messages))
        await entered.wait()
        second = await invoke(boundary, make_scope(auth_headers), messages)
        release.set()
        completed = await first
        assert second[0] == 503 and completed[0] == 200
        assert boundary._active == 0

    asyncio.run(scenario())


def test_exception_details_never_leak(settings, auth_headers, caplog):
    async def failed_app(_scope, _receive, _send):
        raise RuntimeError("PRIVATE_ERROR_SENTINEL")

    boundary = LocalSecurityMiddleware(failed_app, settings)
    status, body = asyncio.run(
        invoke(boundary, make_scope(auth_headers), [{"type": "http.request", "body": b"{}"}])
    )
    assert status == 500
    assert "PRIVATE_ERROR_SENTINEL" not in json.dumps(body)
    assert "PRIVATE_ERROR_SENTINEL" not in caplog.text

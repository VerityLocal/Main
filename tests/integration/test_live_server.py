"""Real TCP/CLI integration; no model loading or fabricated inference results."""

import os
import secrets
import socket
import subprocess
import sys
import time

import httpx

from backend.app.core.config import PROJECT_ROOT
from backend.app.document.builder import build_document


def test_real_loopback_launcher_and_registration(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    auth, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    environment = {
        **os.environ,
        "LOCAL_AI_AUTH_TOKEN": auth,
        "LOCAL_AI_CSRF_TOKEN": csrf,
        "LOCAL_AI_BIND_HOST": "127.0.0.1",
        "LOCAL_AI_PORT": str(port),
        "LOCAL_AI_ALLOWED_ORIGINS": "[]",
        "LOCAL_AI_DATA_DIR": str(tmp_path / "data"),
        "LOCAL_AI_MODEL_CACHE": str(tmp_path / "models"),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "backend.app.main"],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", timeout=2, trust_env=False
        ) as client:
            deadline = time.monotonic() + 20
            while True:
                try:
                    unauthenticated = client.get("/api/v1/health")
                    break
                except httpx.TransportError:
                    assert process.poll() is None, "Loopback launcher exited before readiness"
                    assert time.monotonic() < deadline, "Loopback launcher readiness timed out"
                    time.sleep(0.05)
            assert unauthenticated.status_code == 401
            headers = {"X-Local-Token": auth, "X-CSRF-Token": csrf}
            response = client.get("/api/v1/health", headers=headers)
            assert response.status_code == 200
            health = response.json()
            assert health["implementation"] == "local_analysis_platform"
            assert health["hardware"]["system_ram_total_bytes"] > 0
            document = build_document(
                ["A real loopback Unicode check: café 😀."],
                document_id="live_smoke",
                revision=1,
                block_ids=["live_block"],
            )
            response = client.post(
                "/api/v1/documents/register", headers=headers, json=document.model_dump(mode="json")
            )
            assert response.status_code == 200
            assert response.json()["offset_unit"] == "utf16_code_unit"
            stale = build_document(["Older text."], document_id="live_smoke", revision=0)
            response = client.post(
                "/api/v1/documents/register", headers=headers, json=stale.model_dump(mode="json")
            )
            assert response.status_code == 409
    finally:
        # This process was created by this test. No existing server is stopped.
        if process.poll() is None:
            process.terminate()
        try:
            _stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            _stdout, stderr = process.communicate(timeout=5)
        assert auth not in stderr and csrf not in stderr
        assert "A real loopback Unicode check" not in stderr

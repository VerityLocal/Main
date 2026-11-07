"""Real local engines, source storage and SSE under the security boundary."""

import json

from backend.app.document.builder import build_document
from backend.app.document.offsets import Utf16Index
from backend.app.services.event_manager import EventManager


def events(response):
    return [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]


def test_all_engines_and_replay_with_trusted_source(client, auth_headers):
    text = "😀 Alice visited Paris during the summer of 2024."
    document = build_document([text], document_id="runtime", revision=1)
    response = client.post(
        "/api/v1/sources",
        headers=auth_headers,
        json={
            "source_id": "reference",
            "title": "Reference",
            "text": text,
            "reliability": "user_trusted",
        },
    )
    assert response.status_code == 201
    submitted = client.post(
        "/api/v1/analyses",
        headers=auth_headers,
        json={"document": document.model_dump(mode="json")},
    )
    assert submitted.status_code == 202
    identifier = submitted.json()["request_id"]
    response = client.get(f"/api/v1/analyses/{identifier}/events", headers=auth_headers)
    history = events(response)
    assert history[-1]["payload"]["status"] == "completed"
    assert [e["sequence"] for e in history] == list(range(1, len(history) + 1))
    ai = next(e["payload"] for e in history if e["payload"].get("status") == "unavailable")
    assert ai["findings"] == []
    match = next(e["payload"]["findings"][0] for e in history if "source_count" in e["payload"])
    assert Utf16Index(text).slice(match["start_offset"], match["end_offset"]).startswith("Alice")
    claim = next(e["payload"]["finding"] for e in history if "finding" in e["payload"])
    assert claim["category"] == "INSUFFICIENT_EVIDENCE"
    assert claim["evidence"][0]["nli"] is None
    replay = events(
        client.get(
            f"/api/v1/analyses/{identifier}/events",
            headers={
                **auth_headers,
                "Last-Event-ID": "2",
            },
        )
    )
    assert replay == history[2:]
    assert (
        client.get(
            f"/api/v1/analyses/{identifier}/events",
            headers={
                **auth_headers,
                "Last-Event-ID": "999",
            },
        ).status_code
        == 409
    )
    assert (
        client.get(
            f"/api/v1/analyses/{identifier}/events",
            headers={
                **auth_headers,
                "Last-Event-ID": "bad",
            },
        ).status_code
        == 400
    )


def test_extraction_transfer_validates_offsets_and_external_policy(client, auth_headers, document):
    canonical = document.model_dump(mode="json")
    extraction = {key: value for key, value in canonical.items() if key != "contract_version"}
    for block in extraction["blocks"]:
        del block["normalization"]
    body = {"extraction": extraction, "engines": ["plagiarism"]}
    assert client.post("/api/v1/analyses/text", headers=auth_headers, json=body).status_code == 202
    body["external_search_consent"] = True
    assert client.post("/api/v1/analyses/text", headers=auth_headers, json=body).status_code == 403
    body["external_search_consent"] = False
    extraction["blocks"][0]["end_offset"] += 1
    assert client.post("/api/v1/analyses/text", headers=auth_headers, json=body).status_code == 422


def test_sources_models_and_no_unauthenticated_access(client, auth_headers):
    assert client.get("/api/v1/models/status").status_code == 401
    status = client.get("/api/v1/models/status", headers=auth_headers).json()
    assert status["device"] == "cpu" and not status["gpu_jobs_enabled"]
    assert not status["external_search_enabled"]
    assert all(not model["available"] for model in status["models"].values())
    assert client.post("/api/v1/models/unload", headers=auth_headers, json={}).status_code == 200
    assert client.get("/api/v1/analyses/absent", headers=auth_headers).status_code == 410
    assert (
        client.post("/api/v1/sources/absent/remove", headers=auth_headers, json={}).status_code
        == 200
    )


def test_persistent_history_restart_marks_unfinished_and_keeps_terminal(tmp_path, document):
    path = tmp_path / "events.sqlite3"
    manager = EventManager(path)
    identifier = manager.create(document)
    manager.append(identifier, "analysis.started", {})
    manager.close()
    restarted = EventManager(path)
    assert restarted.get(identifier)["terminal"]
    assert restarted.replay(identifier)[-1][1].payload["code"] == "backend_restarted"
    restarted.append(identifier, "plagiarism.completed", {"late": True})
    assert len(restarted.replay(identifier)) == 2
    restarted.close()


def test_bad_detector_artifact_does_not_prevent_other_engines(
    client, app, auth_headers, document, tmp_path
):
    # A deliberately incompatible artifact must not take down lexical retrieval.
    from backend.app.core.config import Settings

    checkpoint = tmp_path / "bad-model"
    checkpoint.mkdir()
    (checkpoint / "manifest.json").write_text("{}", encoding="utf-8")
    app.state.inference.runner.settings = Settings(
        **{
            **app.state.settings.model_dump(),
            "detector_checkpoint": checkpoint,
            "_env_file": None,
        }
    )
    submitted = client.post(
        "/api/v1/analyses",
        headers=auth_headers,
        json={"document": document.model_dump(mode="json")},
    )
    identifier = submitted.json()["request_id"]
    history = events(client.get(f"/api/v1/analyses/{identifier}/events", headers=auth_headers))
    assert any(e["payload"].get("source_count") == 0 for e in history)
    assert history[-1]["payload"]["status"] == "completed"


def test_event_budget_reserves_terminal_event(tmp_path, document):
    import pytest

    manager = EventManager(tmp_path / "bounded.sqlite3", capacity=1)
    identifier = manager.create(document)
    for _ in range(255):
        manager.append(identifier, "claim_verification.partial", {})
    with pytest.raises(RuntimeError, match="limit"):
        manager.append(identifier, "claim_verification.partial", {})
    manager.append(identifier, "analysis.error", {"code": "output_limit"})
    assert manager.get(identifier)["terminal"]
    assert manager.replay(identifier)[-1][1].sequence == 256
    replacement = manager.create(document)
    assert replacement != identifier
    with pytest.raises(KeyError):
        manager.get(identifier)
    manager.close()

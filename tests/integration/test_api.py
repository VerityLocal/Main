from backend.app.document.builder import build_document


def test_authenticated_health_is_honest_about_phase_scope(client, auth_headers):
    response = client.get("/api/v1/health", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["implementation"] == "local_analysis_platform"
    assert data["components"]["ai_detection"] == "requires_trained_checkpoint"
    assert data["hardware"]["measurement_kind"] == "hardware_snapshot_not_model_benchmark"
    assert response.headers["cache-control"] == "no-store"
    assert len(response.headers["x-request-id"]) == 32


def test_health_requires_token(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_registration_is_idempotent_and_rejects_old_revisions(client, auth_headers, document):
    response = client.post(
        "/api/v1/documents/register", headers=auth_headers, json=document.model_dump(mode="json")
    )
    assert response.status_code == 200
    assert response.json()["changed"] is True
    response = client.post(
        "/api/v1/documents/register", headers=auth_headers, json=document.model_dump(mode="json")
    )
    assert response.status_code == 200 and response.json()["changed"] is False
    old = build_document(["old"], document_id=document.document_id, revision=1)
    changed = build_document(["changed"], document_id=document.document_id, revision=2)
    for candidate in [old, changed]:
        response = client.post(
            "/api/v1/documents/register",
            headers=auth_headers,
            json=candidate.model_dump(mode="json"),
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "revision_conflict"
    assert client.app.state.documents.is_current(document.document_id, 2)


def test_invalid_documents_do_not_echo_private_text(client, auth_headers, document, caplog):
    values = document.model_dump(mode="json")
    values["extracted_text"] = "PRIVATE_DOCUMENT_SENTINEL"
    response = client.post("/api/v1/documents/register", headers=auth_headers, json=values)
    assert response.status_code == 422
    assert "PRIVATE_DOCUMENT_SENTINEL" not in response.text
    assert "PRIVATE_DOCUMENT_SENTINEL" not in caplog.text


def test_invalid_json_is_safe(client, auth_headers):
    response = client.post(
        "/api/v1/documents/register",
        headers={**auth_headers, "Content-Type": "application/json"},
        content='{"private": INVALID_SECRET_CONTENT}',
    )
    assert response.status_code == 422
    assert "INVALID_SECRET_CONTENT" not in response.text


def test_reserved_inference_and_docs_routes_are_not_fake_implementations(client, auth_headers):
    for path in ["/openapi.json", "/docs"]:
        assert client.get(path, headers=auth_headers).status_code == 404
    response = client.post("/api/v1/analyses", headers=auth_headers, json={})
    assert response.status_code == 422


def test_registry_is_cleared_on_shutdown(app, auth_headers, document):
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="http://127.0.0.1:8787") as instance:
        instance.post(
            "/api/v1/documents/register",
            headers=auth_headers,
            json=document.model_dump(mode="json"),
        )
        assert app.state.documents.size == 1
    assert app.state.documents.size == 0

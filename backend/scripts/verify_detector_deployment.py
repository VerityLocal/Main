"""Check a running calibrated pilot through authenticated HTTP and SSE."""

import argparse
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx

from backend.app.core.config import Settings, load_platform_config
from backend.app.document.builder import build_document
from backend.app.document.chunking import sentence_spans
from backend.app.engines.ai_detection.artifact import validate_manifest
from backend.app.schemas.event import EventEnvelope
from backend.app.schemas.finding import Finding
from backend.scripts.dataset_utils import dataset_provenance, file_sha256, read_records


def require(condition, message):
    if not condition:
        raise ValueError(message)


def extraction_for(document):
    return {
        **document.model_dump(mode="json", exclude={"contract_version", "blocks"}),
        "blocks": [
            block.model_dump(mode="json", exclude={"normalization"}) for block in document.blocks
        ],
    }


def stream_events(client, created, deadline, after=0):
    """Reconnect after the server's bounded SSE response, preserving its cursor."""
    events = []
    while time.monotonic() < deadline:
        with client.stream(
            "GET",
            f"analyses/{created['request_id']}/events",
            headers={"Last-Event-ID": str(after)},
        ) as response:
            response.raise_for_status()
            name, identifier, data = "", "", []
            for line in response.iter_lines():
                if time.monotonic() >= deadline:
                    raise TimeoutError("Live analysis exceeded the smoke-check deadline")
                if not line:
                    if data:
                        event = EventEnvelope.model_validate_json("\n".join(data))
                        require(identifier == str(event.sequence), "SSE ID/sequence mismatch")
                        require(event.sequence == after + 1, "SSE replay gap or duplicate")
                        require(
                            event.request_id == created["request_id"]
                            and event.document_id == created["document_id"]
                            and event.document_revision == created["document_revision"],
                            "SSE document/request/revision mismatch",
                        )
                        after = event.sequence
                        events.append((name, event))
                        require(name != "analysis.error", "Live analysis emitted an error")
                        if name == "analysis.completed":
                            return events
                    name, identifier, data = "", "", []
                elif not line.startswith(":"):
                    field, _, value = line.partition(":")
                    value = value.removeprefix(" ")
                    if field == "event":
                        name = value
                    elif field == "id":
                        identifier = value
                    elif field == "data":
                        data.append(value)
    raise TimeoutError("Live analysis exceeded the smoke-check deadline")


def check_case(client, settings, manifest, tokenizer, name, text, *, outside=False):
    document = build_document(
        [text], document_id=f"deployment_smoke_{uuid4().hex}", revision=7, language="en"
    )
    body = {
        "extraction": extraction_for(document),
        "engines": ["ai_detection"],
        "external_search_consent": False,
    }
    started = time.perf_counter()
    response = client.post("analyses/text", json=body)
    require(response.status_code == 202, "Live analysis was not accepted")
    created = response.json()
    require(
        created["document_id"] == document.document_id
        and created["document_revision"] == document.revision
        and created["offset_unit"] == "utf16_code_unit",
        "Submission identity or offset unit mismatch",
    )
    deadline = time.monotonic() + settings.analysis_timeout_seconds + 30
    events = stream_events(client, created, deadline)
    matches = [event.payload for kind, event in events if kind == "ai_detection.completed"]
    require(len(matches) == 1, "Expected one AI detector result")
    result = matches[0]
    if outside:
        require(
            result["status"] == "unavailable"
            and result["findings"] == []
            and "document_score" not in result
            and result["diagnostics"]["outside_trained_input_profile"] is True,
            "Oversized input received a score or an unexpected failure",
        )
    else:
        require(result["status"] == "completed", "Calibrated detector did not complete")
        score = result["document_score"]
        require(math.isfinite(score) and 0 <= score <= 1, "Invalid document probability")
        diagnostics = result["diagnostics"]
        require(
            diagnostics["calibrated"] is True
            and diagnostics["device"] == "cpu"
            and diagnostics["document_label_policy"] == "contains_annotated_ai_v1"
            and diagnostics["document_score_interpretation"]
            == "estimated_probability_contains_annotated_ai"
            and diagnostics["input_profile"] == manifest["input_profile"],
            "Detector deployment profile or mixed-document interpretation mismatch",
        )
        expected = {(s.start_offset, s.end_offset) for s in sentence_spans(text)}
        observed = set()
        for item in result["findings"]:
            finding = Finding.model_validate(item)
            finding.validate_against(document)
            require(
                finding.category == "AI_GENERATED_CANDIDATE"
                and finding.confidence is not None
                and finding.confidence == finding.score
                and finding.calibration_artifact_id == manifest["calibration"]["artifact_id"],
                "Sentence result lacks the configured checkpoint's calibrated probability",
            )
            observed.add((finding.start_offset, finding.end_offset))
        require(
            observed == expected and len(result["findings"]) == len(expected),
            "Sentence findings do not match original UTF-16 spans",
        )
    elapsed = time.perf_counter() - started
    replay = stream_events(client, created, time.monotonic() + 20, after=1)
    require(replay == events[1:], "Terminal SSE replay differs from the original events")
    summary = {
        "name": name,
        "token_count": len(tokenizer.encode(text, truncation=False)),
        "status": result["status"],
        "findings": len(result["findings"]),
        "document_score": result.get("document_score"),
        "elapsed_seconds": elapsed,
        "event_identity_and_replay_verified": True,
        "original_utf16_spans_verified": not outside,
        "outside_profile_abstention_verified": outside,
    }
    print(json.dumps(summary), flush=True)
    return summary, document, body


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data", type=Path, help="Optionally include a mixed validation document")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a new deployment report path")
    settings = Settings()
    checkpoint = settings.detector_checkpoint
    if checkpoint is None:
        raise SystemExit("Configure the calibrated checkpoint and start the backend first")
    manifest_path = checkpoint / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest, load_platform_config(settings.config_dir))
    require(
        manifest.get("calibration")
        and manifest.get("document_label_policy") == "contains_annotated_ai_v1"
        and manifest.get("input_profile", {}).get("max_tokens") == 512,
        "This smoke check requires the calibrated 512-token presence-classifier pilot",
    )
    manifest_digest = file_sha256(manifest_path)
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(
        checkpoint / "tokenizer", local_files_only=True, use_fast=True
    )
    boundary = " ".join(["word"] * (512 - tokenizer.num_special_tokens_to_add(pair=False)))
    oversized = boundary + " word"
    require(
        len(tokenizer.encode(boundary)) == 512 and len(tokenizer.encode(oversized)) == 513,
        "The tokenizer no longer matches the exact boundary fixtures",
    )
    cases = [
        (
            "unicode_revision",
            "Hi 😀. The café opens at nine. Visitors can buy tickets there.",
            False,
        ),
        ("exactly_512_tokens", boundary, False),
        ("513_tokens_abstain", oversized, True),
    ]
    mixed_id = None
    if args.data:
        rows = read_records(args.data)
        provenance = dataset_provenance(args.data, rows)
        require(
            provenance["data_sha256"] == manifest["dataset_provenance"]["data_sha256"],
            "Smoke-check data does not match checkpoint provenance",
        )
        mixed = next(
            row
            for row in rows
            if row["split"] == "validation" and row.get("source_label") == "mixed"
        )
        mixed_id = mixed["id"]
        cases.append(("mixed_validation_document", mixed["text"], False))
    host = "[::1]" if settings.bind_host == "::1" else settings.bind_host
    url = f"http://{host}:{settings.port}/api/v1/"
    timeout = httpx.Timeout(settings.request_timeout_seconds + 5)
    with httpx.Client(base_url=url, timeout=timeout, trust_env=False) as client:
        unauthenticated = client.get("health")
        require(unauthenticated.status_code == 401, "Unauthenticated health was not rejected")
        client.headers["X-Local-Token"] = settings.auth_token.get_secret_value()
        missing_csrf = client.post("analyses/text", json={})
        require(missing_csrf.status_code == 403, "Missing CSRF token was not rejected")
        client.headers["X-CSRF-Token"] = settings.csrf_token.get_secret_value()
        health = client.get("health")
        health.raise_for_status()
        require(
            health.json()["components"]["ai_detection"] == "configured_checkpoint",
            "Running backend has no configured detector",
        )
        summaries = []
        for name, text, outside in cases:
            summary, document, body = check_case(
                client, settings, manifest, tokenizer, name, text, outside=outside
            )
            summaries.append(summary)
        revised = build_document(
            [document.extracted_text + " Updated."],
            document_id=document.document_id,
            revision=document.revision + 1,
            language="en",
        )
        response = client.post("documents/register", json=revised.model_dump(mode="json"))
        response.raise_for_status()
        stale = client.post("analyses/text", json=body)
        require(stale.status_code == 409, "Stale revision was not rejected")
    require(file_sha256(manifest_path) == manifest_digest, "Checkpoint changed during verification")
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kind": "live_authenticated_deployment_smoke_not_accuracy_or_latency_benchmark",
        "manifest_sha256": manifest_digest,
        "weights_sha256": file_sha256(checkpoint / "weights.pt"),
        "calibration_artifact_id": manifest["calibration"]["artifact_id"],
        "unauthenticated_status": unauthenticated.status_code,
        "missing_csrf_status": missing_csrf.status_code,
        "stale_revision_status": stale.status_code,
        "mixed_validation_record_id": mixed_id,
        "cases": summaries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, allow_nan=False)
    print(json.dumps({"deployment_checks_passed": True, "output": str(args.output)}), flush=True)


if __name__ == "__main__":
    main()

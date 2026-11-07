import json
from datetime import UTC, datetime

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from backend.app.core.config import PROJECT_ROOT
from backend.app.schemas.document import Document
from backend.app.schemas.event import EventEnvelope
from backend.app.schemas.finding import Finding
from backend.scripts.export_schemas import schema_artifacts


def test_document_roundtrip(document):
    assert Document.model_validate_json(document.model_dump_json()) == document
    assert Document.model_validate(document.model_dump(mode="json")) == document


@pytest.mark.parametrize("field", ["contract_version", "language", "offset_unit"])
def test_coordinate_and_version_metadata_required(document, field):
    values = document.model_dump(mode="json")
    del values[field]
    with pytest.raises(ValidationError):
        Document.model_validate(values)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("revision", "2"),
        ("revision", True),
        ("offset_unit", "code_point"),
        ("extra", "ignored?"),
        ("extracted_text", "different"),
    ],
)
def test_invalid_document_contract(document, key, value):
    values = document.model_dump(mode="json")
    values[key] = value
    with pytest.raises(ValidationError):
        Document.model_validate(values)


def test_finding_revisions_boundaries_and_confidence(document):
    values = dict(
        finding_id="finding_a",
        document_id=document.document_id,
        revision=document.revision,
        start_offset=5,
        end_offset=7,
        category="EXACT_OVERLAP",
        score=0.8,
    )
    finding = Finding(**values)
    finding.validate_against(document)
    assert finding.confidence is None
    for update in [
        {"revision": 1},
        {"document_id": "wrong"},
        {"end_offset": 999},
        {"start_offset": 6},
    ]:
        with pytest.raises(ValueError):
            Finding(**{**values, **update}).validate_against(document)
    for update in [
        {"confidence": 0.8},
        {"confidence": 2.0},
        {"start_offset": 7},
        {"confidence_interpretation": "probability_calibrated"},
        {"score": float("nan")},
    ]:
        with pytest.raises(ValidationError):
            Finding(**{**values, **update})
    calibrated = Finding(
        **values,
        confidence=0.8,
        confidence_interpretation="probability_calibrated",
        calibration_artifact_id="artifact_a",
    )
    assert calibrated.confidence == 0.8


def test_sse_json_object_and_line_injection_protection():
    envelope = EventEnvelope(
        request_id="request_a",
        document_id="doc_a",
        document_revision=1,
        sequence=3,
        timestamp=datetime.now(UTC),
        payload={"text": "a\nb😀"},
    )
    wire = envelope.to_sse("analysis.completed")
    lines = wire.splitlines()
    assert lines[:2] == ["id: 3", "event: analysis.completed"]
    data = json.loads(lines[2].removeprefix("data: "))
    assert isinstance(data, dict) and data["payload"]["text"] == "a\nb😀"
    assert wire.endswith("\n\n")
    with pytest.raises(ValueError):
        envelope.to_sse("analysis.completed\ndata: malicious")


def test_sse_timestamp_and_sequence_validation():
    values = dict(
        request_id="req",
        document_id="doc",
        document_revision=1,
        sequence=1,
        timestamp=datetime.now(UTC),
    )
    for update in [
        {"sequence": 0},
        {"timestamp": datetime(2026, 1, 1)},
        {"payload": {"x": object()}},
    ]:
        with pytest.raises(ValidationError):
            EventEnvelope(**{**values, **update})


def test_json_schemas_are_valid_reproducible_and_accept_document(document):
    artifacts = schema_artifacts()
    for filename, text in artifacts.items():
        schema = json.loads(text)
        Draft202012Validator.check_schema(schema)
        assert (PROJECT_ROOT / "shared" / "schemas" / filename).read_text(encoding="utf-8") == text
    schema = json.loads(artifacts["document.schema.json"])
    Draft202012Validator(schema).validate(document.model_dump(mode="json"))


def test_documents_are_immutable(document):
    with pytest.raises(ValidationError):
        document.revision = 3

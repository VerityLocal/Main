"""SSE serialization contract, not an implemented streaming server."""

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, JsonValue, field_validator

from backend.app.schemas.document import Contract

EventName = Literal[
    "analysis.started",
    "ai_detection.completed",
    "plagiarism.completed",
    "claim_verification.partial",
    "claim_verification.completed",
    "analysis.completed",
    "analysis.error",
]


class EventEnvelope(Contract):
    contract_version: Literal["1.0.0"] = "1.0.0"
    request_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_revision: int = Field(ge=0)
    sequence: int = Field(ge=1)
    offset_unit: Literal["utf16_code_unit"] = "utf16_code_unit"
    timestamp: datetime
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    diagnostics: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def aware_timestamp(cls, timestamp: datetime) -> datetime:
        if timestamp.utcoffset() is None:
            raise ValueError("Event timestamp requires a timezone")
        return timestamp.astimezone(UTC)

    def to_sse(self, event_name: EventName) -> str:
        # Validate even when called by untyped Python code; prevent line injection.
        names = {
            "analysis.started",
            "ai_detection.completed",
            "plagiarism.completed",
            "claim_verification.partial",
            "claim_verification.completed",
            "analysis.completed",
            "analysis.error",
        }
        if event_name not in names:
            raise ValueError("Unsupported SSE event name")
        data = json.dumps(self.model_dump(mode="json"), ensure_ascii=True, allow_nan=False)
        return f"id: {self.sequence}\nevent: {event_name}\ndata: {data}\n\n"

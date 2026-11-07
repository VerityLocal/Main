"""Scores are separate from calibrated probability estimates."""

from typing import Literal, Self

from pydantic import Field, model_validator

from backend.app.document.offsets import Utf16Index
from backend.app.schemas.document import Contract, Document


class Finding(Contract):
    contract_version: Literal["1.0.0"] = "1.0.0"
    finding_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    revision: int = Field(ge=0)
    offset_unit: Literal["utf16_code_unit"] = "utf16_code_unit"
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    category: Literal[
        "AI_GENERATED_CANDIDATE",
        "EXACT_OVERLAP",
        "REORDERED_TEXT",
        "SEMANTIC_PARAPHRASE",
        "SUPPORTED",
        "CONTRADICTED",
        "INSUFFICIENT_EVIDENCE",
        "CONFLICTING_EVIDENCE",
        "INTRINSIC_CONTRADICTION_CANDIDATE",
    ]
    score: float | None = Field(default=None, allow_inf_nan=False)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    confidence_interpretation: Literal["not_available", "probability_calibrated"] = "not_available"
    calibration_artifact_id: str | None = Field(default=None, min_length=1, max_length=128)
    diagnostics: dict[str, str | float | int | bool | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def coherent_finding(self) -> Self:
        if self.start_offset >= self.end_offset:
            raise ValueError("Finding span must be nonempty and ordered")
        calibrated = self.confidence_interpretation == "probability_calibrated"
        if calibrated != (self.confidence is not None) or calibrated != bool(
            self.calibration_artifact_id
        ):
            raise ValueError("Confidence requires an explicit calibration artifact and policy")
        return self

    def validate_against(self, document: Document) -> None:
        if self.document_id != document.document_id or self.revision != document.revision:
            raise ValueError("Finding belongs to a different document or revision")
        Utf16Index(document.extracted_text).slice(self.start_offset, self.end_offset)

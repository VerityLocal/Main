"""Analysis, local corpus and evidence contracts."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from backend.app.schemas.document import Contract, Document

EngineName = Literal["ai_detection", "plagiarism", "claim_verification"]


class AnalysisRequest(Contract):
    document: Document
    engines: tuple[EngineName, ...] = ("ai_detection", "plagiarism", "claim_verification")
    external_search_consent: bool = False

    @field_validator("engines", mode="before")
    @classmethod
    def arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def bounded(self):
        if not self.engines or len(set(self.engines)) != len(self.engines):
            raise ValueError("Select distinct engines")
        if len(self.document.extracted_text) > 20_000:
            raise ValueError("The current analysis profile supports at most 20000 code points")
        return self


class Source(Contract):
    source_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    title: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=100_000)
    url: str | None = Field(default=None, max_length=2048)
    publication_date: str | None = Field(default=None, max_length=32)
    reliability: Literal["unrated", "user_trusted"] = "unrated"
    retrieved_at: datetime | None = None


class SimilarityMatch(Contract):
    finding_id: str
    document_id: str
    revision: int
    offset_unit: Literal["utf16_code_unit"] = "utf16_code_unit"
    start_offset: int
    end_offset: int
    source_id: str
    source_start_offset: int
    source_end_offset: int
    category: Literal["EXACT_OVERLAP", "REORDERED_TEXT", "SEMANTIC_PARAPHRASE"]
    similarity_score: float
    verification_score: float | None = None
    retrieval_method: str
    confidence: None = None
    diagnostics: dict = Field(default_factory=dict)


class Claim(Contract):
    claim_id: str
    original_text: str
    normalized_claim: str
    start_offset: int
    end_offset: int
    entities: tuple[str, ...] = ()
    temporal_expressions: tuple[str, ...] = ()
    quantities: tuple[str, ...] = ()
    extraction_confidence: None = None
    extraction_method: str

"""Browser extraction transfer: backend computes canonical normalization once."""

from typing import Literal

from pydantic import Field, field_validator

from backend.app.document.normalization import normalize_with_mapping
from backend.app.schemas.analysis import EngineName
from backend.app.schemas.document import (
    AdapterReference,
    Block,
    Contract,
    Document,
    ExtractionMetadata,
)


class ExtractedBlock(Contract):
    block_id: str
    original_text: str = Field(min_length=1, max_length=20_000)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    adapter_ref: AdapterReference
    text_revision: int = Field(ge=0)


class ExtractedDocument(Contract):
    document_id: str
    revision: int
    language: str
    blocks: tuple[ExtractedBlock, ...] = Field(min_length=1, max_length=2048)
    extracted_text: str = Field(min_length=1, max_length=20_000)
    offset_unit: Literal["utf16_code_unit"]
    extraction_metadata: ExtractionMetadata

    @field_validator("blocks", mode="before")
    @classmethod
    def arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value

    def canonical(self):
        blocks = tuple(
            Block(**block.model_dump(), normalization=normalize_with_mapping(block.original_text))
            for block in self.blocks
        )
        return Document(
            **self.model_dump(exclude={"blocks"}), blocks=blocks, contract_version="1.0.0"
        )


class TextAnalysisRequest(Contract):
    extraction: ExtractedDocument
    engines: tuple[EngineName, ...]
    external_search_consent: bool = False

    @field_validator("engines", mode="before")
    @classmethod
    def arrays(cls, value):
        return tuple(value) if isinstance(value, list) else value

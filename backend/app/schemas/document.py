"""Immutable browser-facing document contracts."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.document.normalization import NormalizationMap
from backend.app.document.offsets import Utf16Index

Identifier = str
Surface = Literal[
    "manual", "static_dom", "prosemirror", "lexical", "quill", "slate", "textarea", "google_docs"
]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)


class AdapterReference(Contract):
    surface: Surface
    locator: str = Field(min_length=1, max_length=256)


class ExtractionMetadata(Contract):
    surface: Surface
    scope: Literal["full_document", "rendered_content", "selection", "manual"]
    adapter_version: str = Field(min_length=1, max_length=64)
    source_url: str | None = Field(default=None, max_length=2048)


class Block(Contract):
    block_id: Identifier = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    original_text: str = Field(min_length=1, max_length=200_000)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    adapter_ref: AdapterReference
    text_revision: int = Field(ge=0)
    normalization: NormalizationMap

    @model_validator(mode="after")
    def check_block(self) -> Self:
        index = Utf16Index(self.original_text)
        if self.end_offset - self.start_offset != index.length:
            raise ValueError("Block offsets must match original UTF-16 length")
        self.normalization.validate_original(self.original_text)
        return self


class Document(Contract):
    contract_version: Literal["1.0.0"]
    document_id: Identifier = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    revision: int = Field(ge=0)
    language: str = Field(pattern=r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    blocks: tuple[Block, ...] = Field(min_length=1, max_length=2048)
    extracted_text: str = Field(min_length=1, max_length=200_000)
    offset_unit: Literal["utf16_code_unit"]
    extraction_metadata: ExtractionMetadata

    @field_validator("blocks", mode="before")
    @classmethod
    def json_blocks(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def canonical_blocks(self) -> Self:
        if len({block.block_id for block in self.blocks}) != len(self.blocks):
            raise ValueError("Block IDs must be unique")
        if self.extracted_text != "\n\n".join(block.original_text for block in self.blocks):
            raise ValueError("Extracted text must equal canonical block concatenation")
        index = Utf16Index(self.extracted_text)
        next_start = 0
        for block in self.blocks:
            if block.start_offset != next_start or block.text_revision > self.revision:
                raise ValueError("Invalid block position or text revision")
            if index.slice(block.start_offset, block.end_offset) != block.original_text:
                raise ValueError("Block span does not match extracted text")
            next_start = block.end_offset + 2
        return self

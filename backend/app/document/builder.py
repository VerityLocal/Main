"""Manual document builder; browser adapters will provide their own stable IDs."""

from collections.abc import Sequence
from uuid import uuid4

from backend.app.document.normalization import normalize_with_mapping
from backend.app.document.offsets import utf16_length
from backend.app.schemas.document import AdapterReference, Block, Document, ExtractionMetadata


def build_document(
    texts: Sequence[str],
    *,
    document_id: str | None = None,
    revision: int = 0,
    language: str = "und",
    block_ids: Sequence[str] | None = None,
) -> Document:
    if isinstance(texts, str) or not texts:
        raise ValueError("Supply a nonempty sequence of block texts")
    if block_ids is not None and len(block_ids) != len(texts):
        raise ValueError("Supply one stable ID per block")
    blocks = []
    position = 0
    for i, text in enumerate(texts):
        end = position + utf16_length(text)
        blocks.append(
            Block(
                block_id=block_ids[i] if block_ids is not None else f"block_{uuid4().hex}",
                original_text=text,
                start_offset=position,
                end_offset=end,
                adapter_ref=AdapterReference(surface="manual", locator=f"block:{i}"),
                text_revision=revision,
                normalization=normalize_with_mapping(text),
            )
        )
        position = end + 2
    return Document(
        contract_version="1.0.0",
        document_id=document_id or f"document_{uuid4().hex}",
        revision=revision,
        language=language,
        blocks=tuple(blocks),
        extracted_text="\n\n".join(texts),
        offset_unit="utf16_code_unit",
        extraction_metadata=ExtractionMetadata(
            surface="manual", scope="manual", adapter_version="1.0.0"
        ),
    )

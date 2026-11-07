import pytest
from pydantic import ValidationError

from backend.app.document.builder import build_document
from backend.app.schemas.document import Document
from backend.app.services.document_manager import DocumentManager, RegistryFull, RevisionConflict


def test_canonical_block_positions_and_stable_caller_ids(document):
    assert document.blocks[0].start_offset == 0
    assert document.blocks[1].start_offset == document.blocks[0].end_offset + 2
    assert document.extracted_text == "Café 😀 is Unicode.\n\nA second paragraph."
    assert document.blocks[0].block_id == "block_a"


@pytest.mark.parametrize("kind", ["duplicate_id", "wrong_offset", "future_revision", "bad_map"])
def test_invalid_blocks(document, kind):
    values = document.model_dump(mode="json")
    if kind == "duplicate_id":
        values["blocks"][1]["block_id"] = "block_a"
    elif kind == "wrong_offset":
        values["blocks"][1]["start_offset"] += 1
    elif kind == "future_revision":
        values["blocks"][0]["text_revision"] = 3
    else:
        values["blocks"][0]["normalization"]["unicode_version"] = "wrong"
    with pytest.raises(ValidationError):
        Document.model_validate(values)


@pytest.mark.parametrize("texts", [[], [""], "not a sequence of blocks"])
def test_invalid_builder_input(texts):
    with pytest.raises(ValueError):
        build_document(texts)


def test_wrong_block_id_count():
    with pytest.raises(ValueError):
        build_document(["one", "two"], block_ids=["one"])


def test_revision_registry_idempotence_and_stale_safety(document):
    registry = DocumentManager(2, 60)
    assert registry.register(document)
    assert not registry.register(document)
    assert registry.is_current(document.document_id, document.revision)
    for texts, revision in [(["changed"], 2), (["stale"], 1)]:
        with pytest.raises(RevisionConflict):
            registry.register(
                build_document(texts, document_id=document.document_id, revision=revision)
            )
    newer = build_document(["newer"], document_id=document.document_id, revision=3)
    assert registry.register(newer)
    assert not registry.is_current(document.document_id, 2)
    assert registry.is_current(document.document_id, 3)


def test_registry_full_ttl_and_clear(document):
    now = [0.0]
    registry = DocumentManager(1, 10, clock=lambda: now[0])
    registry.register(document)
    with pytest.raises(RegistryFull):
        registry.register(build_document(["another"], document_id="other"))
    now[0] = 10
    assert registry.size == 0
    assert not registry.is_current(document.document_id, 2)
    registry.register(document)
    registry.clear()
    assert registry.size == 0

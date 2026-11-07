"""Synthetic resource checks, not inference benchmarks."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from backend.app.document.builder import build_document
from backend.app.services.document_manager import DocumentManager, RegistryFull, RevisionConflict


@pytest.mark.resource
def test_registry_capacity_remains_bounded():
    registry = DocumentManager(4, 60)
    for i in range(4):
        registry.register(build_document(["text"], document_id=f"doc_{i}"))
    for i in range(4, 20):
        with pytest.raises(RegistryFull):
            registry.register(build_document(["text"], document_id=f"doc_{i}"))
    assert registry.size == 4
    assert not any(hasattr(record, "text") for record in registry._records.values())


@pytest.mark.resource
def test_concurrent_updates_never_regress_revision():
    registry = DocumentManager(1, 60)

    def register(revision):
        document = build_document([f"revision {revision}"], document_id="shared", revision=revision)
        try:
            registry.register(document)
        except RevisionConflict:
            pass

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(register, range(25)))
    assert registry.is_current("shared", 24)
    assert registry.size == 1

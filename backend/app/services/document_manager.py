"""Bounded TTL revision identity; raw document text is not retained."""

import hashlib
import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from backend.app.schemas.document import Document


class RevisionConflict(ValueError):
    """Stale revision or changed content under an existing revision."""


class RegistryFull(RuntimeError):
    """No free registry slot; active records are not silently evicted."""


@dataclass(frozen=True)
class RevisionRecord:
    revision: int
    digest: str
    expires_at: float


class DocumentManager:
    def __init__(
        self, max_documents: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_documents < 1 or ttl_seconds <= 0:
            raise ValueError("Registry bounds must be positive")
        self._maximum = max_documents
        self._ttl = ttl_seconds
        self._clock = clock
        self._records: dict[str, RevisionRecord] = {}
        self._lock = threading.Lock()

    def _expire(self, now: float) -> None:
        expired = [key for key, record in self._records.items() if record.expires_at <= now]
        for key in expired:
            del self._records[key]

    def register(self, document: Document) -> bool:
        canonical = json.dumps(
            document.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        digest = hashlib.sha256(canonical.encode("ascii")).hexdigest()
        with self._lock:
            now = self._clock()
            self._expire(now)
            old = self._records.get(document.document_id)
            if old and (
                document.revision < old.revision
                or (document.revision == old.revision and digest != old.digest)
            ):
                raise RevisionConflict("Document revision conflicts with registered content")
            if old is None and len(self._records) >= self._maximum:
                raise RegistryFull("Document registry capacity reached")
            self._records[document.document_id] = RevisionRecord(
                document.revision, digest, now + self._ttl
            )
            return old is None or document.revision > old.revision

    def is_current(self, document_id: str, revision: int) -> bool:
        with self._lock:
            self._expire(self._clock())
            record = self._records.get(document_id)
            return record is not None and record.revision == revision

    @property
    def size(self) -> int:
        with self._lock:
            self._expire(self._clock())
            return len(self._records)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

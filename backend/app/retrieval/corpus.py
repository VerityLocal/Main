"""Private SQLite source corpus, bounded by records and total characters."""

import sqlite3
import threading
from pathlib import Path

from backend.app.document.offsets import Utf16Index
from backend.app.schemas.analysis import Source


class Corpus:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, body TEXT NOT NULL)"
        )
        self.db.commit()
        self.lock = threading.RLock()
        self.revision = 0

    def all(self) -> list[Source]:
        with self.lock:
            return [
                Source.model_validate_json(row[0])
                for row in self.db.execute("SELECT body FROM sources ORDER BY id")
            ]

    def add(self, source: Source):
        Utf16Index(source.text)
        with self.lock:
            current = [s for s in self.all() if s.source_id != source.source_id]
            if (
                len(current) >= 256
                or sum(len(s.text) for s in current) + len(source.text) > 2_000_000
            ):
                raise ValueError("Local corpus capacity reached")
            self.db.execute(
                "INSERT OR REPLACE INTO sources VALUES (?,?)",
                (source.source_id, source.model_dump_json()),
            )
            self.db.commit()
            self.revision += 1

    def remove(self, identifier):
        with self.lock:
            self.db.execute("DELETE FROM sources WHERE id=?", (identifier,))
            self.db.commit()
            self.revision += 1

    def close(self):
        self.db.close()

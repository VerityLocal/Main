"""Private, bounded SQLite event replay that survives worker and server restarts."""

import sqlite3
import threading
import time
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.schemas.event import EventEnvelope


class EventManager:
    def __init__(self, path, capacity=32, retention=3600):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self.capacity, self.retention = capacity, retention
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,
                document TEXT, revision INTEGER,
                created REAL, terminal INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(request TEXT, sequence INTEGER, name TEXT, body TEXT,
                PRIMARY KEY(request,sequence));
        """)
        self.db.commit()
        # Never pretend a lost process can resume inference from event history.
        unfinished = self.db.execute("SELECT id FROM requests WHERE terminal=0").fetchall()
        for (identifier,) in unfinished:
            self.append(
                identifier,
                "analysis.error",
                {"code": "backend_restarted", "message": "Resubmit the current document"},
            )

    def prune(self):
        with self.lock:
            expired = self.db.execute(
                "SELECT id FROM requests WHERE terminal=1 AND created<?",
                (time.time() - self.retention,),
            ).fetchall()
            for (identifier,) in expired:
                self.db.execute("DELETE FROM events WHERE request=?", (identifier,))
                self.db.execute("DELETE FROM requests WHERE id=?", (identifier,))
            self.db.commit()

    def create(self, document):
        with self.lock:
            self.prune()
            count = self.db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
            if count >= self.capacity:
                old = self.db.execute(
                    "SELECT id FROM requests WHERE terminal=1 ORDER BY created LIMIT 1"
                ).fetchone()
                if not old:
                    raise RuntimeError("Analysis capacity reached")
                self.db.execute("DELETE FROM events WHERE request=?", old)
                self.db.execute("DELETE FROM requests WHERE id=?", old)
            identifier = uuid4().hex
            self.db.execute(
                "INSERT INTO requests(id,document,revision,created) VALUES (?,?,?,?)",
                (identifier, document.document_id, document.revision, time.time()),
            )
            self.db.commit()
            return identifier

    def get(self, identifier):
        with self.lock:
            self.prune()
            row = self.db.execute(
                "SELECT document,revision,terminal FROM requests WHERE id=?", (identifier,)
            ).fetchone()
            if not row:
                raise KeyError("Request history unavailable")
            return {
                "request_id": identifier,
                "document_id": row[0],
                "document_revision": row[1],
                "terminal": bool(row[2]),
            }

    def append(self, identifier, name, payload, diagnostics=None):
        with self.lock:
            record = self.get(identifier)
            if record["terminal"]:
                return
            sequence = self.db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE request=?", (identifier,)
            ).fetchone()[0]
            terminal = name in {"analysis.completed", "analysis.error"}
            if sequence > 256 or (sequence == 256 and not terminal):
                raise RuntimeError("Event history limit reached")
            event = EventEnvelope(
                request_id=identifier,
                document_id=record["document_id"],
                document_revision=record["document_revision"],
                sequence=sequence,
                timestamp=datetime.now(UTC),
                payload=payload,
                diagnostics=diagnostics or {},
            )
            body = event.model_dump_json()
            if len(body.encode("utf-8")) > 512_000:
                raise RuntimeError("Event payload limit reached")
            total = self.db.execute(
                "SELECT COALESCE(SUM(LENGTH(CAST(body AS BLOB))),0) FROM events WHERE request=?",
                (identifier,),
            ).fetchone()[0]
            # Reserve room for a small terminal/error event after a limit fails.
            limit = 4_000_000 if terminal else 3_999_000
            if total + len(body.encode("utf-8")) > limit:
                raise RuntimeError("Total event history byte limit reached")
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?,?)", (identifier, sequence, name, body)
            )
            if name in {"analysis.completed", "analysis.error"}:
                self.db.execute("UPDATE requests SET terminal=1 WHERE id=?", (identifier,))
            self.db.commit()

    def replay(self, identifier, after=0):
        with self.lock:
            self.get(identifier)
            return [
                (name, EventEnvelope.model_validate_json(body))
                for name, body in self.db.execute(
                    "SELECT name,body FROM events WHERE request=? AND sequence>? ORDER BY sequence",
                    (identifier, after),
                )
            ]

    def close(self):
        self.db.close()

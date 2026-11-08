"""Cola persistente de avisos de emergencia (SQLite). Sobrevive a reinicios y a la falta de internet."""

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

EMERGENCY = "emergency"
CANCEL = "cancel"


@dataclass(frozen=True)
class Notice:
    emergency_id: str
    kind: str
    payload: dict
    attempts: int


class EmergencyQueue:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute(
                """CREATE TABLE IF NOT EXISTS notices (
                    emergency_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    next_try_at REAL NOT NULL DEFAULT 0, sent_at REAL, last_error TEXT,
                    PRIMARY KEY (emergency_id, kind))"""
            )

    def add(self, emergency_id: str, kind: str, payload: dict, now: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR IGNORE INTO notices (emergency_id, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (emergency_id, kind, json.dumps(payload), now),
            )

    def due(self, now: float, limit: int = 20) -> list[Notice]:
        """Avisos sin confirmar listos para reintentar. Una cancelación espera a que su emergencia esté confirmada."""
        with self._lock:
            rows = self._db.execute(
                """SELECT n.emergency_id, n.kind, n.payload, n.attempts FROM notices n
                   WHERE n.sent_at IS NULL AND n.next_try_at <= ?
                     AND (n.kind = 'emergency' OR EXISTS (
                          SELECT 1 FROM notices e WHERE e.emergency_id = n.emergency_id
                          AND e.kind = 'emergency' AND e.sent_at IS NOT NULL))
                   ORDER BY n.created_at LIMIT ?""",
                (now, limit),
            ).fetchall()
        return [Notice(row[0], row[1], json.loads(row[2]), row[3]) for row in rows]

    def get_unsent(self, emergency_id: str, kind: str) -> Notice | None:
        with self._lock:
            row = self._db.execute(
                "SELECT emergency_id, kind, payload, attempts FROM notices "
                "WHERE emergency_id = ? AND kind = ? AND sent_at IS NULL",
                (emergency_id, kind),
            ).fetchone()
        return Notice(row[0], row[1], json.loads(row[2]), row[3]) if row else None

    def mark_sent(self, emergency_id: str, kind: str, now: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE notices SET sent_at = ?, last_error = NULL WHERE emergency_id = ? AND kind = ?",
                (now, emergency_id, kind),
            )

    def mark_failed(
        self, emergency_id: str, kind: str, error: str, next_try_at: float
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE notices SET attempts = attempts + 1, last_error = ?, next_try_at = ? "
                "WHERE emergency_id = ? AND kind = ?",
                (error, next_try_at, emergency_id, kind),
            )

    def pending_count(self) -> int:
        with self._lock:
            return self._db.execute(
                "SELECT COUNT(*) FROM notices WHERE sent_at IS NULL"
            ).fetchone()[0]

    def last_error(self) -> str | None:
        with self._lock:
            row = self._db.execute(
                "SELECT last_error FROM notices WHERE sent_at IS NULL AND last_error IS NOT NULL "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return row[0] if row else None

"""SQLite lead store. One row per canonical URL; notification state lives on the row."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              TEXT PRIMARY KEY,
    canonical_url   TEXT NOT NULL UNIQUE,
    url             TEXT NOT NULL,
    source          TEXT NOT NULL,
    source_detail   TEXT,
    title           TEXT NOT NULL,
    body            TEXT,
    author          TEXT,
    published_at    TEXT,
    date_verified   INTEGER NOT NULL DEFAULT 0,
    discovered_at   TEXT NOT NULL,
    fingerprint     TEXT NOT NULL,
    duplicate_of    TEXT,
    passed          INTEGER NOT NULL,
    reject_reason   TEXT,
    suitability     INTEGER,
    scam_score      INTEGER,
    priority        INTEGER,
    analysis_json   TEXT,
    status          TEXT NOT NULL DEFAULT 'new',
    notify_state    TEXT NOT NULL DEFAULT 'ineligible',
    notified_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_leads_fp ON leads(fingerprint);
CREATE INDEX IF NOT EXISTS idx_leads_discovered ON leads(discovered_at);
CREATE INDEX IF NOT EXISTS idx_leads_notify ON leads(notify_state);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at    TEXT NOT NULL,
    fetched       INTEGER,
    new_leads     INTEGER,
    notified      INTEGER,
    errors        TEXT
);
"""

STATUSES = ("new", "reviewed", "interesting", "contacted", "rejected", "archived")


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def is_empty(self) -> bool:
        return self.conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))

    def get(self, lead_id: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()

    def has(self, lead_id: str) -> bool:
        return self.conn.execute("SELECT 1 FROM leads WHERE id = ?", (lead_id,)).fetchone() is not None

    def by_fingerprint(self, fp: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT id, author FROM leads WHERE fingerprint = ?", (fp,)).fetchall()

    def recent_texts(self, days: int) -> list[sqlite3.Row]:
        since = _iso(datetime.now(timezone.utc) - timedelta(days=days))
        return self.conn.execute(
            "SELECT id, title, body FROM leads WHERE discovered_at >= ? ORDER BY discovered_at DESC LIMIT 3000",
            (since,),
        ).fetchall()

    def insert(self, row: dict) -> None:
        row = dict(row)
        row["published_at"] = _iso(row.get("published_at"))
        row["discovered_at"] = _iso(row["discovered_at"])
        if isinstance(row.get("analysis_json"), dict):
            row["analysis_json"] = json.dumps(row["analysis_json"], default=str)
        cols = ", ".join(row)
        marks = ", ".join(f":{k}" for k in row)
        with self.conn:
            self.conn.execute(f"INSERT OR IGNORE INTO leads ({cols}) VALUES ({marks})", row)

    def pending_notifications(self, max_age_hours: int) -> list[sqlite3.Row]:
        since = _iso(datetime.now(timezone.utc) - timedelta(hours=max_age_hours))
        return self.conn.execute(
            "SELECT * FROM leads WHERE notify_state = 'pending' AND discovered_at >= ? ORDER BY priority DESC",
            (since,),
        ).fetchall()

    def set_notify_state(self, lead_id: str, state: str) -> None:
        notified = _iso(datetime.now(timezone.utc)) if state == "sent" else None
        with self.conn:
            self.conn.execute(
                "UPDATE leads SET notify_state = ?, notified_at = COALESCE(?, notified_at) WHERE id = ?",
                (state, notified, lead_id),
            )

    def set_status(self, lead_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")
        with self.conn:
            self.conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))

    def log_run(self, started_at: datetime, fetched: int, new_leads: int, notified: int, errors: list[str]) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO runs (started_at, fetched, new_leads, notified, errors) VALUES (?, ?, ?, ?, ?)",
                (_iso(started_at), fetched, new_leads, notified, json.dumps(errors)),
            )

    def list_leads(self, limit: int = 20, only_passed: bool = True) -> list[sqlite3.Row]:
        where = "WHERE passed = 1 AND duplicate_of IS NULL" if only_passed else ""
        return self.conn.execute(
            f"SELECT * FROM leads {where} ORDER BY priority DESC, discovered_at DESC LIMIT ?", (limit,)
        ).fetchall()

    def stats(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "total": q("SELECT COUNT(*) FROM leads"),
            "passed_stage1": q("SELECT COUNT(*) FROM leads WHERE passed = 1"),
            "duplicates": q("SELECT COUNT(*) FROM leads WHERE duplicate_of IS NOT NULL"),
            "notified": q("SELECT COUNT(*) FROM leads WHERE notify_state = 'sent'"),
            "runs": q("SELECT COUNT(*) FROM runs"),
        }

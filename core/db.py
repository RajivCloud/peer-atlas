"""SQLite storage for Peer Atlas.

Three tables:
  messages  - raw Discord messages we imported (so re-imports skip duplicates)
  peers     - one row per person, built from their intro message(s)
  settings  - simple key/value store (your name, note template, weekly limit)

SQLite is a single file (data/peer_atlas.db). No server to install.
"""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("PEER_ATLAS_DB", PROJECT_ROOT / "data" / "peer_atlas.db"))

STATUSES = ("not_contacted", "sent", "connected", "skipped")

# Fields the extractor (or you, in Review) can fill in for a peer.
PEER_FIELDS = (
    "name", "role", "company", "experience",
    "location_raw", "city", "region", "country", "lat", "lon",
    "linkedin_url", "skills", "open_to", "other_links",
    "confidence", "needs_review", "review_reason",
    "source_message_ids", "source_text",
)
# These hold lists, stored as JSON text because SQLite has no list type.
JSON_FIELDS = {"skills", "open_to", "other_links", "source_message_ids"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id            TEXT PRIMARY KEY,          -- Discord message id (or a hash for pasted text)
    author_id     TEXT,
    author_handle TEXT NOT NULL,
    timestamp     TEXT,
    content       TEXT NOT NULL,
    linkedin_urls TEXT,                      -- JSON list, normalized
    embed         TEXT,                      -- JSON: LinkedIn link preview (name, company, location)
    processed     INTEGER NOT NULL DEFAULT 0 -- 1 once extraction has run on it
);

CREATE TABLE IF NOT EXISTS peers (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_handle     TEXT NOT NULL UNIQUE,  -- one row per Discord user
    name               TEXT,
    role               TEXT,
    company            TEXT,
    experience         TEXT,
    location_raw       TEXT,                  -- what they typed, e.g. "BLR"
    city               TEXT,                  -- normalized, e.g. "Bengaluru"
    region             TEXT,                  -- state / province / metro, e.g. "California"
    country            TEXT,
    lat                REAL,
    lon                REAL,
    linkedin_url       TEXT,
    skills             TEXT,                  -- JSON list
    open_to            TEXT,                  -- JSON list
    other_links        TEXT,                  -- JSON list
    confidence         REAL,
    needs_review       INTEGER NOT NULL DEFAULT 0,
    review_reason      TEXT,
    reviewed           INTEGER NOT NULL DEFAULT 0, -- 1 = you checked it; extractor won't overwrite
    source_message_ids TEXT,                  -- JSON list
    source_text        TEXT,
    status             TEXT NOT NULL DEFAULT 'not_contacted',
    sent_at            TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_empty(value) -> bool:
    return value is None or value == "" or value == []


@contextmanager
def connect():
    """Open the database, commit on success, always close."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call every time the app starts."""
    with connect() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------- messages

def save_messages(messages: list[dict]) -> int:
    """Store raw messages. Returns how many were new (duplicates are skipped)."""
    rows = [
        {
            "author_id": None, "timestamp": None, **m,
            "linkedin_urls": json.dumps(m.get("linkedin_urls", [])),
            "embed": json.dumps(m["embed"]) if m.get("embed") else None,
        }
        for m in messages
    ]
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            """INSERT OR IGNORE INTO messages
                   (id, author_id, author_handle, timestamp, content, linkedin_urls, embed)
               VALUES (:id, :author_id, :author_handle, :timestamp, :content, :linkedin_urls, :embed)""",
            rows,
        )
        return conn.total_changes - before


def known_message_ids(ids: list[str]) -> set[str]:
    """Which of these message ids are already in the database (for 'N new messages' previews)."""
    if not ids:
        return set()
    with connect() as conn:
        found = set()
        for start in range(0, len(ids), 500):  # SQLite limits how many ? placeholders one query can have
            chunk = ids[start : start + 500]
            marks = ",".join("?" * len(chunk))
            found |= {r[0] for r in conn.execute(f"SELECT id FROM messages WHERE id IN ({marks})", chunk)}
    return found


def pending_messages() -> list[dict]:
    """Messages that haven't been through extraction yet, oldest first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE processed = 0 ORDER BY timestamp"
        ).fetchall()
    messages = []
    for r in rows:
        m = dict(r)
        m["linkedin_urls"] = json.loads(m["linkedin_urls"]) if m["linkedin_urls"] else []
        m["embed"] = json.loads(m["embed"]) if m["embed"] else None
        messages.append(m)
    return messages


def mark_processed(message_ids: list[str]) -> None:
    with connect() as conn:
        conn.executemany(
            "UPDATE messages SET processed = 1 WHERE id = ?", [(i,) for i in message_ids]
        )


def reset_extraction() -> int:
    """Start extraction over (e.g. switching from rules to Claude).
    Deletes peers you haven't reviewed and marks all messages as unprocessed.
    Reviewed peers and their outreach status are kept. Returns how many peers were removed."""
    with connect() as conn:
        removed = conn.execute("DELETE FROM peers WHERE reviewed = 0 AND status = 'not_contacted'").rowcount
        conn.execute("UPDATE messages SET processed = 0")
    return removed


def message_counts() -> dict:
    with connect() as conn:
        total, done = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(processed), 0) FROM messages"
        ).fetchone()
    return {"total": total, "processed": done}


# ---------------------------------------------------------------- peers

def _to_row(peer: dict) -> dict:
    """Python values -> SQLite values (lists become JSON text)."""
    return {k: json.dumps(v) if k in JSON_FIELDS else v for k, v in peer.items()}


def _from_row(row: sqlite3.Row) -> dict:
    """SQLite row -> Python dict (JSON text becomes lists)."""
    peer = dict(row)
    for f in JSON_FIELDS:
        peer[f] = json.loads(peer[f]) if peer[f] else []
    return peer


def save_peer(peer: dict) -> int:
    """Insert a new peer, or merge into the existing row for the same Discord handle.

    Merge rules:
      - a new non-empty value replaces the old one (later intro messages win)
      - an empty value never erases what we already have
      - source_message_ids are combined
      - rows you've reviewed are left alone
    Returns the peer's id.
    """
    handle = peer["discord_handle"]
    incoming = {k: v for k, v in peer.items() if k in PEER_FIELDS}
    now = _now()

    with connect() as conn:
        row = conn.execute("SELECT * FROM peers WHERE discord_handle = ?", (handle,)).fetchone()

        if row is None:
            data = _to_row({**incoming, "discord_handle": handle, "created_at": now, "updated_at": now})
            cols = ", ".join(data)
            marks = ", ".join(f":{c}" for c in data)
            cur = conn.execute(f"INSERT INTO peers ({cols}) VALUES ({marks})", data)
            return cur.lastrowid

        existing = _from_row(row)
        if existing["reviewed"]:
            return existing["id"]

        updates = {k: v for k, v in incoming.items() if not _is_empty(v)}
        if "source_message_ids" in updates:
            merged = existing["source_message_ids"] + updates["source_message_ids"]
            updates["source_message_ids"] = list(dict.fromkeys(merged))  # keep order, drop dupes
        if "needs_review" in incoming:  # 0 is a real answer, so copy it even though it's "falsy"
            updates["needs_review"] = incoming["needs_review"]
        if not updates:
            return existing["id"]

        updates["updated_at"] = now
        data = _to_row(updates)
        sets = ", ".join(f"{c} = :{c}" for c in data)
        conn.execute(f"UPDATE peers SET {sets} WHERE id = :id", {**data, "id": existing["id"]})
        return existing["id"]


def list_peers() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM peers ORDER BY name COLLATE NOCASE").fetchall()
    return [_from_row(r) for r in rows]


def get_peer(peer_id: int) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM peers WHERE id = ?", (peer_id,)).fetchone()
    return _from_row(row) if row else None


def update_peer(peer_id: int, **fields) -> None:
    """Edit fields directly (used by the Review screen). Pass reviewed=1 to lock the row."""
    allowed = set(PEER_FIELDS) | {"reviewed"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unknown peer fields: {sorted(bad)}")
    data = _to_row({**fields, "updated_at": _now()})
    sets = ", ".join(f"{c} = :{c}" for c in data)
    with connect() as conn:
        conn.execute(f"UPDATE peers SET {sets} WHERE id = :id", {**data, "id": peer_id})


def delete_peer(peer_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM peers WHERE id = ?", (peer_id,))


def set_status(peer_id: int, status: str) -> None:
    """Track LinkedIn outreach. Marking 'sent' records the time for the weekly counter."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    sent_at = _now() if status == "sent" else None
    with connect() as conn:
        if status == "sent":
            conn.execute(
                "UPDATE peers SET status = ?, sent_at = ?, updated_at = ? WHERE id = ?",
                (status, sent_at, _now(), peer_id),
            )
        else:  # keep sent_at so "connected" peers still show when you reached out
            conn.execute(
                "UPDATE peers SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), peer_id),
            )


def sent_this_week() -> int:
    """How many requests you've marked sent since Monday (UTC)."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    monday = today - timedelta(days=today.weekday())
    with connect() as conn:
        (n,) = conn.execute(
            "SELECT COUNT(*) FROM peers WHERE sent_at >= ?", (monday.isoformat(timespec="seconds"),)
        ).fetchone()
    return n


# ---------------------------------------------------------------- settings

def get_setting(key: str, default: str | None = None) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

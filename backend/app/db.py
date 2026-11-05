"""SQLite 访问层（无 ORM，保持零额外依赖）。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .config import DB_PATH, ensure_dirs

SCHEMA = """
CREATE TABLE IF NOT EXISTS canvases (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    slug          TEXT NOT NULL UNIQUE,
    framework     TEXT NOT NULL,
    graph         TEXT NOT NULL,
    model_config  TEXT NOT NULL DEFAULT '{}',
    background    TEXT NOT NULL DEFAULT '{}',
    rules         TEXT NOT NULL DEFAULT '[]',
    mode          TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assistant_chats (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL DEFAULT '',
    messages    TEXT NOT NULL DEFAULT '[]',
    canvas_id   TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_chats_time ON assistant_chats(updated_at DESC);

CREATE TABLE IF NOT EXISTS runs (
    id           TEXT PRIMARY KEY,
    canvas_id    TEXT NOT NULL,
    status       TEXT NOT NULL,
    input        TEXT NOT NULL DEFAULT '',
    output       TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT '',
    started_at   TEXT NOT NULL,
    finished_at  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_runs_canvas ON runs(canvas_id, started_at DESC);

CREATE TABLE IF NOT EXISTS agent_models (
    canvas_id      TEXT NOT NULL,
    node_id        TEXT NOT NULL,
    config         TEXT NOT NULL DEFAULT '{}',
    api_key_cipher TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL,
    PRIMARY KEY (canvas_id, node_id)
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """老库平滑升级：缺列就补上，不动已有数据。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(canvases)")}
    if "background" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN background TEXT NOT NULL DEFAULT '{}'")
    if "rules" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN rules TEXT NOT NULL DEFAULT '[]'")
    if "mode" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN mode TEXT NOT NULL DEFAULT ''")


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO app_settings(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, now_iso()),
        )

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
    remote_slug   TEXT NOT NULL DEFAULT '',
    remote_rev    INTEGER NOT NULL DEFAULT 0,
    base_graph_hash TEXT NOT NULL DEFAULT '',
    remote_lib    TEXT NOT NULL DEFAULT '',
    remote_name   TEXT NOT NULL DEFAULT '',
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

-- 向量模型 / 向量库 / 数据源的实例配置
-- config 存非密文字段（JSON），secret_cipher 存密文字段的加密 JSON
CREATE TABLE IF NOT EXISTS providers (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    provider      TEXT NOT NULL,
    name          TEXT NOT NULL DEFAULT '',
    config        TEXT NOT NULL DEFAULT '{}',
    secret_cipher TEXT NOT NULL DEFAULT '',
    scope         TEXT NOT NULL DEFAULT 'global',
    canvas_id     TEXT NOT NULL DEFAULT '',
    is_default    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_providers_kind ON providers(kind, scope, canvas_id);
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
    # ---- 远端同步：记住这张画布绑定的模板、上次同步的版本和图哈希 ----
    if "remote_slug" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN remote_slug TEXT NOT NULL DEFAULT ''")
    if "remote_rev" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN remote_rev INTEGER NOT NULL DEFAULT 0")
    if "base_graph_hash" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN base_graph_hash TEXT NOT NULL DEFAULT ''")
    # 从哪个库拉的：public / private:owner/repo
    if "remote_lib" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN remote_lib TEXT NOT NULL DEFAULT ''")
    # 远端模板名（画布下拉里显示用）
    if "remote_name" not in cols:
        conn.execute("ALTER TABLE canvases ADD COLUMN remote_name TEXT NOT NULL DEFAULT ''")


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


# --------------------------------------------------------------------------- #
# providers：向量模型 / 向量库 / 数据源
# --------------------------------------------------------------------------- #
def list_providers(kind: str = "", scope: str = "", canvas_id: str = "") -> list:
    sql = "SELECT * FROM providers WHERE 1=1"
    args: list = []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if scope:
        sql += " AND scope = ?"
        args.append(scope)
    if canvas_id:
        sql += " AND (scope = 'global' OR canvas_id = ?)"
        args.append(canvas_id)
    sql += " ORDER BY kind, is_default DESC, created_at ASC"
    with get_conn() as conn:
        return [dict(row) for row in conn.execute(sql, args)]


def get_provider(provider_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM providers WHERE id = ?",
                           (provider_id,)).fetchone()
    return dict(row) if row else None


def save_provider(record: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO providers(id, kind, provider, name, config, secret_cipher,"
            " scope, canvas_id, is_default, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET provider=excluded.provider, name=excluded.name,"
            " config=excluded.config, secret_cipher=excluded.secret_cipher,"
            " scope=excluded.scope, canvas_id=excluded.canvas_id,"
            " is_default=excluded.is_default, updated_at=excluded.updated_at",
            (record["id"], record["kind"], record["provider"], record.get("name", ""),
             record.get("config", "{}"), record.get("secret_cipher", ""),
             record.get("scope", "global"), record.get("canvas_id", ""),
             int(record.get("is_default", 0)), record.get("created_at") or now_iso(),
             now_iso()),
        )


def delete_provider(provider_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM providers WHERE id = ?", (provider_id,))
    return cur.rowcount > 0


def clear_provider_default(kind: str, scope: str, canvas_id: str = "") -> None:
    """同一作用域内只允许一个默认项。"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE providers SET is_default = 0 WHERE kind = ? AND scope = ? "
            "AND canvas_id = ?",
            (kind, scope, canvas_id),
        )

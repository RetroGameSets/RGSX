"""Local SQLite storage for the RGSX catalog cache and user-specific state."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 3

PLATFORM_SOURCE_ALIASES = {
    "archive": "Archive",
    "archive.org": "Archive",
    "edgeemu": "EdgeEmu",
    "edgeemu.net": "EdgeEmu",
    "lolroms": "LolRoms",
    "torrent": "Torrent",
    "1fichier": "1Fichier",
    "vimms": "Vimms",
}

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platforms (
    id INTEGER PRIMARY KEY,
    platform_name TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    folder TEXT NOT NULL DEFAULT '',
    platform_image TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER,
    display_name TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (platform_id) REFERENCES platforms(id) ON DELETE CASCADE,
    UNIQUE (platform_id, name, url)
);

CREATE INDEX IF NOT EXISTS idx_games_platform_sort
    ON games(platform_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_games_platform_name
    ON games(platform_id, name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_games_name
    ON games(name COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS game_assets (
    id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL,
    asset_type TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS platform_assets (
    id INTEGER PRIMARY KEY,
    platform_id INTEGER NOT NULL,
    asset_type TEXT NOT NULL,
    file_name TEXT NOT NULL DEFAULT '',
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    data BLOB NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (platform_id) REFERENCES platforms(id) ON DELETE CASCADE,
    UNIQUE (platform_id, asset_type)
);
CREATE INDEX IF NOT EXISTS idx_platform_assets_type ON platform_assets(asset_type);

CREATE TABLE IF NOT EXISTS download_history (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT '',
    game_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_download_history_status ON download_history(status);
CREATE INDEX IF NOT EXISTS idx_download_history_platform_game ON download_history(platform, game_name);

CREATE TABLE IF NOT EXISTS downloaded_games (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    game_name TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(platform, game_name)
);
CREATE INDEX IF NOT EXISTS idx_downloaded_games_platform ON downloaded_games(platform);

CREATE TABLE IF NOT EXISTS local_app_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_changes (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    platform_id INTEGER,
    operation TEXT NOT NULL,
    changed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_catalog_changes_sequence ON catalog_changes(sequence);

CREATE TRIGGER IF NOT EXISTS trg_catalog_platform_insert
AFTER INSERT ON platforms
BEGIN
    INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
    VALUES('platform', NEW.id, NEW.id, 'upsert', NEW.updated_at);
END;

CREATE TRIGGER IF NOT EXISTS trg_catalog_platform_update
AFTER UPDATE ON platforms
BEGIN
    INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
    VALUES('platform', NEW.id, NEW.id, 'upsert', NEW.updated_at);
END;

CREATE TRIGGER IF NOT EXISTS trg_catalog_platform_delete
AFTER DELETE ON platforms
BEGIN
    INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
    VALUES('platform', OLD.id, OLD.id, 'delete', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
END;

CREATE TRIGGER IF NOT EXISTS trg_catalog_game_insert
AFTER INSERT ON games
BEGIN
    INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
    VALUES('game', NEW.id, NEW.platform_id, 'upsert', NEW.updated_at);
END;

CREATE TRIGGER IF NOT EXISTS trg_catalog_game_update
AFTER UPDATE ON games
BEGIN
    INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
    VALUES('game', NEW.id, NEW.platform_id, 'upsert', NEW.updated_at);
END;

CREATE TRIGGER IF NOT EXISTS trg_catalog_game_delete
AFTER DELETE ON games
BEGIN
    INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
    VALUES('game', OLD.id, OLD.platform_id, 'delete', strftime('%Y-%m-%dT%H:%M:%SZ', 'now'));
END;
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def platform_source_from_name(platform_name: Any) -> str:
    text = str(platform_name or "").strip()
    if not text or not text.endswith(")"):
        return ""
    marker = text.rfind("(")
    if marker < 0:
        return ""
    return PLATFORM_SOURCE_ALIASES.get(text[marker + 1:-1].strip().casefold(), "")


def platform_display_name(platform_name: Any) -> str:
    text = str(platform_name or "").strip()
    source = platform_source_from_name(text)
    if not source:
        return text
    return text[:text.rfind("(")].rstrip()


def default_db_path() -> str:
    configured = os.environ.get("RGSX_DB_PATH", "").strip()
    if configured:
        return os.path.abspath(os.path.expandvars(os.path.expanduser(configured)))
    try:
        import config

        return os.path.join(config.SAVE_FOLDER, "rgsx.sqlite3")
    except Exception:
        return os.path.join(os.getcwd(), "rgsx.sqlite3")


def connect(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    path = os.path.abspath(os.fspath(db_path or default_db_path()))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize_database(db_path: str | os.PathLike[str] | None = None) -> str:
    path = os.path.abspath(os.fspath(db_path or default_db_path()))
    with connect(path) as connection:
        connection.executescript(SCHEMA_SQL)
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(platforms)").fetchall()}
        if "source" not in columns:
            connection.execute("ALTER TABLE platforms ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        legacy_rows = connection.execute(
            "SELECT id, platform_name, source FROM platforms WHERE TRIM(source) = ''"
        ).fetchall()
        for row in legacy_rows:
            source = platform_source_from_name(row[1])
            if source:
                connection.execute("UPDATE platforms SET source = ? WHERE id = ?", (source, row[0]))
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
    return path


def database_exists(db_path: str | os.PathLike[str] | None = None) -> bool:
    path = os.path.abspath(os.fspath(db_path or default_db_path()))
    return os.path.isfile(path) and os.path.getsize(path) > 0


def _json_metadata(value: Any) -> str:
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps({"raw": value}, ensure_ascii=False)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return "{}"


def _size_bytes(size: Any) -> int | None:
    if isinstance(size, (int, float)):
        return int(size)
    if not isinstance(size, str) or not size.strip():
        return None
    text = size.strip().replace(",", ".")
    import re

    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMGTPE]?)(?:I?B)?", text, re.IGNORECASE)
    if not match:
        return None
    value = float(match.group(1))
    unit_index = "KMGTPE".find(match.group(2).upper())
    multiplier = 1024 ** (unit_index + 1) if unit_index >= 0 else 1
    return int(value * multiplier)


def upsert_platform(
    connection: sqlite3.Connection,
    platform_name: str,
    folder: str = "",
    platform_image: str = "",
    file_name: str = "",
    sort_order: int = 0,
    timestamp: str | None = None,
    source: str = "",
) -> int:
    now = timestamp or utc_now()
    connection.execute(
          """INSERT INTO platforms(platform_name, source, file_name, folder, platform_image, sort_order, created_at, updated_at)
              VALUES(?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(platform_name) DO UPDATE SET
                 source=excluded.source,
             file_name=excluded.file_name,
             folder=excluded.folder,
             platform_image=excluded.platform_image,
             sort_order=excluded.sort_order,
             updated_at=excluded.updated_at""",
        (platform_name, source.strip(), file_name, folder, platform_image, sort_order, now, now),
    )
    row = connection.execute("SELECT id FROM platforms WHERE platform_name = ?", (platform_name,)).fetchone()
    if row is None:
        raise RuntimeError(f"Unable to create platform: {platform_name}")
    return int(row[0])


def replace_platform_games(
    connection: sqlite3.Connection,
    platform_id: int,
    rows: Iterable[tuple[str, str, str, dict[str, Any]]],
    timestamp: str | None = None,
) -> int:
    now = timestamp or utc_now()
    connection.execute("DELETE FROM games WHERE platform_id = ?", (platform_id,))
    count = 0
    for index, (name, url, size, metadata) in enumerate(rows):
        connection.execute(
            """INSERT INTO games(
                platform_id, name, url, size, size_bytes, display_name, sort_order,
                metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                platform_id,
                name,
                url,
                size,
                _size_bytes(size),
                os.path.splitext(name)[0].strip(),
                index,
                _json_metadata(metadata),
                now,
                now,
            ),
        )
        count += 1
    connection.execute("UPDATE platforms SET updated_at = ? WHERE id = ?", (now, platform_id))
    return count


def upsert_platform_asset(
    connection: sqlite3.Connection,
    platform_id: int,
    asset_type: str,
    file_name: str,
    mime_type: str,
    data: bytes,
    metadata: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> None:
    now = timestamp or utc_now()
    connection.execute(
        """INSERT INTO platform_assets(
            platform_id, asset_type, file_name, mime_type, data, metadata_json, created_at, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform_id, asset_type) DO UPDATE SET
            file_name=excluded.file_name,
            mime_type=excluded.mime_type,
            data=excluded.data,
            metadata_json=excluded.metadata_json,
            updated_at=excluded.updated_at""",
        (
            platform_id,
            asset_type,
            file_name,
            mime_type,
            sqlite3.Binary(data),
            _json_metadata(metadata or {}),
            now,
            now,
        ),
    )


def get_platform_asset(
    platform_name: str,
    asset_type: str = "platform_image",
    db_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    asset = get_platform_assets([platform_name], asset_type, db_path).get(platform_name)
    if asset is None:
        return None
    result = dict(asset)
    result.pop("platform_name", None)
    return result


def get_platform_assets(
    platform_names: Iterable[str],
    asset_type: str = "platform_image",
    db_path: str | os.PathLike[str] | None = None,
) -> dict[str, dict[str, Any]]:
    names = list(dict.fromkeys(str(name).strip() for name in platform_names if str(name).strip()))
    if not names:
        return {}
    initialize_database(db_path)
    placeholders = ", ".join("?" for _ in names)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""SELECT p.platform_name, a.id, a.file_name, a.mime_type, a.data, a.metadata_json
                  FROM platform_assets a
                  JOIN platforms p ON p.id = a.platform_id
                 WHERE p.platform_name IN ({placeholders}) AND a.asset_type = ?""",
            (*names, asset_type),
        ).fetchall()
    return {str(row["platform_name"]): dict(row) for row in rows}


def list_platforms(db_path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, platform_name, source, file_name, folder, platform_image, sort_order, created_at, updated_at "
            "FROM platforms ORDER BY sort_order, id"
        ).fetchall()
    return [dict(row) for row in rows]


def list_platforms_with_game_counts(db_path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    """Load platform metadata and game counts with one SQLite connection."""
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT p.id, p.platform_name, p.source, p.file_name, p.folder, p.platform_image,
                      p.sort_order, p.created_at, p.updated_at, COUNT(g.id) AS game_count
                 FROM platforms p
            LEFT JOIN games g ON g.platform_id = p.id
             GROUP BY p.id, p.platform_name, p.source, p.file_name, p.folder, p.platform_image,
                      p.sort_order, p.created_at, p.updated_at
             ORDER BY p.sort_order, p.id"""
        ).fetchall()
    return [dict(row) for row in rows]


def get_platform_id(connection: sqlite3.Connection, platform_name: str) -> int | None:
    row = connection.execute("SELECT id FROM platforms WHERE platform_name = ?", (platform_name,)).fetchone()
    return int(row[0]) if row else None


def list_games(platform_name: str, db_path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT g.id, p.platform_name, g.name, g.url, g.size, g.size_bytes,
                      g.display_name, g.sort_order, g.metadata_json, g.created_at, g.updated_at
                 FROM games g JOIN platforms p ON p.id = g.platform_id
                WHERE p.platform_name = ? ORDER BY g.sort_order, g.id""",
            (platform_name,),
        ).fetchall()
    return [dict(row) for row in rows]


def count_games(platform_name: str, db_path: str | os.PathLike[str] | None = None) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM games g JOIN platforms p ON p.id = g.platform_id WHERE p.platform_name = ?",
            (platform_name,),
        ).fetchone()
    return int(row[0]) if row else 0


def list_game_counts(db_path: str | os.PathLike[str] | None = None) -> dict[str, int]:
    """Return all platform game counts with one SQLite query."""
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT p.platform_name, COUNT(g.id) AS game_count
                 FROM platforms p
            LEFT JOIN games g ON g.platform_id = p.id
             GROUP BY p.id, p.platform_name"""
        ).fetchall()
    return {str(row["platform_name"]): int(row["game_count"]) for row in rows}


def catalog_sequence(db_path: str | os.PathLike[str] | None = None) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM catalog_changes").fetchone()
    return int(row[0]) if row else 0


def get_sync_cursor(db_path: str | os.PathLike[str] | None = None) -> int | None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'catalog_sync_sequence'"
        ).fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def set_sync_cursor(sequence: int, db_path: str | os.PathLike[str] | None = None) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('catalog_sync_sequence', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(max(0, int(sequence))),),
        )


def get_catalog_visibility_revision(db_path: str | os.PathLike[str] | None = None) -> int | None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'catalog_visibility_revision'"
        ).fetchone()
    if not row:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def set_catalog_visibility_revision(
    revision: int,
    db_path: str | os.PathLike[str] | None = None,
) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('catalog_visibility_revision', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(max(0, int(revision))),),
        )


def load_history(db_path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT platform, game_name, status, url, progress, timestamp, message, task_id, metadata_json
                 FROM download_history ORDER BY id"""
        ).fetchall()
    history: list[dict[str, Any]] = []
    for row in rows:
        entry = {
            "platform": row["platform"],
            "game_name": row["game_name"],
            "status": row["status"],
            "url": row["url"] or None,
            "progress": row["progress"],
            "timestamp": row["timestamp"],
        }
        if row["message"]:
            entry["message"] = row["message"]
        if row["task_id"]:
            entry["task_id"] = row["task_id"]
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
            if isinstance(metadata, dict):
                entry.update(metadata)
        except Exception:
            pass
        history.append(entry)
    return history


def save_history(history: list[dict[str, Any]], db_path: str | os.PathLike[str] | None = None) -> None:
    initialize_database(db_path)
    now = utc_now()
    known_keys = {"platform", "game_name", "status", "url", "progress", "timestamp", "message", "task_id"}
    with connect(db_path) as connection:
        connection.execute("DELETE FROM download_history")
        for entry in history if isinstance(history, list) else []:
            if not isinstance(entry, dict):
                continue
            metadata = {key: value for key, value in entry.items() if key not in known_keys}
            connection.execute(
                """INSERT INTO download_history(
                    platform, game_name, status, url, progress, timestamp, message, task_id,
                    metadata_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(entry.get("platform") or ""),
                    str(entry.get("game_name") or ""),
                    str(entry.get("status") or ""),
                    str(entry.get("url") or ""),
                    float(entry.get("progress") or 0),
                    str(entry.get("timestamp") or ""),
                    str(entry.get("message") or ""),
                    str(entry.get("task_id") or ""),
                    _json_metadata(metadata),
                    now,
                    now,
                ),
            )


def load_downloaded_games(db_path: str | os.PathLike[str] | None = None) -> dict[str, dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            "SELECT platform, game_name, metadata_json FROM downloaded_games ORDER BY id"
        ).fetchall()
    downloaded: dict[str, dict[str, Any]] = {}
    for row in rows:
        metadata: Any = {}
        try:
            metadata = json.loads(row["metadata_json"] or "{}")
        except Exception:
            metadata = {}
        downloaded.setdefault(str(row["platform"]), {})[str(row["game_name"])] = (
            metadata if isinstance(metadata, dict) else {}
        )
    return downloaded


def save_downloaded_games(downloaded: dict[str, dict[str, Any]], db_path: str | os.PathLike[str] | None = None) -> None:
    initialize_database(db_path)
    now = utc_now()
    with connect(db_path) as connection:
        connection.execute("DELETE FROM downloaded_games")
        for platform, games in downloaded.items() if isinstance(downloaded, dict) else []:
            if not isinstance(games, dict):
                continue
            for game_name, metadata in games.items():
                connection.execute(
                    """INSERT INTO downloaded_games(platform, game_name, metadata_json, created_at, updated_at)
                       VALUES(?, ?, ?, ?, ?)""",
                    (str(platform), str(game_name), _json_metadata(metadata), now, now),
                )


def load_local_state(key: str, default: Any = None, db_path: str | os.PathLike[str] | None = None) -> Any:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            "SELECT value_json FROM local_app_state WHERE key = ?", (str(key),)
        ).fetchone()
    if not row:
        return default
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return default


def save_local_state(key: str, value: Any, db_path: str | os.PathLike[str] | None = None) -> None:
    initialize_database(db_path)
    now = utc_now()
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    with connect(db_path) as connection:
        connection.execute(
            """INSERT INTO local_app_state(key, value_json, updated_at) VALUES(?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at""",
            (str(key), encoded, now),
        )


def delete_local_state(key: str, db_path: str | os.PathLike[str] | None = None) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        connection.execute("DELETE FROM local_app_state WHERE key = ?", (str(key),))


LEGACY_MIGRATION_KEY = "legacy_user_state_migration_v1"


def _read_legacy_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as source:
            return json.load(source)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _migrate_legacy_state(connection: sqlite3.Connection, source_folder: Path) -> tuple[int, int, int]:
    history_data = _read_legacy_json(source_folder / "history.json")
    history_count = 0
    if isinstance(history_data, list):
        for entry in history_data:
            if not isinstance(entry, dict):
                continue
            platform = str(entry.get("platform") or "")
            game_name = str(entry.get("game_name") or "")
            status = str(entry.get("status") or "")
            if not platform or not game_name or not status:
                continue
            duplicate = connection.execute(
                """SELECT 1 FROM download_history
                   WHERE platform = ? AND game_name = ? AND status = ? AND url = ? AND timestamp = ?
                   LIMIT 1""",
                (
                    platform,
                    game_name,
                    status,
                    str(entry.get("url") or ""),
                    str(entry.get("timestamp") or ""),
                ),
            ).fetchone()
            if duplicate:
                continue
            known_keys = {"platform", "game_name", "status", "url", "progress", "timestamp", "message", "task_id"}
            metadata = {key: value for key, value in entry.items() if key not in known_keys}
            now = utc_now()
            connection.execute(
                """INSERT INTO download_history(
                    platform, game_name, status, url, progress, timestamp, message, task_id,
                    metadata_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    platform,
                    game_name,
                    status,
                    str(entry.get("url") or ""),
                    float(entry.get("progress") or 0),
                    str(entry.get("timestamp") or ""),
                    str(entry.get("message") or ""),
                    str(entry.get("task_id") or ""),
                    _json_metadata(metadata),
                    now,
                    now,
                ),
            )
            history_count += 1

    downloaded_data = _read_legacy_json(source_folder / "downloaded_games.json")
    downloaded_count = 0
    if isinstance(downloaded_data, dict):
        for platform, games in downloaded_data.items():
            if not isinstance(games, dict):
                continue
            for game_name, metadata in games.items():
                platform_name = str(platform or "")
                name = str(game_name or "")
                if not platform_name or not name:
                    continue
                now = utc_now()
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO downloaded_games(
                        platform, game_name, metadata_json, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?)""",
                    (platform_name, name, _json_metadata(metadata), now, now),
                )
                downloaded_count += int(cursor.rowcount > 0)

    torrent_cache_data = _read_legacy_json(source_folder / "torrent_manifest_cache.json")
    torrent_cache_count = 0
    if isinstance(torrent_cache_data, dict):
        existing = connection.execute(
            "SELECT 1 FROM local_app_state WHERE key = 'torrent_manifest_cache'"
        ).fetchone()
        if not existing:
            connection.execute(
                "INSERT INTO local_app_state(key, value_json, updated_at) VALUES(?, ?, ?)",
                (
                    "torrent_manifest_cache",
                    json.dumps(torrent_cache_data, ensure_ascii=False, separators=(",", ":")),
                    utc_now(),
                ),
            )
            torrent_cache_count = 1

    return history_count, downloaded_count, torrent_cache_count


def _legacy_paths(source_folder: Path) -> list[Path]:
    return [
        source_folder / name
        for name in (
            "history.json",
            "downloaded_games.json",
            "systems_list.json",
            "system_list.json",
            "games",
            "images",
            "platform_games_count_cache.json",
            "global_search_index.json",
            "rom_extensions.json",
            "torrent_manifest_cache.json",
        )
        if (source_folder / name).exists()
    ]


def _legacy_user_state_paths(source_folder: Path) -> list[Path]:
    return [
        source_folder / name
        for name in ("history.json", "downloaded_games.json", "torrent_manifest_cache.json")
        if (source_folder / name).is_file()
    ]


def _validate_legacy_json(source_folder: Path) -> None:
    for path in _legacy_user_state_paths(source_folder):
        try:
            with path.open("r", encoding="utf-8") as source:
                json.load(source)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Legacy JSON illisible: {path}") from exc


def _archive_legacy_paths(source_folder: Path, legacy_paths: list[Path]) -> str | None:
    existing_paths = [path for path in legacy_paths if path.exists()]
    if not existing_paths:
        return None
    archive_folder = source_folder / "backup_old_rgsx" / datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = 1
    while archive_folder.exists():
        archive_folder = source_folder / "backup_old_rgsx" / (
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{suffix}"
        )
        suffix += 1
    archive_folder.mkdir(parents=True, exist_ok=True)
    for path in existing_paths:
        shutil.move(str(path), str(archive_folder / path.name))
    return str(archive_folder)


def migrate_legacy_data(
    save_folder: str | os.PathLike[str],
    db_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Import legacy user state once and archive the old files without importing catalog data."""
    source_folder = Path(save_folder).resolve()
    target = os.path.abspath(os.fspath(db_path or default_db_path()))
    initialize_database(target)
    legacy_paths = _legacy_paths(source_folder)
    user_state_paths = _legacy_user_state_paths(source_folder)
    with connect(target) as connection:
        marker = connection.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (LEGACY_MIGRATION_KEY,)
        ).fetchone()
        if marker:
            _validate_legacy_json(source_folder)
            migrated = _migrate_legacy_state(connection, source_folder)
            if any(migrated):
                connection.commit()
            backup = _archive_legacy_paths(source_folder, legacy_paths)
            result = {"migrated": False, "reason": "already-migrated"}
            if backup:
                result["backup"] = backup
            return result
        if not user_state_paths:
            backup = _archive_legacy_paths(source_folder, legacy_paths)
            result = {"migrated": False, "reason": "no-legacy-user-state"}
            if backup:
                result["backup"] = backup
            return result

        _validate_legacy_json(source_folder)
        history_count, downloaded_count, torrent_cache_count = _migrate_legacy_state(connection, source_folder)
        summary = {
            "history": history_count,
            "downloaded_games": downloaded_count,
            "torrent_manifest_cache": torrent_cache_count,
        }
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, ?)",
            (LEGACY_MIGRATION_KEY, json.dumps(summary, separators=(",", ":"))),
        )
        connection.commit()

    with connect(target) as connection:
        integrity = connection.execute("PRAGMA quick_check").fetchone()
        marker = connection.execute(
            "SELECT value FROM schema_meta WHERE key = ?", (LEGACY_MIGRATION_KEY,)
        ).fetchone()
        if not integrity or integrity[0] != "ok" or not marker or marker[0] != json.dumps(summary, separators=(",", ":")):
            raise RuntimeError("Validation SQLite échouée après migration legacy")
        for table, key in (
            ("download_history", "history"),
            ("downloaded_games", "downloaded_games"),
        ):
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if summary[key] and (not row or int(row[0]) == 0):
                raise RuntimeError(f"Validation SQLite échouée pour {table}")

    backup = _archive_legacy_paths(source_folder, legacy_paths)
    summary.update({"migrated": True, "backup": backup})
    return summary


"""Synchronize the local SQLite catalog with the Sources Manager over HTTPS."""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import urllib.parse
import urllib.request
from typing import Any

import config
import database


_LOCAL_CATALOG_TRIGGERS = {
    "trg_catalog_platform_insert": """CREATE TRIGGER IF NOT EXISTS trg_catalog_platform_insert
        AFTER INSERT ON platforms BEGIN
        INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
        VALUES('platform', NEW.id, NEW.id, 'upsert', NEW.updated_at); END""",
    "trg_catalog_platform_update": """CREATE TRIGGER IF NOT EXISTS trg_catalog_platform_update
        AFTER UPDATE ON platforms BEGIN
        INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
        VALUES('platform', NEW.id, NEW.id, 'upsert', NEW.updated_at); END""",
    "trg_catalog_platform_delete": """CREATE TRIGGER IF NOT EXISTS trg_catalog_platform_delete
        AFTER DELETE ON platforms BEGIN
        INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
        VALUES('platform', OLD.id, OLD.id, 'delete', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')); END""",
    "trg_catalog_game_insert": """CREATE TRIGGER IF NOT EXISTS trg_catalog_game_insert
        AFTER INSERT ON games BEGIN
        INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
        VALUES('game', NEW.id, NEW.platform_id, 'upsert', NEW.updated_at); END""",
    "trg_catalog_game_update": """CREATE TRIGGER IF NOT EXISTS trg_catalog_game_update
        AFTER UPDATE ON games BEGIN
        INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
        VALUES('game', NEW.id, NEW.platform_id, 'upsert', NEW.updated_at); END""",
    "trg_catalog_game_delete": """CREATE TRIGGER IF NOT EXISTS trg_catalog_game_delete
        AFTER DELETE ON games BEGIN
        INSERT INTO catalog_changes(entity_type, entity_id, platform_id, operation, changed_at)
        VALUES('game', OLD.id, OLD.platform_id, 'delete', strftime('%Y-%m-%dT%H:%M:%SZ', 'now')); END""",
}


def _drop_local_catalog_triggers(connection: sqlite3.Connection) -> None:
    for trigger_name in _LOCAL_CATALOG_TRIGGERS:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")


def _restore_local_catalog_triggers(connection: sqlite3.Connection) -> None:
    for statement in _LOCAL_CATALOG_TRIGGERS.values():
        connection.execute(statement)


def _endpoint_url(action: str, **params: Any) -> str:
    base_url = str(getattr(config, "CATALOG_SYNC_URL", "") or "").strip()
    if not base_url:
        return ""
    query = {"action": action}
    query.update({key: value for key, value in params.items() if value is not None})
    separator = "&" if "?" in base_url else "?"
    return base_url + separator + urllib.parse.urlencode(query)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "RGSX-catalog-client",
    }


def _get_json(action: str, **params: Any) -> dict[str, Any]:
    url = _endpoint_url(action, **params)
    if not url:
        raise RuntimeError("RGSX_CATALOG_SYNC_URL is not configured")
    request = urllib.request.Request(url, headers=_headers(), method="GET")
    timeout = max(5, int(getattr(config, "CATALOG_SYNC_TIMEOUT_SEC", 30)))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw_payload = response.read(32 * 1024 * 1024 + 1)
    if len(raw_payload) > 32 * 1024 * 1024:
        raise RuntimeError("Catalog API response exceeds the 32 MiB page limit")
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Catalog API returned invalid JSON") from exc
    if not isinstance(payload, dict) or not payload.get("success", False):
        raise RuntimeError(str(payload.get("error", "Catalog sync request failed")))
    return payload


def _snapshot_pages(entity: str, page_size: int = 1000, platform_id: int | None = None):
    if entity == "platform_assets":
        page_size = min(page_size, 100)
    cursor = 0
    while True:
        parameters = {"entity": entity, "after": cursor, "limit": page_size}
        if platform_id is not None:
            parameters["platform_id"] = platform_id
        payload = _get_json("snapshot", **parameters)
        rows = payload.get("items")
        if not isinstance(rows, list):
            raise RuntimeError(f"Invalid {entity} snapshot page")
        next_cursor = int(payload.get("next_after") or cursor)
        if rows and next_cursor <= cursor:
            raise RuntimeError(f"{entity} snapshot cursor did not advance")
        if not rows and payload.get("has_more"):
            raise RuntimeError(f"{entity} snapshot returned an empty non-final page")
        yield rows
        if not payload.get("has_more"):
            return
        cursor = next_cursor


def _insert_snapshot_page(connection: sqlite3.Connection, entity: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    if entity == "platforms":
        connection.executemany(
            """INSERT INTO platforms(
                id, platform_name, source, file_name, folder, platform_image,
                sort_order, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                int(row.get("id") or 0), str(row.get("platform_name") or ""),
                str(row.get("source") or ""), str(row.get("file_name") or ""),
                str(row.get("folder") or ""), str(row.get("platform_image") or ""),
                int(row.get("sort_order") or 0), str(row.get("created_at") or ""),
                str(row.get("updated_at") or ""),
            ) for row in rows],
        )
        return
    if entity == "games":
        connection.executemany(
            """INSERT INTO games(
                id, platform_id, name, url, size, size_bytes, display_name,
                sort_order, metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                int(row.get("id") or 0), int(row.get("platform_id") or 0),
                str(row.get("name") or ""), str(row.get("url") or ""),
                str(row.get("size") or ""), row.get("size_bytes"),
                str(row.get("display_name") or ""), int(row.get("sort_order") or 0),
                str(row.get("metadata_json") or "{}"), str(row.get("created_at") or ""),
                str(row.get("updated_at") or ""),
            ) for row in rows],
        )
        return
    if entity == "platform_assets":
        try:
            connection.executemany(
                """INSERT INTO platform_assets(
                    id, platform_id, asset_type, file_name, mime_type, data,
                    metadata_json, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [(
                    int(row.get("id") or 0), int(row.get("platform_id") or 0),
                    str(row.get("asset_type") or ""), str(row.get("file_name") or ""),
                    str(row.get("mime_type") or "application/octet-stream"),
                    sqlite3.Binary(base64.b64decode(str(row.get("data_base64") or ""), validate=True)),
                    str(row.get("metadata_json") or "{}"), str(row.get("created_at") or ""),
                    str(row.get("updated_at") or ""),
                ) for row in rows],
            )
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Invalid base64 platform asset in catalog snapshot") from exc
        return
    raise RuntimeError(f"Unsupported catalog snapshot entity: {entity}")


def _replace_local_catalog_from_api(
    db_path: str,
    sequence: int,
    manifest: dict[str, Any] | None = None,
    progress_callback=None,
) -> dict[str, int]:
    database.initialize_database(db_path)
    manifest = manifest or {}
    counts = {"platforms": 0, "games": 0, "platform_assets": 0}
    progress_ranges = {
        "platforms": (5.0, 12.0, max(1, int(manifest.get("platforms") or 0))),
        "games": (12.0, 92.0, max(1, int(manifest.get("games") or 0))),
        "platform_assets": (92.0, 98.0, 1),
    }
    target_directory = os.path.dirname(os.path.abspath(db_path))
    with tempfile.TemporaryDirectory(prefix="rgsx-catalog-stage-", dir=target_directory) as staging_directory:
        staging_path = os.path.join(staging_directory, "catalog.sqlite3")
        staging = sqlite3.connect(staging_path, timeout=30.0)
        staging.row_factory = sqlite3.Row
        staging.execute("PRAGMA foreign_keys = ON")
        staging.executescript(database.SCHEMA_SQL)
        try:
            _drop_local_catalog_triggers(staging)
            staging.execute("BEGIN")
            for entity in ("platforms", "games", "platform_assets"):
                start_progress, end_progress, expected_count = progress_ranges[entity]
                _notify_progress(progress_callback, "sync_snapshot", start_progress, entity)
                for page in _snapshot_pages(entity):
                    _insert_snapshot_page(staging, entity, page)
                    counts[entity] += len(page)
                    entity_progress = min(1.0, counts[entity] / expected_count)
                    current_progress = start_progress + (end_progress - start_progress) * entity_progress
                    _notify_progress(
                        progress_callback,
                        "sync_snapshot",
                        current_progress,
                        f"{entity}:{counts[entity]}/{expected_count}",
                    )
            staging.commit()
        except Exception:
            staging.rollback()
            raise
        finally:
            staging.close()

        with database.connect(db_path) as connection:
            connection.execute("ATTACH DATABASE ? AS catalog_stage", (staging_path,))
            _drop_local_catalog_triggers(connection)
            try:
                connection.execute("BEGIN")
                connection.execute("DELETE FROM platform_assets")
                connection.execute("DELETE FROM games")
                connection.execute("DELETE FROM platforms")
                connection.execute("INSERT INTO platforms SELECT * FROM catalog_stage.platforms")
                connection.execute("INSERT INTO games SELECT * FROM catalog_stage.games")
                connection.execute("INSERT INTO platform_assets SELECT * FROM catalog_stage.platform_assets")
                connection.execute("DELETE FROM catalog_changes")
                connection.execute(
                    """INSERT INTO schema_meta(key, value) VALUES('catalog_sync_sequence', ?)
                       ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                    (str(max(0, int(sequence))),),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                _restore_local_catalog_triggers(connection)
                connection.execute("DETACH DATABASE catalog_stage")
        connection.close()
    return counts


def _sync_catalog_visibility(db_path: str, progress_callback=None) -> dict[str, int]:
    database.initialize_database(db_path)
    local_connection = database.connect(db_path)
    try:
        local_platform_ids = {
            int(row[0]) for row in local_connection.execute("SELECT id FROM platforms").fetchall()
        }
    finally:
        local_connection.close()

    counts = {"platforms": 0, "games": 0, "platform_assets": 0}
    target_directory = os.path.dirname(os.path.abspath(db_path))
    with tempfile.TemporaryDirectory(prefix="rgsx-catalog-visibility-", dir=target_directory) as staging_directory:
        staging_path = os.path.join(staging_directory, "catalog.sqlite3")
        staging = sqlite3.connect(staging_path, timeout=30.0)
        staging.row_factory = sqlite3.Row
        staging.execute("PRAGMA foreign_keys = ON")
        staging.executescript(database.SCHEMA_SQL)
        try:
            _drop_local_catalog_triggers(staging)
            staging.execute("BEGIN")
            remote_platforms: list[dict[str, Any]] = []
            for page in _snapshot_pages("platforms"):
                _insert_snapshot_page(staging, "platforms", page)
                remote_platforms.extend(page)
            remote_platform_ids = {int(row["id"]) for row in remote_platforms}
            new_platform_ids = sorted(remote_platform_ids - local_platform_ids)
            counts["platforms"] = len(remote_platforms)

            for platform_id in new_platform_ids:
                for entity in ("games", "platform_assets"):
                    for page in _snapshot_pages(entity, platform_id=platform_id):
                        _insert_snapshot_page(staging, entity, page)
                        counts[entity] += len(page)
            staging.commit()
        except Exception:
            staging.rollback()
            raise
        finally:
            staging.close()

        with database.connect(db_path) as connection:
            connection.execute("ATTACH DATABASE ? AS catalog_stage", (staging_path,))
            _drop_local_catalog_triggers(connection)
            try:
                connection.execute("BEGIN")
                connection.execute(
                    "DELETE FROM platforms WHERE id NOT IN (SELECT id FROM catalog_stage.platforms)"
                )
                connection.execute(
                    """INSERT INTO platforms
                       SELECT * FROM catalog_stage.platforms WHERE true
                       ON CONFLICT(id) DO UPDATE SET
                           platform_name=excluded.platform_name,
                           source=excluded.source,
                           file_name=excluded.file_name,
                           folder=excluded.folder,
                           platform_image=excluded.platform_image,
                           sort_order=excluded.sort_order,
                           created_at=excluded.created_at,
                           updated_at=excluded.updated_at"""
                )
                connection.execute("INSERT INTO games SELECT * FROM catalog_stage.games")
                connection.execute("INSERT INTO platform_assets SELECT * FROM catalog_stage.platform_assets")
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                _restore_local_catalog_triggers(connection)
                connection.execute("DETACH DATABASE catalog_stage")
        connection.close()
    _notify_progress(progress_callback, "sync_snapshot", 98, "platforms:1/1")
    return counts


def _apply_change(connection: sqlite3.Connection, change: dict[str, Any]) -> None:
    operation = str(change.get("operation") or "")
    entity_type = str(change.get("entity_type") or "")
    entity_id = int(change.get("entity_id") or 0)
    data = change.get("data")
    if entity_id <= 0:
        return

    if operation == "delete":
        table = (
            "platforms" if entity_type == "platform"
            else "games" if entity_type == "game"
            else "platform_assets" if entity_type == "platform_asset"
            else ""
        )
        if table:
            connection.execute(f"DELETE FROM {table} WHERE id = ?", (entity_id,))
        return

    if operation != "upsert" or not isinstance(data, dict):
        return

    if entity_type == "platform":
        connection.execute(
            """INSERT INTO platforms(
                id, platform_name, source, file_name, folder, platform_image,
                sort_order, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                platform_name=excluded.platform_name,
                source=excluded.source,
                file_name=excluded.file_name,
                folder=excluded.folder,
                platform_image=excluded.platform_image,
                sort_order=excluded.sort_order,
                updated_at=excluded.updated_at""",
            (
                entity_id,
                str(data.get("platform_name") or ""),
                str(data.get("source") or ""),
                str(data.get("file_name") or ""),
                str(data.get("folder") or ""),
                str(data.get("platform_image") or ""),
                int(data.get("sort_order") or 0),
                str(data.get("created_at") or ""),
                str(data.get("updated_at") or ""),
            ),
        )
    elif entity_type == "game":
        connection.execute(
            """INSERT INTO games(
                id, platform_id, name, url, size, size_bytes, display_name,
                sort_order, metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                platform_id=excluded.platform_id,
                name=excluded.name,
                url=excluded.url,
                size=excluded.size,
                size_bytes=excluded.size_bytes,
                display_name=excluded.display_name,
                sort_order=excluded.sort_order,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at""",
            (
                entity_id,
                int(data.get("platform_id") or change.get("platform_id") or 0),
                str(data.get("name") or ""),
                str(data.get("url") or ""),
                str(data.get("size") or ""),
                data.get("size_bytes"),
                str(data.get("display_name") or ""),
                int(data.get("sort_order") or 0),
                str(data.get("metadata_json") or "{}"),
                str(data.get("created_at") or ""),
                str(data.get("updated_at") or ""),
            ),
        )
    elif entity_type == "platform_asset":
        try:
            asset_data = base64.b64decode(str(data.get("data_base64") or ""), validate=True)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("Invalid base64 platform asset in catalog delta") from exc
        connection.execute(
            """INSERT INTO platform_assets(
                id, platform_id, asset_type, file_name, mime_type, data,
                metadata_json, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                platform_id=excluded.platform_id,
                asset_type=excluded.asset_type,
                file_name=excluded.file_name,
                mime_type=excluded.mime_type,
                data=excluded.data,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at""",
            (
                entity_id,
                int(data.get("platform_id") or change.get("platform_id") or 0),
                str(data.get("asset_type") or ""),
                str(data.get("file_name") or ""),
                str(data.get("mime_type") or "application/octet-stream"),
                sqlite3.Binary(asset_data),
                str(data.get("metadata_json") or "{}"),
                str(data.get("created_at") or ""),
                str(data.get("updated_at") or ""),
            ),
        )


def _local_catalog_counts(db_path: str) -> tuple[int, int]:
    database.initialize_database(db_path)
    with database.connect(db_path) as connection:
        platforms = int(connection.execute("SELECT COUNT(*) FROM platforms").fetchone()[0])
        games = int(connection.execute("SELECT COUNT(*) FROM games").fetchone()[0])
    return platforms, games


def _apply_changes(db_path: str, changes: list[dict[str, Any]], sequence: int) -> int:
    database.initialize_database(db_path)
    with database.connect(db_path) as connection:
        _drop_local_catalog_triggers(connection)
        connection.execute("BEGIN")
        try:
            for change in changes:
                _apply_change(connection, change)
            connection.execute(
                "INSERT INTO schema_meta(key, value) VALUES('catalog_sync_sequence', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(max(0, int(sequence))),),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            _restore_local_catalog_triggers(connection)
    return len(changes)


def _notify_progress(callback, stage: str, progress: float, detail: str = "") -> None:
    if callback is None:
        return
    try:
        callback(stage, max(0.0, min(100.0, float(progress))), detail)
    except Exception:
        pass


def sync_catalog(db_path: str | None = None, progress_callback=None) -> dict[str, Any]:
    """Synchronize only catalog tables from the HTTPS API; preserve local user state."""
    target = os.path.abspath(db_path or config.DB_PATH)
    database.initialize_database(target)
    manifest = _get_json("manifest")
    remote_sequence = int(manifest.get("sequence") or 0)
    remote_visibility_revision = int(manifest.get("visibility_revision") or 0)
    local_platforms, local_games = _local_catalog_counts(target)
    local_sequence = database.get_sync_cursor(target)
    local_visibility_revision = database.get_catalog_visibility_revision(target)

    full_snapshot = (
        local_sequence is None
        or local_sequence > remote_sequence
        or (
            local_visibility_revision is None
            and (int(manifest.get("platforms") or 0) > 0 or int(manifest.get("games") or 0) > 0)
        )
    )
    visibility_changed = local_visibility_revision != remote_visibility_revision
    if not visibility_changed:
        full_snapshot = full_snapshot or (
            (local_platforms == 0 and int(manifest.get("platforms") or 0) > 0)
            or (local_games == 0 and int(manifest.get("games") or 0) > 0)
        )
    if full_snapshot:
        _notify_progress(progress_callback, "sync_snapshot", 5, "platforms")
        snapshot_counts = _replace_local_catalog_from_api(
            target,
            remote_sequence,
            manifest=manifest,
            progress_callback=progress_callback,
        )
        current = remote_sequence
        mode = "https-full"
        _notify_progress(progress_callback, "sync_snapshot", 98, "changes")
        latest_manifest = _get_json("manifest")
        target_sequence = max(current, int(latest_manifest.get("sequence") or current))
        applied = 0
    else:
        current = local_sequence
        target_sequence = remote_sequence
        applied = 0
        if visibility_changed:
            _notify_progress(progress_callback, "sync_snapshot", 5, "platforms:0/1")
            snapshot_counts = _sync_catalog_visibility(target, progress_callback)
            mode = "https-visibility"
        else:
            snapshot_counts = {}
            mode = "https-incremental"

    while current < target_sequence:
        payload = _get_json("changes", since=current, limit=500)
        target_sequence = max(target_sequence, int(payload.get("sequence") or current))
        raw_changes = payload.get("changes") if isinstance(payload.get("changes"), list) else []
        changes = [item for item in raw_changes if isinstance(item, dict)]
        if not changes:
            latest_sequence = int(payload.get("sequence") or current)
            if latest_sequence > current:
                raise RuntimeError(f"Catalog API has a sequence gap after {current}")
            break
        next_sequence = max(int(change.get("sequence") or current) for change in changes)
        if next_sequence <= current:
            raise RuntimeError("Catalog API returned a non-advancing changes page")
        applied += _apply_changes(target, changes, next_sequence)
        current = next_sequence
        if payload.get("has_more"):
            continue
        if current < target_sequence:
            latest_manifest = _get_json("manifest")
            target_sequence = max(target_sequence, int(latest_manifest.get("sequence") or current))
            if current < target_sequence:
                continue
        break

    if database.get_sync_cursor(target) != current:
        database.set_sync_cursor(current, target)
    database.set_catalog_visibility_revision(remote_visibility_revision, target)
    _notify_progress(progress_callback, "sync_complete", 100, str(current))
    result = {
        "enabled": True,
        "mode": mode,
        "sequence": current,
        "applied": applied,
    }
    if snapshot_counts:
        result.update(snapshot_counts)
    return result

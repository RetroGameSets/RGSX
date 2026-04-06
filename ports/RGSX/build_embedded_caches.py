from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


_TORRENT_DOWNLOAD_SCHEME = "rgsx+torrent"


def _format_size_bytes(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def build_torrent_download_url(source_url: str, file_index: int, relative_path: str, size_bytes: int | None = None) -> str:
    params = {
        "source": source_url,
        "index": str(max(1, int(file_index))),
        "path": relative_path,
    }
    if isinstance(size_bytes, int) and size_bytes > 0:
        params["size"] = str(size_bytes)
    return f"{_TORRENT_DOWNLOAD_SCHEME}://download?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def get_clean_display_name(raw_name, platform_id=None):
    text = str(raw_name or "").strip()
    if not text:
        return ""

    normalized = text.replace("\\", "/")
    leaf_name = normalized.rsplit("/", 1)[-1]
    display_name = Path(leaf_name).stem.strip()

    prefixes = []
    if platform_id:
        prefixes.append(str(platform_id).strip())

    for prefix in prefixes:
        if not prefix:
            continue
        pattern = rf"^{re.escape(prefix)}[\s\-_:]+"
        updated_name = re.sub(pattern, "", display_name, flags=re.IGNORECASE).strip()
        if updated_name:
            display_name = updated_name

    return display_name.strip(" -_/")


def _decode_bencode_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    return str(value or "")


def _bdecode(data: bytes, index: int = 0):
    token = data[index:index + 1]
    if token == b"i":
        end = data.index(b"e", index)
        return int(data[index + 1:end]), end + 1
    if token == b"l":
        items = []
        index += 1
        while data[index:index + 1] != b"e":
            value, index = _bdecode(data, index)
            items.append(value)
        return items, index + 1
    if token == b"d":
        values = {}
        index += 1
        while data[index:index + 1] != b"e":
            key, index = _bdecode(data, index)
            value, index = _bdecode(data, index)
            values[key] = value
        return values, index + 1
    if token.isdigit():
        sep = data.index(b":", index)
        length = int(data[index:sep])
        start = sep + 1
        end = start + length
        return data[start:end], end
    raise ValueError(f"Invalid bencode token at offset {index}: {token!r}")


def is_torrent_manifest_url(url: str | None) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False
    return (parsed.path or "").lower().endswith(".torrent")


def _extract_torrent_source(item) -> tuple[str, str] | None:
    if isinstance(item, (list, tuple)):
        if len(item) < 2:
            return None
        source_name = str(item[0] or "").strip()
        source_url = item[1] if isinstance(item[1], str) else None
        if source_url and is_torrent_manifest_url(source_url):
            return source_name, source_url.strip()
        return None

    if isinstance(item, dict):
        source_url = item.get("torrent_url") or item.get("url") or item.get("download") or item.get("link")
        if not isinstance(source_url, str) or not source_url.strip():
            return None
        source_type = str(item.get("type") or item.get("source_type") or item.get("source") or "").strip().lower()
        if source_type == "torrent" or is_torrent_manifest_url(source_url):
            source_name = item.get("game_name") or item.get("name") or item.get("title") or item.get("game") or item.get("label")
            if not source_name:
                parsed = urllib.parse.urlparse(source_url)
                source_name = urllib.parse.unquote(Path(parsed.path).name)
            return str(source_name or "").strip(), source_url.strip()

    return None


def _extract_torrent_entries_from_bytes(payload: bytes, source_url: str) -> list[dict[str, str | int]]:
    torrent_data, _next_index = _bdecode(payload)
    if not isinstance(torrent_data, dict):
        raise ValueError("Torrent root metadata is not a dictionary")

    info = torrent_data.get(b"info")
    if not isinstance(info, dict):
        raise ValueError("Torrent metadata does not contain an info dictionary")

    entries: list[dict[str, str | int]] = []
    files = info.get(b"files")
    root_name = _decode_bencode_text(info.get(b"name.utf-8") or info.get(b"name") or "").strip()
    if isinstance(files, list):
        for file_index, file_entry in enumerate(files, start=1):
            if not isinstance(file_entry, dict):
                continue
            path_parts = file_entry.get(b"path.utf-8") or file_entry.get(b"path") or []
            if not isinstance(path_parts, list):
                continue
            parts = [_decode_bencode_text(part).strip() for part in path_parts]
            parts = [part for part in parts if part]
            if not parts:
                continue
            full_path = "/".join(parts)
            download_path = "/".join([part for part in [root_name, full_path] if part])
            entries.append(
                {
                    "name": parts[-1],
                    "path": full_path,
                    "download_path": download_path or full_path,
                    "index": file_index,
                    "size_bytes": int(file_entry.get(b"length") or 0),
                    "source_url": source_url,
                }
            )
    else:
        if root_name:
            entries.append(
                {
                    "name": root_name,
                    "path": root_name,
                    "download_path": root_name,
                    "index": 1,
                    "size_bytes": int(info.get(b"length") or 0),
                    "source_url": source_url,
                }
            )

    duplicate_names: dict[str, int] = {}
    for entry in entries:
        name = str(entry["name"])
        duplicate_names[name] = duplicate_names.get(name, 0) + 1

    for entry in entries:
        if duplicate_names.get(str(entry["name"]), 0) > 1:
            entry["name"] = str(entry["path"])

    return entries


def _fetch_torrent_entries(source_url: str) -> list[dict[str, str | int]]:
    request = urllib.request.Request(
        source_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    return _extract_torrent_entries_from_bytes(payload, source_url)


def _iter_game_rows(data):
    if isinstance(data, dict) and "games" in data:
        data = data["games"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []


def _build_platform_search_entries(
    rows,
    torrent_manifest_cache: dict[str, list[dict[str, str | int]]],
    warnings: list[str],
    platform_id: str,
) -> list[dict[str, str | int]]:
    indexed_entries: list[dict[str, str | int]] = []
    for item in rows:
        torrent_source = _extract_torrent_source(item)
        if torrent_source is not None:
            source_name, source_url = torrent_source
            entries = torrent_manifest_cache.get(source_url)
            if entries is None:
                try:
                    entries = _fetch_torrent_entries(source_url)
                    torrent_manifest_cache[source_url] = entries
                except Exception as exc:
                    warnings.append(f"{platform_id}: failed to build torrent cache for {source_name or source_url}: {exc}")
                    entries = []
            for entry in entries:
                game_name = str(entry.get("name") or "").strip()
                if not game_name:
                    continue
                size_bytes = int(entry.get("size_bytes") or 0)
                file_index = int(entry.get("index") or 1)
                relative_path = str(entry.get("download_path") or entry.get("path") or game_name)
                indexed_entries.append(
                    {
                        "platform_id": platform_id,
                        "game_name": game_name,
                        "display_name": get_clean_display_name(game_name, platform_id),
                        "url": build_torrent_download_url(source_url, file_index, relative_path, size_bytes),
                        "size": _format_size_bytes(size_bytes) if size_bytes > 0 else "",
                        "size_bytes": size_bytes,
                    }
                )
            continue

        if isinstance(item, dict):
            name = item.get("game_name") or item.get("name") or item.get("title") or item.get("game")
            if name:
                size = item.get("size") or item.get("filesize") or item.get("length") or ""
                indexed_entries.append(
                    {
                        "platform_id": platform_id,
                        "game_name": str(name),
                        "display_name": get_clean_display_name(name, platform_id),
                        "url": str(item.get("url") or item.get("download") or item.get("link") or item.get("href") or ""),
                        "size": str(size) if size else "",
                        "size_bytes": 0,
                    }
                )
            continue

        if isinstance(item, (list, tuple)):
            if len(item) > 0 and str(item[0] or "").strip():
                size = item[2] if len(item) > 2 and item[2] is not None else ""
                url = item[1] if len(item) > 1 and isinstance(item[1], str) else ""
                indexed_entries.append(
                    {
                        "platform_id": platform_id,
                        "game_name": str(item[0]),
                        "display_name": get_clean_display_name(item[0], platform_id),
                        "url": url,
                        "size": str(size) if size else "",
                        "size_bytes": 0,
                    }
                )
            continue

        if isinstance(item, str) and item.strip():
            indexed_entries.append(
                {
                    "platform_id": platform_id,
                    "game_name": item.strip(),
                    "display_name": get_clean_display_name(item, platform_id),
                    "url": "",
                    "size": "",
                    "size_bytes": 0,
                }
            )
            continue

        if item is not None:
            item_text = str(item)
            indexed_entries.append(
                {
                    "platform_id": platform_id,
                    "game_name": item_text,
                    "display_name": get_clean_display_name(item_text, platform_id),
                    "url": "",
                    "size": "",
                    "size_bytes": 0,
                }
            )

    return indexed_entries


def build_caches(games_dir: Path) -> tuple[dict[str, list[dict[str, str | int]]], dict[str, dict[str, str | int]], list[dict[str, str | int]], list[str]]:
    torrent_manifest_cache: dict[str, list[dict[str, str | int]]] = {}
    platform_count_cache: dict[str, dict[str, str | int]] = {}
    global_search_index: list[dict[str, str | int]] = []
    warnings: list[str] = []

    for game_file in sorted(games_dir.glob("*.json")):
        with game_file.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        rows = _iter_game_rows(data)
        platform_id = game_file.stem
        platform_entries = _build_platform_search_entries(rows, torrent_manifest_cache, warnings, platform_id)
        count = len(platform_entries)
        platform_count_cache[platform_id] = {
            "path": "",
            "mtime_ns": 0,
            "file_name": game_file.name,
            "size_bytes": game_file.stat().st_size,
            "count": int(count),
        }
        global_search_index.extend(platform_entries)

    return torrent_manifest_cache, platform_count_cache, global_search_index, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Build portable RGSX cache files from exported games JSONs.")
    parser.add_argument("--games-dir", required=True, help="Directory containing exported games/*.json files")
    parser.add_argument("--output-dir", required=True, help="Directory where cache JSON files will be written")
    args = parser.parse_args()

    games_dir = Path(args.games_dir)
    output_dir = Path(args.output_dir)
    if not games_dir.is_dir():
        print(json.dumps({"ok": False, "error": f"games directory not found: {games_dir}"}), file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        torrent_manifest_cache, platform_count_cache, global_search_index, warnings = build_caches(games_dir)
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1

    torrent_cache_path = output_dir / "torrent_manifest_cache.json"
    platform_count_cache_path = output_dir / "platform_games_count_cache.json"
    global_search_index_path = output_dir / "global_search_index.json"
    torrent_cache_payload = {"version": 1, "entries": torrent_manifest_cache}
    platform_count_payload = {"version": 2, "entries": platform_count_cache}
    global_search_payload = {"version": 1, "entries": global_search_index}

    torrent_cache_path.write_text(json.dumps(torrent_cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    platform_count_cache_path.write_text(json.dumps(platform_count_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    global_search_index_path.write_text(json.dumps(global_search_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "torrent_manifest_count": len(torrent_manifest_cache),
                "platform_count_entries": len(platform_count_cache),
                "global_search_entries": len(global_search_index),
                "torrent_cache_path": str(torrent_cache_path),
                "platform_count_cache_path": str(platform_count_cache_path),
                "global_search_index_path": str(global_search_index_path),
                "warnings": warnings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""Media Manager: bulk-download game images from ScreenScraper.fr into the local cache.

The UI only reads this module's state; all network work runs in a background thread.
Images: config.MEDIA_FOLDER/{platform_folder}/{game}.jpg (+ _ss / _logo)
"""
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

import config
import database
import screenscraper

logger = logging.getLogger(__name__)

QUEUE_VERSION = 1
# A game is dropped from the queue after this many failed attempts.
MAX_ATTEMPTS = 3
# Retries per game on network errors (waits: 1, 2, 4 s).
NETWORK_RETRIES = 3
# After this many consecutive games fail with network errors, the connection is considered down and the job pauses.
MAX_CONSECUTIVE_NETWORK_FAILURES = 3

# Profile -> media kinds to download. Missing "box" falls back to a screenshot (screenscraper.fetch_game_media).
PROFILES = {
    "default": ("box",),
    "max": ("box", "ss", "logo"),
}
MEDIA_SUFFIX = {"box": "", "ss": "_ss", "logo": "_logo"}
MEDIA_EXTENSIONS = (".jpg", ".png")


def _safe_part(text, max_length=120):
    """Safe file/folder name part: strips path separators, invalid characters and '..'."""
    text = os.path.basename(str(text or "").replace("\\", "/"))
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip().strip(".")
    return text[:max_length].rstrip() or "game"


def media_path(folder, rom_filename, kind="box", ext=".jpg"):
    stem = _safe_part(os.path.splitext(os.path.basename(str(rom_filename or "")))[0])
    return os.path.join(config.MEDIA_FOLDER, _safe_part(folder), f"{stem}{MEDIA_SUFFIX[kind]}{ext}")


def find_media(folder, rom_filename, kind="box"):
    """Return the image path on disk, or None. The UI only uses this (no network)."""
    for ext in MEDIA_EXTENSIONS:
        path = media_path(folder, rom_filename, kind, ext)
        if os.path.isfile(path):
            return path
    return None


def _atomic_write_bytes(path, payload):
    """Write to .tmp first, then rename: no partial files are left behind."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as handle:
        handle.write(payload)
    os.replace(tmp_path, path)


def save_media(folder, rom_filename, kind, media):
    """Persist one validated ScreenScraper media payload in the shared local cache."""
    payload, ext = media
    ext = str(ext or ".jpg").lower().replace(".jpeg", ".jpg")
    if not isinstance(payload, bytes) or not payload:
        raise screenscraper.ScreenScraperError("http", "invalid image payload")
    path = media_path(folder, rom_filename, kind, ext if ext in MEDIA_EXTENSIONS else ".jpg")
    _atomic_write_bytes(path, payload)
    return path


def load_queue():
    try:
        with open(config.MEDIA_QUEUE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            data.setdefault("not_found", [])
            return data
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"Could not read media queue: {exc}")
    return {"version": QUEUE_VERSION, "created_at": "", "profile": "default", "items": [], "not_found": []}


def save_queue(profile, items, not_found):
    data = {
        "version": QUEUE_VERSION,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "profile": profile,
        "items": items,
        # Not-found games are kept so they are not queried again (saves quota).
        "not_found": not_found,
    }
    try:
        _atomic_write_bytes(config.MEDIA_QUEUE_PATH, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    except Exception as exc:
        logger.error(f"Could not write media queue: {exc}")


class MediaManager:
    def __init__(self):
        self.profile = "default"
        self.selected = set()  # selected platform folders
        self.thread = None
        self.cancel_event = threading.Event()
        self.progress = {"done": 0, "total": 0, "found": 0, "not_found": 0, "errors": 0}
        # Status shown in the UI: (translation key, format args) or None
        self.status = None
        self.allowance = None  # (remaining_today, max_per_day)
        self.account_configured = False
        self.platforms = []
        self.pending = 0  # number of games waiting in the queue

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    def list_platforms(self):
        """Group platforms by folder: different sources sharing a folder become one row."""
        try:
            counts = database.list_game_counts(config.DB_PATH)
        except Exception as exc:
            logger.warning(f"Could not read game counts: {exc}")
            counts = {}
        groups = {}
        for entry in getattr(config, "platform_dicts", []) or []:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("platform_name") or "").strip()
            folder = str(entry.get("folder") or "").strip()
            if not name or not folder:
                continue
            group = groups.setdefault(folder, {"folder": folder, "label": "", "platform_names": [], "platform_id": None, "count": 0})
            group["platform_names"].append(name)
            group["count"] += counts.get(name, 0)
            if not group["label"]:
                group["label"] = screenscraper.normalize_platform_name(name) or name
            configured_id = screenscraper.get_configured_system_id(name)
            if configured_id is not None:
                group["platform_id"] = configured_id
            elif group["platform_id"] is None:
                group["platform_id"] = screenscraper.get_system_id(name)
        return sorted(groups.values(), key=lambda g: g["label"].lower())

    def open(self):
        """On page open: read platforms and queue once (avoid DB/file reads every frame)."""
        self.platforms = self.list_platforms()
        self.pending = len(load_queue()["items"])
        username, password = screenscraper.load_account()
        self.account_configured = bool(username.strip() and password)
        self.status = None
        if not self.account_configured:
            self.allowance = None
            self.status = ("media_account_required", ())
            return
        self.allowance = screenscraper.LAST_ALLOWANCE or self.allowance
        threading.Thread(target=self._refresh_allowance, daemon=True).start()
        if screenscraper.system_catalog_cache_is_stale():
            threading.Thread(target=self._refresh_systems, daemon=True).start()

    def _refresh_systems(self):
        try:
            screenscraper.refresh_system_catalog()
        except screenscraper.ScreenScraperError as exc:
            logger.warning("Could not refresh ScreenScraper systems: %s (%s)", exc.kind, exc)
            self.status = (
                ("screenscraper_proxy_outdated", ())
                if exc.kind == "proxy"
                else ("media_error", (exc.kind,))
            )
        else:
            self.platforms = self.list_platforms()
        config.needs_redraw = True

    def _refresh_allowance(self):
        try:
            self.allowance = screenscraper.get_user_info()
        except screenscraper.ScreenScraperError as exc:
            logger.warning(f"Could not read ScreenScraper quota: {exc.kind} ({exc})")
            error_keys = {
                "account_required": "media_account_required",
                "auth": "screenscraper_login_failed",
                "quota": "media_quota_exhausted",
                "rate_limited": "media_rate_limited",
            }
            if exc.kind in error_keys:
                self.status = (error_keys[exc.kind], ())
        config.needs_redraw = True

    def rows(self):
        rows = [("action", None)]
        if self.account_configured and self.pending and not self.running:
            rows.append(("resume", None))
        rows += [("profile", None), ("select_all", None)]
        return rows + [("platform", group) for group in self.platforms]

    def toggle_all(self):
        supported = {g["folder"] for g in self.platforms if g["platform_id"]}
        self.selected = set() if supported <= self.selected else supported

    def estimate(self):
        """(selected game count, requests per game, games the quota covers or None).

        Requests per game: jeuInfos = 1 for every profile (it returns all media URLs).
        Media downloads are assumed not to count against the daily quota.
        """
        games = sum(g["count"] for g in self.platforms if g["folder"] in self.selected and g["platform_id"])
        per_game = 1
        capacity = self.allowance[0] // per_game if self.allowance else None
        return games, per_game, capacity

    def start(self, resume=False):
        if self.running:
            return
        username, password = screenscraper.load_account()
        if not username.strip() or not password:
            self.account_configured = False
            self.allowance = None
            self.status = ("media_account_required", ())
            config.needs_redraw = True
            return
        self.account_configured = True
        self.cancel_event.clear()
        self.status = None
        self.progress = {"done": 0, "total": 0, "found": 0, "not_found": 0, "errors": 0}
        self.thread = threading.Thread(target=self._run, args=(resume,), daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()

    def _build_items(self, platforms):
        queue = load_queue()
        not_found = {(item.get("platform"), item.get("rom_filename")) for item in queue["not_found"]}
        kinds = PROFILES[self.profile]
        items = []
        for group in platforms:
            if group["folder"] not in self.selected or not group["platform_id"]:
                continue
            seen = set()
            for platform_name in group["platform_names"]:
                for row in database.list_games(platform_name, config.DB_PATH):
                    rom_filename = str(row.get("name") or "")
                    key = (group["folder"], rom_filename)
                    if not rom_filename or rom_filename in seen or key in not_found:
                        continue
                    seen.add(rom_filename)
                    if all(find_media(group["folder"], rom_filename, kind) for kind in kinds):
                        continue
                    items.append({
                        "platform": group["folder"],
                        "game_name": str(row.get("display_name") or rom_filename),
                        "rom_filename": rom_filename,
                        "attempts": 0,
                        "last_error": "",
                    })
        return items

    def _download(self, media, folder, rom_filename, kind):
        save_media(folder, rom_filename, kind, media)

    def _process_item(self, item, platform_id):
        """Process one game. Returns 'found' | 'not_found'. Retries with backoff on network errors."""
        kinds = PROFILES[self.profile]
        for attempt in range(NETWORK_RETRIES):
            try:
                urls = screenscraper.fetch_game_media(item["rom_filename"], platform_id, kinds)
                if not urls:
                    return "not_found"
                for kind in kinds:
                    if urls.get(kind) and not find_media(item["platform"], item["rom_filename"], kind):
                        self._download(urls[kind], item["platform"], item["rom_filename"], kind)
                return "found"
            except screenscraper.ScreenScraperError as exc:
                error = exc
            if error.kind != "network" or attempt == NETWORK_RETRIES - 1:
                raise error
            if self.cancel_event.wait(2 ** attempt):
                raise error

    def _run(self, resume):
        queue = load_queue()
        not_found = list(queue["not_found"])
        try:
            platforms = self.list_platforms()
            platform_ids = {group["folder"]: group["platform_id"] for group in platforms}
            if resume:
                self.profile = queue.get("profile") if queue.get("profile") in PROFILES else "default"
                items = list(queue["items"])
            else:
                items = self._build_items(platforms)
        except Exception as exc:
            logger.error(f"Could not build media list: {exc}", exc_info=True)
            self.status = ("media_error", (str(exc),))
            config.needs_redraw = True
            return

        self.progress["total"] = len(items)
        logger.info(f"Media download started: {len(items)} games, profile={self.profile}")
        failed = []
        consecutive_network_failures = 0
        index = 0
        while index < len(items):
            if self.cancel_event.is_set():
                self.status = ("media_cancelled", ())
                break
            item = items[index]
            try:
                platform_id = platform_ids.get(item["platform"])
                if not platform_id:
                    raise screenscraper.ScreenScraperError("unsupported", item["platform"])
                result = self._process_item(item, platform_id)
                consecutive_network_failures = 0
                if result == "found":
                    self.progress["found"] += 1
                else:
                    self.progress["not_found"] += 1
                    not_found.append({"platform": item["platform"], "rom_filename": item["rom_filename"]})
                    logger.info(f"Media not found: {item['platform']}/{item['rom_filename']}")
            except screenscraper.ScreenScraperError as exc:
                if exc.kind in ("quota", "rate_limited", "auth", "account_required"):
                    # Stop and preserve the current item when the service limits or rejects the request.
                    if exc.kind == "quota":
                        self.status = ("media_quota_exhausted", ())
                    elif exc.kind == "rate_limited":
                        self.status = ("media_rate_limited", ())
                    elif exc.kind == "account_required":
                        self.status = ("media_account_required", ())
                    else:
                        self.status = ("media_auth_error", ())
                    logger.warning(f"ScreenScraper {exc.kind} error ({exc}), download paused")
                    break
                if exc.kind == "network":
                    consecutive_network_failures += 1
                item["attempts"] = int(item.get("attempts") or 0) + 1
                item["last_error"] = f"{exc.kind}: {exc}"
                self.progress["errors"] += 1
                logger.warning(f"Media error {item['platform']}/{item['rom_filename']}: {item['last_error']}")
                if item["attempts"] < MAX_ATTEMPTS:
                    failed.append(item)
                if consecutive_network_failures >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                    self.status = ("media_network_paused", ())
                    index += 1
                    break
            except Exception as exc:
                # An unexpected error only affects this game; the batch continues.
                item["attempts"] = int(item.get("attempts") or 0) + 1
                item["last_error"] = str(exc)
                self.progress["errors"] += 1
                logger.error(f"Could not process media {item['rom_filename']}: {exc}", exc_info=True)
                if item["attempts"] < MAX_ATTEMPTS:
                    failed.append(item)
            index += 1
            self.progress["done"] = index
            config.needs_redraw = True

        remaining = failed + items[index:]
        save_queue(self.profile, remaining, not_found)
        self.pending = len(remaining)
        if self.status is None:
            self.status = ("media_done", ())
        self.allowance = screenscraper.LAST_ALLOWANCE or self.allowance
        import preview  # "no image" entries in the preview cache may now be stale
        preview.clear_cache()
        logger.info(f"Media download finished: {self.progress}, {len(remaining)} games queued")
        config.needs_redraw = True


manager = MediaManager()

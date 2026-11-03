"""Media Manager: bulk-download game images from ScreenScraper.fr into the local cache.

The UI only reads this module's state; all network work runs in a background thread.
Images: config.MEDIA_FOLDER/{platform_folder}/{game}.jpg (+ _ss)
"""
import io
import errno
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone

import pygame

import config
import database
import screenscraper
from rgsx_settings import is_screenscraper_disabled

logger = logging.getLogger(__name__)

QUEUE_VERSION = 1
# A game is dropped from the queue after this many failed attempts.
MAX_ATTEMPTS = 3
# Retries per game on network errors (waits: 1, 2, 4 s).
NETWORK_RETRIES = 3
# After this many consecutive games fail with network errors, the connection is considered down and the job pauses.
MAX_CONSECUTIVE_NETWORK_FAILURES = 3
QUEUE_CHECKPOINT_INTERVAL = 25

# Profile -> media kinds to download. Missing "box" falls back to a screenshot (screenscraper.fetch_game_media).
PROFILES = {
    "default": ("box",),
    "max": ("box", "ss"),
}
# Profiles that also need the ScreenScraper summary stored locally.
PROFILES_WITH_SUMMARY = {"max"}
MEDIA_SUFFIX = {"box": "", "ss": "_ss"}
# Stored flag that tells a kind is absent on ScreenScraper, so a missing file is final.
CHECKED_FLAG = {"box": "cover_checked", "ss": "screenshot_checked"}
MEDIA_EXTENSIONS = (".jpg", ".png")
MEDIA_PRESENCE_TTL_SEC = 5
MEDIA_PRESENCE_CACHE_SIZE = 4096
_media_write_lock = threading.Lock()
_media_presence_lock = threading.Lock()
_media_presence_cache = OrderedDict()


def _acquire_media_job_lock():
    lock_path = config.MEDIA_QUEUE_PATH + ".lock"
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    handle = open(lock_path, "a+b")
    if os.fstat(handle.fileno()).st_size == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if isinstance(exc, BlockingIOError) or exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
            return None
        raise
    return handle


def media_job_running_elsewhere():
    """Return whether another RGSX process currently owns the media queue."""
    handle = _acquire_media_job_lock()
    if handle is None:
        return True
    handle.close()
    return False


def acquire_media_job_lock():
    """Acquire the shared media-job lock, or return None when another process owns it."""
    return _acquire_media_job_lock()


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


def local_media_names(folder, rom_filenames, kind="box"):
    """Return the requested ROM names with an image of kind already in the local cache."""
    suffix = MEDIA_SUFFIX[kind]
    directory = os.path.join(config.MEDIA_FOLDER, _safe_part(folder))
    try:
        filenames = set(os.listdir(directory))
    except FileNotFoundError:
        return set()

    present = set()
    for rom_filename in rom_filenames:
        rom_name = str(rom_filename or "")
        stem = _safe_part(os.path.splitext(os.path.basename(rom_name))[0])
        if any(f"{stem}{suffix}{ext}" in filenames for ext in MEDIA_EXTENSIONS):
            present.add(rom_name)
    return present


def _remember_media_presence(folder, rom_filename, present):
    key = (str(folder or ""), str(rom_filename or ""))
    with _media_presence_lock:
        _media_presence_cache[key] = (time.monotonic(), bool(present))
        _media_presence_cache.move_to_end(key)
        while len(_media_presence_cache) > MEDIA_PRESENCE_CACHE_SIZE:
            _media_presence_cache.popitem(last=False)


def has_local_media(folder, rom_filename):
    """Return whether a game has a cached image, memoizing filesystem checks briefly for UI redraws."""
    key = (str(folder or ""), str(rom_filename or ""))
    now = time.monotonic()
    with _media_presence_lock:
        cached = _media_presence_cache.get(key)
        if cached and now - cached[0] < MEDIA_PRESENCE_TTL_SEC:
            _media_presence_cache.move_to_end(key)
            return cached[1]
    present = bool(find_media(folder, rom_filename, "box") or find_media(folder, rom_filename, "ss"))
    _remember_media_presence(folder, rom_filename, present)
    return present


def local_game(folder, rom_filename, system_id, kinds, need_summary=False):
    """Answer from disk and SQLite only, before any ScreenScraper request.

    Returns {"found", "summary", "media": {kind: path}} when every requested kind is either on disk
    or marked as absent on ScreenScraper, and the summary is stored when requested.
    Returns None when ScreenScraper must still be asked.
    """
    record = screenscraper.cached_game_info(rom_filename, system_id)
    if record is not None and not record["found"]:
        return {"found": False, "summary": "", "media": {}}
    if need_summary and record is None:
        return None
    media = {}
    for kind in kinds:
        path = find_media(folder, rom_filename, kind)
        if path:
            media[kind] = path
        elif not (record and record[CHECKED_FLAG[kind]]):
            return None
    return {"found": True, "summary": record["summary"] if record else "", "media": media}


def _atomic_write_bytes(path, payload):
    """Write to .tmp first, then rename: no partial files are left behind."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, "wb") as handle:
        handle.write(payload)
    os.replace(tmp_path, path)


def _png_to_jpg(payload, path):
    """Re-encode PNG bytes as JPEG at path with pygame (no Pillow needed). Transparent pixels become black.

    Returns False and leaves no file behind when the conversion fails.
    """
    tmp_path = path + ".tmp.jpg"
    try:
        image = pygame.image.load(io.BytesIO(payload), "image.png")
        flat = pygame.Surface(image.get_size())
        flat.fill((0, 0, 0))
        flat.blit(image, (0, 0))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pygame.image.save(flat, tmp_path)
        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        logger.debug("PNG to JPEG conversion failed: %s", exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return False


def save_media(folder, rom_filename, kind, media):
    """Persist one validated ScreenScraper media payload in the shared local cache. PNG is stored as JPEG when possible."""
    payload, ext = media
    ext = str(ext or ".jpg").lower().replace(".jpeg", ".jpg")
    if not isinstance(payload, bytes) or not payload:
        raise screenscraper.ScreenScraperError("http", "invalid image payload")
    with _media_write_lock:
        if ext == ".png":
            jpg_path = media_path(folder, rom_filename, kind, ".jpg")
            if _png_to_jpg(payload, jpg_path):
                _remember_media_presence(folder, rom_filename, True)
                return jpg_path
        path = media_path(folder, rom_filename, kind, ext if ext in MEDIA_EXTENSIONS else ".jpg")
        _atomic_write_bytes(path, payload)
        _remember_media_presence(folder, rom_filename, True)
        return path


def convert_png_cache(root=None):
    """Convert every cached PNG under root to JPEG, then delete the PNG. Returns (converted, failed).

    A PNG whose JPEG already exists is only deleted, since find_media() already prefers the JPEG.
    """
    root = root or config.MEDIA_FOLDER
    converted = failed = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".png"):
                continue
            png_path = os.path.join(dirpath, name)
            jpg_path = os.path.splitext(png_path)[0] + ".jpg"
            try:
                if os.path.exists(jpg_path):
                    os.remove(png_path)
                    converted += 1
                    continue
                with open(png_path, "rb") as handle:
                    payload = handle.read()
                if _png_to_jpg(payload, jpg_path):
                    os.remove(png_path)
                    converted += 1
                else:
                    failed += 1
            except OSError as exc:
                logger.debug("PNG cache conversion skipped %s: %s", png_path, exc)
                failed += 1
    return converted, failed


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
        return True
    except Exception as exc:
        logger.error("Could not write media queue: %s", exc, exc_info=True)
        return False


class MediaManager:
    def __init__(self):
        self.profile = "default"
        self.selected = set()  # selected platform folders
        self.thread = None
        self.cancel_event = threading.Event()
        self.progress = {"done": 0, "total": 0, "found": 0, "not_found": 0, "errors": 0}
        # Status shown in the UI: (translation key, format args) or None
        self.status = None
        self.active = {}
        self._state_lock = threading.Lock()
        self.allowance = None  # (remaining_today, max_per_day)
        self.max_threads = None
        self.thread_limit_ready = threading.Event()
        self._thread_limit_lock = threading.Lock()
        self._pending_start = None
        self.toast_notification = None
        self.toast_start_time = 0
        self.toast_duration = 3500
        self.toast_until = 0
        self.account_configured = False
        self.platforms = []
        self.media_counts_ready = False
        self._platforms_lock = threading.Lock()
        self.pending = 0  # number of games waiting in the queue

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive())

    @property
    def active_games(self):
        with self._state_lock:
            return list(self.active.values())

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
        already_running = self.running
        with self._platforms_lock:
            self.platforms = self.list_platforms()
            self.media_counts_ready = False
        self.pending = len(load_queue()["items"])
        username, password = screenscraper.load_account()
        self.account_configured = bool(username.strip() and password)
        logger.info("Media Manager opened (ScreenScraper account configured: %s)", self.account_configured)
        self.status = None
        threading.Thread(target=self._refresh_media_counts, daemon=True).start()
        if not self.account_configured:
            self.allowance = None
            self.max_threads = None
            self.thread_limit_ready.set()
            self.status = ("media_account_required", ())
            return
        self.allowance = screenscraper.LAST_ALLOWANCE or self.allowance
        if not already_running:
            with self._thread_limit_lock:
                self.max_threads = None
                self._pending_start = None
                self.thread_limit_ready.clear()
            threading.Thread(target=self._refresh_allowance, daemon=True).start()
        if screenscraper.system_catalog_cache_is_stale():
            threading.Thread(target=self._refresh_systems, daemon=True).start()

    def _refresh_systems(self):
        try:
            screenscraper.refresh_system_catalog()
        except screenscraper.ScreenScraperError as exc:
            logger.warning("Could not refresh ScreenScraper systems: %s (%s)", exc.kind, exc)
            self.status = ("media_error", (exc.kind,))
        else:
            with self._platforms_lock:
                self.platforms = self.list_platforms()
                self.media_counts_ready = False
            self._refresh_media_counts()
        config.needs_redraw = True

    def _refresh_media_counts(self):
        """Count catalog games with locally cached images without blocking the menu."""
        with self._platforms_lock:
            platforms = [dict(group) for group in self.platforms]
        queued_not_found = {
            (str(item.get("platform") or ""), str(item.get("rom_filename") or ""))
            for item in load_queue()["not_found"]
            if isinstance(item, dict)
        }
        media_counts = {}
        try:
            for group in platforms:
                available_stems = set()
                available_cover_stems = set()
                media_dir = os.path.join(config.MEDIA_FOLDER, _safe_part(group["folder"]))
                try:
                    with os.scandir(media_dir) as entries:
                        for entry in entries:
                            if not entry.is_file() or not entry.name.lower().endswith(MEDIA_EXTENSIONS):
                                continue
                            stem = os.path.splitext(entry.name)[0]
                            is_screenshot = stem.lower().endswith(MEDIA_SUFFIX["ss"])
                            if is_screenshot:
                                stem = stem[:-len(MEDIA_SUFFIX["ss"])]
                            available_stems.add(stem.casefold())
                            if not is_screenshot:
                                available_cover_stems.add(stem.casefold())
                except FileNotFoundError:
                    pass

                seen = set()
                scraped = 0
                not_found = 0
                missing_cover = 0
                for platform_name in group["platform_names"]:
                    for row in database.list_games(platform_name, config.DB_PATH):
                        rom_filename = str(row.get("name") or "")
                        if not rom_filename or rom_filename in seen:
                            continue
                        seen.add(rom_filename)
                        stem = _safe_part(os.path.splitext(os.path.basename(rom_filename))[0]).casefold()
                        if stem in available_stems:
                            scraped += 1
                        if stem not in available_cover_stems and (group["folder"], rom_filename) in queued_not_found:
                            not_found += 1
                        elif stem not in available_cover_stems:
                            missing_cover += 1
                media_counts[group["folder"]] = {
                    "count": len(seen),
                    "scraped_count": scraped,
                    "not_found_count": not_found,
                    "missing_count": missing_cover,
                }
        except Exception as exc:
            logger.warning("Could not count locally scraped games: %s", exc, exc_info=True)
            if self.status is None or self.status[0] == "media_done":
                self.status = ("media_error", (str(exc),))
            config.needs_redraw = True
            return

        with self._platforms_lock:
            self.platforms = [
                {**group, **media_counts.get(group["folder"], {})}
                for group in self.platforms
            ]
            self.media_counts_ready = True
        config.needs_redraw = True

    def _refresh_allowance(self):
        error = None
        try:
            self.allowance = screenscraper.get_user_info()
            self.max_threads = screenscraper.MAX_THREADS
            if not isinstance(self.max_threads, int) or self.max_threads < 1:
                logger.error("ScreenScraper user info did not contain a valid maxthreads value")
                self.max_threads = None
                self.status = ("media_threads_unavailable", ())
        except screenscraper.ScreenScraperError as exc:
            logger.warning(f"Could not read ScreenScraper quota: {exc.kind} ({exc})")
            error_keys = {
                "account_required": "media_account_required",
                "auth": "screenscraper_login_failed",
                "quota": "media_quota_exhausted",
                "rate_limited": "media_rate_limited",
            }
            error = (error_keys.get(exc.kind, "media_error"), (exc.kind,))
            self.max_threads = None
        except Exception as exc:
            logger.exception("Could not verify the ScreenScraper thread limit")
            error = ("media_error", (str(exc),))
            self.max_threads = None
        finally:
            with self._thread_limit_lock:
                self.thread_limit_ready.set()
                pending_start = self._pending_start
                self._pending_start = None
            if error:
                self.status = error
            if pending_start is not None:
                if self.max_threads:
                    self.start(resume=pending_start)
                elif self.status is None:
                    self.status = ("media_threads_unavailable", ())
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
        """Return missing games, API requests per game, and games covered by the quota."""
        games = 0
        for group in self.platforms:
            if group["folder"] not in self.selected or not group["platform_id"]:
                continue
            if self.media_counts_ready and self.profile == "default":
                games += group.get("missing_count", group["count"])
            else:
                games += group["count"]
        per_game = 1
        capacity = self.allowance[0] // per_game if self.allowance else None
        return games, per_game, capacity

    def start(self, resume=False):
        if self.running or is_screenscraper_disabled():
            return
        username, password = screenscraper.load_account()
        if not username.strip() or not password:
            self.account_configured = False
            self.allowance = None
            self.status = ("media_account_required", ())
            config.needs_redraw = True
            return
        self.account_configured = True
        with self._thread_limit_lock:
            if not self.thread_limit_ready.is_set():
                self._pending_start = resume
                self.status = ("media_threads_loading", ())
                config.needs_redraw = True
                return
            if not isinstance(self.max_threads, int) or self.max_threads < 1:
                if self.status is None or self.status[0] == "media_threads_loading":
                    self.status = ("media_threads_unavailable", ())
                config.needs_redraw = True
                return
            self.cancel_event.clear()
            self.status = None
            self.toast_notification = None
            self.toast_start_time = 0
            self.toast_until = 0
            self.progress = {"done": 0, "total": 0, "found": 0, "not_found": 0, "errors": 0}
            self.thread = threading.Thread(target=self._run_with_notification, args=(resume,), daemon=True)
            self.thread.start()

    def _finish_notification(self):
        status_key = self.status[0] if self.status else None
        if status_key == "media_job_busy":
            self.toast_notification = ("media_toast_busy", ())
        elif self.progress["total"]:
            toast_key = "media_toast_done" if status_key == "media_done" else "media_toast_stopped"
            self.toast_notification = (toast_key, (self.progress["done"], self.progress["total"]))
        else:
            return
        self.toast_start_time = pygame.time.get_ticks()
        self.toast_until = self.toast_start_time + self.toast_duration
        config.needs_redraw = True

    def _run_with_notification(self, resume):
        try:
            lock_handle = _acquire_media_job_lock()
        except OSError as exc:
            logger.exception("Could not lock the media queue")
            self.status = ("media_error", (str(exc),))
            self._finish_notification()
            return
        if lock_handle is None:
            self.status = ("media_job_busy", ())
            self._finish_notification()
            return
        try:
            self._run(resume)
        except Exception as exc:
            logger.exception("Media scraping stopped unexpectedly")
            self.status = ("media_error", (str(exc),))
        finally:
            lock_handle.close()
            self._finish_notification()

    def cancel(self):
        self.cancel_event.set()

    def _persist_queue(self, items, not_found):
        if save_queue(self.profile, items, not_found):
            if self.status and self.status[0] == "media_queue_save_error":
                self.status = None
            return True
        self.status = ("media_queue_save_error", ())
        config.needs_redraw = True
        return False

    def _build_items(self, platforms):
        queue = load_queue()
        not_found = {(item.get("platform"), item.get("rom_filename")) for item in queue["not_found"]}
        kinds = PROFILES[self.profile]
        need_summary = self.profile in PROFILES_WITH_SUMMARY
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
                    if local_game(group["folder"], rom_filename, group["platform_id"], kinds, need_summary) is not None:
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
        need_summary = self.profile in PROFILES_WITH_SUMMARY
        for attempt in range(NETWORK_RETRIES):
            local = local_game(item["platform"], item["rom_filename"], platform_id, kinds, need_summary)
            if local is not None:
                self._set_current_found(item, platform_id)
                return "found" if local["found"] else "not_found"
            try:
                urls = screenscraper.fetch_game_media(item["rom_filename"], platform_id, kinds, origin="media manager")
                if urls is None:
                    self._set_current_found(item, platform_id)
                    return "not_found"
                for kind in kinds:
                    if urls.get(kind) and not find_media(item["platform"], item["rom_filename"], kind):
                        self._download(urls[kind], item["platform"], item["rom_filename"], kind)
                    self._set_current_found(item, platform_id)
                return "found"
            except screenscraper.ScreenScraperError as exc:
                error = exc
            if error.kind != "network" or attempt == NETWORK_RETRIES - 1:
                raise error
            if self.cancel_event.wait(2 ** attempt):
                raise error

    def _set_current_found(self, item, platform_id):
        """Record what a worker has found on disk for this game."""
        found = {kind: int(find_media(item["platform"], item["rom_filename"], kind) is not None) for kind in PROFILES[self.profile]}
        if self.profile in PROFILES_WITH_SUMMARY:
            record = screenscraper.cached_game_info(item["rom_filename"], platform_id)
            found["summary"] = int(bool(record and record["found"] and record["summary"]))
        key = (item["platform"], item["rom_filename"])
        with self._state_lock:
            self.active[key] = {"game": item["game_name"], "found": found}
        config.needs_redraw = True

    def _process_tracked_item(self, item, platform_id):
        key = (item["platform"], item["rom_filename"])
        with self._state_lock:
            self.active[key] = {"game": item["game_name"], "found": None}
        config.needs_redraw = True
        try:
            return self._process_item(item, platform_id)
        finally:
            with self._state_lock:
                self.active.pop(key, None)
            config.needs_redraw = True

    def _run(self, resume):
        worker_limit = self.max_threads
        if not isinstance(worker_limit, int) or worker_limit < 1:
            self.status = ("media_threads_unavailable", ())
            config.needs_redraw = True
            return
        queue = load_queue()
        not_found = list(queue["not_found"])
        try:
            platforms = self.list_platforms()
            platform_ids = {group["folder"]: group["platform_id"] for group in platforms}
            if resume:
                self.profile = queue.get("profile") if queue.get("profile") in PROFILES else "default"
                items = []
                seen = set()
                for item in queue["items"]:
                    if not isinstance(item, dict):
                        continue
                    key = (str(item.get("platform") or ""), str(item.get("rom_filename") or ""))
                    if not all(key) or key in seen:
                        continue
                    seen.add(key)
                    items.append(item)
            else:
                items = self._build_items(platforms)
        except Exception as exc:
            logger.error(f"Could not build media list: {exc}", exc_info=True)
            self.status = ("media_error", (str(exc),))
            config.needs_redraw = True
            return

        self.progress["total"] = len(items)
        logger.info(f"Media download started: {len(items)} games, profile={self.profile}, {screenscraper.quota_summary()}")
        pending_items = list(items)
        if not self._persist_queue(pending_items, not_found):
            self.pending = len(pending_items)
            return
        failed = []
        paused_items = []
        consecutive_network_failures = 0
        stop_submitting = False
        since_checkpoint = 0
        with ThreadPoolExecutor(max_workers=worker_limit, thread_name_prefix="rgsx-media") as executor:
            running = {}
            while pending_items or running:
                if not self.cancel_event.is_set() and not stop_submitting:
                    while pending_items and len(running) < worker_limit:
                        item = pending_items.pop(0)
                        platform_id = platform_ids.get(item["platform"])
                        if not platform_id:
                            item["attempts"] = int(item.get("attempts") or 0) + 1
                            item["last_error"] = f"unsupported: {item['platform']}"
                            self.progress["errors"] += 1
                            if item["attempts"] < MAX_ATTEMPTS:
                                failed.append(item)
                            self.progress["done"] += 1
                            continue
                        future = executor.submit(self._process_tracked_item, item, platform_id)
                        running[future] = item

                if not running:
                    break
                completed, _ = wait(running, timeout=0.2, return_when=FIRST_COMPLETED)
                if not completed:
                    continue

                for future in completed:
                    item = running.pop(future)
                    try:
                        result = future.result()
                    except screenscraper.ScreenScraperError as exc:
                        if exc.kind in ("quota", "rate_limited", "auth", "account_required"):
                            status_keys = {
                                "quota": "media_quota_exhausted",
                                "rate_limited": "media_rate_limited",
                                "account_required": "media_account_required",
                                "auth": "media_auth_error",
                            }
                            self.status = (status_keys[exc.kind], ())
                            logger.warning("ScreenScraper %s error (%s), download paused", exc.kind, exc)
                            paused_items.append(item)
                            stop_submitting = True
                            continue
                        if exc.kind == "network":
                            consecutive_network_failures += 1
                        item["attempts"] = int(item.get("attempts") or 0) + 1
                        item["last_error"] = f"{exc.kind}: {exc}"
                        self.progress["errors"] += 1
                        logger.warning("Media error %s/%s: %s", item["platform"], item["rom_filename"], item["last_error"])
                        if item["attempts"] < MAX_ATTEMPTS:
                            failed.append(item)
                        if consecutive_network_failures >= MAX_CONSECUTIVE_NETWORK_FAILURES:
                            self.status = ("media_network_paused", ())
                            stop_submitting = True
                    except Exception as exc:
                        item["attempts"] = int(item.get("attempts") or 0) + 1
                        item["last_error"] = str(exc)
                        self.progress["errors"] += 1
                        logger.error("Could not process media %s: %s", item["rom_filename"], exc, exc_info=True)
                        if item["attempts"] < MAX_ATTEMPTS:
                            failed.append(item)
                    else:
                        consecutive_network_failures = 0
                        if result == "found":
                            self.progress["found"] += 1
                        else:
                            self.progress["not_found"] += 1
                            not_found.append({"platform": item["platform"], "rom_filename": item["rom_filename"]})
                            logger.info("Media not found: %s/%s", item["platform"], item["rom_filename"])
                    finally:
                        if not (
                            isinstance(self.status, tuple)
                            and self.status[0] in ("media_quota_exhausted", "media_rate_limited", "media_account_required", "media_auth_error")
                            and item in paused_items
                        ):
                            self.progress["done"] += 1

                self.pending = len(pending_items) + len(running) + len(failed) + len(paused_items)
                since_checkpoint += len(completed)
                if since_checkpoint >= QUEUE_CHECKPOINT_INTERVAL or stop_submitting or self.cancel_event.is_set():
                    queued = paused_items + failed + list(running.values()) + pending_items
                    if not self._persist_queue(queued, not_found):
                        stop_submitting = True
                    since_checkpoint = 0
                config.needs_redraw = True

        if self.cancel_event.is_set() and self.status is None:
            self.status = ("media_cancelled", ())
        remaining = paused_items + failed + pending_items
        self._persist_queue(remaining, not_found)
        self.pending = len(remaining)
        if self.status is None:
            self.status = ("media_done", ())
        self.allowance = screenscraper.LAST_ALLOWANCE or self.allowance
        import preview  # "no image" entries in the preview cache may now be stale
        preview.clear_cache()
        self._refresh_media_counts()
        logger.info(f"Media download finished: {self.progress}, {len(remaining)} games queued, {screenscraper.quota_summary()}")
        config.needs_redraw = True


manager = MediaManager()

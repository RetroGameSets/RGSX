"""Game list preview panel with delayed ScreenScraper downloads.

A request is recorded when the selection (focus) changes. A local cover is shown at once;
the background thread then waits config.SCREENSCRAPER_PREVIEW_DELAY_SEC and, if the selection is unchanged,
fetches the synopsis (and the cover only when it is missing locally). Synopses are kept in
SQLite, so a game already queried is read from the database without an API call.
"""
import logging
import threading
import time
from collections import OrderedDict

import pygame

import config
from media_manager import find_media, save_media
import screenscraper
from rgsx_settings import is_screenscraper_disabled

logger = logging.getLogger(__name__)

# Kept small for low-RAM devices.
CACHE_SIZE = 24

_cache = OrderedDict()  # (folder, rom_filename, w, h) -> completed preview data
_lock = threading.Lock()
_wanted = None  # (key, request time)
_wake = threading.Event()
_thread = None


def clear_cache():
    with _lock:
        _cache.clear()
    config.needs_redraw = True


def _load_scaled(path, width, height):
    try:
        image = pygame.image.load(path)
        scale = min(width / image.get_width(), height / image.get_height())
        size = (max(1, int(image.get_width() * scale)), max(1, int(image.get_height() * scale)))
        return pygame.transform.smoothscale(image, size)
    except Exception as exc:
        # Corrupt/unreadable file: show the placeholder instead of crashing.
        logger.warning(f"Could not load preview {path}: {exc}")
        return None


def _store_preview(key, status, summary, image):
    preview = {"status": status, "image": image, "summary": summary}
    with _lock:
        _cache[key] = preview
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    with _lock:
        current = _wanted[0] if _wanted else None
    if current == key:
        config.needs_redraw = True


def _local_cover(key):
    folder, rom_filename, width, height = key
    path = find_media(folder, rom_filename, "box")
    return _load_scaled(path, width, height) if path else None


def _fetch_summary(key, image):
    folder, rom_filename, width, height = key
    path = find_media(folder, rom_filename, "box")
    summary = ""
    platform_name = ""
    configured_system_id = None
    for platform in getattr(config, "platform_dicts", []) or []:
        if not isinstance(platform, dict) or str(platform.get("folder") or "") != str(folder):
            continue
        candidate_name = str(platform.get("platform_name") or "")
        if not candidate_name:
            continue
        candidate_system_id = screenscraper.get_configured_system_id(candidate_name)
        if not platform_name:
            platform_name = candidate_name
        if candidate_system_id is not None:
            platform_name = candidate_name
            configured_system_id = candidate_system_id
            break
    try:
        if not platform_name:
            raise screenscraper.ScreenScraperError("unsupported", folder)
        system_id = screenscraper.resolve_system_id(platform_name, configured_system_id)
        cached = screenscraper.cached_game_info(rom_filename, system_id)
        if cached is not None and cached["found"]:
            summary = cached["summary"][:12000]
        # A stored answer is reused. The API is only needed for a game never queried, or a cover
        # missing locally that ScreenScraper has not yet been asked for.
        if cached is None or (cached["found"] and not path and not cached["cover_checked"]):
            result = screenscraper.fetch_game_info(
                rom_filename, system_id, origin="preview", kinds=() if path else ("box",)
            )
            if result is not None:
                summary = result["summary"][:12000]
                box_media = result["media"].get("box")
                if box_media and not path:
                    path = save_media(folder, rom_filename, "box", box_media)
    except screenscraper.ScreenScraperError as exc:
        logger.warning(f"Could not fetch preview for {rom_filename}: {exc.kind} ({exc})")
    except OSError as exc:
        logger.error(f"Could not save preview for {rom_filename}: {exc}")
    status = "ready" if path or summary else "unavailable"
    if path and image is None:
        image = _load_scaled(path, width, height)
    _store_preview(key, status, summary, image)


def _settle_after_error(key):
    """Leave no entry stuck in 'loading' when the worker fails unexpectedly."""
    with _lock:
        entry = _cache.get(key)
    if entry is None or entry["status"] == "loading":
        image = entry["image"] if entry else None
        _store_preview(key, "ready" if image else "unavailable", "", image)


def _process(key, requested_at):
    with _lock:
        entry = _cache.get(key)
    if entry is not None and entry["status"] != "loading":
        return
    if entry is None:
        # The local cover needs no network, so it is shown before the selection delay.
        image = _local_cover(key)
        _store_preview(key, "loading", "", image)
    else:
        image = entry["image"]
    if _wake.wait(max(0.0, config.SCREENSCRAPER_PREVIEW_DELAY_SEC - (time.monotonic() - requested_at))):
        return
    if is_screenscraper_disabled():
        _store_preview(key, "ready" if image else "unavailable", "", image)
    else:
        _fetch_summary(key, image)


def _worker():
    while True:
        _wake.wait()
        _wake.clear()
        with _lock:
            wanted = _wanted
        if wanted is None:
            continue
        key, requested_at = wanted
        try:
            _process(key, requested_at)
        except Exception:
            # One failing game must not stop the thread: the next selection still gets a preview.
            logger.exception(f"Preview worker failed for {key[1]}")
            _settle_after_error(key)


def get_preview_data(folder, rom_filename, width, height):
    """Return preview state, image, and synopsis; a loading entry may already carry the local cover."""
    global _wanted, _thread
    key = (folder, rom_filename, int(width), int(height))
    with _lock:
        entry = _cache.get(key)
        if entry is not None:
            _cache.move_to_end(key)
            if entry["status"] != "loading":
                return entry
        if _wanted is None or _wanted[0] != key:
            _wanted = (key, time.monotonic())
            _wake.set()
    if _thread is None or not _thread.is_alive():
        _thread = threading.Thread(target=_worker, daemon=True)
        _thread.start()
    return entry or {"status": "loading", "image": None, "summary": ""}


def get_preview(folder, rom_filename, width, height):
    """Return the scaled cover image when ready."""
    return get_preview_data(folder, rom_filename, width, height)["image"]

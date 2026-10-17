"""Game list preview panel with delayed ScreenScraper downloads.

A request is recorded when the selection (focus) changes; the background thread waits
DOWNLOAD_DELAY_SEC before fetching the cover and synopsis if the selection is unchanged.
"""
import logging
import threading
import time
from collections import OrderedDict

import pygame

import config
from media_manager import find_media, save_media
import screenscraper

logger = logging.getLogger(__name__)

DOWNLOAD_DELAY_SEC = 2.0
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


def _store_preview(key, path, status, summary):
    _, _, width, height = key
    surface = _load_scaled(path, width, height) if path else None
    preview = {"status": status, "image": surface, "summary": summary}
    with _lock:
        _cache[key] = preview
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    with _lock:
        current = _wanted[0] if _wanted else None
    if current == key:
        config.needs_redraw = True


def _worker():
    while True:
        _wake.wait()
        _wake.clear()
        while True:
            with _lock:
                wanted = _wanted
            if wanted is None:
                break
            key, requested_at = wanted
            delay = DOWNLOAD_DELAY_SEC - (time.monotonic() - requested_at)
            if delay > 0:
                time.sleep(delay)
                continue
            break
        if wanted is None:
            continue
        with _lock:
            if key in _cache:
                continue
        folder, rom_filename, width, height = key
        path = find_media(folder, rom_filename, "box")
        if config.SCREENSCRAPER_TEMPORARILY_DISABLED:
            _store_preview(key, path, "ready" if path else "unavailable", "")
            continue
        summary = ""
        status = "unavailable"
        platform_name = ""
        configured_system_id = None
        system_id = None
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
            result = screenscraper.fetch_game_info(rom_filename, system_id)
            if result is not None:
                summary = result["summary"][:12000]
                box_media = result["media"].get("box")
                if box_media and not path:
                    path = save_media(folder, rom_filename, "box", box_media)
            status = "ready" if path or summary else "unavailable"
        except screenscraper.ScreenScraperError as exc:
            if system_id and (exc.kind == "proxy" or (exc.kind == "http" and str(exc) == "unknown_action")):
                logger.warning("ScreenScraper proxy does not support game_info; falling back to game_media")
                try:
                    media = screenscraper.fetch_game_media(rom_filename, system_id, ("box",))
                    if media and media.get("box") and not path:
                        path = save_media(folder, rom_filename, "box", media["box"])
                except screenscraper.ScreenScraperError as fallback_exc:
                    logger.warning(
                        f"Could not fetch preview for {rom_filename}: "
                        f"{fallback_exc.kind} ({fallback_exc})"
                    )
            else:
                logger.warning(f"Could not fetch preview for {rom_filename}: {exc.kind} ({exc})")
            status = "ready" if path else "unavailable"
        except OSError as exc:
            logger.error(f"Could not save preview for {rom_filename}: {exc}")
            status = "ready" if path else "unavailable"
        _store_preview(key, path, status, summary)


def get_preview_data(folder, rom_filename, width, height):
    """Return preview state, image, and synopsis; request them after the selection delay."""
    global _wanted, _thread
    key = (folder, rom_filename, int(width), int(height))
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        if _wanted is None or _wanted[0] != key:
            _wanted = (key, time.monotonic())
            _wake.set()
    if _thread is None:
        _thread = threading.Thread(target=_worker, daemon=True)
        _thread.start()
    return {"status": "loading", "image": None, "summary": ""}


def get_preview(folder, rom_filename, width, height):
    """Return the scaled cover image when ready."""
    return get_preview_data(folder, rom_filename, width, height)["image"]

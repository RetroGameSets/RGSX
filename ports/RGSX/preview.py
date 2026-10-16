"""Game list preview panel: reads only from the local cache, never makes network requests.

A request is recorded when the selection (focus) changes; the background thread waits
DEBOUNCE_SEC and, if the selection is unchanged, loads the image and scales it to the panel.
"""
import logging
import threading
import time
from collections import OrderedDict

import pygame

import config
from media_manager import find_media

logger = logging.getLogger(__name__)

DEBOUNCE_SEC = 0.2
# Kept small for low-RAM devices.
CACHE_SIZE = 24

_cache = OrderedDict()  # (folder, rom_filename, w, h) -> Surface or None (no image)
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


def _worker():
    while True:
        _wake.wait()
        _wake.clear()
        while True:
            with _lock:
                key, requested_at = _wanted
            delay = DEBOUNCE_SEC - (time.monotonic() - requested_at)
            if delay > 0:
                time.sleep(delay)
                continue
            break
        with _lock:
            if key in _cache:
                continue
        folder, rom_filename, width, height = key
        path = find_media(folder, rom_filename, "box")
        surface = _load_scaled(path, width, height) if path else None
        with _lock:
            _cache[key] = surface
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
        with _lock:
            current = _wanted[0]
        if current == key:
            config.needs_redraw = True


def get_preview(folder, rom_filename, width, height):
    """Return the scaled Surface when ready; None while loading or without an image (placeholder is drawn)."""
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
    return None


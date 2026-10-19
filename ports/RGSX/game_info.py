"""Fetch and display metadata from the ScreenScraper API."""
import logging
from io import BytesIO
import threading

import pygame

import config
import media_manager
import preview
import screenscraper
from language import _

logger = logging.getLogger(__name__)

GAME_INFO_KINDS = ("box", "ss")


def _save_downloaded_media(folder, rom_filename, media):
    """Keep downloaded images in the media folder so the next opening reads them locally."""
    for kind, (payload, extension) in media.items():
        if media_manager.find_media(folder, rom_filename, kind):
            continue
        try:
            media_manager.save_media(folder, rom_filename, kind, (payload, extension))
        except (OSError, screenscraper.ScreenScraperError) as exc:
            logger.warning("Could not save ScreenScraper %s for %s: %s", kind, rom_filename, exc)
    preview.clear_cache()


def open_game_info(rom_filename, game_name, platform_name, return_state="game"):
    """Open the ScreenScraper details page and fetch its content asynchronously."""
    config.game_info_request_id += 1
    request_id = config.game_info_request_id
    config.game_info_game_name = str(game_name or rom_filename)
    config.game_info_platform_name = str(platform_name or "")
    config.game_info_cover_surface = None
    config.game_info_screenshot_surface = None
    config.game_info_summary = ""
    config.game_info_loading = True
    config.game_info_error_message = ""
    config.game_info_return_state = return_state
    config.previous_menu_state = return_state
    config.menu_state = "game_info"
    config.needs_redraw = True
    threading.Thread(
        target=_fetch_game_info,
        args=(request_id, str(rom_filename or ""), str(platform_name or "")),
        daemon=True,
    ).start()


def _platform_folder(platform_name):
    platform_dict = getattr(config, "platform_dict_by_name", {}).get(platform_name) or {}
    return str(platform_dict.get("folder") or "")


def _decode_images(rom_filename, media, from_files):
    """Decode images read from the local media folder (paths) or downloaded this time (payloads)."""
    images = {}
    for kind, source in media.items():
        try:
            if from_files:
                images[kind] = pygame.image.load(source)
            else:
                payload, extension = source
                images[kind] = pygame.image.load(BytesIO(payload), f"{kind}{extension}")
        except (pygame.error, OSError, ValueError) as exc:
            logger.warning("Could not decode %s image for %s: %s", kind, rom_filename, exc)
    return images


def _fetch_game_info(request_id, rom_filename, platform_name):
    try:
        system_id = screenscraper.resolve_system_id(platform_name)
        folder = _platform_folder(platform_name)
        local = media_manager.local_game(folder, rom_filename, system_id, GAME_INFO_KINDS, need_summary=True) if folder else None
        if local is not None:
            found = local["found"]
            summary = local["summary"][:12000] if found else ""
            images = _decode_images(rom_filename, local["media"], from_files=True) if found else {}
        else:
            result = screenscraper.fetch_game_info(rom_filename, system_id, origin="details", kinds=GAME_INFO_KINDS)
            found = result is not None
            summary = result["summary"][:12000] if found else ""
            images = _decode_images(rom_filename, result["media"], from_files=False) if found else {}
            if found and folder:
                _save_downloaded_media(folder, rom_filename, result["media"])
        if not found:
            error_message = _("screenscraper_game_not_found")
        elif not summary and not images:
            logger.info("ScreenScraper has no synopsis or media for %s", rom_filename)
            error_message = _("screenscraper_game_no_content")
        else:
            error_message = ""
    except screenscraper.ScreenScraperError as exc:
        logger.warning("Could not load ScreenScraper details for %s: %s (%s)", rom_filename, exc.kind, exc)
        error_keys = {
            "account_required": "screenscraper_account_required",
            "auth": "screenscraper_login_failed",
            "config": "screenscraper_dev_credentials_missing",
            "quota": "media_quota_exhausted",
            "rate_limited": "screenscraper_rate_limited",
            "unsupported": "media_unsupported",
        }
        key = error_keys.get(exc.kind)
        error_message = _(key) if key else _("media_error").format(f"{exc.kind}: {exc}")
        summary = ""
        images = {}
    except Exception:
        logger.exception("Unexpected error loading ScreenScraper details for %s", rom_filename)
        error_message = _("media_error").format("http")
        summary = ""
        images = {}

    if config.game_info_request_id != request_id or config.menu_state != "game_info":
        return

    config.game_info_summary = summary
    config.game_info_cover_surface = images.get("box")
    config.game_info_screenshot_surface = images.get("ss")
    config.game_info_error_message = error_message
    config.game_info_loading = False
    config.needs_redraw = True

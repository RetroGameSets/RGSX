"""Fetch and display metadata from the ScreenScraper proxy."""
import logging
from io import BytesIO
import threading

import pygame

import config
import screenscraper
from language import _

logger = logging.getLogger(__name__)


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


def _fetch_game_info(request_id, rom_filename, platform_name):
    try:
        system_id = screenscraper.resolve_system_id(platform_name)
        result = screenscraper.fetch_game_info(rom_filename, system_id)
        if result is None:
            summary = ""
            images = {}
            error_message = _("screenscraper_game_not_found")
        else:
            summary = result["summary"][:12000]
            images = {}
            for kind, (payload, extension) in result["media"].items():
                try:
                    images[kind] = pygame.image.load(
                        BytesIO(payload),
                        f"{kind}{extension}",
                    )
                except (pygame.error, OSError, ValueError) as exc:
                    logger.warning("Could not decode ScreenScraper %s for %s: %s", kind, rom_filename, exc)
            error_message = ""
    except screenscraper.ScreenScraperError as exc:
        logger.warning("Could not load ScreenScraper details for %s: %s (%s)", rom_filename, exc.kind, exc)
        error_keys = {
            "account_required": "screenscraper_account_required",
            "auth": "screenscraper_login_failed",
            "config": "screenscraper_dev_credentials_missing",
            "quota": "media_quota_exhausted",
            "rate_limited": "screenscraper_rate_limited",
            "proxy": "screenscraper_proxy_outdated",
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

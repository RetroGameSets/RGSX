"""Client for RGSX's server-side ScreenScraper proxy."""
import base64
import json
import logging
import os
import re
import sqlite3
import threading
import time
import unicodedata

import requests

import config
import database

logger = logging.getLogger(__name__)

SOURCE_SUFFIXES = {"Archive", "Archive.org", "LolRoms", "Torrent", "1Fichier", "Vimms", "EdgeEmu", "EdgeEmu.net"}
PLATFORM_ALIASES = {
    "Family Computer Disk System (Famicom)": "Family Computer Disk System",
    "Nintendo Famicom Disk System": "Family Computer Disk System",
    "NES": "Nintendo Entertainment System",
}
SYSTEM_CATALOG_TTL_SEC = 30 * 24 * 60 * 60


def normalize_platform_name(platform_name):
    """Strip source suffixes from RGSX platform labels for ScreenScraper lookups."""
    text = str(platform_name or "").strip()
    if not text:
        return ""

    while True:
        match = re.search(r'\(([^()]+)\)\s*$', text)
        if not match:
            break
        suffix = match.group(1).strip()
        if suffix in SOURCE_SUFFIXES or suffix == "RomHacks":
            text = text[:match.start()].rstrip()
            continue
        break

    return PLATFORM_ALIASES.get(text, text)


# Daily quota from the last API response: (remaining_today, max_per_day) or None
LAST_ALLOWANCE = None
# Quota counters from the last ssuser block. The API docs make quota handling by the client mandatory.
QUOTA = {}
_request_lock = threading.Lock()
_last_request_at = 0.0
_system_cache_lock = threading.Lock()
_system_refresh_lock = threading.Lock()
_system_cache = None


class ScreenScraperError(Exception):
    """kind: 'quota' | 'auth' | 'config' | 'network' | 'http' | 'proxy' | 'unsupported'"""

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind


def load_account():
    """Return the user's ScreenScraper account: (username, password), empty strings when not set."""
    try:
        with open(config.SCREENSCRAPER_ACCOUNT_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return str(data.get("username") or ""), str(data.get("password") or "")
    except FileNotFoundError:
        pass
    except Exception as exc:
        logger.warning(f"Could not read ScreenScraper account: {type(exc).__name__}")
    return "", ""


def save_account(username, password):
    global LAST_ALLOWANCE
    os.makedirs(os.path.dirname(config.SCREENSCRAPER_ACCOUNT_PATH), exist_ok=True)
    with open(config.SCREENSCRAPER_ACCOUNT_PATH, "w", encoding="utf-8") as handle:
        json.dump({"username": username, "password": password}, handle)
    # The quota belongs to the account: the last known values are no longer valid.
    LAST_ALLOWANCE = None
    QUOTA.clear()


def get_configured_system_id(platform_name):
    platform_key = str(platform_name or "").strip().casefold()
    if not platform_key:
        return None
    for platform in getattr(config, "platform_dicts", []) or []:
        if not isinstance(platform, dict):
            continue
        if str(platform.get("platform_name") or "").strip().casefold() != platform_key:
            continue
        value = platform.get("screenscraper_system_id")
        if value is None or value == "":
            continue
        try:
            system_id = int(value)
        except (TypeError, ValueError):
            logger.warning("Invalid ScreenScraper system ID for platform %s", platform_name)
            return None
        if system_id > 0:
            return system_id
        logger.warning("Invalid ScreenScraper system ID for platform %s", platform_name)
        return None
    return None


def get_system_id(platform_name, configured_system_id=None):
    if configured_system_id is None:
        configured_system_id = get_configured_system_id(platform_name)
    if configured_system_id is not None:
        try:
            system_id = int(configured_system_id)
        except (TypeError, ValueError):
            logger.warning("Invalid ScreenScraper system ID for platform %s", platform_name)
        else:
            if system_id > 0:
                return system_id
            logger.warning("Invalid ScreenScraper system ID for platform %s", platform_name)

    keys = _platform_system_keys(platform_name)
    for system in _cached_systems():
        system_keys = {
            _system_lookup_key(system.get("name")),
            _system_lookup_key(system.get("short_name")),
        }
        if keys & system_keys:
            return int(system["system_id"])

    return None


def _system_lookup_key(value):
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "", text)


def _platform_system_keys(platform_name):
    normalized = normalize_platform_name(platform_name)
    keys = {
        _system_lookup_key(platform_name),
        _system_lookup_key(normalized),
    }
    alias = PLATFORM_ALIASES.get(normalized)
    if alias:
        keys.add(_system_lookup_key(alias))
    return {key for key in keys if key}


def _cached_systems():
    global _system_cache
    with _system_cache_lock:
        if _system_cache is None:
            try:
                _system_cache = database.list_screenscraper_systems(config.DB_PATH)
            except (OSError, sqlite3.Error) as exc:
                logger.warning("Could not read ScreenScraper systems from SQLite: %s", exc)
                _system_cache = []
        return _system_cache


def system_catalog_cache_is_stale():
    try:
        return database.screenscraper_systems_cache_is_stale(
            SYSTEM_CATALOG_TTL_SEC,
            config.DB_PATH,
        )
    except (OSError, sqlite3.Error) as exc:
        logger.warning("Could not check the ScreenScraper system cache age: %s", exc)
        return True


def refresh_system_catalog():
    """Refresh and persist the ScreenScraper system IDs through the server proxy."""
    global _system_cache
    with _system_refresh_lock:
        if not system_catalog_cache_is_stale():
            return len(_cached_systems())

        data = _proxy_request("system_list")
        systems = data.get("systems")
        if not isinstance(systems, list):
            raise ScreenScraperError("http", "invalid ScreenScraper system list")

        valid_systems = []
        for system in systems:
            if not isinstance(system, dict):
                continue
            try:
                system_id = int(system.get("id") or system.get("system_id") or 0)
            except (TypeError, ValueError):
                continue
            name = str(system.get("name") or system.get("nom") or "").strip()
            short_name = str(
                system.get("short_name")
                or system.get("shortname")
                or system.get("nomcourt")
                or ""
            ).strip()
            if system_id > 0 and (name or short_name):
                valid_systems.append({
                    "system_id": system_id,
                    "name": name,
                    "short_name": short_name,
                })
        if not valid_systems:
            raise ScreenScraperError("http", "empty ScreenScraper system list")

        try:
            database.replace_screenscraper_systems(valid_systems, config.DB_PATH)
        except (OSError, sqlite3.Error, ValueError) as exc:
            logger.error("Could not save ScreenScraper system list to SQLite: %s", exc)
            raise ScreenScraperError("database", "could not save system list") from exc
        with _system_cache_lock:
            _system_cache = valid_systems
        return len(valid_systems)


def resolve_system_id(platform_name, configured_system_id=None):
    """Resolve from configured or cached ScreenScraper IDs, refreshing the cache if needed."""
    system_id = get_system_id(platform_name, configured_system_id)
    if system_id is None and system_catalog_cache_is_stale():
        refresh_system_catalog()
        system_id = get_system_id(platform_name, configured_system_id)
    if system_id is None:
        raise ScreenScraperError("unsupported", str(platform_name or ""))
    return system_id


def _wait_for_request_slot():
    global _last_request_at
    with _request_lock:
        max_per_min = QUOTA.get("max_min")
        if max_per_min:
            wait = _last_request_at + 60.0 / max_per_min - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        _last_request_at = time.monotonic()


def _proxy_request(action, **params):
    """Call the server proxy; developer credentials and media URLs stay server-side."""
    proxy_url = str(getattr(config, "SCREENSCRAPER_PROXY_URL", "") or "").strip()
    if not proxy_url.startswith("https://"):
        raise ScreenScraperError("config", "ScreenScraper proxy must use HTTPS")
    _wait_for_request_slot()
    username, password = load_account()
    payload = {"action": action, **params}
    if username and password:
        payload.update({"ssid": username, "sspassword": password})
    try:
        response = requests.post(proxy_url, json=payload, timeout=60, allow_redirects=False)
    except requests.RequestException as exc:
        raise ScreenScraperError("network", type(exc).__name__)
    try:
        data = response.json()
    except ValueError:
        raise ScreenScraperError("http", "invalid proxy response")
    if not isinstance(data, dict):
        raise ScreenScraperError("http", "invalid proxy response")
    if response.status_code == 200 and data.get("success") is True:
        return data
    reason = str(data.get("error") or "")
    if reason == "unknown_action":
        kind = "proxy"
    elif reason == "config":
        kind = "config"
    elif reason in {
        "auth",
        "authentication_rejected",
        "developer_credentials_rejected",
        "invalid_account",
        "software_rejected",
    } or response.status_code in (401, 403):
        kind = "auth"
    elif reason in {"quota", "rate_limited"} or response.status_code == 429:
        kind = "quota"
    elif response.status_code >= 500:
        kind = "network"
    else:
        kind = "http"
    raise ScreenScraperError(kind, reason or f"HTTP {response.status_code}")


def _update_allowance(ssuser):
    """Store the quota counters of an ssuser block (also sent for users without an account)."""
    global LAST_ALLOWANCE

    def number(*names):
        for name in names:
            try:
                return int((ssuser or {})[name])
            except (KeyError, TypeError, ValueError):
                pass
        return None

    values = {
        "today": number("requeststoday"),
        "max_day": number("maxrequestsperday"),
        "ko_today": number("requestskotoday"),
        "max_ko_day": number("maxrequestskoperday"),
        # Spelled maxrequestspermin in ssuserInfos and maxrequestsperdmin in jeuInfos docs
        "max_min": number("maxrequestspermin", "maxrequestsperdmin"),
    }
    QUOTA.update({key: value for key, value in values.items() if value is not None})
    if QUOTA.get("max_day"):
        LAST_ALLOWANCE = (max(0, QUOTA["max_day"] - QUOTA.get("today", 0)), QUOTA["max_day"])


def _check_quota():
    """Stop before the server refuses with 430/431 when the known counters are used up."""
    if QUOTA.get("max_day") and QUOTA.get("today", 0) >= QUOTA["max_day"]:
        raise ScreenScraperError("quota", "daily request quota reached")
    if QUOTA.get("max_ko_day") and QUOTA.get("ko_today", 0) >= QUOTA["max_ko_day"]:
        raise ScreenScraperError("quota", "daily not-found quota reached")


def _record_game_response(data):
    if data.get("ssuser"):
        _update_allowance(data["ssuser"])
    else:
        _update_allowance({
            "requeststoday": QUOTA.get("today", 0) + 1,
            "requestskotoday": QUOTA.get("ko_today", 0) + (not data.get("found")),
        })


def _decode_game_media(data):
    media_data = data.get("media") or {}
    if not isinstance(media_data, dict):
        raise ScreenScraperError("http", "invalid media response")
    media = {}
    for kind, item in media_data.items():
        if kind not in {"box", "ss", "logo"} or not isinstance(item, dict):
            continue
        extension = str(item.get("extension") or ".jpg").lower()
        if extension not in {".jpg", ".png"}:
            extension = ".jpg"
        try:
            payload = base64.b64decode(item.get("data_base64", ""), validate=True)
        except (ValueError, TypeError):
            raise ScreenScraperError("http", "invalid media payload")
        if not payload or len(payload) > 3 * 1024 * 1024:
            raise ScreenScraperError("http", "invalid media size")
        media[kind] = (payload, extension)
    return media


def get_user_info():
    """Refresh the quota (works without an account too) and return LAST_ALLOWANCE.

    With an account, raises ScreenScraperError("auth") when the login is not accepted.
    """
    data = _proxy_request("user_info")
    username, password = load_account()
    ssuser = data.get("ssuser") or {}
    if username and password:
        # niveau 0 / another pseudo: the username/password pair was not accepted
        returned_id = str(ssuser.get("id") or "")
        if str(ssuser.get("niveau") or "0") == "0" or (returned_id and returned_id.lower() != username.lower()):
            raise ScreenScraperError("auth", "ScreenScraper login refused")
    _update_allowance(ssuser)
    return LAST_ALLOWANCE


def fetch_game_media(rom_filename, system_id, kinds):
    """Return a game's downloaded media bytes by kind, without exposing upstream URLs."""
    _check_quota()
    data = _proxy_request(
        "game_media",
        system_id=int(system_id),
        rom_filename=os.path.basename(str(rom_filename)),
        kinds=list(kinds),
    )
    _record_game_response(data)
    if not data.get("found"):
        return None
    return _decode_game_media(data)


def fetch_game_info(rom_filename, system_id):
    """Return a game's ScreenScraper synopsis and cover/screenshot bytes."""
    _check_quota()
    data = _proxy_request(
        "game_info",
        system_id=int(system_id),
        rom_filename=os.path.basename(str(rom_filename)),
    )
    _record_game_response(data)
    if not data.get("found"):
        return None
    summary = data.get("summary", "")
    if not isinstance(summary, str):
        raise ScreenScraperError("http", "invalid game summary")
    return {"summary": summary, "media": _decode_game_media(data)}

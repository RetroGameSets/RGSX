"""Client for the ScreenScraper API, called directly with the user's account."""
import html
import json
import logging
import os
import re
import threading
import time
import unicodedata
from urllib.parse import urlparse

import requests

import config
import database
from sqlite_compat import sqlite3

logger = logging.getLogger(__name__)

SOURCE_SUFFIXES = {"Archive", "Archive.org", "LolRoms", "Torrent", "1Fichier", "Vimms", "EdgeEmu", "EdgeEmu.net"}
PLATFORM_ALIASES = {
    "Family Computer Disk System (Famicom)": "Family Computer Disk System",
    "Nintendo Famicom Disk System": "Family Computer Disk System",
    "NES": "Nintendo Entertainment System",
}
SYSTEM_CATALOG_TTL_SEC = 30 * 24 * 60 * 60
API_BASE_URL = "https://api.screenscraper.fr/api2/"
SOFTNAME = "RGSX"
MEDIA_MAX_BYTES = 3 * 1024 * 1024
# Media kind -> ScreenScraper media types (first type with a URL wins); regions by preference
MEDIA_TYPES = {"box": ("box-2D",), "ss": ("ss",)}
MEDIA_REGIONS = ("wor", "us", "eu", "ss", "jp")


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
    """kind: 'quota' | 'rate_limited' | 'auth' | 'account_required' | 'config' | 'network' | 'http' | 'unsupported' | 'database'"""

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
    logger.info("ScreenScraper user account saved (complete: %s)", bool(username and password))


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
    """Refresh and persist the ScreenScraper system IDs from systemesListe.php."""
    global _system_cache
    with _system_refresh_lock:
        if not system_catalog_cache_is_stale():
            return len(_cached_systems())

        valid_systems = _normalize_systems(_api_request("systemesListe.php", {}))
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


_developer_credentials_lock = threading.Lock()
_developer_credentials_cache = None


def _fetch_developer_credentials():
    """Fetch (devid, devpassword) from the RGSX credentials API. The response is never logged."""
    try:
        response = requests.get(config.SCREENSCRAPER_CREDENTIALS_API_URL, timeout=10, allow_redirects=False)
    except requests.RequestException:
        raise ScreenScraperError("network", "ScreenScraper developer credentials API unreachable") from None
    if response.status_code != 200:
        raise ScreenScraperError("config", f"ScreenScraper developer credentials API answered HTTP {response.status_code}")
    try:
        payload = response.json()
    except ValueError:
        raise ScreenScraperError("config", "ScreenScraper developer credentials API returned invalid JSON") from None
    if not isinstance(payload, dict):
        payload = {}
    devid = str(payload.get("devid") or "")
    devpassword = str(payload.get("devpassword") or "")
    if not (devid and devpassword):
        raise ScreenScraperError("config", "ScreenScraper developer credentials API returned no credentials")
    return devid, devpassword


def _developer_credentials():
    """Return (devid, devpassword), fetched once per session and kept in memory only."""
    global _developer_credentials_cache
    with _developer_credentials_lock:
        if _developer_credentials_cache is None:
            _developer_credentials_cache = _fetch_developer_credentials()
        return _developer_credentials_cache



def _api_request(endpoint, params):
    """GET an API2 endpoint with the developer and user credentials; return its response block.

    Returns None when ScreenScraper answers 404 (unknown game). The URL is never logged or
    chained into the error, because it carries the credentials.
    """
    username, password = load_account()
    if not (username and password):
        raise ScreenScraperError("account_required", "ScreenScraper account required")
    devid, devpassword = _developer_credentials()
    query = {
        **params,
        "devid": devid,
        "devpassword": devpassword,
        "softname": SOFTNAME,
        "output": "json",
        "ssid": username,
        "sspassword": password,
    }
    _wait_for_request_slot()
    try:
        response = requests.get(API_BASE_URL + endpoint, params=query, timeout=30, allow_redirects=False)
    except requests.RequestException:
        raise ScreenScraperError("network", "request failed") from None
    status = response.status_code
    if status == 404:
        return None
    kind = None
    if status in (430, 431):
        kind = "quota"
    elif status in (403, 426):
        kind = "auth"
    elif status in (401, 423, 429):
        kind = "rate_limited"
    elif status >= 500:
        kind = "network"
    elif status != 200:
        kind = "http"
    if kind:
        raise ScreenScraperError(kind, f"HTTP {status}")
    try:
        data = response.json()
    except ValueError:
        raise ScreenScraperError("http", "invalid ScreenScraper response") from None
    block = data.get("response") if isinstance(data, dict) else None
    if not isinstance(block, dict):
        raise ScreenScraperError("http", "invalid ScreenScraper response")
    return block


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


def quota_summary():
    """Remaining requests for today, for the logs."""
    if not LAST_ALLOWANCE:
        return "quota unknown"
    remaining, maximum = LAST_ALLOWANCE
    return f"{remaining} of {maximum} requests left today"


def _record_game_response(ssuser, found, origin):
    if ssuser:
        _update_allowance(ssuser)
    else:
        _update_allowance({
            "requeststoday": QUOTA.get("today", 0) + 1,
            "requestskotoday": QUOTA.get("ko_today", 0) + (0 if found else 1),
        })
    # Batch downloads would log one line per game; their end-of-batch summary covers them.
    if origin != "media manager":
        logger.info(
            "ScreenScraper game request (%s, %s): %s, %s",
            origin,
            "server count" if ssuser else "local estimate",
            "found" if found else "not found",
            quota_summary(),
        )


def _first_value(*values):
    """Return the first value that is not None, like PHP's ?? operator."""
    for value in values:
        if value is not None:
            return value
    return None


def _trimmed(value):
    return value.strip() if isinstance(value, str) else ""


def _plain_text(value):
    return html.unescape(re.sub(r"<[^>]*>", "", value)).strip()


def _system_name(system):
    name = _first_value(system.get("nomsysteme"), system.get("nom"), system.get("name"), "")
    if _trimmed(name):
        return _trimmed(name)
    if isinstance(name, dict):
        for key in ("fr", "en", "text"):
            if _trimmed(name.get(key)):
                return _trimmed(name[key])
    noms = system.get("noms")
    names = noms if isinstance(noms, (list, dict)) and len(noms) > 0 else name
    if isinstance(names, dict) and "nom" in names:
        names = names["nom"]
    if isinstance(names, dict) and "text" in names:
        names = [names]
    if not isinstance(names, (list, dict)):
        return ""
    items = list(names.values()) if isinstance(names, dict) else names
    fallback = ""
    for localized in items:
        if isinstance(localized, str):
            text = _trimmed(localized)
            language = ""
        elif isinstance(localized, dict):
            text = _trimmed(_first_value(localized.get("text"), localized.get("nom"), localized.get("name")))
            language_value = _first_value(localized.get("langue"), localized.get("lang"), localized.get("language"), "")
            language = str(language_value).lower() if isinstance(language_value, (str, int, float)) else ""
        else:
            continue
        if not text:
            continue
        if language in ("en", "eng", "english"):
            return text
        if not fallback:
            fallback = text
    return fallback


def _normalize_systems(block):
    """Map systemesListe.php to [{system_id, name, short_name}], skipping unusable entries."""
    source = block.get("systemes") if isinstance(block, dict) else None
    if source is None:
        source = []
    if isinstance(source, dict) and "systeme" in source:
        source = source["systeme"]
    if isinstance(source, dict) and "id" in source:
        source = [source]
    if not isinstance(source, list):
        raise ScreenScraperError("http", "invalid ScreenScraper system list")
    systems = []
    for system in source:
        if not isinstance(system, dict):
            continue
        try:
            system_id = int(system.get("id"))
        except (TypeError, ValueError):
            continue
        name = _system_name(system)
        short_name = _trimmed(_first_value(system.get("shortname"), system.get("nomcourt"), system.get("short_name"), ""))
        if system_id < 1 or not (name or short_name):
            continue
        systems.append({"system_id": system_id, "name": name, "short_name": short_name})
    if not systems:
        raise ScreenScraperError("http", "empty ScreenScraper system list")
    return systems


def _media_url(media):
    url = str(media.get("url") or "")
    try:
        parts = urlparse(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if parts.scheme.lower() != "https" or not (host == "screenscraper.fr" or host.endswith(".screenscraper.fr")):
        return None
    return url + ("&" if "?" in url else "?") + "maxwidth=640"


def _download_image(media):
    """Download one media item from screenscraper.fr over HTTPS. Returns (bytes, extension) or None."""
    url = _media_url(media)
    if url is None:
        return None
    deadline = time.monotonic() + 25
    body = bytearray()
    try:
        response = requests.get(url, timeout=(10, 25), allow_redirects=False, stream=True)
        try:
            content_type = response.headers.get("Content-Type", "").lower()
            if response.status_code != 200 or not content_type.startswith("image/"):
                return None
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > MEDIA_MAX_BYTES or time.monotonic() > deadline:
                    return None
        finally:
            response.close()
    except requests.RequestException as exc:
        logger.warning(f"ScreenScraper media download failed: {type(exc).__name__}")
        return None
    if not body:
        return None
    extension = str(media.get("format") or "jpg").lower()
    if extension == "jpeg":
        extension = "jpg"
    if extension not in ("jpg", "png"):
        extension = "jpg"
    return bytes(body), "." + extension


def _region_rank(region):
    try:
        return MEDIA_REGIONS.index(region)
    except ValueError:
        return len(MEDIA_REGIONS)


def _pick_media(medias, kind):
    for wanted_type in MEDIA_TYPES[kind]:
        candidates = [item for item in medias if item.get("type") == wanted_type and item.get("url")]
        if candidates:
            return min(candidates, key=lambda item: _region_rank(item.get("region")))
    return None


def _download_media(game, kinds, box_fallback):
    medias = game.get("medias")
    medias = [item for item in medias if isinstance(item, dict)] if isinstance(medias, list) else []
    media = {}
    for kind in kinds:
        chosen = _pick_media(medias, kind)
        downloaded = _download_image(chosen) if chosen else None
        if downloaded is None and kind == "box" and box_fallback:
            fallback = next((item for item in medias if item.get("type") == "ss" and item.get("url")), None)
            downloaded = _download_image(fallback) if fallback else None
        if downloaded is not None:
            media[kind] = downloaded
    return media


def _is_french(language):
    return language == "fr" or language.startswith("fr-") or language.startswith("fra")


def _game_summary(game):
    summary = _first_value(game.get("synopsis"), game.get("synopsys"), game.get("descriptions"), game.get("description"), "")
    if isinstance(summary, str):
        return _plain_text(summary)
    if isinstance(summary, dict):
        items = [(0, summary)] if "text" in summary else list(summary.items())
    elif isinstance(summary, list):
        items = list(enumerate(summary))
    else:
        return ""
    fallback = ""
    for key, item in items:
        if isinstance(item, str):
            text = _plain_text(item)
            language = str(key).lower()
        elif isinstance(item, dict):
            raw_text = _first_value(item.get("text"), item.get("description"), item.get("synopsis"), "")
            text = _plain_text(raw_text) if isinstance(raw_text, str) else ""
            language = str(_first_value(item.get("langue"), item.get("lang"), item.get("language"), key)).lower()
        else:
            continue
        if not text:
            continue
        if _is_french(language):
            return text
        if not fallback:
            fallback = text
    return fallback


def _rom_name(rom_filename):
    return os.path.basename(str(rom_filename))


def _store_game_summary(rom_filename, system_id, game, cover_checked=None, screenshot_checked=None):
    try:
        database.save_game_summary(
            int(system_id),
            _rom_name(rom_filename),
            _game_summary(game) if game is not None else "",
            found=game is not None,
            cover_checked=cover_checked,
            screenshot_checked=screenshot_checked,
            db_path=config.DB_PATH,
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning(f"Could not store ScreenScraper summary: {type(exc).__name__}")


def cached_game_info(rom_filename, system_id):
    """Return {"found", "summary", "cover_checked", "screenshot_checked"} stored for a ROM, or None when it was never queried."""
    try:
        return database.load_game_summary(int(system_id), _rom_name(rom_filename), config.DB_PATH)
    except (OSError, sqlite3.Error, ValueError) as exc:
        logger.warning(f"Could not read stored ScreenScraper summary: {type(exc).__name__}")
        return None


def _has_media(game, kind):
    medias = game.get("medias")
    medias = [item for item in medias if isinstance(item, dict)] if isinstance(medias, list) else []
    return _pick_media(medias, kind) is not None


def _query_game(rom_filename, system_id, kinds=()):
    """Return (game or None, ssuser) for one ROM. The caller records the quota counters.

    The outcome is stored in SQLite, including 'not found', so a repeated visit costs no request.
    A media kind counts as checked only when it was requested and ScreenScraper lists none,
    so a kind that is listed but failed to download is still retried.
    """
    block = _api_request("jeuInfos.php", {
        "systemeid": int(system_id),
        "romtype": "rom",
        "romnom": _rom_name(rom_filename),
    })
    if block is None:
        _store_game_summary(rom_filename, system_id, None)
        return None, {}
    ssuser = block.get("ssuser") if isinstance(block.get("ssuser"), dict) else {}
    game = block.get("jeu")
    game = game if isinstance(game, dict) else None
    wanted = set(kinds)
    cover_checked = (not _has_media(game, "box")) if game is not None and "box" in wanted else None
    screenshot_checked = (not _has_media(game, "ss")) if game is not None and "ss" in wanted else None
    _store_game_summary(rom_filename, system_id, game, cover_checked, screenshot_checked)
    return game, ssuser


def get_user_info():
    """Refresh the account quota and return LAST_ALLOWANCE.

    Needs a ScreenScraper account (ssuserInfos is refused without it). Raises
    ScreenScraperError("auth") when the login is not accepted.
    """
    username, _password = load_account()
    block = _api_request("ssuserInfos.php", {})
    if block is None:
        raise ScreenScraperError("http", "ScreenScraper user info not found")
    ssuser = block.get("ssuser") if isinstance(block.get("ssuser"), dict) else {}
    # niveau 0 / another pseudo: the username/password pair was not accepted
    returned_id = str(ssuser.get("id") or "")
    niveau = str(ssuser.get("niveau") or "0")
    if returned_id and returned_id.lower() != username.lower():
        logger.warning("ScreenScraper login refused: returned account does not match the configured one")
        raise ScreenScraperError("auth", "ScreenScraper login refused")
    if niveau == "0":
        logger.warning("ScreenScraper login refused (level 0)")
        raise ScreenScraperError("auth", "ScreenScraper login refused")
    _update_allowance(ssuser)
    logger.info("ScreenScraper login OK (level %s): %s", niveau, quota_summary())
    return LAST_ALLOWANCE


def fetch_game_media(rom_filename, system_id, kinds, origin):
    """Return a game's downloaded media bytes by kind, without exposing upstream URLs."""
    _check_quota()
    game, ssuser = _query_game(rom_filename, system_id, kinds)
    _record_game_response(ssuser, found=game is not None, origin=origin)
    if game is None:
        return None
    wanted = set(kinds)
    return _download_media(game, [kind for kind in MEDIA_TYPES if kind in wanted], box_fallback=True)


def fetch_game_info(rom_filename, system_id, origin, kinds=("box", "ss")):
    """Return a game's ScreenScraper synopsis and the requested cover/screenshot bytes."""
    _check_quota()
    game, ssuser = _query_game(rom_filename, system_id, kinds)
    _record_game_response(ssuser, found=game is not None, origin=origin)
    if game is None:
        return None
    wanted = set(kinds)
    media = _download_media(game, [kind for kind in MEDIA_TYPES if kind in wanted], box_fallback=False)
    return {"summary": _game_summary(game), "media": media}

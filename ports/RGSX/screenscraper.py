"""ScreenScraper.fr API v2 client for the Media Manager (bulk cover download).

Developer credentials come from the environment (SCREENSCRAPER_DEV_ID, SCREENSCRAPER_DEV_PASSWORD,
SCREENSCRAPER_SOFTNAME) or from screenscraper_credentials.py, which the release workflow generates.
The user's own ScreenScraper account (optional, raises the daily quota) is set in Settings and stored in
config.SCREENSCRAPER_ACCOUNT_PATH.
Credentials are sent in every URL (API and media), so URLs and requests exceptions are never logged.
"""
import json
import logging
import os
import threading
import time

import requests

import config
from scraper import normalize_scraper_platform_name

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.screenscraper.fr/api2"

# RGSX platform name -> ScreenScraper systemeid (ids from ES-DE's ScreenScraper platform map)
SYSTEM_IDS = {
    "3DO Interactive Multiplayer": 29,
    "3DS": 17,
    "Amiga CD32": 130,
    "Amiga CDTV": 129,
    "Amiga OCS ECS": 64,
    "Apple II": 86,
    "Apple IIGS": 217,
    "Arcadia 2001": 94,
    "Archimedes": 84,
    "Astrocade": 44,
    "Atari 2600": 26,
    "Atari 5200": 40,
    "Atari 7800": 41,
    "Atari Lynx": 28,
    "Atari ST": 42,
    "Channel-F": 80,
    "ColecoVision": 48,
    "Commodore 64": 66,
    "Commodore Plus4": 99,
    "Commodore VIC-20": 73,
    "CreatiVision": 241,
    "Dos (x86)": 135,
    "Dreamcast": 23,
    "Family Computer Disk System": 106,
    "Final Burn Neo": 75,
    "FM-TOWNS": 253,
    "Gamate": 266,
    "Game Boy": 9,
    "Game Boy Advance": 12,
    "Game Boy Color": 10,
    "Game Cube": 13,
    "Game Gear": 21,
    "Game Master": 103,
    "Game.com": 121,
    "Game and Watch": 52,
    "Jaguar": 27,
    "Macintosh": 146,
    "Master System": 2,
    "Mattel Intellivision": 115,
    "Mega CD": 20,
    "Mega Drive": 1,
    "Mega Duck Cougar Boy": 90,
    "MSX1": 113,
    "MSX2+": 116,
    "Naomi": 56,
    "Neo-Geo CD": 70,
    "Neo-Geo Pocket": 25,
    "Neo-Geo Pocket Color": 82,
    "Neo-Geo": 142,
    "Nintendo 64": 14,
    "Nintendo DS": 15,
    "Nintendo DSi": 15,
    "Nintendo Entertainment System": 3,
    "Odyssey2": 104,
    "PC Engine": 31,
    "PC Engine CD": 114,
    "PC Engine SuperGrafx": 105,
    "PC-9800": 208,
    "PlayStation": 57,
    "PlayStation 2": 58,
    "PlayStation 3": 59,
    "PlayStation Portable": 61,
    "PlayStation Vita": 62,
    "Pokemon Mini": 211,
    "PV-1000": 74,
    "Satellaview": 107,
    "Saturn": 22,
    "ScummVM": 123,
    "Sega 32X": 19,
    "Sega Pico": 250,
    "SG-1000": 109,
    "Sharp X1": 220,
    "SuFami Turbo": 108,
    "Super A'Can": 100,
    "Super Cassette Vision": 67,
    "Super Nintendo Entertainment System": 4,
    "Supervision": 207,
    "Switch (1Fichier)": 225,
    "TI-99": 205,
    "V.Smile": 120,
    "Vectrex": 102,
    "Virtual Boy": 11,
    "Wii": 16,
    "Wii (Virtual Console)": 16,
    "Wii U": 18,
    "Windows (1Fichier)": 138,
    "WonderSwan": 45,
    "WonderSwan Color": 46,
    "Xbox": 32,
    "Xbox 360": 33,
    "ZX Spectrum": 76,
}

# Media kind -> ScreenScraper media types, in order of preference
MEDIA_TYPES = {"box": ("box-2D",), "ss": ("ss",), "logo": ("wheel-hd", "wheel")}
REGION_ORDER = ("wor", "us", "eu", "ss", "jp")
# Media are resized server side: enough for the preview panel, saves disk space and download time.
MEDIA_MAX_WIDTH = 640

# Daily quota from the last API response: (remaining_today, max_per_day) or None
LAST_ALLOWANCE = None
# Quota counters from the last ssuser block. The API docs make quota handling by the client mandatory.
QUOTA = {}
_request_lock = threading.Lock()
_last_request_at = 0.0


class ScreenScraperError(Exception):
    """kind: 'quota' | 'auth' | 'config' | 'network' | 'http' | 'unsupported'"""

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind


def get_credentials():
    """Return (dev_id, dev_password, softname). Environment variables win over the generated file."""
    try:
        import screenscraper_credentials as generated
    except ImportError:
        generated = None

    def value(name, default=""):
        return str(os.environ.get(name) or getattr(generated, name, "") or default).strip()

    return value("SCREENSCRAPER_DEV_ID"), value("SCREENSCRAPER_DEV_PASSWORD"), value("SCREENSCRAPER_SOFTNAME", "RGSX")


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


def get_system_id(platform_name):
    return SYSTEM_IDS.get(normalize_scraper_platform_name(platform_name))


def _api_get(endpoint, params, timeout=20):
    """Call the API and return JSON, or None when the game is not found (HTTP 404)."""
    dev_id, dev_password, softname = get_credentials()
    if not dev_id or not dev_password:
        raise ScreenScraperError("auth", "ScreenScraper developer credentials missing")
    username, password = load_account()
    if username and password:
        params = {"ssid": username, "sspassword": password, **params}
    global _last_request_at
    with _request_lock:
        # Stay under the per-minute limit (maxrequestspermin) instead of waiting for HTTP 429.
        max_per_min = QUOTA.get("max_min")
        if max_per_min:
            wait = _last_request_at + 60.0 / max_per_min - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        _last_request_at = time.monotonic()
    try:
        response = requests.get(
            f"{API_BASE_URL}/{endpoint}",
            params={"devid": dev_id, "devpassword": dev_password, "softname": softname, "output": "json", **params},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        # str(exc) contains the URL with the credentials
        raise ScreenScraperError("network", type(exc).__name__)

    # Status codes from the ScreenScraper API v2 documentation
    status = response.status_code
    if status == 200:
        try:
            return response.json()
        except ValueError:
            raise ScreenScraperError("http", "invalid JSON response")
    if status == 404:
        return None
    if status in (430, 431):
        # 430: daily request quota reached, 431: daily quota of unrecognized ROMs reached
        raise ScreenScraperError("quota", f"HTTP {status}")
    if status in (403, 426):
        # 403: wrong developer credentials, 426: software blacklisted or obsolete
        raise ScreenScraperError("auth", f"HTTP {status}")
    if status in (401, 423, 429) or status >= 500:
        # 401: API closed for non-members (server load), 423: API closed, 429: too many requests/threads
        raise ScreenScraperError("network", f"HTTP {status}")
    raise ScreenScraperError("http", f"HTTP {status}")


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


def get_user_info():
    """Refresh the quota (works without an account too) and return LAST_ALLOWANCE.

    With an account, raises ScreenScraperError("auth") when the login is not accepted.
    """
    dev_id, dev_password, _ = get_credentials()
    if not dev_id or not dev_password:
        # Not the user's fault: this build has no developer credentials
        raise ScreenScraperError("config", "ScreenScraper developer credentials missing")
    username, password = load_account()
    data = _api_get("ssuserInfos.php", {})
    ssuser = ((data or {}).get("response") or {}).get("ssuser") or {}
    if username and password:
        # niveau 0 / another pseudo: the username/password pair was not accepted
        returned_id = str(ssuser.get("id") or "")
        if str(ssuser.get("niveau") or "0") == "0" or (returned_id and returned_id.lower() != username.lower()):
            raise ScreenScraperError("auth", "ScreenScraper login refused")
    _update_allowance(ssuser)
    return LAST_ALLOWANCE


def _pick_media(medias, media_types):
    """Return (url, ext) of the best media for the given types, preferring world/US/EU regions."""
    for media_type in media_types:
        candidates = [m for m in medias if m.get("type") == media_type and m.get("url")]
        if candidates:
            best = min(candidates, key=lambda m: REGION_ORDER.index(m.get("region")) if m.get("region") in REGION_ORDER else len(REGION_ORDER))
            return f"{best['url']}&maxwidth={MEDIA_MAX_WIDTH}", "." + str(best.get("format") or "jpg").lower()
    return None


def fetch_game_media(rom_filename, system_id, kinds):
    """Return a game's media: {"box": (url, ext), "ss": ..., "logo": ...}, or None if the game is not found.

    One API request per game; ScreenScraper matches the ROM file name inside the given system.
    No crc/md5/sha1 + romtaille: the ROM is not downloaded yet and catalog sizes are rounded.
    """
    _check_quota()
    data = _api_get("jeuInfos.php", {
        "systemeid": system_id,
        "romtype": "rom",
        "romnom": os.path.basename(str(rom_filename)),
    })
    response = (data or {}).get("response") or {}
    if response.get("ssuser"):
        _update_allowance(response["ssuser"])
    else:
        # ssuser is not sent with every response (and never with a 404): count locally.
        _update_allowance({"requeststoday": QUOTA.get("today", 0) + 1,
                           "requestskotoday": QUOTA.get("ko_today", 0) + (data is None)})
    game = response.get("jeu")
    if not game:
        return None
    medias = game.get("medias") or []
    urls = {}
    for kind in kinds:
        media = _pick_media(medias, MEDIA_TYPES[kind])
        if media:
            urls[kind] = media
    # Without box art, fall back to a screenshot for the preview.
    if "box" in kinds and "box" not in urls:
        media = _pick_media(medias, MEDIA_TYPES["ss"])
        if media:
            urls["box"] = media
    return urls

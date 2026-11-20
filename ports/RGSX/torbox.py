"""Client TorBox (https://api-docs.torbox.app/).

Envoie un lien web ou un fichier .torrent sur le compte TorBox de l'utilisateur, attend que
TorBox ait le fichier sur ses serveurs, puis renvoie un lien CDN direct pour le télécharger.
"""
import logging
import time

import requests  # type: ignore

logger = logging.getLogger(__name__)

API_BASE = "https://api.torbox.app/v1/api"

ERROR_MESSAGES = {
    "BAD_TOKEN": "TB: Invalid API key",
    "AUTH_ERROR": "TB: Authentication error",
    "NO_AUTH": "TB: No credentials provided",
    "PLAN_RESTRICTED_FEATURE": "TB: Plan upgrade required",
    "DOWNLOAD_TOO_LARGE": "TB: Download too large for plan",
    "MONTHLY_LIMIT": "TB: Monthly limit reached",
    "COOLDOWN_LIMIT": "TB: Download cooldown active",
    "ACTIVE_LIMIT": "TB: Max active downloads reached",
    "LINK_OFFLINE": "TB: Link offline or inaccessible",
    "ITEM_NOT_FOUND": "TB: Item not found",
    "UNSUPPORTED_SITE": "TB: Site not supported",
    "TEMPORARILY_DISABLED": "TB: Site temporarily disabled",
    "INVALID_LINK": "TB: Invalid link",
    "BOZO_TORRENT": "TB: Invalid torrent file",
    "NO_SERVERS_AVAILABLE_ERROR": "TB: No servers available",
    "DOWNLOAD_SERVER_ERROR": "TB: Download server error",
}

# Limite du plan le plus élevé (Pro) d'après la table d'erreurs DOWNLOAD_TOO_LARGE de la doc.
# TorBox ajoute toujours le torrent entier : au-delà, aucun plan ne peut l'accepter.
MAX_PLAN_DOWNLOAD_BYTES = 536870912000

# Etats TorBox indiquant un échec définitif côté serveur
_FAILED_STATES = ("error", "failed", "missingfiles")


class TorBoxError(RuntimeError):
    def __init__(self, message: str, code: str | None = None, data=None):
        super().__init__(message)
        self.code = code or ""
        self.data = data


class TorBoxCanceled(TorBoxError):
    pass


def _raise_for_payload(payload, status_code: int):
    payload = payload if isinstance(payload, dict) else {}
    code = str(payload.get("error") or "")
    detail = str(payload.get("detail") or "")
    data = payload.get("data")
    if code in ERROR_MESSAGES:
        raise TorBoxError(ERROR_MESSAGES[code], code, data)
    if detail or code:
        raise TorBoxError(f"TB: {detail or code}", code, data)
    raise TorBoxError(f"TB: Unexpected response (HTTP {status_code})", code, data)


def _call(method: str, endpoint: str, api_key: str, *, auth_param: bool = False, **kwargs):
    """Appelle l'API et renvoie `data` si `success` est vrai, sinon lève TorBoxError."""
    params = dict(kwargs.pop("params", None) or {})
    headers = dict(kwargs.pop("headers", None) or {})
    if auth_param:
        params["token"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = requests.request(method, f"{API_BASE}/{endpoint}", params=params, headers=headers,
                            timeout=kwargs.pop("timeout", 30), **kwargs)
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict) and payload.get("success") is True:
        return payload.get("data"), payload
    _raise_for_payload(payload, resp.status_code)


def _find_item(list_endpoint: str, api_key: str, predicate):
    data, _payload = _call("GET", list_endpoint, api_key, params={"bypass_cache": "true"})
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and predicate(item):
            return item
    return None


def _wait_until_present(list_endpoint: str, item_id, api_key: str, cancel_event=None, status_callback=None,
                        timeout: float = 3600, poll_interval: float = 5):
    """Interroge `mylist` jusqu'à ce que TorBox ait le fichier (`download_present`)."""
    deadline = time.time() + timeout
    while True:
        if cancel_event is not None and cancel_event.is_set():
            raise TorBoxCanceled("TB: Canceled")
        try:
            data, _payload = _call("GET", list_endpoint, api_key, params={"id": item_id, "bypass_cache": "true"})
        except requests.RequestException as e:
            logger.debug(f"TorBox mylist erreur transitoire: {e}")
            data = None
        item = data[0] if isinstance(data, list) and data else data
        if isinstance(item, dict):
            state = str(item.get("download_state") or "")
            logger.debug(f"TorBox {list_endpoint} id={item_id}: state={state} progress={item.get('progress')} present={item.get('download_present')}")
            if status_callback is not None:
                try:
                    status_callback(item)
                except Exception:
                    pass
            if item.get("download_present"):
                return item
            if any(s in state.lower() for s in _FAILED_STATES) or (list_endpoint.startswith("webdl") and item.get("error")):
                raise TorBoxError(f"TB: Download failed ({item.get('error') or state})")
        if time.time() >= deadline:
            raise TorBoxError("TB: Download not ready (timeout)")
        if cancel_event is not None:
            if cancel_event.wait(poll_interval):
                raise TorBoxCanceled("TB: Canceled")
        else:
            time.sleep(poll_interval)


def _bencode_end(buf: bytes, i: int) -> int:
    """Renvoie l'index juste après la valeur bencodée commençant à `i`."""
    c = buf[i:i + 1]
    if c == b"i":
        return buf.index(b"e", i) + 1
    if c in (b"l", b"d"):
        i += 1
        while buf[i:i + 1] != b"e":
            i = _bencode_end(buf, i)
        return i + 1
    colon = buf.index(b":", i)
    return colon + 1 + int(buf[i:colon])


def torrent_info_hash(torrent_bytes: bytes) -> str | None:
    """Info-hash v1 (SHA1 du dictionnaire `info`), utilisé par TorBox comme `hash`."""
    import hashlib
    try:
        if torrent_bytes[:1] != b"d":
            return None
        i = 1
        while torrent_bytes[i:i + 1] != b"e":
            key_end = _bencode_end(torrent_bytes, i)
            key = torrent_bytes[torrent_bytes.index(b":", i) + 1:key_end]
            value_end = _bencode_end(torrent_bytes, key_end)
            if key == b"info":
                return hashlib.sha1(torrent_bytes[key_end:value_end]).hexdigest()
            i = value_end
    except (ValueError, IndexError):
        return None
    return None


def _normalize_path(path: str) -> str:
    return str(path or "").replace("\\", "/").strip("/")


def select_file(files, relative_path: str | None = None, size_bytes: int = 0):
    """Choisit le fichier TorBox correspondant au chemin du torrent (ou le plus gros fichier)."""
    files = [f for f in (files or []) if isinstance(f, dict) and f.get("id") is not None]
    if not files:
        return None
    target = _normalize_path(relative_path or "")
    if target:
        base = target.rsplit("/", 1)[-1]
        for f in files:
            name = _normalize_path(f.get("name") or f.get("absolute_path") or "")
            if name == target or name.endswith("/" + target) or target.endswith("/" + name):
                return f
        same_name = [f for f in files if _normalize_path(f.get("short_name") or f.get("name") or "").rsplit("/", 1)[-1] == base]
        if size_bytes > 0:
            sized = [f for f in same_name if int(f.get("size") or 0) == size_bytes]
            if sized:
                return sized[0]
        if same_name:
            return same_name[0]
        if size_bytes > 0:
            sized = [f for f in files if int(f.get("size") or 0) == size_bytes]
            if len(sized) == 1:
                return sized[0]
        return None
    return max(files, key=lambda f: int(f.get("size") or 0))


def resolve_web_download(link: str, api_key: str, cancel_event=None, status_callback=None,
                         timeout: float = 1800, poll_interval: float = 5) -> dict:
    """Ajoute `link` aux Web Downloads TorBox et renvoie {'url', 'name', 'size', 'id'}."""
    webdl_id = None
    try:
        data, _payload = _call("POST", "webdl/createwebdownload", api_key, data={"link": link})
        if isinstance(data, dict):
            webdl_id = data.get("webdownload_id") or data.get("webdl_id") or data.get("id")
    except TorBoxError as e:
        if e.code != "DUPLICATE_ITEM":
            raise
        if isinstance(e.data, dict):
            webdl_id = e.data.get("webdownload_id") or e.data.get("webdl_id") or e.data.get("id")
    if webdl_id is None:
        existing = _find_item("webdl/mylist", api_key, lambda it: it.get("original_url") == link)
        if existing is None:
            raise TorBoxError("TB: No web download id returned")
        webdl_id = existing.get("id")
    logger.info(f"TorBox web download ajouté: id={webdl_id}")

    item = _wait_until_present("webdl/mylist", webdl_id, api_key, cancel_event, status_callback, timeout, poll_interval)
    chosen = select_file(item.get("files"))
    file_id = chosen.get("id") if chosen else 0
    url, _payload = _call("GET", "webdl/requestdl", api_key, auth_param=True,
                          params={"web_id": webdl_id, "file_id": file_id})
    if not url:
        raise TorBoxError("TB: No download link returned")
    return {
        "url": str(url),
        "name": (chosen or {}).get("short_name") or item.get("name"),
        "size": int((chosen or {}).get("size") or item.get("size") or 0),
        "id": webdl_id,
    }


def resolve_torrent(torrent_bytes: bytes, api_key: str, relative_path: str | None = None, size_bytes: int = 0,
                    name: str | None = None, cancel_event=None, status_callback=None,
                    timeout: float = 3600, poll_interval: float = 5) -> dict:
    """Ajoute le .torrent aux Torrents TorBox et renvoie {'url', 'name', 'size', 'id'} du fichier voulu."""
    torrent_id = None
    torrent_hash = torrent_info_hash(torrent_bytes)
    try:
        files = {"file": ((name or "download") + ".torrent", torrent_bytes, "application/x-bittorrent")}
        data, _payload = _call("POST", "torrents/createtorrent", api_key, files=files,
                               data={"allow_zip": "false"}, timeout=60)
        if isinstance(data, dict):
            torrent_id = data.get("torrent_id") or data.get("id")
            torrent_hash = data.get("hash") or torrent_hash
    except TorBoxError as e:
        if e.code != "DUPLICATE_ITEM":
            raise
        if isinstance(e.data, dict):
            torrent_id = e.data.get("torrent_id") or e.data.get("id")
    if torrent_id is None:
        if not torrent_hash:
            raise TorBoxError("TB: No torrent id returned")
        existing = _find_item("torrents/mylist", api_key, lambda it: str(it.get("hash") or "").lower() == str(torrent_hash).lower())
        if existing is None:
            raise TorBoxError("TB: No torrent id returned")
        torrent_id = existing.get("id")
    logger.info(f"TorBox torrent ajouté: id={torrent_id} hash={torrent_hash}")

    item = _wait_until_present("torrents/mylist", torrent_id, api_key, cancel_event, status_callback, timeout, poll_interval)
    chosen = select_file(item.get("files"), relative_path, size_bytes)
    if chosen is None:
        raise TorBoxError(f"TB: File not found in torrent ({relative_path})")
    url, _payload = _call("GET", "torrents/requestdl", api_key, auth_param=True,
                          params={"torrent_id": torrent_id, "file_id": chosen.get("id")})
    if not url:
        raise TorBoxError("TB: No download link returned")
    return {
        "url": str(url),
        "name": chosen.get("short_name") or chosen.get("name"),
        "size": int(chosen.get("size") or 0),
        "id": torrent_id,
    }

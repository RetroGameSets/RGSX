import json
import logging
import os
import re
import shutil
import hashlib
import signal
import stat
import subprocess
import threading
import time

import requests  # type: ignore
import socket

import config
from language import _  # noqa: F401 (garde la cohérence des messages traduits)

logger = logging.getLogger(__name__)


class BackendUnavailableError(RuntimeError):
    """qBittorrent n'a pas pu démarrer ou s'authentifier (pas une erreur de
    téléchargement)."""


# Port WebUI cible pour l'instance qBittorrent pilotée par RGSX : distinct du port par défaut (8080) pour ne jamais entrer en conflit avec une éventuelle instance personnelle de l'utilisateur.
_TARGET_PORT = 18572
_DEFAULT_USERNAME = "admin"
_CONFIGURED_PASSWORD = str(getattr(config, "TORRENT_QBITTORRENT_WEBUI_PASSWORD", "") or "")
_STARTUP_TIMEOUT_SECONDS = 120
_TEMP_PASSWORD_PATTERNS = [
    re.compile(r"temporary password.*?:\s*([^\s]+)", re.IGNORECASE),
    re.compile(r"mot de passe temporaire.*?:\s*([^\s]+)", re.IGNORECASE),
]

_PROGS_DIR = os.path.join(config.APP_FOLDER, "assets", "progs")
_PORTABLE_7Z = os.path.join(_PROGS_DIR, "qbittorrent-portable.7z")
_NOX_LINUX = os.path.join(_PROGS_DIR, "qbittorrent-nox_linux")
_extract_dir = os.path.join(config.CONFIG_FOLDER, "qbittorrent-portable")
_profile_dir = os.path.join(config.CONFIG_FOLDER, "qbt_profile")

# Base URL courante du WebUI : mutable, mise à jour une fois le port final connu
# (immédiatement pour Linux, après reconfiguration pour Windows).
_base_url = f"http://127.0.0.1:{_TARGET_PORT}"


def _url(path: str) -> str:
    return f"{_base_url}{path}"


def _extract_portable_windows() -> str | None:
    """Extrait qbittorrent-portable.7z (une seule fois) dans CONFIG_FOLDER, qui est
    toujours inscriptible (contrairement à APP_FOLDER, parfois en lecture seule).
    Retourne le lanceur qbittorrent-portable.exe : lancer app\\qbittorrent.exe
    directement plante (le lanceur configure des variables d'environnement Qt
    nécessaires, ex. QT_PLUGIN_PATH, absentes sinon)."""
    launcher_path = os.path.join(_extract_dir, "qbittorrent-portable.exe")
    if os.path.isfile(launcher_path):
        return launcher_path
    if not os.path.isfile(_PORTABLE_7Z):
        return None
    seven_zip = getattr(config, "SEVEN_Z_EXE", os.path.join(_PROGS_DIR, "7z.exe"))
    try:
        os.makedirs(_extract_dir, exist_ok=True)
        result = subprocess.run(
            [seven_zip, "x", _PORTABLE_7Z, f"-o{_extract_dir}", "-y"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if result.returncode != 0:
            logger.error("qbittorrent_backend: extraction 7z échouée: %s", result.stdout[-500:])
            return None
    except Exception as exc:
        logger.error("qbittorrent_backend: extraction qbittorrent-portable.7z échouée: %s", exc)
        return None
    return launcher_path if os.path.isfile(launcher_path) else None


def _ensure_ini_settings(ini_path: str, settings: "dict[str, dict[str, str]]") -> None:
    """Insère les clés manquantes dans un .ini existant sans toucher au reste (préserve
    les clés déjà présentes, même si l'utilisateur ou qBittorrent les a modifiées depuis
    - évite de régénérer/réordonner un profil déjà fonctionnel à chaque lancement)."""
    lines: list[str] = []
    if os.path.isfile(ini_path):
        with open(ini_path, "r", encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()

    remaining = {section: dict(keys) for section, keys in settings.items()}
    section_name = None
    out_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section_name in remaining and remaining[section_name]:
                for key, value in remaining.pop(section_name).items():
                    out_lines.append(f"{key}={value}\n")
            section_name = stripped[1:-1]
        elif section_name in remaining and "=" in stripped:
            remaining[section_name].pop(stripped.split("=", 1)[0].strip(), None)
        out_lines.append(line)
    if section_name in remaining and remaining[section_name]:
        for key, value in remaining.pop(section_name).items():
            out_lines.append(f"{key}={value}\n")
    for section, keys in remaining.items():
        if not keys:
            continue
        if out_lines and not out_lines[-1].endswith("\n"):
            out_lines.append("\n")
        out_lines.append(f"[{section}]\n")
        for key, value in keys.items():
            out_lines.append(f"{key}={value}\n")

    os.makedirs(os.path.dirname(ini_path), exist_ok=True)
    with open(ini_path, "w", encoding="utf-8") as handle:
        handle.writelines(out_lines)


def _preseed_windows_profile() -> None:
    """Écrit/complète qBittorrent.ini AVANT chaque lancement pour accepter la popup
    "Legal notice", fixer le port WebUI et démarrer directement minimisé dans la zone de
    notification (jamais de fenêtre au premier plan), sans dépendre du passage
    d'arguments par le lanceur Portapps (qui ne les transmet pas à l'exécutable réel).
    Clés confirmées par un lancement manuel réel : [LegalNotice] Accepted=true."""
    config_dir = os.path.join(_extract_dir, "data", "profile", "qBittorrent", "config")
    ini_path = os.path.join(config_dir, "qBittorrent.ini")
    _ensure_ini_settings(ini_path, {
        "LegalNotice": {"Accepted": "true"},
        "Preferences": {
            "General\\Locale": "en_US",
            "WebUI\\Enabled": "true",
            "WebUI\\Port": str(_TARGET_PORT),
            "WebUI\\Address": "0.0.0.0",
            "WebUI\\LocalHostAuth": "false",
            "WebUI\\AuthSubnetWhitelistEnabled": "false",
            "General\\SystemTrayEnabled": "true",
            "General\\StartMinimized": "true",
            "General\\MinimizeToTray": "true",
            "General\\CloseToTray": "true",
            # Evite le popup "Torrent file association" au premier lancement.
            # Certaines versions utilisent la clé historiquement mal orthographiée.
            "Win32\\NeverCheckFileAssocation": "true",
            "Win32\\NeverCheckFileAssociation": "true",
        },
    })

    # Migration de sécurité: une version précédente a pu écrire un profil Windows
    # "localhost-only". Si ce pattern est détecté, on le relaxe pour rétablir
    # l'accès WebUI depuis le LAN sans écraser des personnalisations utilisateur.
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        if "WebUI\\Address=127.0.0.1" in content and "WebUI\\AuthSubnetWhitelist=127.0.0.1/32" in content:
            updated = content.replace("WebUI\\Address=127.0.0.1", "WebUI\\Address=0.0.0.0")
            updated = updated.replace("WebUI\\AuthSubnetWhitelistEnabled=true", "WebUI\\AuthSubnetWhitelistEnabled=false")
            if updated != content:
                with open(ini_path, "w", encoding="utf-8") as handle:
                    handle.write(updated)
                logger.info("qbittorrent_backend: migration profil Windows WebUI localhost-only -> LAN activée")
    except Exception as exc:
        logger.debug("qbittorrent_backend: migration profil Windows WebUI ignorée: %s", exc)


def _preseed_linux_profile(webui_port: int) -> None:
    """Prépare un profil qBittorrent-nox stable et indépendant de la langue système.

    On force la locale en anglais pour normaliser les logs. On évite de forcer
    des clés réseau restrictives (bind localhost / whitelist locale) afin de ne
    pas casser un accès WebUI LAN voulu par l'utilisateur.
    """
    config_dir = os.path.join(_profile_dir, "qBittorrent", "config")
    ini_path = os.path.join(config_dir, "qBittorrent.conf")
    _ensure_ini_settings(ini_path, {
        "LegalNotice": {"Accepted": "true"},
        "Preferences": {
            "General\\Locale": "en_US",
            "WebUI\\Enabled": "true",
            "WebUI\\Port": str(webui_port),
            "WebUI\\LocalHostAuth": "false",
        },
    })

    # Migration de sécurité: une version précédente a pu écrire un profil Linux
    # "localhost-only". Si ce pattern est détecté, on le relaxe pour rétablir
    # l'accès WebUI depuis le LAN sans toucher aux configurations personnalisées.
    try:
        with open(ini_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
        if "WebUI\\Address=127.0.0.1" in content and "WebUI\\AuthSubnetWhitelist=127.0.0.1/32" in content:
            updated = content.replace("WebUI\\Address=127.0.0.1", "WebUI\\Address=0.0.0.0")
            updated = updated.replace("WebUI\\AuthSubnetWhitelistEnabled=true", "WebUI\\AuthSubnetWhitelistEnabled=false")
            if updated != content:
                with open(ini_path, "w", encoding="utf-8") as handle:
                    handle.write(updated)
                logger.info("qbittorrent_backend: migration profil Linux WebUI localhost-only -> LAN activée")
    except Exception as exc:
        logger.debug("qbittorrent_backend: migration profil Linux WebUI ignorée: %s", exc)


def _find_qbittorrent_executable() -> str | None:
    """Localise l'exécutable qBittorrent à utiliser : binaire embarqué en priorité,
    sinon une installation déjà présente sur la machine."""
    if config.OPERATING_SYSTEM == "Windows":
        bundled = _extract_portable_windows()
        if bundled:
            return bundled
        candidates = [
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "qBittorrent", "qbittorrent.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "qBittorrent", "qbittorrent.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "qBittorrent", "qbittorrent.exe"),
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate):
                return candidate
        resolved = shutil.which("qbittorrent.exe") or shutil.which("qbittorrent")
        if resolved:
            return resolved
        try:
            result = subprocess.run(
                ["reg", "query", r"HKLM\SOFTWARE\qBittorrent", "/v", "InstallDir"],
                capture_output=True, text=True, timeout=5, check=False,
            )
            match = re.search(r"InstallDir\s+REG_SZ\s+(.+)", result.stdout)
            if match:
                exe_path = os.path.join(match.group(1).strip(), "qbittorrent.exe")
                if os.path.isfile(exe_path):
                    return exe_path
        except Exception as exc:
            logger.debug("qbittorrent_backend: lecture registre échouée: %s", exc)
        return None

    # Linux/Batocera : binaire headless embarqué (statique) en priorité.
    if os.path.isfile(_NOX_LINUX):
        try:
            mode = os.stat(_NOX_LINUX).st_mode
            os.chmod(_NOX_LINUX, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        except Exception as exc:
            logger.debug("qbittorrent_backend: chmod +x échoué sur %s: %s", _NOX_LINUX, exc)
        return _NOX_LINUX
    for name in ("qbittorrent-nox", "qbittorrent"):
        resolved = shutil.which(name)
        if resolved:
            return resolved
    return None


def is_available() -> bool:
    """Indique si un fallback qBittorrent est utilisable sur cette machine."""
    return _find_qbittorrent_executable() is not None


_launch_lock = threading.Lock()
_qbt_process: "subprocess.Popen | None" = None
_prewarm_lock = threading.Lock()
_prewarm_thread: "threading.Thread | None" = None


def _suppress_qbittorrent_window_windows(launcher_pid: int | None, duration_seconds: float = 8.0) -> None:
    """Empêche qBittorrent de voler le focus au démarrage sur Windows.

    Le lanceur portable peut brièvement afficher une fenêtre avant la minimisation
    interne de qBittorrent. Cette routine masque agressivement toute fenêtre
    qBittorrent détectée pendant quelques secondes.
    """
    if config.OPERATING_SYSTEM != "Windows":
        return

    def _run() -> None:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            SW_HIDE = 0
            WM_CLOSE = 0x0010
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

            def _query_process_image_name(pid: int) -> str:
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
                if not handle:
                    return ""
                try:
                    size = wintypes.DWORD(32768)
                    buffer = ctypes.create_unicode_buffer(size.value)
                    if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                        return (buffer.value or "").strip().lower()
                except Exception:
                    return ""
                finally:
                    try:
                        kernel32.CloseHandle(handle)
                    except Exception:
                        pass
                return ""

            # Cache PID -> appartient (ou non) a qBittorrent pendant cette courte fenêtre.
            process_match_cache: dict[int, bool] = {}

            def _is_qbittorrent_pid(pid: int) -> bool:
                if pid in process_match_cache:
                    return process_match_cache[pid]
                image_path = _query_process_image_name(pid)
                image_name = os.path.basename(image_path)
                match = (
                    image_name in ("qbittorrent.exe", "qbittorrent-nox.exe")
                    or "qbittorrent" in image_name
                )
                process_match_cache[pid] = match
                return match

            enum_windows_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            end_time = time.time() + max(duration_seconds, 1.0)
            while time.time() < end_time:
                handles_to_hide: list[int] = []

                @enum_windows_proc
                def _enum_cb(hwnd, _lparam):
                    if not user32.IsWindowVisible(hwnd):
                        return True

                    title_len = user32.GetWindowTextLengthW(hwnd)
                    title = ""
                    if title_len > 0:
                        buf = ctypes.create_unicode_buffer(title_len + 1)
                        user32.GetWindowTextW(hwnd, buf, title_len + 1)
                        title = (buf.value or "").strip()

                    window_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
                    pid = int(window_pid.value)
                    pid_matches = launcher_pid is not None and pid == int(launcher_pid)
                    process_matches = _is_qbittorrent_pid(pid)

                    # Ferme immédiatement la popup d'association torrent/magnet qui
                    # bloque le bootstrap WebUI au premier lancement.
                    title_lower = title.lower()
                    if (pid_matches or process_matches) and "torrent file association" in title_lower:
                        try:
                            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                        except Exception:
                            pass
                        return True

                    if pid_matches or process_matches:
                        handles_to_hide.append(int(hwnd))
                    return True

                user32.EnumWindows(_enum_cb, 0)

                for hwnd in handles_to_hide:
                    try:
                        user32.ShowWindow(wintypes.HWND(hwnd), SW_HIDE)
                    except Exception:
                        pass

                time.sleep(0.2)
        except Exception as exc:
            logger.debug("qbittorrent_backend: suppression fenêtre Windows non disponible: %s", exc)

    threading.Thread(target=_run, daemon=True, name="qbt-hide-window").start()


def _wait_for_webui(session: requests.Session, base_url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = session.get(f"{base_url}/api/v2/app/version", timeout=2)
            # Sur qBittorrent, l’endpoint répond parfois 403 au premier appel tant que
            # l’UI n’a pas encore fini son bootstrap ou tant qu’un login n’est pas établi.
            if resp.status_code in (200, 403):
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(0.5)
    return False


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            sock.connect((host, port))
            return True
    except OSError:
        return False


def _find_free_webui_port() -> int:
    return _TARGET_PORT


def _probe_existing_webui_session(webui_port: int) -> "requests.Session | None":
    session = requests.Session()
    base_url = f"http://127.0.0.1:{webui_port}"
    if not _wait_for_webui(session, base_url, timeout=3):
        return None
    if not _login(session, base_url, []):
        return None
    return session


def _terminate_existing_qbittorrent_processes() -> None:
    if config.OPERATING_SYSTEM == "Windows":
        try:
            subprocess.run(["taskkill", "/F", "/IM", "qbittorrent.exe", "/T"], check=False, capture_output=True, text=True)
        except Exception as exc:
            logger.debug("qbittorrent_backend: impossible de tuer l'instance qBittorrent Windows: %s", exc)
        return

    try:
        result = subprocess.run(["ps", "-eo", "pid=,comm="], capture_output=True, text=True, check=False)
    except Exception as exc:
        logger.debug("qbittorrent_backend: impossible de lister les processus qBittorrent: %s", exc)
        return

    pids_to_kill: list[int] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid_text, cmd = parts[0], parts[1]
        cmd_lower = cmd.lower()
        if "qbittorrent" in cmd_lower and "python" not in cmd_lower:
            try:
                pids_to_kill.append(int(pid_text))
            except ValueError:
                continue

    for pid in pids_to_kill:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
        except Exception:
            pass

    time.sleep(1.0)
    for pid in pids_to_kill:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
        else:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass


def _login(session: requests.Session, base_url: str, stdout_lines: "list[str]", timeout: float = 8.0) -> bool:
    headers = {"Referer": base_url, "Origin": base_url, "X-Requested-With": "XMLHttpRequest"}

    def _try_localhost_bypass() -> bool:
        try:
            resp = session.get(f"{base_url}/api/v2/app/preferences", timeout=3)
            if resp.status_code == 200:
                logger.debug("qbittorrent_backend: WebUI localhost accessible sans login")
                return True
        except requests.exceptions.RequestException:
            pass
        return False

    def _extract_temp_password() -> str | None:
        for line in stdout_lines:
            for pattern in _TEMP_PASSWORD_PATTERNS:
                match = pattern.search(line)
                if match:
                    return match.group(1).strip()
        return None

    def _is_banned_response(status_code: int, body: str) -> bool:
        if status_code != 403:
            return False
        lowered = body.lower()
        ban_markers = [
            "banni",
            "banned",
            "too many",
            "too_many",
            "rate limit",
            "ip has been banned",
        ]
        return any(marker in lowered for marker in ban_markers)

    def _try(username: str, password: str, label: str) -> tuple[bool, bool]:
        try:
            session.cookies.clear()
            resp = session.post(
                f"{base_url}/api/v2/auth/login",
                data={"username": username, "password": password},
                headers=headers,
                timeout=5,
            )
            body = resp.text.strip().lower()
            # Certaines versions/builds de qBittorrent renvoient 204 (No Content)
            # quand l'authentification réussit, au lieu de 200 "Ok.".
            if (resp.status_code == 200 and body.startswith("ok")) or resp.status_code == 204:
                logger.debug("qbittorrent_backend: authentification WebUI réussie via %s", label)
                return True, False
            logger.debug("qbittorrent_backend: tentative auth WebUI (%s) refusée: status=%s, body=%s", label, resp.status_code, body[:120])
            if _is_banned_response(resp.status_code, body):
                logger.warning("qbittorrent_backend: WebUI a signalé un bannissement temporaire IP pendant l'authentification")
                return False, True
            return False, False
        except requests.exceptions.RequestException:
            return False, False

    password_candidates: list[tuple[str, str]] = []

    # Le mot de passe temporaire est prioritaire au premier démarrage pour éviter
    # une rafale d'échecs sur des mots de passe persistants potentiellement faux.
    temp_password = _extract_temp_password()
    if temp_password:
        password_candidates.append((temp_password, "temporary"))

    if _CONFIGURED_PASSWORD:
        password_candidates.append((_CONFIGURED_PASSWORD, "configured"))

    attempted_passwords: set[str] = set()
    for password, label in password_candidates:
        ok, banned = _try(_DEFAULT_USERNAME, password, label)
        attempted_passwords.add(password)
        if ok:
            return True
        if banned:
            return False

    if _try_localhost_bypass():
        return True

    deadline = time.time() + timeout
    while time.time() < deadline:
        temp_password = _extract_temp_password()
        if temp_password and temp_password not in attempted_passwords:
            ok, banned = _try(_DEFAULT_USERNAME, temp_password, "temporary")
            attempted_passwords.add(temp_password)
            if ok:
                return True
            if banned:
                return False

        if temp_password:
            ok, banned = _try(_DEFAULT_USERNAME, temp_password, "temporary")
            if ok:
                return True
            if banned:
                return False

        if _try_localhost_bypass():
            return True
        time.sleep(0.25)

    return False


def _ensure_qbittorrent_running() -> "requests.Session | None":
    """Démarre (si besoin) l'instance qBittorrent dédiée à RGSX et retourne une
    session HTTP authentifiée sur son WebUI, ou None en cas d'échec."""
    global _qbt_process, _base_url

    session = requests.Session()
    with _launch_lock:
        if _qbt_process is not None and _qbt_process.poll() is None:
            if _wait_for_webui(session, _base_url, timeout=_STARTUP_TIMEOUT_SECONDS) and _login(session, _base_url, []):
                return session
            return None

        for candidate_port in [_TARGET_PORT]:
            existing_session = _probe_existing_webui_session(candidate_port)
            if existing_session is not None:
                _base_url = f"http://127.0.0.1:{candidate_port}"
                logger.info("qbittorrent_backend: réutilisation d'une instance qBittorrent existante sur le port %s", candidate_port)
                return existing_session

        exe_path = _find_qbittorrent_executable()
        if not exe_path:
            return None

        os.makedirs(_profile_dir, exist_ok=True)
        is_windows = config.OPERATING_SYSTEM == "Windows"
        webui_port = _TARGET_PORT if is_windows else _find_free_webui_port()
        if not is_windows and _is_port_open("127.0.0.1", webui_port):
            logger.warning("qbittorrent_backend: port WebUI %s déjà occupé, tentative de fermeture d'une instance qBittorrent précédente", webui_port)
            _terminate_existing_qbittorrent_processes()
            time.sleep(1.0)
        if is_windows:
            # Le port WebUI et l'acceptation de la popup "Legal notice" sont pré-écrits
            # dans qBittorrent.ini avant le premier lancement (voir _preseed_windows_profile) :
            # le lanceur Portapps ne transmet pas d'arguments CLI au binaire réel, donc
            # --webui-port/--confirm-legal-notice n'auraient aucun effet ici.
            _preseed_windows_profile()
            cmd = [exe_path]
        else:
            _preseed_linux_profile(webui_port)
            cmd = [exe_path, f"--profile={_profile_dir}", f"--webui-port={webui_port}", "--confirm-legal-notice"]
        bootstrap_url = f"http://127.0.0.1:{webui_port}"
        logger.info("qbittorrent_backend: démarrage de %s sur le port WebUI %s", exe_path, webui_port)

        stdout_lines: list[str] = []
        try:
            popen_kwargs = {
                "cwd": os.path.dirname(exe_path) or None,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "bufsize": 1,
            }

            if is_windows:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

                creationflags = 0
                if hasattr(subprocess, "CREATE_NO_WINDOW"):
                    creationflags |= subprocess.CREATE_NO_WINDOW

                popen_kwargs.update({
                    "stdin": subprocess.DEVNULL,
                    "startupinfo": startupinfo,
                    "creationflags": creationflags,
                })

            process = subprocess.Popen(cmd, **popen_kwargs)
        except Exception as exc:
            logger.error("qbittorrent_backend: impossible de lancer qBittorrent: %s", exc)
            return None

        if is_windows:
            _suppress_qbittorrent_window_windows(getattr(process, "pid", None), duration_seconds=8.0)

        def _drain() -> None:
            if not process.stdout:
                return
            for line in iter(process.stdout.readline, ""):
                if line:
                    stdout_lines.append(line)
                    logger.debug("[qbittorrent] %s", line.strip())

        threading.Thread(target=_drain, daemon=True).start()
        _qbt_process = process

        if not _wait_for_webui(session, bootstrap_url, timeout=_STARTUP_TIMEOUT_SECONDS):
            logger.warning("qbittorrent_backend: WebUI indisponible après %ss (%s attendu)", _STARTUP_TIMEOUT_SECONDS, bootstrap_url)
            return None

        if not _login(session, bootstrap_url, stdout_lines):
            logger.warning("qbittorrent_backend: authentification WebUI échouée")
            return None

        try:
            session.post(
                f"{bootstrap_url}/api/v2/app/setPreferences",
                data={"json": json.dumps({
                    "bypass_local_auth": True,
                    "web_ui_port": webui_port,
                    "web_ui_username": _DEFAULT_USERNAME,
                    "web_ui_password": _CONFIGURED_PASSWORD,
                    "dht": True,
                    "pex": True,
                    "lsd": True,
                    "bittorrent_protocol": 0,  # TCP + µTP
                    "encryption": 0,  # préférer le chiffrement sans l'exiger
                })},
                headers={"Referer": bootstrap_url},
                timeout=5,
            )
        except requests.exceptions.RequestException as exc:
            logger.debug("qbittorrent_backend: setPreferences initial échoué: %s", exc)

        # Après setPreferences, certaines versions invalident le cookie de session.
        # On force une nouvelle authentification pour garantir une session valide.
        session = requests.Session()
        if not _wait_for_webui(session, bootstrap_url, timeout=5):
            logger.warning("qbittorrent_backend: WebUI indisponible après application des préférences")
            return None
        if not _login(session, bootstrap_url, stdout_lines):
            logger.warning("qbittorrent_backend: authentification échouée après application des préférences")
            return None

        _base_url = f"http://127.0.0.1:{webui_port}"
        if bootstrap_url != _base_url:
            # Le port WebUI vient de changer : qBittorrent redémarre son serveur HTTP,
            # il faut se reconnecter sur le nouveau port avant de continuer.
            session = requests.Session()
            if not _wait_for_webui(session, _base_url, timeout=_STARTUP_TIMEOUT_SECONDS):
                logger.warning("qbittorrent_backend: WebUI indisponible sur le port cible %s après reconfiguration", _TARGET_PORT)
                return None
            if not _login(session, _base_url, stdout_lines):
                logger.warning("qbittorrent_backend: authentification échouée sur le port cible après reconfiguration")
                return None

        return session


def _torrent_info_by_tag(session: requests.Session, tag: str) -> dict | None:
    try:
        resp = session.get(_url("/api/v2/torrents/info"), params={"tag": tag}, timeout=5)
        resp.raise_for_status()
        items = resp.json()
        return items[0] if items else None
    except requests.exceptions.RequestException:
        return None


def _torrent_info_by_hash(session: requests.Session, torrent_hash: str) -> dict | None:
    try:
        resp = session.get(_url("/api/v2/torrents/info"), params={"hashes": torrent_hash}, timeout=5)
        resp.raise_for_status()
        items = resp.json()
        return items[0] if items else None
    except requests.exceptions.RequestException:
        return None


def _find_existing_torrent_by_save_path(session: requests.Session, save_path: str) -> dict | None:
    try:
        resp = session.get(_url("/api/v2/torrents/info"), params={"category": "rgsx"}, timeout=5)
        resp.raise_for_status()
        items = resp.json() or []
    except requests.exceptions.RequestException:
        return None

    wanted = os.path.normpath(save_path)
    for item in items:
        item_save_path = os.path.normpath(str(item.get("save_path") or ""))
        if item_save_path == wanted:
            return item
    return None


def _torrent_files(session: requests.Session, torrent_hash: str) -> list[dict]:
    try:
        resp = session.get(_url("/api/v2/torrents/files"), params={"hash": torrent_hash}, timeout=5)
        resp.raise_for_status()
        return resp.json() or []
    except requests.exceptions.RequestException:
        return []


def _resolve_target_file_index(files: list[dict], relative_path: str) -> int | None:
    normalized_target = relative_path.replace("\\", "/").strip("/")
    for file_info in files:
        idx = file_info.get("index")
        if idx is None:
            continue
        name = str(file_info.get("name") or "").replace("\\", "/")
        if name == normalized_target or name.endswith("/" + normalized_target):
            try:
                return int(idx)
            except Exception:
                continue
    return None


def _count_active_peers(session: requests.Session, torrent_hash: str, field: str) -> int:
    """Nombre de pairs actuellement CONNECTÉS ET échangeant réellement des données sur
    `field` ("dl_speed" en téléchargement, "up_speed" en seed). Plus parlant que
    `num_seeds` (pairs ayant 100% du contenu) qui reste souvent à 0 sur un petit swarm
    alors que le transfert avance normalement via des leechers."""
    try:
        resp = session.get(_url("/api/v2/sync/torrentPeers"), params={"hash": torrent_hash}, timeout=5)
        resp.raise_for_status()
        peers = resp.json().get("peers") or {}
        return sum(1 for peer in peers.values() if float(peer.get(field) or 0) > 0)
    except requests.exceptions.RequestException:
        return 0


def _apply_file_selection(session: requests.Session, torrent_hash: str, relative_path: str) -> tuple[int | None, int]:
    """Ne télécharger que le fichier ciblé dans un torrent multi-fichiers (ex: gros pack collection)."""
    files = _torrent_files(session, torrent_hash)
    if not files:
        return None, 0
    if len(files) <= 1:
        single_size = 0
        try:
            single_size = int(files[0].get("size") or files[0].get("length") or 0)
        except Exception:
            single_size = 0
        return 0, single_size

    target_index = _resolve_target_file_index(files, relative_path)
    if target_index is None:
        logger.warning("qbittorrent_backend: impossible de résoudre le fichier cible pour %s", relative_path)
        return None, 0

    target_size = 0
    for file_info in files:
        try:
            if int(file_info.get("index") or -1) == target_index:
                target_size = int(file_info.get("size") or file_info.get("length") or 0)
                break
        except Exception:
            continue

    with _selected_file_indexes_lock:
        selected_indexes = _selected_file_indexes_by_hash.setdefault(torrent_hash, set())
        selected_indexes.add(target_index)
        selected_snapshot = set(selected_indexes)

    other_indexes = []
    selected_sorted = []
    for file_info in files:
        idx = file_info.get("index")
        if idx is None:
            continue
        try:
            normalized_idx = int(idx)
        except Exception:
            continue
        if normalized_idx in selected_snapshot:
            selected_sorted.append(normalized_idx)
        else:
            other_indexes.append(normalized_idx)

    try:
        if other_indexes:
            session.post(
                _url("/api/v2/torrents/filePrio"),
                data={"hash": torrent_hash, "id": "|".join(str(i) for i in sorted(other_indexes)), "priority": 0},
                headers={"Referer": _base_url}, timeout=5,
            )
        if selected_sorted:
            session.post(
                _url("/api/v2/torrents/filePrio"),
                data={"hash": torrent_hash, "id": "|".join(str(i) for i in sorted(selected_sorted)), "priority": 1},
                headers={"Referer": _base_url}, timeout=5,
            )
    except requests.exceptions.RequestException as exc:
        logger.debug("qbittorrent_backend: application priorités fichiers échouée: %s", exc)
    return target_index, target_size


def _get_target_file_progress(files: list[dict], target_file_index: int | None, fallback_size: int) -> tuple[int, int, bool]:
    if target_file_index is None:
        normalized_size = max(0, int(fallback_size or 0))
        return 0, normalized_size, False

    for file_info in files:
        idx = file_info.get("index")
        if idx is None:
            continue
        try:
            normalized_idx = int(idx)
        except Exception:
            continue
        if normalized_idx != target_file_index:
            continue

        try:
            file_size = int(file_info.get("size") or file_info.get("length") or fallback_size or 0)
        except Exception:
            file_size = int(fallback_size or 0)
        try:
            file_progress = float(file_info.get("progress") or 0.0)
        except Exception:
            file_progress = 0.0

        normalized_size = max(0, file_size)
        downloaded_bytes = min(normalized_size, max(0, int(round(normalized_size * file_progress))))
        return downloaded_bytes, normalized_size, file_progress >= 1.0

    normalized_size = max(0, int(fallback_size or 0))
    return 0, normalized_size, False


_STATE_PHASE_MAP = {
    "metaDL": "connecting",
    "allocating": "connecting",
    "checkingResumeData": "verifying",
    "checkingDL": "verifying",
    "checkingUP": "verifying",
    "stalledDL": "waiting",
    "downloading": "downloading",
    "forcedDL": "downloading",
    "queuedDL": "connecting",
}
_DONE_STATES = {"pausedUP", "uploading", "stalledUP", "forcedUP", "queuedUP", "checkingUP"}
_ERROR_STATES = {"error", "missingFiles"}

# Suivi des torrents laissés en seed dans qBittorrent après un téléchargement réussi.
# qBittorrent garde le torrent enregistré dans sa propre base tant qu'on ne demande pas
# sa suppression explicitement (stop_seed) - il reprendra le seed tout seul au prochain lancement.
_active_qbt_downloads: dict[str, dict] = {}
_active_qbt_seeds: dict[str, dict] = {}
_active_qbt_refs_lock = threading.Lock()
_selected_file_indexes_by_hash: dict[str, set[int]] = {}
_selected_file_indexes_lock = threading.Lock()


def _register_active_download(task_id: str, torrent_hash: str, original_history_url: str, target_file_index: int | None) -> None:
    with _active_qbt_refs_lock:
        _active_qbt_downloads[task_id] = {
            "hash": torrent_hash,
            "original_history_url": original_history_url,
            "target_file_index": target_file_index,
        }


def _promote_active_download_to_seed(task_id: str, seed_info: dict) -> None:
    with _active_qbt_refs_lock:
        _active_qbt_downloads.pop(task_id, None)
        _active_qbt_seeds[task_id] = seed_info


def _pop_active_reference(task_id: str | None = None, original_history_url: str | None = None) -> tuple[str | None, dict | None]:
    with _active_qbt_refs_lock:
        if task_id:
            seed_entry = _active_qbt_seeds.pop(task_id, None)
            if seed_entry is not None:
                return task_id, seed_entry
            download_entry = _active_qbt_downloads.pop(task_id, None)
            if download_entry is not None:
                return task_id, download_entry

        if original_history_url:
            for tracked_task_id, info in list(_active_qbt_seeds.items()):
                if info.get("original_history_url") == original_history_url:
                    return tracked_task_id, _active_qbt_seeds.pop(tracked_task_id, None)
            for tracked_task_id, info in list(_active_qbt_downloads.items()):
                if info.get("original_history_url") == original_history_url:
                    return tracked_task_id, _active_qbt_downloads.pop(tracked_task_id, None)

    return None, None


def _has_other_hash_references(torrent_hash: str, exclude_task_id: str | None = None) -> bool:
    with _active_qbt_refs_lock:
        for tracked_task_id, info in _active_qbt_downloads.items():
            if tracked_task_id == exclude_task_id:
                continue
            if info.get("hash") == torrent_hash:
                return True
        for tracked_task_id, info in _active_qbt_seeds.items():
            if tracked_task_id == exclude_task_id:
                continue
            if info.get("hash") == torrent_hash:
                return True
    return False


def _cleanup_hash_state_if_unused(torrent_hash: str) -> None:
    if not torrent_hash or _has_other_hash_references(torrent_hash):
        return
    with _selected_file_indexes_lock:
        _selected_file_indexes_by_hash.pop(torrent_hash, None)


def is_process_running() -> bool:
    return _qbt_process is not None and _qbt_process.poll() is None


def prewarm_startup() -> bool:
    """Best effort: démarre/réutilise qBittorrent dès le lancement de RGSX.
    Retourne True si une session WebUI est prête, sinon False."""
    session = None
    try:
        session = _ensure_qbittorrent_running()
        if session is None:
            logger.info("qbittorrent_backend: pré-lancement indisponible (binaire absent ou auth impossible)")
            return False
        logger.info("qbittorrent_backend: pré-lancement OK, WebUI prête")
        return True
    except Exception as exc:
        logger.debug("qbittorrent_backend: pré-lancement échoué: %s", exc)
        return False
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


def prewarm_startup_async() -> None:
    """Déclenche un pré-lancement non bloquant de qBittorrent (au plus un thread)."""
    global _prewarm_thread

    if is_process_running():
        return

    with _prewarm_lock:
        if _prewarm_thread is not None and _prewarm_thread.is_alive():
            return

        def _runner() -> None:
            global _prewarm_thread
            try:
                prewarm_startup()
            finally:
                with _prewarm_lock:
                    _prewarm_thread = None

        _prewarm_thread = threading.Thread(
            target=_runner,
            name="qbt-prewarm-startup",
            daemon=True,
        )
        _prewarm_thread.start()


def has_active_seed(task_id: str | None = None, original_history_url: str | None = None) -> bool:
    """Indique si un seed qBittorrent est suivi pour ce task_id/URL DANS CETTE SESSION
    RGSX (évite de démarrer qBittorrent inutilement pour un arrêt qui ne le concerne pas)."""
    if task_id and task_id in _active_qbt_seeds:
        return True
    if original_history_url:
        return any(info.get("original_history_url") == original_history_url for info in _active_qbt_seeds.values())
    return False


def _seed_status_worker(task_id: str, session: "requests.Session") -> None:
    """Met à jour périodiquement le statut 'Seeding' (peers/vitesse UL) dans l'historique
    RGSX tant que le torrent reste dans qBittorrent. Import tardif de network pour éviter
    un import circulaire (network importe déjà ce module au niveau module)."""
    import network as _network
    while True:
        entry = _active_qbt_seeds.get(task_id)
        if entry is None:
            return
        try:
            info = _torrent_info_by_tag(session, entry["tag"])
        except requests.exceptions.RequestException:
            time.sleep(3.0)
            continue
        if info is None:
            _, removed_entry = _pop_active_reference(task_id=task_id)
            if removed_entry is not None:
                _cleanup_hash_state_if_unused(str(removed_entry.get("hash") or ""))
            return
        ul_speed = float(info.get("upspeed") or 0) / (1024 * 1024)
        # Même logique côté seed : `num_seeds` reste souvent à 0 alors qu'on upload réellement
        # à des leechers (peers partiels) ; on affiche plutôt le nombre de pairs à qui on
        # envoie actuellement des données (up_speed>0).
        active_uploaders = _count_active_peers(session, entry["hash"], "up_speed") if ul_speed > 0 else 0
        try:
            _network._update_seeding_status(entry["original_history_url"], peers=active_uploaders, ul_speed=ul_speed)
        except Exception:
            pass
        time.sleep(3.0)


def stop_seed(task_id: str | None = None, original_history_url: str | None = None) -> bool:
    """Arrête un seed qBittorrent actif : supprime le torrent + ses fichiers."""
    if not has_active_seed(task_id, original_history_url) and not is_process_running():
        return False

    task_id, entry = _pop_active_reference(task_id=task_id, original_history_url=original_history_url)
    if not task_id:
        return False
    tag = entry["tag"] if entry else f"rgsx_{task_id}"
    torrent_hash = str(entry.get("hash") or "") if entry else ""

    if torrent_hash and _has_other_hash_references(torrent_hash, exclude_task_id=task_id):
        history_url = original_history_url or (entry.get("original_history_url") if entry else "")
        if history_url:
            try:
                import network as _network
                _network._stop_seeding_status(history_url)
            except Exception:
                pass
        logger.info("qbittorrent_backend: seed détaché pour task_id=%s, torrent conservé car encore partagé", task_id)
        return True

    session = requests.Session()
    if not (_wait_for_webui(session, _base_url, timeout=5) and _login(session, _base_url, [])):
        _cleanup_hash_state_if_unused(torrent_hash)
        return False
    info = _torrent_info_by_tag(session, tag)
    if info is None:
        _cleanup_hash_state_if_unused(torrent_hash)
        return entry is not None
    try:
        session.post(_url("/api/v2/torrents/delete"),
                     data={"hashes": info["hash"], "deleteFiles": "true"},
                     headers={"Referer": _base_url}, timeout=5)
    except requests.exceptions.RequestException as exc:
        logger.debug("qbittorrent_backend: suppression torrent échouée: %s", exc)
        return False

    history_url = original_history_url or (entry.get("original_history_url") if entry else "")
    if history_url:
        try:
            import network as _network
            _network._stop_seeding_status(history_url)
        except Exception:
            pass
    _cleanup_hash_state_if_unused(torrent_hash or str(info.get("hash") or ""))
    logger.info("qbittorrent_backend: seed arrêté pour task_id=%s", task_id)
    return True


def download_torrent_via_qbittorrent(
    torrent_meta: dict,
    dest_dir: str,
    dest_path: str,
    task_id: str,
    cancel_ev,
    progress_queue,
    original_history_url: str = "",
    pause_ev=None,
) -> tuple[bool, str]:
    """Télécharge un torrent via une installation qBittorrent existante (WebUI API)."""
    source_url = str(torrent_meta.get("source_url") or "")
    relative_path = str(torrent_meta.get("relative_path") or "").strip() or os.path.basename(dest_path)
    fallback_name = os.path.basename(relative_path) or os.path.basename(dest_path)
    total_size = int(torrent_meta.get("size_bytes") or 0)
    tag = f"rgsx_{task_id}"

    if progress_queue is not None:
        progress_queue.put((task_id, 0, total_size, 0.0, 0, 0, "qbt_initializing"))
    session = _ensure_qbittorrent_running()
    if session is None:
        raise BackendUnavailableError("qBittorrent introuvable, non démarré ou authentification échouée")

    if progress_queue is not None:
        progress_queue.put((task_id, 0, total_size, 0.0, 0, 0, "qbt_fetching_metadata"))
    headers = _build_torrent_headers()
    torrent_bytes = requests.get(source_url, timeout=30, headers=headers).content

    source_key = hashlib.sha1(source_url.encode("utf-8", errors="ignore")).hexdigest()[:12]
    temp_dir = os.path.join(dest_dir, ".rgsx_torrent", source_key)
    os.makedirs(temp_dir, exist_ok=True)
    download_completed = False
    registered_download_reference = False

    try:
        if progress_queue is not None:
            progress_queue.put((task_id, 0, total_size, 0.0, 0, 0, "qbt_adding_torrent"))
        files = {"torrents": (fallback_name + ".torrent", torrent_bytes, "application/x-bittorrent")}
        data = {"savepath": temp_dir, "tags": tag, "category": "rgsx"}
        resp = session.post(_url("/api/v2/torrents/add"), files=files, data=data,
                             headers={"Referer": _base_url}, timeout=15)
        torrent_hash = None
        if resp.status_code == 409:
            logger.info("qbittorrent_backend: torrent déjà présent, réutilisation de l'instance existante")
            info = _find_existing_torrent_by_save_path(session, temp_dir)
            if info:
                torrent_hash = str(info.get("hash") or "")
        else:
            resp.raise_for_status()
            deadline = time.time() + 10
            while time.time() < deadline and torrent_hash is None:
                info = _find_existing_torrent_by_save_path(session, temp_dir)
                if info:
                    torrent_hash = info.get("hash")
                else:
                    time.sleep(0.5)
        if not torrent_hash:
            raise RuntimeError("qBittorrent n'a pas confirmé l'ajout du torrent")

        target_file_index, target_file_size = _apply_file_selection(session, torrent_hash, relative_path)
        _register_active_download(task_id, torrent_hash, original_history_url, target_file_index)
        registered_download_reference = True
        reported_total_size = target_file_size or total_size
        if progress_queue is not None:
            progress_queue.put((task_id, 0, reported_total_size, 0.0, 0, 0, "qbt_searching_peers"))

        while True:
            if cancel_ev is not None and cancel_ev.is_set():
                if registered_download_reference:
                    _pop_active_reference(task_id=task_id)
                    registered_download_reference = False
                if not _has_other_hash_references(torrent_hash, exclude_task_id=task_id):
                    try:
                        session.post(_url("/api/v2/torrents/delete"),
                                     data={"hashes": torrent_hash, "deleteFiles": "true"},
                                     headers={"Referer": _base_url}, timeout=5)
                    except requests.exceptions.RequestException:
                        pass
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    _cleanup_hash_state_if_unused(torrent_hash)
                raise RuntimeError(_("download_canceled") if _ else "Download canceled")

            if pause_ev is not None and pause_ev.is_set():
                # Vraie pause côté qBittorrent (pas juste un arrêt du polling RGSX) : le
                # torrent reste enregistré, juste suspendu, aucune donnée n'est perdue.
                try:
                    session.post(_url("/api/v2/torrents/pause"),
                                 data={"hashes": torrent_hash}, headers={"Referer": _base_url}, timeout=5)
                except requests.exceptions.RequestException as exc:
                    logger.debug("qbittorrent_backend: mise en pause échouée: %s", exc)
                info = _torrent_info_by_hash(session, torrent_hash)
                file_entries = _torrent_files(session, torrent_hash)
                downloaded, size, _file_completed = _get_target_file_progress(
                    file_entries,
                    target_file_index,
                    int(target_file_size or (info or {}).get("size") or total_size or 0),
                )
                if size > 0:
                    progress_queue.put((task_id, downloaded, size, 0.0, 0, 0, "qbt_paused"))
                while pause_ev.is_set():
                    if cancel_ev is not None and cancel_ev.is_set():
                        break
                    time.sleep(0.3)
                try:
                    session.post(_url("/api/v2/torrents/resume"),
                                 data={"hashes": torrent_hash}, headers={"Referer": _base_url}, timeout=5)
                except requests.exceptions.RequestException as exc:
                    logger.debug("qbittorrent_backend: reprise échouée: %s", exc)
                continue

            info = _torrent_info_by_hash(session, torrent_hash)
            if info is None:
                time.sleep(1.0)
                continue

            state = str(info.get("state") or "")
            file_entries = _torrent_files(session, torrent_hash)
            downloaded, size, file_completed = _get_target_file_progress(
                file_entries,
                target_file_index,
                int(target_file_size or info.get("size") or total_size or 0),
            )
            if target_file_index is None:
                downloaded = int(info.get("downloaded") or 0)
                size = int(target_file_size or info.get("size") or total_size or 0)
            speed_mib_s = float(info.get("dlspeed") or 0) / (1024 * 1024)
            # `num_seeds` (pairs ayant 100% du contenu) reste souvent à 0 sur un petit swarm et
            # prête à confusion dans l'UI ("0SD" alors que le téléchargement avance bien) : on
            # affiche plutôt le nombre de pairs qui nous envoient réellement des données là.
            active_senders = _count_active_peers(session, torrent_hash, "dl_speed") if speed_mib_s > 0 else 0
            peers = int(info.get("num_leechs") or 0) + int(info.get("num_seeds") or 0)
            state_phase = _STATE_PHASE_MAP.get(state, "waiting")
            phase = {
                "connecting": "qbt_connecting",
                "waiting": "qbt_searching_peers",
                "verifying": "qbt_verifying",
                "downloading": "qbt_downloading",
            }.get(state_phase, "qbt_searching_peers")
            if size > 0 or progress_queue is not None:
                progress_queue.put((task_id, min(downloaded, size), size, speed_mib_s, active_senders, peers, phase))

            if state in _ERROR_STATES:
                raise RuntimeError(f"qBittorrent: état d'erreur ({state})")

            if file_completed or state in _DONE_STATES or float(info.get("progress") or 0) >= 1.0:
                content_path = str(info.get("content_path") or "")
                downloaded_path = _resolve_downloaded_file(content_path, temp_dir, relative_path, fallback_name)
                if not downloaded_path or not os.path.isfile(downloaded_path):
                    raise FileNotFoundError(f"Fichier téléchargé introuvable pour {relative_path}")
                # Le téléchargement lui-même est terminé et intact à partir d'ici : un échec
                # de finalisation (hard-link/copie vers dest_path) ne doit plus effacer
                # temp_dir (voir except plus bas), au risque de perdre des données réelles
                # pour un incident de post-traitement seulement.
                download_completed = True
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                # Ne JAMAIS déplacer/supprimer le fichier suivi par qBittorrent : le torrent
                # reste enregistré et continue de seeder (suppression uniquement via
                # stop_seed, sur demande explicite de l'utilisateur - annulation/suppression/
                # arrêt du partage). On copie donc le résultat vers dest_path (hard-link si
                # même volume, copie classique en repli) sans toucher au fichier source.
                try:
                    os.link(downloaded_path, dest_path)
                except OSError:
                    shutil.copy2(downloaded_path, dest_path)
                _promote_active_download_to_seed(task_id, {
                    "hash": torrent_hash, "tag": tag, "dest_path": dest_path,
                    "original_history_url": original_history_url,
                })
                registered_download_reference = False
                if original_history_url:
                    threading.Thread(
                        target=_seed_status_worker, args=(task_id, session),
                        name=f"qbt-seed-{task_id}", daemon=True,
                    ).start()
                final_size = os.path.getsize(dest_path)
                progress_queue.put((task_id, final_size, max(reported_total_size, final_size), 0.0))
                return True, _("network_download_ok").format(os.path.basename(dest_path))

            time.sleep(1.0)
    except Exception:
        if registered_download_reference:
            _pop_active_reference(task_id=task_id)
            registered_download_reference = False
        if not download_completed:
            if not _has_other_hash_references(torrent_hash or "", exclude_task_id=task_id):
                shutil.rmtree(temp_dir, ignore_errors=True)
                _cleanup_hash_state_if_unused(torrent_hash or "")
        raise


def _resolve_downloaded_file(content_path: str, temp_dir: str, relative_path: str, fallback_name: str) -> str | None:
    # Pour un torrent MULTI-fichiers, qBittorrent renvoie souvent le dossier racine du
    # torrent dans content_path (pas le fichier ciblé) : os.path.exists() serait vrai
    # pour ce dossier, provoquant un hard-link/copie vers un répertoire (PermissionError).
    # isfile() exclut ce cas et fait retomber sur la résolution par chemin/nom ci-dessous.
    if content_path and os.path.isfile(content_path):
        return content_path
    normalized_parts = [p for p in relative_path.replace("\\", "/").split("/") if p not in ("", ".")]
    expected = os.path.join(temp_dir, *normalized_parts) if normalized_parts else os.path.join(temp_dir, fallback_name)
    if os.path.isfile(expected):
        return expected
    exact_filename = os.path.basename(relative_path) or fallback_name
    for current_root, _dirs, filenames in os.walk(temp_dir):
        for filename in filenames:
            if filename == exact_filename:
                return os.path.join(current_root, filename)
    return None


def _build_torrent_headers() -> dict:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
    }


def shutdown() -> None:
    """Arrête l'instance qBittorrent dédiée à RGSX (appelée à la fermeture de l'app)."""
    global _qbt_process
    if _qbt_process is not None and _qbt_process.poll() is None:
        try:
            _qbt_process.terminate()
            _qbt_process.wait(timeout=5)
        except Exception:
            try:
                _qbt_process.kill()
            except Exception:
                pass
    _qbt_process = None

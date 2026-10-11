import json
import os
import logging
import re
import threading
import time
import config
import database
from datetime import datetime

logger = logging.getLogger(__name__)

_history_write_state_lock = threading.Lock()
_history_write_failures = 0
_history_write_last_error = ""
_history_write_last_failure_ts = 0.0
_history_write_last_log_ts = 0.0
_history_write_last_probe_ts = 0.0
_history_write_ok = True

_HISTORY_WRITE_FAILURE_COOLDOWN_SEC = 1.5


def _set_history_write_status(ok, error_message=""):
    global _history_write_ok, _history_write_last_error
    with _history_write_state_lock:
        _history_write_ok = bool(ok)
        _history_write_last_error = error_message or ""
        failures = _history_write_failures
        last_failure_ts = _history_write_last_failure_ts

    setattr(config, "history_write_ok", bool(ok))
    setattr(config, "history_write_error", error_message or "")
    setattr(config, "history_write_failure_count", failures)
    setattr(config, "history_write_last_failure_ts", last_failure_ts)


def _register_history_write_failure(exc):
    global _history_write_failures, _history_write_last_failure_ts, _history_write_last_log_ts

    now = time.time()
    raw_error = str(exc)
    message = (
        f"Erreur ecriture history.json: {raw_error}. "
        "Le telechargement continue sans sauvegarde temps reel."
    )

    with _history_write_state_lock:
        _history_write_failures += 1
        _history_write_last_failure_ts = now

    _set_history_write_status(False, message)

    should_log = False
    with _history_write_state_lock:
        if _history_write_failures in (1, 5, 20):
            should_log = True
        elif now - _history_write_last_log_ts >= 5.0:
            should_log = True
        if should_log:
            _history_write_last_log_ts = now

    if should_log:
        logger.error(message)


def _register_history_write_success():
    global _history_write_failures
    recovered = False
    with _history_write_state_lock:
        recovered = _history_write_failures > 0
        _history_write_failures = 0
    _set_history_write_status(True, "")
    if recovered:
        logger.info("Ecriture SQLite de l'historique retablie")


def get_history_write_status():
    with _history_write_state_lock:
        return {
            "ok": _history_write_ok,
            "message": _history_write_last_error,
            "failures": _history_write_failures,
            "last_failure_ts": _history_write_last_failure_ts,
            "last_probe_ts": _history_write_last_probe_ts,
        }


def check_history_write_access(force=False):
    global _history_write_last_probe_ts
    _history_write_last_probe_ts = time.time()
    try:
        database.initialize_database(config.DB_PATH)
        with database.connect(config.DB_PATH) as connection:
            connection.execute("SELECT 1").fetchone()
        _register_history_write_success()
        return True, ""
    except Exception as exc:
        _register_history_write_failure(exc)
        return False, get_history_write_status().get("message", "")


def init_history():
    """Initialise le stockage local SQLite de l'historique."""
    try:
        database.initialize_database(config.DB_PATH)
    except Exception as exc:
        logger.error(f"Erreur lors de l'initialisation SQLite: {exc}")
    check_history_write_access(force=True)
    return config.DB_PATH


def load_history():
    """Charge l'historique depuis la SQLite locale."""
    try:
        history = database.load_history(config.DB_PATH)
        return [
            entry for entry in history
            if isinstance(entry, dict) and all(key in entry for key in ("platform", "game_name", "status"))
        ]
    except Exception as exc:
        logger.error(f"Erreur lors de la lecture de l'historique SQLite: {exc}")
        return []


def save_history(history, force=False):
    """Sauvegarde l'historique dans la SQLite locale."""
    now = time.time()
    state = get_history_write_status()
    if (
        not force
        and not state.get("ok", True)
        and (now - float(state.get("last_failure_ts", 0.0) or 0.0)) < _HISTORY_WRITE_FAILURE_COOLDOWN_SEC
    ):
        return False
    try:
        database.save_history(history, config.DB_PATH)
        _register_history_write_success()
        return True
    except Exception as exc:
        _register_history_write_failure(exc)
        return False

def add_to_history(platform, game_name, status, url=None, progress=0, message=None, timestamp=None):
    """Ajoute une entrée à l'historique."""
    history = load_history()
    entry = {
        "platform": platform,
        "game_name": game_name,
        "status": status,
        "url": url,
        "progress": progress,
        "timestamp": timestamp or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    if message:
        entry["message"] = message
    history.append(entry)
    save_history(history)
    logger.info(f"Ajout à l'historique : platform={platform}, game_name={game_name}, status={status}, progress={progress}")
    return entry

def clear_history():
    """Vide l'historique en conservant les téléchargements en cours."""
    history_path = getattr(config, 'HISTORY_PATH')
    try:
        # Charger l'historique actuel
        current_history = load_history()

        active_statuses = {"Downloading", "Téléchargement", "downloading", "Extracting", "Converting", "Queued", "Seeding"}

        active_task_ids = set(getattr(config, 'download_tasks', {}).keys())
        active_progress_urls = set(getattr(config, 'download_progress', {}).keys())
        queued_urls = {
            item.get("url") for item in getattr(config, 'download_queue', [])
            if isinstance(item, dict) and item.get("url")
        }
        queued_task_ids = {
            item.get("task_id") for item in getattr(config, 'download_queue', [])
            if isinstance(item, dict) and item.get("task_id")
        }

        def is_truly_active(entry):
            if not isinstance(entry, dict):
                return False

            status = entry.get("status")
            if status not in active_statuses:
                return False

            task_id = entry.get("task_id")
            url = entry.get("url")

            if status == "Seeding":
                return True

            if status == "Queued":
                return task_id in queued_task_ids or url in queued_urls

            return task_id in active_task_ids or url in active_progress_urls

        preserved_entries = [entry for entry in current_history if is_truly_active(entry)]

        save_history(preserved_entries)
        
        removed_count = len(current_history) - len(preserved_entries)
        logger.info(f"Historique vidé : {history_path} ({removed_count} entrées supprimées, {len(preserved_entries)} conservées)")
    except Exception as e:
        logger.error(f"Erreur lors du vidage de {history_path} : {e}")


# ==================== GESTION DES JEUX TÉLÉCHARGÉS ====================

IGNORED_ROM_SCAN_EXTENSIONS = {
    '.bak', '.bmp', '.db', '.gif', '.ini', '.jpeg', '.jpg', '.json', '.log', '.mp4',
    '.nfo', '.pdf', '.png', '.srm', '.sav', '.state', '.svg', '.txt', '.webp', '.xml'
}


def normalize_downloaded_game_name(game_name):
    """Normalise un nom de jeu pour les comparaisons en ignorant extension et tags."""
    if not isinstance(game_name, str):
        return ""

    normalized = os.path.basename(game_name.strip())
    if not normalized:
        return ""

    normalized = os.path.splitext(normalized)[0]
    normalized = re.sub(r'\s*[\[(][^\])]*[\])]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized)
    return normalized.strip().lower()


def _normalize_downloaded_games_dict(downloaded):
    """Normalise la structure de downloaded_games.json en restant rétrocompatible."""
    normalized_downloaded = {}

    if not isinstance(downloaded, dict):
        return normalized_downloaded

    for platform_name, games in downloaded.items():
        if not isinstance(platform_name, str):
            continue
        if not isinstance(games, dict):
            continue

        normalized_games = {}
        for game_name, metadata in games.items():
            normalized_name = normalize_downloaded_game_name(game_name)
            if not normalized_name:
                continue
            normalized_games[normalized_name] = metadata if isinstance(metadata, dict) else {}

        if normalized_games:
            normalized_downloaded[platform_name] = normalized_games

    return normalized_downloaded


def _count_downloaded_games(downloaded_games_dict):
    return sum(len(games) for games in downloaded_games_dict.values() if isinstance(games, dict))


def scan_roms_for_downloaded_games():
    """Scanne les dossiers ROMs et ajoute les jeux trouvés à downloaded_games.json."""
    from utils import load_games

    downloaded = _normalize_downloaded_games_dict(getattr(config, 'downloaded_games', {}))
    platform_dicts = list(getattr(config, 'platform_dicts', []) or [])

    if not platform_dicts:
        return 0, 0

    scanned_platforms = 0
    added_games = 0

    for platform_entry in platform_dicts:
        if not isinstance(platform_entry, dict):
            continue

        platform_name = (platform_entry.get('platform_name') or '').strip()
        folder_name = (platform_entry.get('folder') or '').strip()
        if not platform_name or not folder_name:
            continue

        roms_path = os.path.join(config.ROMS_FOLDER, folder_name)
        if not os.path.isdir(roms_path):
            continue

        available_games = load_games(platform_name)
        available_names = {
            normalize_downloaded_game_name(game.name)
            for game in available_games
            if normalize_downloaded_game_name(game.name)
        }
        if not available_names:
            continue

        platform_games = downloaded.setdefault(platform_name, {})
        scanned_platforms += 1

        for root, _, filenames in os.walk(roms_path):
            for filename in filenames:
                file_ext = os.path.splitext(filename)[1].lower()
                if file_ext in IGNORED_ROM_SCAN_EXTENSIONS:
                    continue

                normalized_name = normalize_downloaded_game_name(filename)
                if not normalized_name or normalized_name not in available_names:
                    continue

                if normalized_name not in platform_games:
                    platform_games[normalized_name] = {}
                    added_games += 1

    config.downloaded_games = downloaded
    save_downloaded_games(downloaded)
    logger.info(
        "Scan ROMs terminé : %s jeux ajoutés sur %s plateformes",
        added_games,
        scanned_platforms,
    )
    return added_games, scanned_platforms

def load_downloaded_games():
    """Charge la liste des jeux téléchargés depuis la SQLite locale."""
    try:
        downloaded = database.load_downloaded_games(config.DB_PATH)
        normalized_downloaded = _normalize_downloaded_games_dict(downloaded)
        logger.debug(f"Jeux téléchargés chargés depuis SQLite : {_count_downloaded_games(normalized_downloaded)} jeux")
        return normalized_downloaded
    except Exception as exc:
        logger.error(f"Erreur lors de la lecture des jeux téléchargés SQLite: {exc}")
        return {}


def save_downloaded_games(downloaded_games_dict):
    """Sauvegarde la liste des jeux téléchargés dans la SQLite locale."""
    try:
        normalized_downloaded = _normalize_downloaded_games_dict(downloaded_games_dict)
        database.save_downloaded_games(normalized_downloaded, config.DB_PATH)
        logger.debug(f"Jeux téléchargés sauvegardés dans SQLite : {_count_downloaded_games(normalized_downloaded)} jeux")
    except Exception as exc:
        logger.error(f"Erreur lors de l'écriture des jeux téléchargés SQLite: {exc}")


def mark_game_as_downloaded(platform_name, game_name, file_size=None):
    """Marque un jeu comme téléchargé."""
    downloaded = config.downloaded_games
    normalized_name = normalize_downloaded_game_name(game_name)
    if not normalized_name:
        return
    
    if platform_name not in downloaded:
        downloaded[platform_name] = {}
    
    downloaded[platform_name][normalized_name] = {}
    
    # Sauvegarder immédiatement
    save_downloaded_games(downloaded)
    logger.info(f"Jeu marqué comme téléchargé : {platform_name} / {normalized_name}")


def is_game_downloaded(platform_name, game_name):
    """Vérifie si un jeu a déjà été téléchargé."""
    downloaded = config.downloaded_games
    normalized_name = normalize_downloaded_game_name(game_name)
    return bool(normalized_name) and platform_name in downloaded and normalized_name in downloaded.get(platform_name, {})

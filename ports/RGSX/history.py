import json
import os
import logging
import re
import threading
import time
import config
from datetime import datetime

logger = logging.getLogger(__name__)


def _atomic_write_json(target_path, payload):
    temp_path = f"{target_path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp_path, "w", encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        last_error = None
        for attempt in range(5):
            try:
                os.replace(temp_path, target_path)
                last_error = None
                break
            except PermissionError as e:
                last_error = e
                time.sleep(0.15 * (attempt + 1))

        if last_error is not None:
            raise last_error
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass

# Chemin par défaut pour history.json

def init_history():
    """Initialise le fichier history.json s'il n'existe pas."""
    history_path = getattr(config, 'HISTORY_PATH')
    # Vérifie si le fichier history.json existe, sinon le crée
    if not os.path.exists(history_path):
        try:
            os.makedirs(os.path.dirname(history_path), exist_ok=True)
            with open(history_path, "w", encoding='utf-8') as f:
                json.dump([], f)  # Initialise avec une liste vide
            logger.info(f"Fichier d'historique créé : {history_path}")
        except OSError as e:
            logger.error(f"Erreur lors de la création du fichier d'historique : {e}")
    else:
        logger.info(f"Fichier d'historique trouvé : {history_path}")
    return history_path

def load_history():
    """Charge l'historique depuis history.json avec gestion d'erreur robuste."""
    history_path = getattr(config, 'HISTORY_PATH')
    try:
        if not os.path.exists(history_path):
            logger.debug(f"Aucun fichier d'historique trouvé à {history_path}")
            return []
        
        # Vérifier que le fichier n'est pas vide avant de lire
        if os.path.getsize(history_path) == 0:
            logger.warning(f"Fichier history.json vide détecté, retour liste vide")
            return []
        
        with open(history_path, "r", encoding='utf-8') as f:
            content = f.read()
            if not content or content.strip() == '':
                logger.warning(f"Contenu history.json vide, retour liste vide")
                return []
            
            history = json.loads(content)
            
            # Valider la structure : liste de dictionnaires avec 'platform', 'game_name', 'status'
            if not isinstance(history, list):
                logger.warning(f"Format history.json invalide (pas une liste), retour liste vide")
                return []
            
            # Filtrer les entrées valides au lieu de tout rejeter
            valid_entries = []
            invalid_count = 0
            for entry in history:
                if isinstance(entry, dict) and all(key in entry for key in ['platform', 'game_name', 'status']):
                    valid_entries.append(entry)
                else:
                    invalid_count += 1
                    logger.warning(f"Entrée d'historique invalide ignorée : {entry}")
            
            if invalid_count > 0:
                logger.info(f"Historique chargé : {len(valid_entries)} valides, {invalid_count} invalides ignorées")
            #logger.debug(f"Historique chargé depuis {history_path}, {len(valid_entries)} entrées")
            return valid_entries
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors de la lecture de {history_path} : {e}")
        return []
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la lecture de {history_path} : {e}")
        return []

def save_history(history):
    """Sauvegarde l'historique dans history.json de manière atomique."""
    history_path = getattr(config, 'HISTORY_PATH')
    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        _atomic_write_json(history_path, history)
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture de {history_path} : {e}")

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

        active_statuses = {"Downloading", "Téléchargement", "downloading", "Extracting", "Converting", "Queued"}

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
    """Charge la liste des jeux déjà téléchargés depuis downloaded_games.json."""
    downloaded_path = getattr(config, 'DOWNLOADED_GAMES_PATH')
    try:
        if not os.path.exists(downloaded_path):
            logger.debug(f"Aucun fichier downloaded_games.json trouvé à {downloaded_path}")
            return {}
        
        if os.path.getsize(downloaded_path) == 0:
            logger.warning(f"Fichier downloaded_games.json vide")
            return {}
        
        with open(downloaded_path, "r", encoding='utf-8') as f:
            content = f.read()
            if not content or content.strip() == '':
                return {}
            
            downloaded = json.loads(content)
            
            if not isinstance(downloaded, dict):
                logger.warning(f"Format downloaded_games.json invalide (pas un dict)")
                return {}

            normalized_downloaded = _normalize_downloaded_games_dict(downloaded)
            logger.debug(f"Jeux téléchargés chargés : {_count_downloaded_games(normalized_downloaded)} jeux")
            return normalized_downloaded
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors de la lecture de {downloaded_path} : {e}")
        return {}
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la lecture de {downloaded_path} : {e}")
        return {}


def save_downloaded_games(downloaded_games_dict):
    """Sauvegarde la liste des jeux téléchargés dans downloaded_games.json."""
    downloaded_path = getattr(config, 'DOWNLOADED_GAMES_PATH')
    try:
        normalized_downloaded = _normalize_downloaded_games_dict(downloaded_games_dict)
        os.makedirs(os.path.dirname(downloaded_path), exist_ok=True)
        _atomic_write_json(downloaded_path, normalized_downloaded)
        logger.debug(f"Jeux téléchargés sauvegardés : {_count_downloaded_games(normalized_downloaded)} jeux")
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture de {downloaded_path} : {e}")


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

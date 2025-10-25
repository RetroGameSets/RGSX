import json
import os
import logging
import config
from datetime import datetime

logger = logging.getLogger(__name__)

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
        
        # Écriture atomique : écrire dans un fichier temporaire puis renommer
        temp_path = history_path + '.tmp'
        with open(temp_path, "w", encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
            f.flush()  # Forcer l'écriture sur disque
            os.fsync(f.fileno())  # Synchroniser avec le système de fichiers
        
        # Renommer atomiquement (remplace l'ancien fichier)
        os.replace(temp_path, history_path)
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture de {history_path} : {e}")
        # Nettoyer le fichier temporaire en cas d'erreur
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass

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
        
        # Conserver uniquement les entrées avec statut actif (téléchargement, extraction ou conversion en cours)
        # Supporter les deux variantes de statut (anglais et français)
        active_statuses = {"Downloading", "Téléchargement", "downloading", "Extracting", "Converting", "Queued"}
        preserved_entries = [
            entry for entry in current_history 
            if entry.get("status") in active_statuses
        ]
        
        # Sauvegarder l'historique filtré
        with open(history_path, "w", encoding='utf-8') as f:
            json.dump(preserved_entries, f, indent=2, ensure_ascii=False)
        
        removed_count = len(current_history) - len(preserved_entries)
        logger.info(f"Historique vidé : {history_path} ({removed_count} entrées supprimées, {len(preserved_entries)} conservées)")
    except Exception as e:
        logger.error(f"Erreur lors du vidage de {history_path} : {e}")


# ==================== GESTION DES JEUX TÉLÉCHARGÉS ====================

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
            
            logger.debug(f"Jeux téléchargés chargés : {sum(len(v) for v in downloaded.values())} jeux")
            return downloaded
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
        os.makedirs(os.path.dirname(downloaded_path), exist_ok=True)
        
        # Écriture atomique
        temp_path = downloaded_path + '.tmp'
        with open(temp_path, "w", encoding='utf-8') as f:
            json.dump(downloaded_games_dict, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        
        os.replace(temp_path, downloaded_path)
        logger.debug(f"Jeux téléchargés sauvegardés : {sum(len(v) for v in downloaded_games_dict.values())} jeux")
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture de {downloaded_path} : {e}")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except:
            pass


def mark_game_as_downloaded(platform_name, game_name, file_size=None):
    """Marque un jeu comme téléchargé."""
    downloaded = config.downloaded_games
    
    if platform_name not in downloaded:
        downloaded[platform_name] = {}
    
    downloaded[platform_name][game_name] = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "size": file_size or "N/A"
    }
    
    # Sauvegarder immédiatement
    save_downloaded_games(downloaded)
    logger.info(f"Jeu marqué comme téléchargé : {platform_name} / {game_name}")


def is_game_downloaded(platform_name, game_name):
    """Vérifie si un jeu a déjà été téléchargé."""
    downloaded = config.downloaded_games
    return platform_name in downloaded and game_name in downloaded.get(platform_name, {})

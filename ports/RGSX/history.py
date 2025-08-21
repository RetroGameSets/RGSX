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
    """Charge l'historique depuis history.json."""
    history_path = getattr(config, 'HISTORY_PATH')
    try:
        if not os.path.exists(history_path):
            logger.debug(f"Aucun fichier d'historique trouvé à {history_path}")
            return []
        with open(history_path, "r", encoding='utf-8') as f:
            history = json.load(f)
            # Valider la structure : liste de dictionnaires avec 'platform', 'game_name', 'status'
            for entry in history:
                if not all(key in entry for key in ['platform', 'game_name', 'status']):
                    logger.warning(f"Entrée d'historique invalide : {entry}")
                    return []
            #logger.debug(f"Historique chargé depuis {history_path}, {len(history)} entrées")
            return history
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors de la lecture de {history_path} : {e}")
        return []

def save_history(history):
    """Sauvegarde l'historique dans history.json."""
    history_path = getattr(config, 'HISTORY_PATH')
    try:
        os.makedirs(os.path.dirname(history_path), exist_ok=True)
        with open(history_path, "w", encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        logger.debug(f"Historique sauvegardé dans {history_path}")
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
    """Vide l'historique."""
    history_path = getattr(config, 'HISTORY_PATH')
    try:
        with open(history_path, "w", encoding='utf-8') as f:
            json.dump([], f)
        logger.info(f"Historique vidé : {history_path}")
    except Exception as e:
        logger.error(f"Erreur lors du vidage de {history_path} : {e}")
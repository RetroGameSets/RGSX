import json
import os
import logging
import config
from config import HISTORY_PATH

logger = logging.getLogger(__name__)

# Chemin par défaut pour history.json
DEFAULT_HISTORY_PATH = "/userdata/saves/ports/rgsx/history.json"

def init_history():
    """Initialise le fichier history.json s'il n'existe pas."""
    history_path = getattr(config, 'HISTORY_PATH', DEFAULT_HISTORY_PATH)
    if not os.path.exists(history_path):
        try:
            os.makedirs(os.path.dirname(history_path), exist_ok=True)
            with open(history_path, "w") as f:
                json.dump([], f)
            logger.info(f"Fichier history.json créé à {history_path}")
        except Exception as e:
            logger.error(f"Erreur lors de la création de history.json : {e}")
            return False
    return True

def load_history():
    """Charge l'historique depuis history.json."""
    history_path = getattr(config, 'HISTORY_PATH', DEFAULT_HISTORY_PATH)
    try:
        with open(history_path, "r") as f:
            history = json.load(f)
            # Valider la structure : liste de dictionnaires avec 'platform', 'game_name', 'status'
            for entry in history:
                if not all(key in entry for key in ['platform', 'game_name', 'status']):
                    logger.warning(f"Entrée d'historique invalide : {entry}")
                    return []
            return history
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors de la lecture de {history_path} : {e}")
        return []

def save_history(history):
    """Sauvegarde l'historique dans history.json."""
    history_path = getattr(config, 'HISTORY_PATH', DEFAULT_HISTORY_PATH)
    try:
        with open(history_path, "w") as f:
            json.dump(history, f, indent=2)
        logger.debug(f"Historique sauvegardé dans {history_path}")
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture de {history_path} : {e}")

def add_to_history(platform, game_name, status):
    """Ajoute une entrée à l'historique."""
    history = load_history()
    history.append({
        "platform": platform,
        "game_name": game_name,
        "status": status
    })
    save_history(history)
    logger.info(f"Ajout à l'historique : platform={platform}, game_name={game_name}, status={status}")

def clear_history():
    """Vide l'historique."""
    history_path = getattr(config, 'HISTORY_PATH', DEFAULT_HISTORY_PATH)
    try:
        with open(history_path, "w") as f:
            json.dump([], f)
        logger.info(f"Historique vidé : {history_path}")
    except Exception as e:
        logger.error(f"Erreur lors du vidage de {history_path} : {e}")
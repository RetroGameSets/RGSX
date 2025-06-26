import json
import os
import time
from config import cache_dir

HISTORY_FILE = os.path.join(cache_dir, "downloads.json")

def init_history():
    """Initialise le fichier d'historique si non existant."""
    print(f"Initialisation historique: {HISTORY_FILE}")
    try:
        os.makedirs(cache_dir, exist_ok=True)  # Créer le dossier cache si nécessaire
        if not os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, 'w') as f:
                json.dump([], f)
            print("Fichier downloads.json créé")
    except Exception as e:
        print(f"Erreur initialisation historique: {str(e)}")

def add_download(game_name, platform, url, status, error_msg=None):
    """Ajoute une entrée à l'historique."""
    print(f"Ajout à l'historique: {game_name}, {platform}, {status}")
    entry = {
        "game_name": game_name,
        "platform": platform,
        "url": url,
        "status": status,  # "success" ou "failed"
        "error_msg": error_msg if error_msg else "",
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        if not os.path.exists(HISTORY_FILE):
            init_history()  # Réessayer de créer le fichier si absent
        with open(HISTORY_FILE, 'r') as f:
            history = json.load(f)
        history.append(entry)
        with open(HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
        print("Entrée ajoutée à l'historique")
    except Exception as e:
        print(f"Erreur ajout historique: {str(e)}")
        # Ne pas lever d'exception pour éviter le crash

def load_history():
    """Charge l'historique des téléchargements."""
    print(f"Chargement historique depuis {HISTORY_FILE}")
    try:
        if not os.path.exists(HISTORY_FILE):
            init_history()  # Créer le fichier si absent
        with open(HISTORY_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Erreur chargement historique: {str(e)}")
        return []
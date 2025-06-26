import requests
import subprocess
import re
import os
import threading
import pygame
import zipfile
import json
from urllib.parse import urljoin, unquote
import asyncio
import config
from utils import sanitize_filename
import logging

logger = logging.getLogger(__name__)

JSON_EXTENSIONS = "/userdata/roms/ports/RGSX/rom_extensions.json"

def test_internet():
    logger.debug("Test de connexion Internet")
    try:
        result = subprocess.run(['ping', '-c', '4', '8.8.8.8'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.debug("Connexion Internet OK")
            return True
        else:
            logger.debug("Échec ping 8.8.8.8")
            return False
    except Exception as e:
        logger.debug(f"Erreur test Internet: {str(e)}")
        return False

def scrape_games(base_url):
    logger.debug(f"Début scrape_games pour {base_url}")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(base_url, headers=headers, timeout=10)
        logger.debug(f"Status code: {response.status_code}")
        response.raise_for_status()
        html_content = response.text
        zip_files = re.findall(r'href=(?:"|\')?([^"\s]+\.zip)(?:"|\')?', html_content)
        return [(unquote(os.path.basename(f)), urljoin(base_url, f)) for f in zip_files]
    except Exception as e:
        logger.debug(f"Erreur scrape_games: {str(e)}")
        return []

def load_extensions_json():
    """Charge le fichier JSON contenant les extensions supportées."""
    try:
        with open(JSON_EXTENSIONS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de {JSON_EXTENSIONS}: {e}")
        return []

def is_extension_supported(filename, platform, extensions_data):
    """Vérifie si l'extension du fichier est supportée pour la plateforme donnée."""
    extension = os.path.splitext(filename)[1].lower()
    dest_dir = os.path.join("/userdata/roms", platform)
    for system in extensions_data:
        if system["folder"] == dest_dir:
            return extension in system["extensions"]
    logger.warning(f"Aucun système trouvé pour le dossier {dest_dir}")
    return False

def extract_zip(zip_path, dest_dir, url):
    """Extrait le contenu du fichier ZIP dans le dossier cible avec un suivi progressif de la progression."""
    try:
        lock = threading.Lock()
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Calculer la taille totale des fichiers à extraire
            total_size = sum(info.file_size for info in zip_ref.infolist() if not info.is_dir())
            logger.info(f"Taille totale à extraire: {total_size} octets")
            if total_size == 0:
                logger.warning("ZIP vide ou ne contenant que des dossiers")
                return True, "ZIP vide extrait avec succès"

            extracted_size = 0
            os.makedirs(dest_dir, exist_ok=True)

            # Extraire chaque fichier par morceaux
            chunk_size = 8192
            for info in zip_ref.infolist():
                if info.is_dir():
                    continue
                file_path = os.path.join(dest_dir, info.filename)
                # Créer les dossiers parents si nécessaire
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                # Extraire le fichier en lisant par morceaux
                with zip_ref.open(info) as source, open(file_path, 'wb') as dest:
                    file_size = info.file_size
                    file_extracted = 0
                    while True:
                        chunk = source.read(chunk_size)
                        if not chunk:
                            break
                        dest.write(chunk)
                        file_extracted += len(chunk)
                        extracted_size += len(chunk)
                        with lock:
                            config.download_progress[url]["downloaded_size"] = extracted_size
                            config.download_progress[url]["total_size"] = total_size
                            config.download_progress[url]["status"] = "Extracting"
                            config.download_progress[url]["progress_percent"] = (extracted_size / total_size * 100) if total_size > 0 else 0
                        logger.debug(f"Extraction {info.filename}, chunk: {len(chunk)}, file_extracted: {file_extracted}/{file_size}, total_extracted: {extracted_size}/{total_size}, progression: {(extracted_size/total_size*100):.1f}%")
                # Définir les permissions du fichier extrait
                os.chmod(file_path, 0o644)

        # Définir les permissions des dossiers
        for root, dirs, _ in os.walk(dest_dir):
            for dir_name in dirs:
                os.chmod(os.path.join(root, dir_name), 0o755)

        # Supprimer le fichier ZIP
        os.remove(zip_path)
        logger.info(f"Fichier ZIP {zip_path} extrait dans {dest_dir} et supprimé")
        return True, "ZIP extrait avec succès"
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de {zip_path}: {e}")
        return False, str(e)

async def download_rom(url, platform, game_name, is_zip_non_supported=False):
    logger.debug(f"Début téléchargement: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}")
    result = [None, None]  # [success, message]
    
    def download_thread():
        logger.debug(f"Thread téléchargement démarré pour {url}")
        try:
            # Vérification des permissions d'écriture
            dest_dir = os.path.join("/userdata/roms", platform)
            logger.debug(f"Vérification répertoire destination: {dest_dir}")
            os.makedirs(dest_dir, exist_ok=True)
            if not os.access(dest_dir, os.W_OK):
                raise PermissionError(f"Pas de permission d'écriture dans {dest_dir}")
                
            sanitized_name = sanitize_filename(game_name)
            dest_path = os.path.join(dest_dir, f"{sanitized_name}")
            logger.debug(f"Chemin destination: {dest_path}")
            
            # Initialisation de la progression
            lock = threading.Lock()
            with lock:
                config.download_progress[url] = {"downloaded_size": 0, "total_size": 0, "status": "Downloading", "progress_percent": 0}
            logger.debug(f"Progression initialisée pour {url}")
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            logger.debug(f"Envoi requête GET à {url}")
            response = requests.get(url, stream=True, headers=headers, timeout=30)
            logger.debug(f"Réponse reçue, status: {response.status_code}")
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            logger.debug(f"Taille totale: {total_size} octets")
            with lock:
                config.download_progress[url]["total_size"] = total_size
            
            downloaded = 0
            with open(dest_path, 'wb') as f:
                logger.debug(f"Ouverture fichier: {dest_path}")
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        with lock:
                            config.download_progress[url]["downloaded_size"] = downloaded
                            config.download_progress[url]["status"] = "Downloading"
                            config.download_progress[url]["progress_percent"] = (downloaded / total_size * 100) if total_size > 0 else 0
                        #logger.debug(f"Progression: {downloaded}/{total_size} octets")
            
            # Gestion selon le statut de l'extension
            if is_zip_non_supported:
                # Extraire le ZIP non supporté
                with lock:
                    config.download_progress[url]["downloaded_size"] = 0
                    config.download_progress[url]["total_size"] = 0
                    config.download_progress[url]["status"] = "Extracting"
                    config.download_progress[url]["progress_percent"] = 0
                success, msg = extract_zip(dest_path, dest_dir, url)
                if not success:
                    raise Exception(f"Échec de l'extraction du ZIP: {msg}")
                result[0] = True
                result[1] = f"Téléchargé et extrait : {game_name}"
            else:
                # Fichier supporté, définir les permissions
                os.chmod(dest_path, 0o644)
                logger.debug(f"Téléchargement terminé: {dest_path}")
                result[0] = True
                result[1] = f"Téléchargé : {game_name}"
        except Exception as e:
            logger.error(f"Erreur téléchargement {url}: {str(e)}")
            if url in config.download_progress:
                with lock:
                    del config.download_progress[url]
            if os.path.exists(dest_path):
                os.remove(dest_path)
            result[0] = False
            result[1] = str(e)
        finally:
            logger.debug(f"Thread téléchargement terminé pour {url}")

    thread = threading.Thread(target=download_thread)
    logger.debug(f"Démarrage thread pour {url}")
    thread.start()
    while thread.is_alive():
        pygame.event.pump()
        await asyncio.sleep(0.1)  # Attendre que le thread termine
    thread.join()
    logger.debug(f"Thread rejoint pour {url}")
    return result[0], result[1]

def check_extension_before_download(url, platform, game_name):
    """Vérifie l'extension avant de lancer le téléchargement."""
    try:
        sanitized_name = sanitize_filename(game_name)
        extensions_data = load_extensions_json()
        if not extensions_data:
            logger.error(f"Fichier {JSON_EXTENSIONS} vide ou introuvable")
            return False, "Fichier de configuration des extensions introuvable", False
        is_zip = os.path.splitext(sanitized_name)[1].lower() == ".zip"
        if not is_extension_supported(sanitized_name, platform, extensions_data):
            if is_zip:
                return False, "Fichiers compressés non supportés par cette plateforme, extraction automatique après le téléchargement.", True
            return False, f"L'extension de {sanitized_name} n'est pas supportée pour {platform}", False
        return True, "", False
    except Exception as e:
        logger.error(f"Erreur vérification extension {url}: {str(e)}")
        return False, str(e), False
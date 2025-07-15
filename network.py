import requests
import subprocess
import os
import threading
import pygame # type: ignore
import sys
import asyncio
import config
from config import OTA_VERSION_ENDPOINT, OTA_UPDATE_SCRIPT
from utils import sanitize_filename, extract_zip, extract_rar
from history import save_history
import logging
import queue
import time

logger = logging.getLogger(__name__)


cache = {}
CACHE_TTL = 3600  # 1 heure
        
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

async def check_for_updates():
    try:
        logger.debug("Vérification de la version disponible sur le serveur")
        config.current_loading_system = "Mise à jour en cours... Patientez l'ecran reste figé..Puis relancer l'application"
        config.loading_progress = 5.0
        config.needs_redraw = True
        response = requests.get(OTA_VERSION_ENDPOINT, timeout=5)
        response.raise_for_status()
        if response.headers.get("content-type") != "application/json":
            raise ValueError(f"Le fichier version.json n'est pas un JSON valide (type de contenu : {response.headers.get('content-type')})")
        version_data = response.json()
        latest_version = version_data.get("version")
        logger.debug(f"Version distante : {latest_version}, version locale : {config.app_version}")

        if latest_version != config.app_version:
            config.current_loading_system = f"Mise à jour disponible : {latest_version}"
            config.loading_progress = 10.0
            config.needs_redraw = True
            logger.debug(f"Téléchargement du script de mise à jour : {OTA_UPDATE_SCRIPT}")

            update_script_path = "/userdata/roms/ports/rgsx-update.sh"
            logger.debug(f"Téléchargement de {OTA_UPDATE_SCRIPT} vers {update_script_path}")
            with requests.get(OTA_UPDATE_SCRIPT, stream=True, timeout=10) as r:
                r.raise_for_status()
                with open(update_script_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            config.loading_progress = min(50.0, config.loading_progress + 5.0)
                            config.needs_redraw = True
                            await asyncio.sleep(0)

            config.current_loading_system = "Préparation de la mise à jour..."
            config.loading_progress = 60.0
            config.needs_redraw = True
            logger.debug(f"Rendre {update_script_path} exécutable")
            subprocess.run(["chmod", "+x", update_script_path], check=True)
            logger.debug(f"Script {update_script_path} rendu exécutable")

            logger.debug(f"Vérification de l'existence et des permissions de {update_script_path}")
            if not os.path.isfile(update_script_path):
                logger.error(f"Le script {update_script_path} n'existe pas")
                return False, f"Erreur : le script {update_script_path} n'existe pas"
            if not os.access(update_script_path, os.X_OK):
                logger.error(f"Le script {update_script_path} n'est pas exécutable")
                return False, f"Erreur : le script {update_script_path} n'est pas exécutable"

            wrapper_script_path = "/userdata/roms/ports/RGSX/update/run.update"
            logger.debug(f"Vérification de l'existence et des permissions de {wrapper_script_path}")
            if not os.path.isfile(wrapper_script_path):
                logger.error(f"Le script wrapper {wrapper_script_path} n'existe pas")
                return False, f"Erreur : le script wrapper {wrapper_script_path} n'existe pas"
            if not os.access(wrapper_script_path, os.X_OK):
                logger.error(f"Le script wrapper {wrapper_script_path} n'est pas exécutable")
                subprocess.run(["chmod", "+x", wrapper_script_path], check=True)
                logger.debug(f"Script wrapper {wrapper_script_path} rendu exécutable")

            logger.debug("Désactivation des événements Pygame QUIT")
            pygame.event.set_blocked(pygame.QUIT)

            config.current_loading_system = "Application de la mise à jour..."
            config.loading_progress = 80.0
            config.needs_redraw = True
            logger.debug(f"Exécution du script wrapper : {wrapper_script_path}")
            result = os.system(f"{wrapper_script_path} &")
            logger.debug(f"Résultat de os.system : {result}")
            if result != 0:
                logger.error(f"Échec du lancement du script wrapper : code de retour {result}")
                return False, f"Échec du lancement du script wrapper : code de retour {result}"

            config.current_loading_system = "Mise à jour déclenchée, redémarrage..."
            config.loading_progress = 100.0
            config.needs_redraw = True
            logger.debug("Mise à jour déclenchée, arrêt de l'application")
            config.update_triggered = True
            pygame.quit()
            sys.exit(0)
        else:
            logger.debug("Aucune mise à jour logicielle disponible")
            return True, "Aucune mise à jour disponible"

    except Exception as e:
        logger.error(f"Erreur OTA : {str(e)}")
        return False, f"Erreur lors de la vérification des mises à jour : {str(e)}"



# File d'attente pour la progression
import queue
progress_queue = queue.Queue()



async def download_rom(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    logger.debug(f"Début téléchargement: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}, task_id={task_id}")
    result = [None, None]
    
    # Vider la file d'attente avant de commencer
    while not progress_queue.empty():
        try:
            progress_queue.get_nowait()
            logger.debug(f"File progress_queue vidée pour {game_name}")
        except queue.Empty:
            break
    
    def download_thread():
        logger.debug(f"Thread téléchargement démarré pour {url}, task_id={task_id}")
        try:
            dest_dir = None
            for platform_dict in config.platform_dicts:
                if platform_dict["platform"] == platform:
                    dest_dir = platform_dict.get("folder")
                    break
            if not dest_dir:
                dest_dir = os.path.join("/userdata/roms", platform.lower().replace(" ", ""))
            
            os.makedirs(dest_dir, exist_ok=True)
            if not os.access(dest_dir, os.W_OK):
                raise PermissionError(f"Pas de permission d'écriture dans {dest_dir}")
                
            sanitized_name = sanitize_filename(game_name)
            dest_path = os.path.join(dest_dir, f"{sanitized_name}")
            logger.debug(f"Chemin destination: {dest_path}")
            
            headers = {'User-Agent': 'Mozilla/5.0'}
            response = requests.get(url, stream=True, headers=headers, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            logger.debug(f"Taille totale: {total_size} octets")
            
            # Initialiser la progression avec task_id
            progress_queue.put((task_id, 0, total_size))
            logger.debug(f"Progression initiale envoyée: 0% pour {game_name}, task_id={task_id}")
            
            downloaded = 0
            chunk_size = 4096
            last_update_time = time.time()
            update_interval = 0.5  # Mettre à jour toutes les 0,5 secondes
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        size_received = len(chunk)
                        f.write(chunk)
                        downloaded += size_received
                        current_time = time.time()
                        if current_time - last_update_time >= update_interval:
                            progress = (downloaded / total_size * 100) if total_size > 0 else 0
                            progress_queue.put((task_id, downloaded, total_size))
                            # logger.debug(f"Progress update sent: {progress:.1f}% for {game_name}, task_id={task_id}")
                            last_update_time = current_time
                    else:
                        logger.debug("Chunk vide reçu")
            
            os.chmod(dest_path, 0o644)
            logger.debug(f"Téléchargement terminé: {dest_path}")
            result[0] = True
            result[1] = f"Download_OK: {game_name}"
        except Exception as e:
            logger.error(f"Erreur téléchargement {url}: {str(e)}")
            result[0] = False
            result[1] = f"Erreur téléchargement {game_name}: {str(e)}"
        finally:
            logger.debug(f"Thread téléchargement terminé pour {url}, task_id={task_id}")
            progress_queue.put((task_id, result[0], result[1]))
            logger.debug(f"Final result sent to queue: success={result[0]}, message={result[1]}, task_id={task_id}")

    thread = threading.Thread(target=download_thread)
    thread.start()
    
    # Boucle principale pour mettre à jour la progression
    while thread.is_alive():
        try:
            while not progress_queue.empty():
                data = progress_queue.get()
                logger.debug(f"Progress queue data received: {data}")
                if len(data) != 3 or data[0] != task_id:  # Ignorer les données d'une autre tâche
                    logger.debug(f"Ignoring queue data for task_id={data[0]}, expected={task_id}")
                    continue
                if isinstance(data[1], bool):  # Fin du téléchargement
                    success, message = data[1], data[2]
                    for entry in config.history:
                        if entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                            entry["status"] = "Download_OK" if success else "Erreur"
                            entry["progress"] = 100 if success else 0
                            entry["message"] = message
                            save_history(config.history)
                            config.needs_redraw = True
                            logger.debug(f"Final update in history: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                            break
                else:
                    downloaded, total_size = data[1], data[2]
                    progress = (downloaded / total_size * 100) if total_size > 0 else 0
                    for entry in config.history:
                        if entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                            entry["progress"] = progress
                            entry["status"] = "Téléchargement"
                            config.needs_redraw = True
                            # logger.debug(f"Progress updated in history: {progress:.1f}% for {game_name}, task_id={task_id}")
                            break
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"Erreur mise à jour progression: {str(e)}")
    
    thread.join()
    logger.debug(f"Thread joined for {url}, task_id={task_id}")
    return result[0], result[1]

async def download_from_1fichier(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    logger.debug(f"Début téléchargement 1fichier: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}, task_id={task_id}")
    result = [None, None]

    # Vider la file d'attente avant de commencer
    while not progress_queue.empty():
        try:
            progress_queue.get_nowait()
            logger.debug(f"File progress_queue vidée pour {game_name}")
        except queue.Empty:
            break

    def download_thread():
        logger.debug(f"Thread téléchargement 1fichier démarré pour {url}, task_id={task_id}")
        try:
            link = url.split('&af=')[0]
            dest_dir = None
            for platform_dict in config.platform_dicts:
                if platform_dict["platform"] == platform:
                    dest_dir = platform_dict.get("folder")
                    break
            if not dest_dir:
                logger.warning(f"Aucun dossier 'folder' trouvé pour la plateforme {platform}")
                dest_dir = os.path.join("/userdata/roms", platform)

            logger.debug(f"Vérification répertoire destination: {dest_dir}")
            os.makedirs(dest_dir, exist_ok=True)
            if not os.access(dest_dir, os.W_OK):
                raise PermissionError(f"Pas de permission d'écriture dans {dest_dir}")

            headers = {
                "Authorization": f"Bearer {config.API_KEY_1FICHIER}",
                "Content-Type": "application/json"
            }
            payload = {
                "url": link,
                "pretty": 1
            }

            logger.debug(f"Envoi requête POST à https://api.1fichier.com/v1/file/info.cgi pour {url}")
            response = requests.post("https://api.1fichier.com/v1/file/info.cgi", headers=headers, json=payload, timeout=30)
            logger.debug(f"Réponse reçue, status: {response.status_code}")
            response.raise_for_status()
            file_info = response.json()

            if "error" in file_info and file_info["error"] == "Resource not found":
                logger.error(f"Le fichier {game_name} n'existe pas sur 1fichier")
                result[0] = False
                result[1] = f"Le fichier {game_name} n'existe pas"
                return

            filename = file_info.get("filename", "").strip()
            if not filename:
                logger.error("Impossible de récupérer le nom du fichier")
                result[0] = False
                result[1] = "Impossible de récupérer le nom du fichier"
                return

            sanitized_filename = sanitize_filename(filename)
            dest_path = os.path.join(dest_dir, sanitized_filename)
            logger.debug(f"Chemin destination: {dest_path}")

            logger.debug(f"Envoi requête POST à https://api.1fichier.com/v1/download/get_token.cgi pour {url}")
            response = requests.post("https://api.1fichier.com/v1/download/get_token.cgi", headers=headers, json=payload, timeout=30)
            logger.debug(f"Réponse reçue, status: {response.status_code}")
            response.raise_for_status()
            download_info = response.json()

            final_url = download_info.get("url")
            if not final_url:
                logger.error("Impossible de récupérer l'URL de téléchargement")
                result[0] = False
                result[1] = "Impossible de récupérer l'URL de téléchargement"
                return

            lock = threading.Lock()
            retries = 10
            retry_delay = 10
            # Initialiser la progression avec task_id
            progress_queue.put((task_id, 0, 0))  # Taille initiale inconnue
            logger.debug(f"Progression initiale envoyée: 0% pour {game_name}, task_id={task_id}")
            for attempt in range(retries):
                try:
                    logger.debug(f"Tentative {attempt + 1} : Envoi requête GET à {final_url}")
                    with requests.get(final_url, stream=True, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30) as response:
                        logger.debug(f"Réponse reçue, status: {response.status_code}")
                        response.raise_for_status()
                        total_size = int(response.headers.get('content-length', 0))
                        logger.debug(f"Taille totale: {total_size} octets")
                        with lock:
                            for entry in config.history:
                                if entry["url"] == url and entry["status"] == "downloading":
                                    entry["total_size"] = total_size
                                    config.needs_redraw = True
                                    break
                            progress_queue.put((task_id, 0, total_size))  # Mettre à jour la taille totale

                        downloaded = 0
                        chunk_size = 8192
                        last_update_time = time.time()
                        update_interval = 0.5  # Mettre à jour toutes les 0,5 secondes
                        with open(dest_path, 'wb') as f:
                            logger.debug(f"Ouverture fichier: {dest_path}")
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    current_time = time.time()
                                    if current_time - last_update_time >= update_interval:
                                        with lock:
                                            for entry in config.history:
                                                if entry["url"] == url and entry["status"] == "downloading":
                                                    entry["progress"] = (downloaded / total_size * 100) if total_size > 0 else 0
                                                    entry["status"] = "Téléchargement"
                                                    config.needs_redraw = True
                                                    logger.debug(f"Progression mise à jour: {entry['progress']:.1f}% pour {game_name}")
                                                    break
                                        progress_queue.put((task_id, downloaded, total_size))
                                        last_update_time = current_time

                    if is_zip_non_supported:
                        with lock:
                            for entry in config.history:
                                if entry["url"] == url and entry["status"] == "Téléchargement":
                                    entry["progress"] = 0
                                    entry["status"] = "Extracting"
                                    config.needs_redraw = True
                                    break
                        extension = os.path.splitext(dest_path)[1].lower()
                        if extension == ".zip":
                            success, msg = extract_zip(dest_path, dest_dir, url)
                        elif extension == ".rar":
                            success, msg = extract_rar(dest_path, dest_dir, url)
                        else:
                            raise Exception(f"Type d'archive non supporté: {extension}")
                        if not success:
                            raise Exception(f"Échec de l'extraction de l'archive: {msg}")
                        result[0] = True
                        result[1] = f"Downloaded / extracted : {game_name}"
                    else:
                        os.chmod(dest_path, 0o644)
                        logger.debug(f"Téléchargement terminé: {dest_path}")
                        result[0] = True
                        result[1] = f"Download_OK : {game_name}"
                    return

                except requests.exceptions.RequestException as e:
                    logger.error(f"Tentative {attempt + 1} échouée : {e}")
                    if attempt < retries - 1:
                        time.sleep(retry_delay)
                    else:
                        logger.error("Nombre maximum de tentatives atteint")
                        result[0] = False
                        result[1] = f"Échec du téléchargement après {retries} tentatives"
                        return

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur API 1fichier : {e}")
            result[0] = False
            result[1] = f"Erreur lors de la requête API, la clé est peut-être incorrecte: {str(e)}"

        finally:
            logger.debug(f"Thread téléchargement 1fichier terminé pour {url}, task_id={task_id}")
            progress_queue.put((task_id, result[0], result[1]))
            logger.debug(f"Final result sent to queue: success={result[0]}, message={result[1]}, task_id={task_id}")

    thread = threading.Thread(target=download_thread)
    logger.debug(f"Démarrage thread pour {url}, task_id={task_id}")
    thread.start()

    # Boucle principale pour mettre à jour la progression
    while thread.is_alive():
        try:
            while not progress_queue.empty():
                data = progress_queue.get()
                logger.debug(f"Progress queue data received: {data}")
                if len(data) != 3 or data[0] != task_id:  # Ignorer les données d'une autre tâche
                    logger.debug(f"Ignoring queue data for task_id={data[0]}, expected={task_id}")
                    continue
                if isinstance(data[1], bool):  # Fin du téléchargement
                    success, message = data[1], data[2]
                    for entry in config.history:
                        if entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                            entry["status"] = "Download_OK" if success else "Erreur"
                            entry["progress"] = 100 if success else 0
                            entry["message"] = message
                            save_history(config.history)
                            config.needs_redraw = True
                            logger.debug(f"Final update in history: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                            break
                else:
                    downloaded, total_size = data[1], data[2]
                    progress = (downloaded / total_size * 100) if total_size > 0 else 0
                    for entry in config.history:
                        if entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                            entry["progress"] = progress
                            entry["status"] = "Téléchargement"
                            config.needs_redraw = True
                            # logger.debug(f"Progress updated in history: {progress:.1f}% for {game_name}, task_id={task_id}")
                            break
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"Erreur mise à jour progression: {str(e)}")

    thread.join()
    logger.debug(f"Thread joined for {url}, task_id={task_id}")
    return result[0], result[1]


def is_1fichier_url(url):
    """Détecte si l'URL est un lien 1fichier."""
    return "1fichier.com" in url


import requests
import subprocess
import os
import threading
import pygame # type: ignore
import zipfile
import asyncio
import config
from config import OTA_VERSION_ENDPOINT,APP_FOLDER, UPDATE_FOLDER, OTA_UPDATE_ZIP
from utils import sanitize_filename, extract_zip, extract_rar, load_api_key_1fichier
from history import save_history
import logging
import queue
import time
import os
from language import _  # Import de la fonction de traduction


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
        config.current_loading_system = _("network_checking_updates")
        config.loading_progress = 5.0
        config.needs_redraw = True
        response = requests.get(OTA_VERSION_ENDPOINT, timeout=5)
        response.raise_for_status()
        if response.headers.get("content-type") != "application/json":
            raise ValueError(f"Le fichier version.json n'est pas un JSON valide (type de contenu : {response.headers.get('content-type')})")
        version_data = response.json()
        latest_version = version_data.get("version")
        logger.debug(f"Version distante : {latest_version}, version locale : {config.app_version}")
        UPDATE_ZIP = OTA_UPDATE_ZIP.replace("RGSX.zip", f"RGSX_v{latest_version}.zip")
        logger.debug(f"URL de mise à jour : {UPDATE_ZIP}")
        if latest_version != config.app_version:
            config.current_loading_system = _("network_update_available").format(latest_version)
            config.loading_progress = 10.0
            config.needs_redraw = True
            logger.debug(f"Téléchargement du ZIP de mise à jour : {UPDATE_ZIP}")

            # Créer le dossier UPDATE_FOLDER s'il n'existe pas
            os.makedirs(UPDATE_FOLDER, exist_ok=True)
            update_zip_path = os.path.join(UPDATE_FOLDER, "RGSX.zip")
            logger.debug(f"Téléchargement de {UPDATE_ZIP} vers {update_zip_path}")

            # Télécharger le ZIP
            with requests.get(UPDATE_ZIP, stream=True, timeout=10) as r:
                r.raise_for_status()
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                with open(update_zip_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            config.loading_progress = 10.0 + (40.0 * downloaded / total_size) if total_size > 0 else 10.0
                            config.needs_redraw = True
                            await asyncio.sleep(0)
            logger.debug(f"ZIP téléchargé : {update_zip_path}")

            # Extraire le contenu du ZIP dans APP_FOLDER
            config.current_loading_system = _("network_extracting_update")
            config.loading_progress = 60.0
            config.needs_redraw = True
            success, message = extract_update(update_zip_path, APP_FOLDER, UPDATE_ZIP)
            if not success:
                logger.error(f"Échec de l'extraction : {message}")
                return False, _("network_extraction_failed").format(message)

            # Supprimer le fichier ZIP après extraction
            if os.path.exists(update_zip_path):
                os.remove(update_zip_path)
                logger.debug(f"Fichier ZIP {update_zip_path} supprimé")

            config.current_loading_system = _("network_update_completed")
            config.loading_progress = 100.0
            config.needs_redraw = True
            logger.debug("Mise à jour terminée avec succès")

            # Configurer la popup pour afficher le message de succès
            config.menu_state = "update_result"
            config.update_result_message = _("network_update_success").format(latest_version)
            config.update_result_error = False
            config.update_result_start_time = pygame.time.get_ticks()
            config.needs_redraw = True
            logger.debug(f"Affichage de la popup de mise à jour réussie")

            return True, _("network_update_success_message")
        else:
            logger.debug("Aucune mise à jour disponible")
            return True, _("network_no_update_available")

    except Exception as e:
        logger.error(f"Erreur OTA : {str(e)}")
        config.menu_state = "update_result"
        config.update_result_message = _("network_update_error").format(str(e))
        config.update_result_error = True
        config.update_result_start_time = pygame.time.get_ticks()
        config.needs_redraw = True
        return False, _("network_check_update_error").format(str(e))

def extract_update(zip_path, dest_dir, source_url):
    try:
        # Vérifier et ajuster les permissions du répertoire de destination
        os.makedirs(dest_dir, exist_ok=True)
        try:
            subprocess.run(["chmod", "-R", "u+rw", dest_dir], check=True)
            logger.debug(f"Permissions ajustées pour {dest_dir}")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Impossible d'ajuster les permissions pour {dest_dir}: {str(e)}")

        # Extraire le ZIP
        skipped_files = []
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for file_info in zip_ref.infolist():
                try:
                    zip_ref.extract(file_info, dest_dir)
                except PermissionError as e:
                    logger.warning(f"Impossible d'extraire {file_info.filename}: {str(e)}")
                    skipped_files.append(file_info.filename)
                except Exception as e:
                    logger.warning(f"Erreur lors de l'extraction de {file_info.filename}: {str(e)}")
                    skipped_files.append(file_info.filename)

        if skipped_files:
            message = _("network_extraction_partial").format(', '.join(skipped_files))
            logger.warning(message)
            return True, message  # Considérer comme succès si certains fichiers sont extraits
        return True, _("network_extraction_success")

    except Exception as e:
        logger.error(f"Erreur critique lors de l'extraction du ZIP {source_url}: {str(e)}")
        return False, _("network_zip_extraction_error").format(source_url, str(e))

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
                dest_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), platform.lower().replace(" ", ""))
            
            os.makedirs(dest_dir, exist_ok=True)
            if not os.access(dest_dir, os.W_OK):
                raise PermissionError(f"Pas de permission d'écriture dans {dest_dir}")
                
            sanitized_name = sanitize_filename(game_name)
            dest_path = os.path.join(dest_dir, f"{sanitized_name}")
            logger.debug(f"Chemin destination: {dest_path}")
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Utiliser une session pour gérer les cookies
            session = requests.Session()
            session.headers.update(headers)
            
            # Première requête HEAD pour obtenir la vraie URL
            logger.debug(f"Première requête HEAD vers {url}")
            head_response = session.head(url, timeout=30, allow_redirects=False)
            logger.debug(f"HEAD Status: {head_response.status_code}, Headers: {dict(head_response.headers)}")
            
            # Suivre la redirection manuellement si nécessaire
            final_url = url
            if head_response.status_code in [301, 302, 303, 307, 308]:
                final_url = head_response.headers.get('Location', url)
                logger.debug(f"Redirection détectée vers: {final_url}")
            
            # Requête GET vers l'URL finale avec en-têtes spécifiques
            download_headers = headers.copy()
            download_headers['Accept'] = 'application/octet-stream, */*'
            download_headers['Referer'] = 'https://myrient.erista.me/'
            response = session.get(final_url, stream=True, timeout=30, allow_redirects=False, headers=download_headers)
            logger.debug(f"Status code: {response.status_code}")
            logger.debug(f"Headers: {dict(response.headers)}")
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            logger.debug(f"Taille totale: {total_size} octets")
            
            if total_size == 0:
                logger.warning(f"Taille de fichier 0, possible redirection ou erreur. URL finale: {response.url}")
                # Vérifier si c'est une redirection
                if response.url != url:
                    logger.debug(f"Redirection détectée: {url} -> {response.url}")
            
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
                            # Calculer le pourcentage correctement et le limiter entre 0 et 100
                            progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                            progress_percent = max(0, min(100, progress_percent))
                            progress_queue.put((task_id, downloaded, total_size))
                            last_update_time = current_time
                    else:
                        logger.debug("Chunk vide reçu")
            
            os.chmod(dest_path, 0o644)
            logger.debug(f"Téléchargement terminé: {dest_path}")
            
            # Vérifier si l'extraction est nécessaire pour les archives non supportées
            if is_zip_non_supported:
                logger.debug(f"Extraction automatique nécessaire pour {dest_path}")
                extension = os.path.splitext(dest_path)[1].lower()
                if extension == ".zip":
                    try:
                        # Mettre à jour le statut avant l'extraction
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                                    entry["status"] = "Extracting"
                                    entry["progress"] = 0
                                    entry["message"] = "Préparation de l'extraction..."
                                    save_history(config.history)
                                    config.needs_redraw = True
                                    break
                        
                        success, msg = extract_zip(dest_path, dest_dir, url)
                        if success:
                            logger.debug(f"Extraction ZIP réussie: {msg}")
                            result[0] = True
                            result[1] = _("network_download_extract_ok").format(game_name)
                        else:
                            logger.error(f"Erreur extraction ZIP: {msg}")
                            result[0] = False
                            result[1] = _("network_extraction_failed").format(msg)
                    except Exception as e:
                        logger.error(f"Exception lors de l'extraction: {str(e)}")
                        result[0] = False
                        result[1] = f"Erreur téléchargement {game_name}: {str(e)}"
                elif extension == ".rar":
                    try:
                        success, msg = extract_rar(dest_path, dest_dir, url)
                        if success:
                            logger.debug(f"Extraction RAR réussie: {msg}")
                            result[0] = True
                            result[1] = _("network_download_extract_ok").format(game_name)
                        else:
                            logger.error(f"Erreur extraction RAR: {msg}")
                            result[0] = False
                            result[1] = _("network_extraction_failed").format(msg)
                    except Exception as e:
                        logger.error(f"Exception lors de l'extraction RAR: {str(e)}")
                        result[0] = False
                        result[1] = f"Erreur extraction RAR {game_name}: {str(e)}"
                else:
                    logger.warning(f"Type d'archive non supporté: {extension}")
                    result[0] = True
                    result[1] = _("network_download_ok").format(game_name)
            else:
                result[0] = True
                result[1] = _("network_download_ok").format(game_name)
        except Exception as e:
            logger.error(f"Erreur téléchargement {url}: {str(e)}")
            result[0] = False
            result[1] = _("network_download_error").format(game_name, str(e))
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
                    # Vérifier si config.history est une liste avant d'itérer
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                # Utiliser une variable intermédiaire pour stocker le message
                                message_text = message
                                entry["message"] = message_text
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.debug(f"Final update in history: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                                break
                else:
                    downloaded, total_size = data[1], data[2]
                    # Calculer le pourcentage correctement et le limiter entre 0 et 100
                    progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                    progress_percent = max(0, min(100, progress_percent))
                    
                    # Vérifier si config.history est une liste avant d'itérer
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                                entry["progress"] = progress_percent
                                entry["status"] = "Téléchargement"
                                entry["downloaded_size"] = downloaded
                                entry["total_size"] = total_size
                                config.needs_redraw = True
                                break
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error(f"Erreur mise à jour progression: {str(e)}")
    
    thread.join()
    logger.debug(f"Thread joined for {url}, task_id={task_id}")
    return result[0], result[1]

async def download_from_1fichier(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    load_api_key_1fichier()
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
                dest_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), platform)

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
                result[1] = _("network_file_not_found").format(game_name)
                return

            filename = file_info.get("filename", "").strip()
            if not filename:
                logger.error("Impossible de récupérer le nom du fichier")
                result[0] = False
                result[1] = _("network_cannot_get_filename")
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
                result[1] = _("network_cannot_get_download_url")
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
                            # Vérifier si config.history est une liste avant d'itérer
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url and entry["status"] == "downloading":
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
                                            # Vérifier si config.history est une liste avant d'itérer
                                            if isinstance(config.history, list):
                                                for entry in config.history:
                                                    if "url" in entry and entry["url"] == url and entry["status"] == "downloading":
                                                        # Calculer le pourcentage correctement et le limiter entre 0 et 100
                                                        progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                                                        progress_percent = max(0, min(100, progress_percent))
                                                        entry["progress"] = progress_percent
                                                        entry["status"] = "Téléchargement"
                                                        entry["downloaded_size"] = downloaded
                                                        entry["total_size"] = total_size
                                                        config.needs_redraw = True
                                                        logger.debug(f"Progression mise à jour: {entry['progress']:.1f}% pour {game_name}")
                                                        break
                                        progress_queue.put((task_id, downloaded, total_size))
                                        last_update_time = current_time

                    if is_zip_non_supported:
                        with lock:
                            # Vérifier si config.history est une liste avant d'itérer
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url and entry["status"] == "Téléchargement":
                                        entry["progress"] = 0
                                        entry["status"] = "Extracting"
                                        config.needs_redraw = True
                                        break
                        extension = os.path.splitext(dest_path)[1].lower()
                        if extension == ".zip":
                            try:
                                success, msg = extract_zip(dest_path, dest_dir, url)
                                if success:
                                    logger.debug(f"Extraction ZIP réussie: {msg}")
                                    result[0] = True
                                    result[1] = _("network_download_extract_ok").format(game_name)
                                else:
                                    logger.error(f"Erreur extraction ZIP: {msg}")
                                    result[0] = False
                                    result[1] = _("network_extraction_failed").format(msg)
                            except Exception as e:
                                logger.error(f"Exception lors de l'extraction: {str(e)}")
                                result[0] = False
                                result[1] = f"Erreur téléchargement {game_name}: {str(e)}"
                        elif extension == ".rar":
                            try:
                                success, msg = extract_rar(dest_path, dest_dir, url)
                                if success:
                                    logger.debug(f"Extraction RAR réussie: {msg}")
                                    result[0] = True
                                    result[1] = _("network_download_extract_ok").format(game_name)
                                else:
                                    logger.error(f"Erreur extraction RAR: {msg}")
                                    result[0] = False
                                    result[1] = _("network_extraction_failed").format(msg)
                            except Exception as e:
                                logger.error(f"Exception lors de l'extraction RAR: {str(e)}")
                                result[0] = False
                                result[1] = f"Erreur extraction RAR {game_name}: {str(e)}"
                        else:
                            logger.warning(f"Type d'archive non supporté: {extension}")
                            result[0] = True
                            result[1] = _("network_download_ok").format(game_name)
                    else:
                        os.chmod(dest_path, 0o644)
                        logger.debug(f"Téléchargement terminé: {dest_path}")
                        result[0] = True
                        result[1] = _("network_download_ok").format(game_name)
                    return

                except requests.exceptions.RequestException as e:
                    logger.error(f"Tentative {attempt + 1} échouée : {e}")
                    if attempt < retries - 1:
                        time.sleep(retry_delay)
                    else:
                        logger.error("Nombre maximum de tentatives atteint")
                        result[0] = False
                        result[1] = _("network_download_failed").format(retries)
                        return

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur API 1fichier : {e}")
            result[0] = False
            result[1] = _("network_api_error").format(str(e))

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
                    # Vérifier si config.history est une liste avant d'itérer
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                # Utiliser une variable intermédiaire pour stocker le message
                                message_text = message
                                entry["message"] = message_text
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.debug(f"Final update in history: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                                break
                else:
                    downloaded, total_size = data[1], data[2]
                    # Calculer le pourcentage correctement et le limiter entre 0 et 100
                    progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                    progress_percent = max(0, min(100, progress_percent))
                    
                    # Vérifier si config.history est une liste avant d'itérer
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                                entry["progress"] = progress_percent
                                entry["status"] = "Téléchargement"
                                entry["downloaded_size"] = downloaded
                                entry["total_size"] = total_size
                                config.needs_redraw = True
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
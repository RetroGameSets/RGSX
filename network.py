import requests
import subprocess
import re
import os
import threading
import pygame # type: ignore
import zipfile
import json
import time
import asyncio
import config
from utils import sanitize_filename
from history import add_to_history, load_history
import logging

logger = logging.getLogger(__name__)

JSON_EXTENSIONS = "/userdata/roms/ports/RGSX/rom_extensions.json"
cache = {}
CACHE_TTL = 3600  # 1 heure

def fetch_data(url):
    """Récupère des données depuis une URL avec mise en cache."""
    current_time = time.time()
    if url in cache and current_time - cache[url]["timestamp"] < CACHE_TTL:
        return cache[url]["data"]
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        cache[url] = {"data": data, "timestamp": current_time}
        return data
    except requests.RequestException as e:
        logging.error(f"Erreur lors de la requête {url} : {e}")
        return None
        
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
    dest_dir = None
    for platform_dict in config.platform_dicts:
        if platform_dict["platform"] == platform:
            dest_dir = platform_dict.get("folder")
            break
    if not dest_dir:
        logger.warning(f"Aucun dossier 'folder' trouvé pour la plateforme {platform}")
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
            total_size = sum(info.file_size for info in zip_ref.infolist() if not info.is_dir())
            logger.info(f"Taille totale à extraire: {total_size} octets")
            if total_size == 0:
                logger.warning("ZIP vide ou ne contenant que des dossiers")
                return True, "ZIP vide extrait avec succès"

            extracted_size = 0
            os.makedirs(dest_dir, exist_ok=True)
            chunk_size = 8192
            for info in zip_ref.infolist():
                if info.is_dir():
                    continue
                file_path = os.path.join(dest_dir, info.filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
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
                            config.needs_redraw = True  # Forcer le redraw
                        logger.debug(f"Extraction {info.filename}, chunk: {len(chunk)}, file_extracted: {file_extracted}/{file_size}, total_extracted: {extracted_size}/{total_size}, progression: {(extracted_size/total_size*100):.1f}%")
                os.chmod(file_path, 0o644)

        for root, dirs, _ in os.walk(dest_dir):
            for dir_name in dirs:
                os.chmod(os.path.join(root, dir_name), 0o755)

        os.remove(zip_path)
        logger.info(f"Fichier ZIP {zip_path} extrait dans {dest_dir} et supprimé")
        return True, "ZIP extrait avec succès"
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de {zip_path}: {e}")
        return False, str(e)

def extract_rar(rar_path, dest_dir, url):
    """Extrait le contenu du fichier RAR dans le dossier cible, préservant la structure des dossiers."""
    try:
        lock = threading.Lock()
        os.makedirs(dest_dir, exist_ok=True)
        
        result = subprocess.run(['unrar'], capture_output=True, text=True)
        if result.returncode not in [0, 1]:
            logger.error("Commande unrar non disponible")
            return False, "Commande unrar non disponible"

        result = subprocess.run(['unrar', 'l', '-v', rar_path], capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            logger.error(f"Erreur lors de la liste des fichiers RAR: {error_msg}")
            return False, f"Échec de la liste des fichiers RAR: {error_msg}"

        logger.debug(f"Sortie brute de 'unrar l -v {rar_path}':\n{result.stdout}")

        total_size = 0
        files_to_extract = []
        root_dirs = set()
        lines = result.stdout.splitlines()
        in_file_list = False
        for line in lines:
            if line.startswith("----"):
                in_file_list = not in_file_list
                continue
            if in_file_list:
                match = re.match(r'^\s*(\S+)\s+(\d+)\s+\d*\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+(.+)$', line)
                if match:
                    attrs = match.group(1)
                    file_size = int(match.group(2))
                    file_date = match.group(3)
                    file_name = match.group(4).strip()
                    if 'D' not in attrs:
                        files_to_extract.append((file_name, file_size))
                        total_size += file_size
                        root_dir = file_name.split('/')[0] if '/' in file_name else ''
                        if root_dir:
                            root_dirs.add(root_dir)
                        logger.debug(f"Ligne parsée: {file_name}, taille: {file_size}, date: {file_date}")
                    else:
                        logger.debug(f"Dossier ignoré: {file_name}")
                else:
                    logger.debug(f"Ligne ignorée (format inattendu): {line}")

        logger.info(f"Taille totale à extraire (RAR): {total_size} octets")
        logger.debug(f"Fichiers à extraire: {files_to_extract}")
        logger.debug(f"Dossiers racines détectés: {root_dirs}")
        if total_size == 0:
            logger.warning("RAR vide, ne contenant que des dossiers, ou erreur de parsing")
            return False, "RAR vide ou erreur lors de la liste des fichiers"

        with lock:
            config.download_progress[url]["downloaded_size"] = 0
            config.download_progress[url]["total_size"] = total_size
            config.download_progress[url]["status"] = "Extracting"
            config.download_progress[url]["progress_percent"] = 0
            config.needs_redraw = True

        escaped_rar_path = rar_path.replace(" ", "\\ ")
        escaped_dest_dir = dest_dir.replace(" ", "\\ ")
        process = subprocess.Popen(['unrar', 'x', '-y', escaped_rar_path, escaped_dest_dir], 
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            logger.error(f"Erreur lors de l'extraction de {rar_path}: {stderr}")
            return False, f"Erreur lors de l'extraction: {stderr}"

        extracted_size = 0
        extracted_files = []
        total_files = len(files_to_extract)
        for i, (expected_file, file_size) in enumerate(files_to_extract):
            file_path = os.path.join(dest_dir, expected_file)
            if os.path.exists(file_path):
                extracted_size += file_size
                extracted_files.append(expected_file)
                os.chmod(file_path, 0o644)
                logger.debug(f"Fichier extrait: {expected_file}, taille: {file_size}, chemin: {file_path}")
                with lock:
                    config.download_progress[url]["downloaded_size"] = extracted_size
                    config.download_progress[url]["status"] = "Extracting"
                    config.download_progress[url]["progress_percent"] = ((i + 1) / total_files * 100) if total_files > 0 else 0
                    config.needs_redraw = True
            else:
                logger.warning(f"Fichier non trouvé après extraction: {expected_file}")

        missing_files = [f for f, _ in files_to_extract if f not in extracted_files]
        if missing_files:
            logger.warning(f"Fichiers non extraits: {', '.join(missing_files)}")
            return False, f"Fichiers non extraits: {', '.join(missing_files)}"

        if dest_dir == "/userdata/roms/ps3" and len(root_dirs) == 1:
            root_dir = root_dirs.pop()
            old_path = os.path.join(dest_dir, root_dir)
            new_path = os.path.join(dest_dir, f"{root_dir}.ps3")
            if os.path.isdir(old_path):
                try:
                    os.rename(old_path, new_path)
                    logger.info(f"Dossier renommé: {old_path} -> {new_path}")
                except Exception as e:
                    logger.error(f"Erreur lors du renommage de {old_path} en {new_path}: {str(e)}")
                    return False, f"Erreur lors du renommage du dossier: {str(e)}"
            else:
                logger.warning(f"Dossier racine {old_path} non trouvé après extraction")
        elif dest_dir == "/userdata/roms/ps3" and len(root_dirs) > 1:
            logger.warning(f"Plusieurs dossiers racines détectés dans l'archive: {root_dirs}. Aucun renommage effectué.")

        for root, dirs, _ in os.walk(dest_dir):
            for dir_name in dirs:
                os.chmod(os.path.join(root, dir_name), 0o755)

        os.remove(rar_path)
        logger.info(f"Fichier RAR {rar_path} extrait dans {dest_dir} et supprimé")
        return True, "RAR extrait avec succès"
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de {rar_path}: {str(e)}")
        return False, str(e)
    finally:
        if os.path.exists(rar_path):
            try:
                os.remove(rar_path)
                logger.info(f"Fichier RAR {rar_path} supprimé après échec de l'extraction")
            except Exception as e:
                logger.error(f"Erreur lors de la suppression de {rar_path}: {str(e)}")

async def download_rom(url, platform, game_name, is_zip_non_supported=False):
    logger.debug(f"Début téléchargement: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}")
    result = [None, None]
    
    def download_thread():
        logger.debug(f"Thread téléchargement démarré pour {url}")
        try:
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
                
            sanitized_name = sanitize_filename(game_name)
            dest_path = os.path.join(dest_dir, f"{sanitized_name}")
            logger.debug(f"Chemin destination: {dest_path}")
            
            lock = threading.Lock()
            with lock:
                config.download_progress[url] = {
                    "downloaded_size": 0,
                    "total_size": 0,
                    "status": "Téléchargement",
                    "progress_percent": 0,
                    "game_name": game_name
                }
                config.needs_redraw = True  # Forcer le redraw
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
                config.needs_redraw = True  # Forcer le redraw
            
            downloaded = 0
            with open(dest_path, 'wb') as f:
                logger.debug(f"Ouverture fichier: {dest_path}")
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        with lock:
                            config.download_progress[url]["downloaded_size"] = downloaded
                            config.download_progress[url]["status"] = "Téléchargement"
                            config.download_progress[url]["progress_percent"] = (downloaded / total_size * 100) if total_size > 0 else 0
                            config.needs_redraw = True  # Forcer le redraw
                        #logger.debug(f"Progression: {downloaded}/{total_size} octets, {config.download_progress[url]['progress_percent']:.1f}%")
            
            if is_zip_non_supported:
                with lock:
                    config.download_progress[url]["downloaded_size"] = 0
                    config.download_progress[url]["total_size"] = 0
                    config.download_progress[url]["status"] = "Extracting"
                    config.download_progress[url]["progress_percent"] = 0
                    config.needs_redraw = True  # Forcer le redraw
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
        except Exception as e:
            logger.error(f"Erreur téléchargement {url}: {str(e)}")
            if url in config.download_progress:
                with lock:
                    del config.download_progress[url]
            if os.path.exists(dest_path):
                os.remove(dest_path)
            result[0] = False
            result[1] = f"Erreur téléchargement {game_name}"
        finally:
            logger.debug(f"Thread téléchargement terminé pour {url}")
            with lock:
                config.download_result_message = result[1]
                config.download_result_error = not result[0]
                config.download_result_start_time = pygame.time.get_ticks()
                config.menu_state = "download_result"
                config.needs_redraw = True  # Forcer le redraw
                # Enregistrement dans l'historique
                add_to_history(platform, game_name, "OK" if result[0] else "Error")
                config.history = load_history()  # Recharger l'historique
                logger.debug(f"Enregistrement dans l'historique: platform={platform}, game_name={game_name}, status={'Download_OK' if result[0] else 'Erreur'}")

    thread = threading.Thread(target=download_thread)
    logger.debug(f"Démarrage thread pour {url}")
    thread.start()
    while thread.is_alive():
        pygame.event.pump()
        await asyncio.sleep(0.1)
    thread.join()
    logger.debug(f"Thread rejoint pour {url}")
    
    return result[0], result[1]

def check_extension_before_download(game_name, platform, url):
    """Vérifie l'extension avant de lancer le téléchargement et retourne un tuple de 4 éléments."""
    try:
        sanitized_name = sanitize_filename(game_name)
        extensions_data = load_extensions_json()
        if not extensions_data:
            logger.error(f"Fichier {JSON_EXTENSIONS} vide ou introuvable")
            return None

        is_supported = is_extension_supported(sanitized_name, platform, extensions_data)
        extension = os.path.splitext(sanitized_name)[1].lower()
        is_archive = extension in (".zip", ".rar")

        if is_supported:
            logger.debug(f"L'extension de {sanitized_name} est supportée pour {platform}")
            return (url, platform, game_name, False)
        elif is_archive:
            logger.debug(f"Archive {extension.upper()} détectée pour {sanitized_name}, extraction automatique prévue")
            return (url, platform, game_name, True)
        else:
            logger.debug(f"Extension non supportée ({extension}) pour {sanitized_name}, avertissement affiché")
            return (url, platform, game_name, False)
    except Exception as e:
        logger.error(f"Erreur vérification extension {url}: {str(e)}")
        return None

def is_1fichier_url(url):
    """Détecte si l'URL est un lien 1fichier."""
    return "1fichier.com" in url


def download_from_1fichier(url, platform, game_name, is_zip_non_supported=False):
    """Télécharge un fichier depuis 1fichier en utilisant l'API officielle."""
    logger.debug(f"Début téléchargement 1fichier: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}")
    result = [None, None]

    def download_thread():
        logger.debug(f"Thread téléchargement 1fichier démarré pour {url}")
        try:
            # Nettoyer l'URL
            link = url.split('&af=')[0]

            # Déterminer le répertoire de destination
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

            # Préparer les en-têtes et le payload
            headers = {
                "Authorization": f"Bearer {config.API_KEY_1FICHIER}",
                "Content-Type": "application/json"
            }
            payload = {
                "url": link,
                "pretty": 1
            }

            # Étape 1 : Obtenir les informations du fichier
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

            # Étape 2 : Obtenir le jeton de téléchargement
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

            # Étape 3 : Initialiser la progression
            lock = threading.Lock()
            with lock:
                config.download_progress[url] = {
                    "downloaded_size": 0,
                    "total_size": 0,
                    "status": "Téléchargement",
                    "progress_percent": 0,
                    "game_name": game_name
                }
                config.needs_redraw = True
            logger.debug(f"Progression initialisée pour {url}")

            # Étape 4 : Télécharger le fichier
            retries = 10
            retry_delay = 10
            for attempt in range(retries):
                try:
                    logger.debug(f"Tentative {attempt + 1} : Envoi requête GET à {final_url}")
                    with requests.get(final_url, stream=True, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30) as response:
                        logger.debug(f"Réponse reçue, status: {response.status_code}")
                        response.raise_for_status()
                        total_size = int(response.headers.get('content-length', 0))
                        logger.debug(f"Taille totale: {total_size} octets")
                        with lock:
                            config.download_progress[url]["total_size"] = total_size
                            config.needs_redraw = True

                        downloaded = 0
                        with open(dest_path, 'wb') as f:
                            logger.debug(f"Ouverture fichier: {dest_path}")
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    with lock:
                                        config.download_progress[url]["downloaded_size"] = downloaded
                                        config.download_progress[url]["status"] = "Téléchargement"
                                        config.download_progress[url]["progress_percent"] = (downloaded / total_size * 100) if total_size > 0 else 0
                                        config.needs_redraw = True
                                    #logger.debug(f"Progression: {downloaded}/{total_size} octets, {config.download_progress[url]['progress_percent']:.1f}%")

                    # Étape 5 : Extraire si nécessaire
                    if is_zip_non_supported:
                        with lock:
                            config.download_progress[url]["downloaded_size"] = 0
                            config.download_progress[url]["total_size"] = 0
                            config.download_progress[url]["status"] = "Extracting"
                            config.download_progress[url]["progress_percent"] = 0
                            config.needs_redraw = True
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
                        import time
                        time.sleep(retry_delay)
                    else:
                        logger.error("Nombre maximum de tentatives atteint")
                        result[0] = False
                        result[1] = f"Échec du téléchargement après {retries} tentatives"
                        return

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur API 1fichier : {e}")
            result[0] = False
            result[1] = f"Erreur lors de la requête API, la clé est peut etre incorrecte: {str(e)}"

        finally:
            logger.debug(f"Thread téléchargement 1fichier terminé pour {url}")
            with lock:
                config.download_result_message = result[1]
                config.download_result_error = not result[0]
                config.download_result_start_time = pygame.time.get_ticks()
                config.menu_state = "download_result"
                config.needs_redraw = True
                # Enregistrement dans l'historique
                add_to_history(platform, game_name, "Download_OK" if result[0] else "Erreur")
                config.history = load_history()
                logger.debug(f"Enregistrement dans l'historique: platform={platform}, game_name={game_name}, status={'Download_OK' if result[0] else 'Erreur'}")

    thread = threading.Thread(target=download_thread)
    logger.debug(f"Démarrage thread pour {url}")
    thread.start()
    thread.join()
    logger.debug(f"Thread rejoint pour {url}")

    return result[0], result[1]
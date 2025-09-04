import requests
import subprocess
import os
import sys
import threading
import pygame # type: ignore
import zipfile
import asyncio
import config
from config import OTA_VERSION_ENDPOINT,APP_FOLDER, UPDATE_FOLDER, OTA_UPDATE_ZIP
from utils import sanitize_filename, extract_zip, extract_rar, load_api_key_1fichier, normalize_platform_name
from history import save_history
import logging
import datetime
import queue
import time
import os
from language import _  # Import de la fonction de traduction


logger = logging.getLogger(__name__)


cache = {}
CACHE_TTL = 3600  # 1 heure
        
def test_internet():
    """Teste la connexion Internet de manière complète et portable pour Windows et Linux/Batocera."""
    logger.debug("=== Début test de connexion Internet complet ===")
    
    # Test 1: Ping vers serveurs DNS publics
    ping_option = '-n' if sys.platform.startswith("win") else '-c'
    dns_servers = ['8.8.8.8', '1.1.1.1', '208.67.222.222']  # Google, Cloudflare, OpenDNS
    
    ping_success = False
    for dns_server in dns_servers:
        logger.debug(f"Test ping vers {dns_server} avec option {ping_option}")
        try:
            result = subprocess.run(
                ['ping', ping_option, '2', dns_server],
                capture_output=True,
                text=True,
                timeout=8
            )
            if result.returncode == 0:
                logger.debug(f"[OK] Ping vers {dns_server} réussi")
                ping_success = True
                break
            else:
                logger.debug(f"[FAIL] Ping vers {dns_server} échoué (code: {result.returncode})")
                if result.stderr:
                    logger.debug(f"Erreur ping: {result.stderr.strip()}")
        except subprocess.TimeoutExpired:
            logger.debug(f"[FAIL] Timeout ping vers {dns_server}")
        except Exception as e:
            logger.debug(f"[FAIL] Exception ping vers {dns_server}: {str(e)}")
    
    # Test 2: Tentative de résolution DNS
    dns_success = False
    try:
        import socket
        logger.debug("Test de résolution DNS pour google.com")
        socket.gethostbyname('google.com')
        logger.debug("[OK] Résolution DNS réussie")
        dns_success = True
    except socket.gaierror as e:
        logger.debug(f"[FAIL] Erreur résolution DNS: {str(e)}")
    except Exception as e:
        logger.debug(f"[FAIL] Exception résolution DNS: {str(e)}")
    
    # Test 3: Tentative de connexion HTTP
    http_success = False
    test_urls = [
        'http://www.google.com',
        'http://www.cloudflare.com',
        'https://httpbin.org/get'
    ]
    
    for test_url in test_urls:
        logger.debug(f"Test connexion HTTP vers {test_url}")
        try:
            response = requests.get(test_url, timeout=5, allow_redirects=True)
            if response.status_code == 200:
                logger.debug(f"[OK] Connexion HTTP vers {test_url} réussie (code: {response.status_code})")
                http_success = True
                break
            else:
                logger.debug(f"[FAIL] Connexion HTTP vers {test_url} échouée (code: {response.status_code})")
        except requests.exceptions.Timeout:
            logger.debug(f"[FAIL] Timeout connexion HTTP vers {test_url}")
        except requests.exceptions.ConnectionError as e:
            logger.debug(f"[FAIL] Erreur connexion HTTP vers {test_url}: {str(e)}")
        except Exception as e:
            logger.debug(f"[FAIL] Exception connexion HTTP vers {test_url}: {str(e)}")
    
    # Analyse des résultats
    total_tests = 3
    passed_tests = sum([ping_success, dns_success, http_success])
    
    logger.debug(f"=== Résultats test Internet: {passed_tests}/{total_tests} tests réussis ===")
    logger.debug(f"Ping: {'[OK]' if ping_success else '[FAIL]'}")
    logger.debug(f"DNS:  {'[OK]' if dns_success else '[FAIL]'}")
    logger.debug(f"HTTP: {'[OK]' if http_success else '[FAIL]'}")
    
    # Diagnostic et conseils
    if passed_tests == 0:
        logger.error("Aucune connexion Internet détectée. Vérifiez:")
        logger.error("- Câble réseau ou WiFi connecté")
        logger.error("- Configuration proxy/firewall")
        logger.error("- Paramètres réseau système")
        return False
    elif passed_tests < total_tests:
        logger.warning(f"Connexion Internet partielle ({passed_tests}/{total_tests})")
        if not ping_success:
            logger.warning("- Ping échoué: possible blocage ICMP par firewall")
        if not dns_success:
            logger.warning("- DNS échoué: problème serveurs DNS")
        if not http_success:
            logger.warning("- HTTP échoué: possible blocage proxy/firewall")
        return True  # Connexion partielle acceptable
    else:
        logger.debug("[OK] Connexion Internet complète et fonctionnelle")
        return True


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
            update_zip_path = os.path.join(UPDATE_FOLDER, f"RGSX_v{latest_version}.zip")
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
            # Message succès de mise à jour
            config.update_result_message = _("network_update_success").format(latest_version)
            # Utiliser aussi le système générique de popup pour affichage
            config.popup_message = config.update_result_message
            config.popup_timer = 5000  # 5 secondes
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
        config.popup_message = config.update_result_message
        config.popup_timer = 5000
        config.update_result_error = True
        config.update_result_start_time = pygame.time.get_ticks()
        config.needs_redraw = True
        return False, _("network_check_update_error").format(str(e))

def extract_update(zip_path, dest_dir, source_url):
    
    try:
        os.makedirs(dest_dir, exist_ok=True)
        logger.debug(f"Tentative d'ouverture du ZIP : {zip_path}")
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

# File d'attente pour la progression - une par tâche
progress_queues = {}



async def download_rom(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    logger.debug(f"Début téléchargement: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}, task_id={task_id}")
    result = [None, None]
    
    # Créer une queue spécifique pour cette tâche
    if task_id not in progress_queues:
        progress_queues[task_id] = queue.Queue()
    
    def download_thread():
        logger.debug(f"Thread téléchargement démarré pour {url}, task_id={task_id}")
        try:
            # Use symlink path if enabled
            from rgsx_settings import apply_symlink_path
            
            dest_dir = None
            for platform_dict in config.platform_dicts:
                if platform_dict.get("platform_name") == platform:
                    platform_folder = platform_dict.get("folder", normalize_platform_name(platform))
                    dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)
                    logger.debug(f"Répertoire de destination trouvé pour {platform}: {dest_dir}")
                    break
            if not dest_dir:
                platform_folder = normalize_platform_name(platform)
                dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)

            # Spécifique: si le système est "00 BIOS" on force le dossier BIOS
            if platform == "00 BIOS":
                dest_dir = config.BIOS_FOLDER
                logger.debug(f"Plateforme '00 BIOS' détectée, destination forcée vers BIOS_FOLDER: {dest_dir}")
            
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
            
            session = requests.Session()
            session.headers.update(headers)
            
            download_headers = headers.copy()
            download_headers['Accept'] = 'application/octet-stream, */*'
            download_headers['Referer'] = 'https://myrient.erista.me/'

            # Préparation spécifique archive.org : récupérer quelques pages pour obtenir cookies éventuels
            if 'archive.org/download/' in url:
                try:
                    pre_id = url.split('/download/')[1].split('/')[0]
                    session.get('https://archive.org/robots.txt', timeout=10)
                    session.get(f'https://archive.org/metadata/{pre_id}', timeout=10)
                    logger.debug(f"Pré-chargement cookies/metadata archive.org pour {pre_id}")
                except Exception as e:
                    logger.debug(f"Pré-chargement archive.org ignoré: {e}")
            # Tentatives multiples avec variations d'en-têtes pour contourner certains 401/403 (archive.org / hotlink protection)
            header_variants = [
                download_headers,
                {  # Variante sans Referer spécifique
                    'User-Agent': headers['User-Agent'],
                    'Accept': 'application/octet-stream,*/*;q=0.8',
                    'Accept-Language': headers['Accept-Language'],
                    'Connection': 'keep-alive'
                },
                {  # Variante minimaliste type curl
                    'User-Agent': 'curl/8.4.0',
                    'Accept': '*/*'
                },
                {  # Variante avec Referer archive.org
                    'User-Agent': headers['User-Agent'],
                    'Accept': '*/*',
                    'Referer': 'https://archive.org/'
                }
            ]
            response = None
            last_status = None
            for attempt, hv in enumerate(header_variants, start=1):
                try:
                    logger.debug(f"Tentative téléchargement {attempt}/{len(header_variants)} avec headers: {hv}")
                    r = session.get(url, stream=True, timeout=30, allow_redirects=True, headers=hv)
                    last_status = r.status_code
                    logger.debug(f"Status code tentative {attempt}: {r.status_code}")
                    if r.status_code in (401, 403):
                        # Lire un petit bout pour voir si message utile
                        try:
                            snippet = r.text[:200]
                            logger.debug(f"Réponse {r.status_code} snippet: {snippet}")
                        except Exception:
                            pass
                        continue  # Essayer variante suivante
                    r.raise_for_status()
                    response = r
                    break
                except requests.RequestException as e:
                    logger.debug(f"Erreur tentative {attempt}: {e}")
                    # Si ce n'est pas une erreur auth explicite et qu'on a un code => on sort
                    if isinstance(e, requests.HTTPError) and last_status not in (401, 403):
                        break
            if response is None:
                # Fallback metadata archive.org pour message clair
                if 'archive.org/download/' in url:
                    try:
                        identifier = url.split('/download/')[1].split('/')[0]
                        meta_resp = session.get(f'https://archive.org/metadata/{identifier}', timeout=15)
                        if meta_resp.status_code == 200:
                            meta_json = meta_resp.json()
                            if meta_json.get('is_dark'):
                                raise requests.HTTPError(f"Item archive.org restreint (is_dark=true): {identifier}")
                            if not meta_json.get('files'):
                                raise requests.HTTPError(f"Item archive.org sans fichiers listés: {identifier}")
                            # Fichier peut avoir un nom différent : informer
                            available = [f.get('name') for f in meta_json.get('files', [])][:10]
                            raise requests.HTTPError(f"Accès refusé (HTTP {last_status}). Fichiers disponibles exemples: {available}")
                        else:
                            raise requests.HTTPError(f"HTTP {last_status} & metadata {meta_resp.status_code} pour {identifier}")
                    except requests.HTTPError:
                        raise
                    except Exception as e:
                        raise requests.HTTPError(f"HTTP {last_status} après variations; metadata échec: {e}")
                auth_msg = f"HTTP {last_status} après variations d'en-têtes" if last_status else "Aucune réponse valide"
                raise requests.HTTPError(auth_msg)
            
            total_size = int(response.headers.get('content-length', 0))
            logger.debug(f"Taille totale: {total_size} octets")
            if isinstance(config.history, list):
                for entry in config.history:
                    if "url" in entry and entry["url"] == url:
                        entry["total_size"] = total_size  # Ajouter la taille totale
                        save_history(config.history)
                        break
            
            # Initialiser la progression avec task_id
            progress_queues[task_id].put((task_id, 0, total_size))
            logger.debug(f"Progression initiale envoyée: 0% pour {game_name}, task_id={task_id}")
            
            downloaded = 0
            chunk_size = 4096
            last_update_time = time.time()
            last_downloaded = 0
            update_interval = 0.1  # Mettre à jour toutes les 0,1 secondes
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        size_received = len(chunk)
                        f.write(chunk)
                        downloaded += size_received
                        current_time = time.time()
                        if current_time - last_update_time >= update_interval:
                            # Calcul de la vitesse en Mo/s
                            delta = downloaded - last_downloaded
                            speed = delta / (current_time - last_update_time) / (1024 * 1024)
                            last_downloaded = downloaded
                            last_update_time = current_time
                            progress_queues[task_id].put((task_id, downloaded, total_size, speed))

            
            os.chmod(dest_path, 0o644)
            logger.debug(f"Téléchargement terminé: {dest_path}")
            
            if is_zip_non_supported:
                logger.debug(f"Extraction automatique nécessaire pour {dest_path}")
                extension = os.path.splitext(dest_path)[1].lower()
                if extension == ".zip":
                    try:
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
            progress_queues[task_id].put((task_id, result[0], result[1]))
            logger.debug(f"Final result sent to queue: success={result[0]}, message={result[1]}, task_id={task_id}")

    thread = threading.Thread(target=download_thread)
    thread.start()
    
    # Boucle principale pour mettre à jour la progression
    while thread.is_alive():
        try:
            task_queue = progress_queues.get(task_id)
            if task_queue:
                while not task_queue.empty():
                    data = task_queue.get()
                    #logger.debug(f"Progress queue data received: {data}")
                    if isinstance(data[1], bool):  # Fin du téléchargement
                        success, message = data[1], data[2]
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement", "Extracting"]:
                                    entry["status"] = "Download_OK" if success else "Erreur"
                                    entry["progress"] = 100 if success else 0
                                    entry["message"] = message
                                    save_history(config.history)
                                    config.needs_redraw = True
                                    logger.debug(f"Final update in history: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                                    break
                    else:
                        if len(data) >= 4:
                            downloaded, total_size, speed = data[1], data[2], data[3]
                        else:
                            downloaded, total_size = data[1], data[2]
                            speed = 0.0
                        progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                        progress_percent = max(0, min(100, progress_percent))
                            
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                                    entry["progress"] = progress_percent
                                    entry["status"] = "Téléchargement"
                                    entry["downloaded_size"] = downloaded
                                    entry["total_size"] = total_size
                                    entry["speed"] = speed  # Ajout de la vitesse
                                    config.needs_redraw = True
                                    break           
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Erreur mise à jour progression: {str(e)}")
    
    thread.join()
    # Nettoyer la queue
    if task_id in progress_queues:
        del progress_queues[task_id]
    return result[0], result[1]

async def download_from_1fichier(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    config.API_KEY_1FICHIER = load_api_key_1fichier()
    logger.debug(f"Début téléchargement 1fichier: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}, task_id={task_id}")
    logger.debug(f"Clé API 1fichier: {'présente' if config.API_KEY_1FICHIER else 'absente'}")
    result = [None, None]

    # Créer une queue spécifique pour cette tâche
    logger.debug(f"Création queue pour task_id={task_id}")
    if task_id not in progress_queues:
        progress_queues[task_id] = queue.Queue()

    def download_thread():
        logger.debug(f"Thread téléchargement 1fichier démarré pour {url}, task_id={task_id}")
        try:
            link = url.split('&af=')[0]
            logger.debug(f"URL nettoyée: {link}")
            # Use symlink path if enabled
            from rgsx_settings import apply_symlink_path
            
            dest_dir = None
            for platform_dict in config.platform_dicts:
                if platform_dict.get("platform_name") == platform:
                    platform_folder = platform_dict.get("folder", normalize_platform_name(platform))
                    dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)
                    break
            if not dest_dir:
                logger.warning(f"Aucun dossier 'folder' trouvé pour la plateforme {platform}")
                platform_folder = normalize_platform_name(platform)
                dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)
            logger.debug(f"Répertoire destination déterminé: {dest_dir}")

            # Spécifique: si le système est "00 BIOS" on force le dossier BIOS
            if platform == "00 BIOS":
                dest_dir = config.BIOS_FOLDER
                logger.debug(f"Plateforme '00 BIOS' détectée, destination forcée vers BIOS_FOLDER: {dest_dir}")

            logger.debug(f"Vérification répertoire destination: {dest_dir}")
            os.makedirs(dest_dir, exist_ok=True)
            logger.debug(f"Répertoire créé ou existant: {dest_dir}")
            if not os.access(dest_dir, os.W_OK):
                logger.error(f"Pas de permission d'écriture dans {dest_dir}")
                raise PermissionError(f"Pas de permission d'écriture dans {dest_dir}")

            headers = {
                "Authorization": f"Bearer {config.API_KEY_1FICHIER}",
                "Content-Type": "application/json"
            }
            payload = {
                "url": link,
                "pretty": 1
            }
            logger.debug(f"Préparation requête file/info pour {link}")
            response = requests.post("https://api.1fichier.com/v1/file/info.cgi", headers=headers, json=payload, timeout=30)
            logger.debug(f"Réponse file/info reçue, code: {response.status_code}")
            response.raise_for_status()
            file_info = response.json()

            if "error" in file_info and file_info["error"] == "Resource not found":
                logger.error(f"Le fichier {game_name} n'existe pas sur 1fichier")
                result[0] = False
                result[1] = _("network_file_not_found").format(game_name)
                return

            filename = file_info.get("filename", "").strip()
            if not filename:
                logger.error(f"Impossible de récupérer le nom du fichier")
                result[0] = False
                result[1] = _("network_cannot_get_filename")
                return

            sanitized_filename = sanitize_filename(filename)
            dest_path = os.path.join(dest_dir, sanitized_filename)
            logger.debug(f"Chemin destination: {dest_path}")
            logger.debug(f"Envoi requête get_token pour {link}")
            response = requests.post("https://api.1fichier.com/v1/download/get_token.cgi", headers=headers, json=payload, timeout=30)
            logger.debug(f"Réponse get_token reçue, code: {response.status_code}")
            response.raise_for_status()
            download_info = response.json()

            final_url = download_info.get("url")
            if not final_url:
                logger.error(f"Impossible de récupérer l'URL de téléchargement")
                result[0] = False
                result[1] = _("network_cannot_get_download_url")
                return

            logger.debug(f"URL de téléchargement obtenue: {final_url}")
            lock = threading.Lock()
            retries = 10
            retry_delay = 10
            logger.debug(f"Initialisation progression avec taille inconnue pour task_id={task_id}")
            progress_queues[task_id].put((task_id, 0, 0))  # Taille initiale inconnue
            for attempt in range(retries):
                logger.debug(f"Début tentative {attempt + 1} pour télécharger {final_url}")
                try:
                    with requests.get(final_url, stream=True, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30) as response:
                        logger.debug(f"Réponse GET reçue, code: {response.status_code}")
                        response.raise_for_status()
                        total_size = int(response.headers.get('content-length', 0))
                        logger.debug(f"Taille totale: {total_size} octets")
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url:
                                    entry["total_size"] = total_size  # Ajouter la taille totale
                                    save_history(config.history)
                                    break
                        with lock:
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url and entry["status"] == "downloading":
                                        entry["total_size"] = total_size
                                        config.needs_redraw = True
                                        break
                            progress_queues[task_id].put((task_id, 0, total_size))  # Mettre à jour la taille totale

                        downloaded = 0
                        chunk_size = 8192
                        last_update_time = time.time()
                        update_interval = 0.1  # Mettre à jour toutes les 0,1 secondes
                        logger.debug(f"Ouverture fichier: {dest_path}")
                        with open(dest_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    current_time = time.time()
                                    if current_time - last_update_time >= update_interval:
                                        with lock:
                                            if isinstance(config.history, list):
                                                for entry in config.history:
                                                    if "url" in entry and entry["url"] == url and entry["status"] == "downloading":
                                                        progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                                                        progress_percent = max(0, min(100, progress_percent))
                                                        entry["progress"] = progress_percent
                                                        entry["status"] = "Téléchargement"
                                                        entry["downloaded_size"] = downloaded
                                                        entry["total_size"] = total_size
                                                        config.needs_redraw = True
                                                        break
                                        progress_queues[task_id].put((task_id, downloaded, total_size))
                                        last_update_time = current_time

                    if is_zip_non_supported:
                        with lock:
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url and entry["status"] == "Téléchargement":
                                        entry["progress"] = 0
                                        entry["status"] = "Extracting"
                                        config.needs_redraw = True
                                        break
                        extension = os.path.splitext(dest_path)[1].lower()
                        logger.debug(f"Début extraction, type d'archive: {extension}")
                        if extension == ".zip":
                            try:
                                success, msg = extract_zip(dest_path, dest_dir, url)
                                logger.debug(f"Extraction ZIP terminée: {msg}")
                                if success:
                                    result[0] = True
                                    result[1] = _("network_download_extract_ok").format(game_name)
                                else:
                                    logger.error(f"Erreur extraction ZIP: {msg}")
                                    result[0] = False
                                    result[1] = _("network_extraction_failed").format(msg)
                            except Exception as e:
                                logger.error(f"Exception lors de l'extraction ZIP: {str(e)}")
                                result[0] = False
                                result[1] = f"Erreur téléchargement {game_name}: {str(e)}"
                        elif extension == ".rar":
                            try:
                                success, msg = extract_rar(dest_path, dest_dir, url)
                                logger.debug(f"Extraction RAR terminée: {msg}")
                                if success:
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
                        logger.debug(f"Application des permissions sur {dest_path}")
                        os.chmod(dest_path, 0o644)
                        logger.debug(f"Téléchargement terminé: {dest_path}")
                        result[0] = True
                        result[1] = _("network_download_ok").format(game_name)
                    return

                except requests.exceptions.RequestException as e:
                    logger.error(f"Tentative {attempt + 1} échouée: {e}")
                    if attempt < retries - 1:
                        logger.debug(f"Attente de {retry_delay} secondes avant nouvelle tentative")
                        time.sleep(retry_delay)
                    else:
                        logger.error(f"Nombre maximum de tentatives atteint")
                        result[0] = False
                        result[1] = _("network_download_failed").format(retries)
                        return

        except requests.exceptions.RequestException as e:
            logger.error(f"Erreur API 1fichier: {e}")
            result[0] = False
            result[1] = _("network_api_error").format(str(e))

        finally:
            logger.debug(f"Thread téléchargement 1fichier terminé pour {url}, task_id={task_id}")
            progress_queues[task_id].put((task_id, result[0], result[1]))
            logger.debug(f"Résultat final envoyé à la queue: success={result[0]}, message={result[1]}, task_id={task_id}")

    logger.debug(f"Démarrage thread pour {url}, task_id={task_id}")
    thread = threading.Thread(target=download_thread)
    thread.start()

    # Boucle principale pour mettre à jour la progression
    logger.debug(f"Début boucle de progression pour task_id={task_id}")
    while thread.is_alive():
        try:
            task_queue = progress_queues.get(task_id)
            if task_queue:
                while not task_queue.empty():
                    data = task_queue.get()
                    logger.debug(f"Données queue progression reçues: {data}")
                    if isinstance(data[1], bool):  # Fin du téléchargement
                        success, message = data[1], data[2]
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement", "Extracting"]:
                                    entry["status"] = "Download_OK" if success else "Erreur"
                                    entry["progress"] = 100 if success else 0
                                    entry["message"] = message
                                    save_history(config.history)
                                    config.needs_redraw = True
                                    logger.debug(f"Mise à jour finale historique: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                                    break
                    else:
                        downloaded, total_size = data[1], data[2]
                        progress_percent = int(downloaded / total_size * 100) if total_size > 0 else 0
                        progress_percent = max(0, min(100, progress_percent))
                        
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                                    entry["progress"] = progress_percent
                                    entry["status"] = "Téléchargement"
                                    entry["downloaded_size"] = downloaded
                                    entry["total_size"] = total_size
                                    config.needs_redraw = True
                                    break
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Erreur mise à jour progression: {str(e)}")

    logger.debug(f"Fin boucle de progression, attente fin thread pour task_id={task_id}")
    thread.join()
    logger.debug(f"Thread terminé, nettoyage queue pour task_id={task_id}")
    # Nettoyer la queue
    if task_id in progress_queues:
        del progress_queues[task_id]
    logger.debug(f"Fin download_from_1fichier, résultat: success={result[0]}, message={result[1]}")
    return result[0], result[1]
def is_1fichier_url(url):
    """Détecte si l'URL est un lien 1fichier."""
    return "1fichier.com" in url
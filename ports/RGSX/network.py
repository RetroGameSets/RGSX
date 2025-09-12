import requests
import subprocess
import os
import sys
import threading
import zipfile
import asyncio
import config
from config import HEADLESS
try:
    if not HEADLESS:
        import pygame  # type: ignore
    else:
        pygame = None  # type: ignore
except Exception:
    pygame = None  # type: ignore
from config import OTA_VERSION_ENDPOINT,APP_FOLDER, UPDATE_FOLDER, OTA_UPDATE_ZIP
from utils import sanitize_filename, extract_zip, extract_rar, load_api_key_1fichier, load_api_key_alldebrid, normalize_platform_name, load_api_keys
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
            raise ValueError(
                f"Le fichier version.json n'est pas un JSON valide (type de contenu : {response.headers.get('content-type')})"
            )
        version_data = response.json()
        latest_version = version_data.get("version")
        logger.debug(f"Version distante : {latest_version}, version locale : {config.app_version}")

        # --- Protection anti-downgrade ---
        def _parse_version(v: str):
            try:
                return [int(p) for p in str(v).strip().split('.') if p.isdigit()]
            except Exception:
                return [0]

        local_parts = _parse_version(getattr(config, 'app_version', '0'))
        remote_parts = _parse_version(latest_version or '0')
        # Normaliser longueur
        max_len = max(len(local_parts), len(remote_parts))
        local_parts += [0] * (max_len - len(local_parts))
        remote_parts += [0] * (max_len - len(remote_parts))
        logger.debug(f"Comparaison versions normalisées local={local_parts} remote={remote_parts}")
        if remote_parts <= local_parts:
            # Pas de mise à jour si version distante identique ou inférieure (empêche downgrade accidentel)
            logger.info("Version distante inférieure ou égale – skip mise à jour (anti-downgrade)")
            return True, _("network_no_update_available") if _ else "No update (local >= remote)"

        # À ce stade latest_version est strictement > version locale
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

            # Configurer la popup puis redémarrer automatiquement
            config.menu_state = "restart_popup"
            config.update_result_message = _("network_update_success").format(latest_version)
            config.popup_message = config.update_result_message
            config.popup_timer = 2000
            config.update_result_error = False
            config.update_result_start_time = pygame.time.get_ticks() if pygame is not None else 0
            config.needs_redraw = True
            logger.debug(f"Affichage de la popup de mise à jour réussie, redémarrage imminent")

            try:
                from utils import restart_application
                restart_application(2000)
            except Exception as e:
                logger.error(f"Erreur lors du redémarrage après mise à jour: {e}")

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
        config.update_result_start_time = pygame.time.get_ticks() if pygame is not None else 0
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
# Cancellation and thread tracking per download task
cancel_events = {}
download_threads = {}

def request_cancel(task_id: str) -> bool:
    """Request cancellation for a running download task by its task_id."""
    ev = cancel_events.get(task_id)
    if ev is not None:
        try:
            ev.set()
            logger.debug(f"Cancel requested for task_id={task_id}")
            return True
        except Exception as e:
            logger.debug(f"Failed to set cancel for task_id={task_id}: {e}")
            return False
    logger.debug(f"No cancel event found for task_id={task_id}")
    return False

def cancel_all_downloads():
    """Cancel all active downloads and attempt to stop threads quickly."""
    for tid, ev in list(cancel_events.items()):
        try:
            ev.set()
        except Exception:
            pass
    # Optionally join threads briefly
    for tid, th in list(download_threads.items()):
        try:
            if th.is_alive():
                th.join(timeout=0.2)
        except Exception:
            pass



async def download_rom(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    logger.debug(f"Début téléchargement: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}, task_id={task_id}")
    result = [None, None]
    
    # Créer une queue/cancel spécifique pour cette tâche
    if task_id not in progress_queues:
        progress_queues[task_id] = queue.Queue()
    if task_id not in cancel_events:
        cancel_events[task_id] = threading.Event()
    
    def download_thread():
        logger.debug(f"Thread téléchargement démarré pour {url}, task_id={task_id}")
        try:
            cancel_ev = cancel_events.get(task_id)
            # Use symlink path if enabled
            from rgsx_settings import apply_symlink_path
            
            dest_dir = None
            for platform_dict in config.platform_dicts:
                if platform_dict.get("platform_name") == platform:
                    # Priorité: clé 'folder'; fallback legacy: 'dossier'; sinon normalisation du nom de plateforme
                    platform_folder = platform_dict.get("folder") or platform_dict.get("dossier") or normalize_platform_name(platform)
                    dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)
                    logger.debug(f"Répertoire de destination trouvé pour {platform}: {dest_dir}")
                    break
            if not dest_dir:
                platform_folder = normalize_platform_name(platform)
                dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)

            # Spécifique: si le système est "BIOS" on force le dossier BIOS
            if platform_folder == "bios" or platform == "BIOS" or platform == "- BIOS by TMCTV -":
                dest_dir = config.USERDATA_FOLDER
                logger.debug(f"Plateforme 'BIOS' détectée, destination forcée vers USERDATA_FOLDER: {dest_dir}")
            
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
                    if cancel_ev is not None and cancel_ev.is_set():
                        logger.debug(f"Annulation détectée, arrêt du téléchargement pour task_id={task_id}")
                        result[0] = False
                        result[1] = _("download_canceled") if _ else "Download canceled"
                        try:
                            f.close()
                        except Exception:
                            pass
                        try:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                        except Exception:
                            pass
                        break
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
            
            # Forcer extraction si plateforme BIOS même si le pré-check ne l'avait pas marqué
            force_extract = is_zip_non_supported
            if not force_extract:
                try:
                    bios_like = {"BIOS", "- BIOS by TMCTV -", "- BIOS"}
                    if platform_folder == "bios" or platform in bios_like:
                        force_extract = True
                        logger.debug("Extraction forcée activée pour BIOS")
                except Exception:
                    pass

            if force_extract:
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

    thread = threading.Thread(target=download_thread, daemon=True)
    download_threads[task_id] = thread
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
    try:
        download_threads.pop(task_id, None)
    except Exception:
        pass
    # Drain any remaining final message to ensure history is saved
    try:
        task_queue = progress_queues.get(task_id)
        if task_queue:
            while not task_queue.empty():
                data = task_queue.get()
                if isinstance(data[1], bool):
                    success, message = data[1], data[2]
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                entry["message"] = message
                                save_history(config.history)
                                break
    except Exception:
        pass

    # Exécuter la mise à jour de la liste des jeux d'EmulationStation UNIQUEMENT sur Batocera
    try:
        from config import get_operating_system
        OPERATING_SYSTEM=get_operating_system()
        if str(OPERATING_SYSTEM).lower() == "linux":
            resp = requests.get("http://127.0.0.1:1234/reloadgames", timeout=2)
            content = (resp.text or "").strip()
            logger.debug(f"Résultat mise à jour liste des jeux: HTTP {resp.status_code} - {content}")
        else:
            logger.debug(f"Mise à jour liste des jeux ignorée (environnement non Linux: {getattr(config, 'OPERATING_SYSTEM', 'unknown')})")
    except Exception as e:
        logger.debug(f"Échec mise à jour via requête HTTP locale (Batocera): {e}")
    
    # Nettoyer la queue
    if task_id in progress_queues:
        del progress_queues[task_id]
    cancel_events.pop(task_id, None)
    return result[0], result[1]

async def download_from_1fichier(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    # Charger/rafraîchir les clés API (mtime aware)
    keys_info = load_api_keys()
    config.API_KEY_1FICHIER = keys_info.get('1fichier', '')
    config.API_KEY_ALLDEBRID = keys_info.get('alldebrid', '')
    config.API_KEY_REALDEBRID = keys_info.get('realdebrid', '')
    if not config.API_KEY_1FICHIER and config.API_KEY_ALLDEBRID:
        logger.debug("Clé 1fichier absente, utilisation fallback AllDebrid")
    if not config.API_KEY_1FICHIER and not config.API_KEY_ALLDEBRID and config.API_KEY_REALDEBRID:
        logger.debug("Clé 1fichier & AllDebrid absentes, utilisation fallback RealDebrid")
    elif not config.API_KEY_1FICHIER and not config.API_KEY_ALLDEBRID and not config.API_KEY_REALDEBRID:
        logger.debug("Aucune clé API disponible (1fichier, AllDebrid, RealDebrid)")
    logger.debug(f"Début téléchargement 1fichier: {game_name} depuis {url}, is_zip_non_supported={is_zip_non_supported}, task_id={task_id}")
    logger.debug(
        f"Clé API 1fichier: {'présente' if config.API_KEY_1FICHIER else 'absente'} / "
        f"AllDebrid: {'présente' if config.API_KEY_ALLDEBRID else 'absente'} / "
        f"RealDebrid: {'présente' if config.API_KEY_REALDEBRID else 'absente'} (reloaded={keys_info.get('reloaded')})"
    )
    result = [None, None]

    # Créer une queue spécifique pour cette tâche
    logger.debug(f"Création queue pour task_id={task_id}")
    if task_id not in progress_queues:
        progress_queues[task_id] = queue.Queue()
    if task_id not in cancel_events:
        cancel_events[task_id] = threading.Event()

    provider_used = None  # '1F', 'AD', 'RD'

    def _set_provider_in_history(pfx: str):
        try:
            if not pfx:
                return
            if isinstance(config.history, list):
                for entry in config.history:
                    if entry.get("url") == url:
                        entry["provider"] = pfx
                        entry["provider_prefix"] = f"{pfx}:"
                        try:
                            save_history(config.history)
                        except Exception:
                            pass
                        config.needs_redraw = True
                        break
        except Exception:
            pass

    def download_thread():
        logger.debug(f"Thread téléchargement 1fichier démarré pour {url}, task_id={task_id}")
        # Assurer l'accès à provider_used dans cette closure (lecture/écriture)
        nonlocal provider_used
        try:
            cancel_ev = cancel_events.get(task_id)
            link = url.split('&af=')[0]
            logger.debug(f"URL nettoyée: {link}")
            # Use symlink path if enabled
            from rgsx_settings import apply_symlink_path
            
            dest_dir = None
            for platform_dict in config.platform_dicts:
                if platform_dict.get("platform_name") == platform:
                    platform_folder = platform_dict.get("folder") or platform_dict.get("dossier") or normalize_platform_name(platform)
                    dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)
                    break
            if not dest_dir:
                logger.warning(f"Aucun dossier 'folder'/'dossier' trouvé pour la plateforme {platform}")
                platform_folder = normalize_platform_name(platform)
                dest_dir = apply_symlink_path(config.ROMS_FOLDER, platform_folder)
            logger.debug(f"Répertoire destination déterminé: {dest_dir}")

            # Spécifique: si le système est "- BIOS by TMCTV -" on force le dossier BIOS
            if platform_folder == "bios" or platform == "BIOS" or platform == "- BIOS by TMCTV -":
                dest_dir = config.USERDATA_FOLDER
                logger.debug(f"Plateforme '- BIOS by TMCTV -' détectée, destination forcée vers USERDATA_FOLDER: {dest_dir}")

            logger.debug(f"Vérification répertoire destination: {dest_dir}")
            os.makedirs(dest_dir, exist_ok=True)
            logger.debug(f"Répertoire créé ou existant: {dest_dir}")
            if not os.access(dest_dir, os.W_OK):
                logger.error(f"Pas de permission d'écriture dans {dest_dir}")
                raise PermissionError(f"Pas de permission d'écriture dans {dest_dir}")

            # Choisir la stratégie d'accès: 1fichier direct via API, sinon AllDebrid pour débrider
            if config.API_KEY_1FICHIER:
                logger.debug("Mode téléchargement sélectionné: 1fichier (API directe)")
                headers = {
                    "Authorization": f"Bearer {config.API_KEY_1FICHIER}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "url": link,
                    "pretty": 1
                }
                logger.debug(f"Préparation requête 1fichier file/info pour {link}")
                response = requests.post("https://api.1fichier.com/v1/file/info.cgi", headers=headers, json=payload, timeout=30)
                logger.debug(f"Réponse file/info reçue, code: {response.status_code}")
                file_info = None
                raw_fileinfo_text = None
                try:
                    raw_fileinfo_text = response.text
                except Exception:
                    pass
                try:
                    file_info = response.json()
                except Exception:
                    file_info = None
                if response.status_code != 200:
                    # 403 souvent = clé invalide ou accès interdit
                    friendly = None
                    raw_err = None
                    if isinstance(file_info, dict):
                        raw_err = file_info.get('message') or file_info.get('error') or file_info.get('status')
                        if raw_err == 'Bad token':
                            friendly = "1F: Clé API 1fichier invalide"
                        elif raw_err:
                            friendly = f"1F: {raw_err}"
                    if not friendly:
                        if response.status_code == 403:
                            friendly = "1F: Accès refusé (403)"
                        elif response.status_code == 401:
                            friendly = "1F: Non autorisé (401)"
                        else:
                            friendly = f"1F: Erreur HTTP {response.status_code}"
                    result[0] = False
                    result[1] = friendly
                    try:
                        result.append({"raw_error_1fichier_fileinfo": raw_err or raw_fileinfo_text})
                    except Exception:
                        pass
                    return
                # Status 200 requis à partir d'ici
                file_info = file_info if isinstance(file_info, dict) else {}
                if "error" in file_info and file_info["error"] == "Resource not found":
                    logger.error(f"Le fichier {game_name} n'existe pas sur 1fichier")
                    result[0] = False
                    try:
                        if _:
                            # Build translated message safely without nesting quotes in f-string
                            not_found_tpl = _("network_file_not_found")
                            msg_nf = not_found_tpl.format(game_name) if "{" in not_found_tpl else f"{not_found_tpl} {game_name}"
                            result[1] = f"1F: {msg_nf}"
                        else:
                            result[1] = f"1F: File not found {game_name}"
                    except Exception:
                        result[1] = f"1F: File not found {game_name}"
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
                logger.debug(f"Envoi requête 1fichier get_token pour {link}")
                response = requests.post("https://api.1fichier.com/v1/download/get_token.cgi", headers=headers, json=payload, timeout=30)
                status_1f = response.status_code
                raw_text_1f = None
                try:
                    raw_text_1f = response.text
                except Exception:
                    pass
                logger.debug(f"Réponse get_token reçue, code: {status_1f} body_snippet={(raw_text_1f[:120] + '...') if raw_text_1f and len(raw_text_1f) > 120 else raw_text_1f}")
                download_info = None
                try:
                    download_info = response.json()
                except Exception:
                    download_info = None
                # Même en cas de code !=200 on tente de récupérer un message JSON exploitable
                if status_1f != 200:
                    friendly_1f = None
                    raw_error_1f = None
                    if isinstance(download_info, dict):
                        # Exemples de réponses d'erreur 1fichier: {"status":"KO","message":"Bad token"} ou autres
                        raw_error_1f = download_info.get('message') or download_info.get('status')
                        # Mapping simple pour les messages fréquents / cas premium requis
                        ONEFICHIER_ERROR_MAP = {
                            "Bad token": "1F: Clé API invalide",
                            "Must be a customer (Premium, Access) #236": "1F: Compte Premium requis",
                        }
                        if raw_error_1f:
                            friendly_1f = ONEFICHIER_ERROR_MAP.get(raw_error_1f)
                    if not friendly_1f:
                        # Fallback générique sur code HTTP
                        if status_1f == 403:
                            friendly_1f = "1F: Accès refusé (403)"
                        elif status_1f == 401:
                            friendly_1f = "1F: Non autorisé (401)"
                        elif status_1f >= 500:
                            friendly_1f = f"1F: Erreur serveur ({status_1f})"
                        else:
                            friendly_1f = f"1F: Erreur ({status_1f})"
                    # Stocker et retourner tôt car pas de token valide
                    result[0] = False
                    result[1] = friendly_1f
                    try:
                        result.append({"raw_error_1fichier": raw_error_1f or raw_text_1f})
                    except Exception:
                        pass
                    return
                # Si status 200 on continue normalement
                response.raise_for_status()
                if not isinstance(download_info, dict):
                    logger.error("Réponse 1fichier inattendue (pas un JSON) pour get_token")
                    result[0] = False
                    result[1] = _("network_api_error").format("1fichier invalid JSON") if _ else "1fichier invalid JSON"
                    return
                final_url = download_info.get("url")
                if not final_url:
                    logger.error("Impossible de récupérer l'URL de téléchargement")
                    result[0] = False
                    result[1] = _("network_cannot_get_download_url")
                    return
                logger.debug(f"URL de téléchargement obtenue via 1fichier: {final_url}")
                provider_used = '1F'
                _set_provider_in_history(provider_used)
            else:
                final_url = None
                filename = None
                # Tentative AllDebrid
                if getattr(config, 'API_KEY_ALLDEBRID', ''):
                    logger.debug("Mode téléchargement sélectionné: AllDebrid (fallback 1)")
                    try:
                        ad_key = config.API_KEY_ALLDEBRID
                        params = {'agent': 'RGSX', 'apikey': ad_key, 'link': link}
                        logger.debug("Requête AllDebrid link/unlock en cours")
                        response = requests.get("https://api.alldebrid.com/v4/link/unlock", params=params, timeout=30)
                        logger.debug(f"Réponse AllDebrid reçue, code: {response.status_code}")
                        response.raise_for_status()
                        ad_json = response.json()
                        if ad_json.get('status') == 'success':
                            data = ad_json.get('data', {})
                            filename = data.get('filename') or game_name
                            final_url = data.get('link') or data.get('download') or data.get('streamingLink')
                            if final_url:
                                logger.debug("Débridage réussi via AllDebrid")
                                provider_used = 'AD'
                                _set_provider_in_history(provider_used)
                        else:
                            logger.warning(f"AllDebrid status != success: {ad_json}")
                    except Exception as e:
                        logger.error(f"Erreur AllDebrid fallback: {e}")
                # Tentative RealDebrid si pas de final_url
                if not final_url and getattr(config, 'API_KEY_REALDEBRID', ''):
                    logger.debug("Tentative fallback RealDebrid (unlock)")
                    try:
                        rd_key = config.API_KEY_REALDEBRID
                        headers_rd = {"Authorization": f"Bearer {rd_key}"}
                        rd_resp = requests.post(
                            "https://api.real-debrid.com/rest/1.0/unrestrict/link",
                            data={"link": link},
                            headers=headers_rd,
                            timeout=30
                        )
                        status = rd_resp.status_code
                        raw_text = None
                        rd_json = None
                        try:
                            raw_text = rd_resp.text
                        except Exception:
                            pass
                        # Tenter JSON même si statut != 200
                        try:
                            rd_json = rd_resp.json()
                        except Exception:
                            rd_json = None
                        logger.debug(f"Réponse RealDebrid code={status} body_snippet={(raw_text[:120] + '...') if raw_text and len(raw_text) > 120 else raw_text}")

                        # Mapping erreurs RD (liste partielle, extensible)
                        REALDEBRID_ERROR_MAP = {
                            # Values intentionally WITHOUT prefix; we'll add 'RD:' dynamically
                            1: "Bad request",
                            2: "Unsupported hoster",
                            3: "Temporarily unavailable",
                            4: "File not found",
                            5: "Too many requests",
                            6: "Access denied",
                            8: "Not premium account",
                            9: "No traffic left",
                            11: "Internal error",
                            20: "Premium account only",  # normalisation wording
                        }

                        error_code = None
                        error_message = None            # Friendly / mapped message (to display in history)
                        error_message_raw = None        # Raw provider message ('error') kept for debugging if needed
                        if rd_json and isinstance(rd_json, dict):
                            # Format attendu quand erreur: {'error_code': int, 'error': 'message'}
                            error_code = rd_json.get('error_code') or rd_json.get('error') if isinstance(rd_json.get('error'), int) else rd_json.get('error_code')
                            if isinstance(error_code, str) and error_code.isdigit():
                                error_code = int(error_code)
                            api_error_text = rd_json.get('error') if isinstance(rd_json.get('error'), str) else None
                            if error_code is not None:
                                mapped = REALDEBRID_ERROR_MAP.get(error_code)
                                # Raw API error sometimes returns 'hoster_not_free' while code=20
                                if api_error_text and api_error_text.strip().lower() == 'hoster_not_free':
                                    api_error_text = 'Premium account only'
                                if mapped and not mapped.lower().startswith('rd:'):
                                    mapped = f"RD: {mapped}"
                                if not mapped and api_error_text and not api_error_text.lower().startswith('rd:'):
                                    api_error_text = f"RD: {api_error_text}"
                                error_message = mapped or api_error_text or f"RD: error {error_code}"
                                # Conserver la version brute séparément
                                error_message_raw = api_error_text if api_error_text and api_error_text != error_message else None
                        # Succès si 200 et presence 'download'
                        if status == 200 and rd_json and rd_json.get('download'):
                            final_url = rd_json.get('download')
                            filename = rd_json.get('filename') or filename or game_name
                            logger.debug("Débridage réussi via RealDebrid")
                            provider_used = 'RD'
                            _set_provider_in_history(provider_used)
                        else:
                            if error_message:
                                logger.warning(f"RealDebrid a renvoyé une erreur (code interne {error_code}): {error_message}")
                            else:
                                # Pas d'erreur structurée -> traiter statut HTTP
                                if status == 503:
                                    error_message = "RD: service unavailable (503)"
                                elif status >= 500:
                                    error_message = f"RD: server error ({status})"
                                elif status == 429:
                                    error_message = "RD: rate limited (429)"
                                else:
                                    error_message = f"RD: unexpected status ({status})"
                                logger.warning(f"RealDebrid fallback échec: {error_message}")
                                # Pas de détail JSON -> utiliser friendly comme raw aussi
                                error_message_raw = error_message
                            # Conserver message dans result si aucun autre provider ne réussit
                            if not final_url:
                                # Marquer le provider même en cas d'erreur pour affichage du préfixe dans l'historique
                                if provider_used is None:
                                    provider_used = 'RD'
                                    _set_provider_in_history(provider_used)
                                result[0] = False
                                # Pour l'interface: stocker le message friendly en priorité
                                result[1] = error_message or error_message_raw
                                # Stocker la version brute pour éventuel usage avancé
                                try:
                                    if isinstance(result, list):
                                        # Ajouter un dict auxiliaire pour meta erreurs
                                        result.append({"raw_error_realdebrid": error_message_raw})
                                except Exception:
                                    pass
                    except Exception as e:
                        logger.error(f"Exception RealDebrid fallback: {e}")
                if not final_url:
                    logger.error("Aucune URL directe obtenue (AllDebrid & RealDebrid échoués ou absents)")
                    result[0] = False
                    if result[1] is None:
                        result[1] = _("network_api_error").format("No provider available") if _ else "No provider available"
                    return
                if not filename:
                    filename = game_name
                sanitized_filename = sanitize_filename(filename)
                dest_path = os.path.join(dest_dir, sanitized_filename)
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
                        last_downloaded = 0
                        update_interval = 0.1  # Mettre à jour toutes les 0,1 secondes
                        logger.debug(f"Ouverture fichier: {dest_path}")
                        with open(dest_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                if cancel_ev is not None and cancel_ev.is_set():
                                    logger.debug(f"Annulation détectée, arrêt du téléchargement 1fichier pour task_id={task_id}")
                                    result[0] = False
                                    result[1] = _("download_canceled") if _ else "Download canceled"
                                    try:
                                        f.close()
                                    except Exception:
                                        pass
                                    try:
                                        if os.path.exists(dest_path):
                                            os.remove(dest_path)
                                    except Exception:
                                        pass
                                    break
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
                                        # Calcul de la vitesse en Mo/s
                                        delta = downloaded - last_downloaded
                                        speed = (delta / (current_time - last_update_time) / (1024 * 1024)) if (current_time - last_update_time) > 0 else 0.0
                                        last_downloaded = downloaded
                                        last_update_time = current_time
                                        progress_queues[task_id].put((task_id, downloaded, total_size, speed))

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
    thread = threading.Thread(target=download_thread, daemon=True)
    download_threads[task_id] = thread
    thread.start()

    # Boucle principale pour mettre à jour la progression
    logger.debug(f"Début boucle de progression pour task_id={task_id}")
    while thread.is_alive():
        try:
            task_queue = progress_queues.get(task_id)
            if task_queue:
                while not task_queue.empty():
                    data = task_queue.get()
                    #logger.debug(f"Données queue progression reçues: {data}")
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

    logger.debug(f"Fin boucle de progression, attente fin thread pour task_id={task_id}")
    thread.join()
    try:
        download_threads.pop(task_id, None)
    except Exception:
        pass
    logger.debug(f"Thread terminé, nettoyage queue pour task_id={task_id}")
    # Drain any remaining final message to ensure history is saved
    try:
        task_queue = progress_queues.get(task_id)
        if task_queue:
            while not task_queue.empty():
                data = task_queue.get()
                if isinstance(data[1], bool):
                    success, message = data[1], data[2]
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                entry["message"] = message
                                save_history(config.history)
                                break
    except Exception:
        pass
    # Nettoyer la queue
    if task_id in progress_queues:
        del progress_queues[task_id]
    cancel_events.pop(task_id, None)
    logger.debug(f"Fin download_from_1fichier, résultat: success={result[0]}, message={result[1]}")
    return result[0], result[1]

def is_1fichier_url(url):
    """Détecte si l'URL est un lien 1fichier."""
    return "1fichier.com" in url
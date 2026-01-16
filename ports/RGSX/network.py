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
from display import show_toast
import logging
import datetime
from datetime import datetime
from history import load_history

import queue
import time
import os
import json
from pathlib import Path
from language import _  # Import de la fonction de traduction
import re
import html as html_module
from urllib.parse import urljoin, unquote



logger = logging.getLogger(__name__)

# --- File d'attente de téléchargements (worker) ---
def download_queue_worker():
    """Worker qui surveille la file d'attente et lance le prochain téléchargement si aucun n'est actif."""
    import time
    while True:
        try:
            if not config.download_active and config.download_queue:
                job = config.download_queue.pop(0)
                config.download_active = True
                logger.info(f"[QUEUE] Lancement du téléchargement: {job.get('game_name','?')} ({job.get('url','?')})")
                # Démarrer le téléchargement selon le provider
                url = job['url']
                platform = job['platform']
                game_name = job['game_name']
                is_zip_non_supported = job.get('is_zip_non_supported', False)
                task_id = job.get('task_id') or f"queue_{int(time.time()*1000)}"
                # Choix du provider (1fichier ou direct)
                if is_1fichier_url(url):
                    t = threading.Thread(target=lambda: asyncio.run(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id)), daemon=True)
                else:
                    t = threading.Thread(target=lambda: asyncio.run(download_rom(url, platform, game_name, is_zip_non_supported, task_id)), daemon=True)
                t.start()
                # Le flag download_active sera remis à False à la fin du téléchargement (voir ci-dessous)
            time.sleep(1)
        except Exception as e:
            logger.error(f"[QUEUE] Erreur dans le worker de file d'attente: {e}")
            time.sleep(2)

# Hook à appeler à la fin de chaque téléchargement pour libérer le slot
def notify_download_finished():
    config.download_active = False

# ================== TÉLÉCHARGEMENT 1FICHIER GRATUIT ==================
# Fonction pour télécharger depuis 1fichier sans API key (mode gratuit)
# Compatible RGSX - Sans BeautifulSoup ni httpx

# Regex pour détecter le compte à rebours
WAIT_REGEXES_1F = [
    # Patterns avec multiplication par 60 (minutes -> secondes)
    r'var\s+ct\s*=\s*(\d+)\s*\*\s*60',  # var ct = X * 60;
    r'var\s+ct\s*=\s*(\d+)\s*\*60',     # var ct = X*60;
    # Patterns avec temps en minutes explicite
    r'(?:veuillez\s+)?patiente[rz]\s*(\d+)\s*(?:min|minute)s?\b',
    r'please\s+wait\s*(\d+)\s*(?:min|minute)s?\b',
    # Patterns avec temps en secondes
    r'(?:veuillez\s+)?patiente[rz]\s*(\d+)\s*(?:sec|secondes?|s)\b',
    r'please\s+wait\s*(\d+)\s*(?:sec|seconds?)\b',
    r'var\s+ct\s*=\s*(\d+)\s*;',  # var ct = X;
]

def extract_wait_seconds_1f(html_text):
    """Extrait le temps d'attente depuis le HTML 1fichier"""
    for i, pattern in enumerate(WAIT_REGEXES_1F):
        match = re.search(pattern, html_text, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            # Les deux premiers patterns sont en minutes (avec *60)
            if i < 2 or 'min' in pattern.lower():
                seconds = value * 60
            else:
                seconds = value
            logger.debug(f"1fichier wait time detected: {value} ({'minutes' if i < 2 or 'min' in pattern.lower() else 'seconds'}) = {seconds}s total")
            return seconds
    return 0

def download_1fichier_free_mode(url, dest_dir, session, log_callback=None, progress_callback=None, wait_callback=None, cancel_event=None):
    """
    Télécharge un fichier depuis 1fichier.com en mode gratuit (sans API key).
    Compatible RGSX - Sans BeautifulSoup ni httpx.
    
    Args:
        url: URL 1fichier
        dest_dir: Dossier de destination
        session: Session requests
        log_callback: Fonction appelée avec les messages de log
        progress_callback: Fonction appelée avec (filename, downloaded, total, percent)
        wait_callback: Fonction appelée avec (remaining_seconds, total_seconds)
        cancel_event: threading.Event pour annuler le téléchargement
        
    Returns:
        (success: bool, filepath: str|None, error_message: str|None)
    """
    
    def _log(msg):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass
        logger.info(msg)
    
    def _progress(filename, downloaded, total, pct):
        if progress_callback:
            try:
                progress_callback(filename, downloaded, total, pct)
            except Exception:
                pass
    
    def _wait(remaining, total_wait):
        if wait_callback:
            try:
                wait_callback(remaining, total_wait)
            except Exception:
                pass
    
    try:
        os.makedirs(dest_dir, exist_ok=True)
        _log(_("free_mode_download").format(url))
        
        # 1. GET page initiale
        if cancel_event and cancel_event.is_set():
            return (False, None, "Annulé")
        
        r = session.get(url, allow_redirects=True, timeout=30)
        r.raise_for_status()
        html = r.text
        
        # 2. Détection compte à rebours
        wait_s = extract_wait_seconds_1f(html)
        
        if wait_s > 0:
            _log(f"{wait_s}s...")
            for remaining in range(wait_s, 0, -1):
                if cancel_event and cancel_event.is_set():
                    return (False, None, "Annulé")
                _wait(remaining, wait_s)
                time.sleep(1)
        
        # 3. Chercher formulaire et soumettre
        if cancel_event and cancel_event.is_set():
            return (False, None, "Annulé")
            
        form_match = re.search(r'<form[^>]*id=[\"\']f1[\"\'][^>]*>(.*?)</form>', html, re.DOTALL | re.IGNORECASE)
        
        if form_match:
            form_html = form_match.group(1)
            
            # Extraire les champs
            data = {}
            for inp_match in re.finditer(r'<input[^>]+>', form_html, re.IGNORECASE):
                inp = inp_match.group(0)
                
                name_m = re.search(r'name=[\"\']([^\"\']+)', inp)
                value_m = re.search(r'value=[\"\']([^\"\']*)', inp)
                
                if name_m:
                    name = name_m.group(1)
                    value = value_m.group(1) if value_m else ''
                    data[name] = html_module.unescape(value)
            
            # POST formulaire
            _log(_("free_mode_submitting"))
            html = None
            # Parfois la soumission renvoie une page demandant d'attendre encore (rate-limit) --
            # on retry jusqu'à 3 fois en respectant le temps indiqué dans la page de réponse.
            max_post_attempts = 3
            post_attempt = 0
            while post_attempt < max_post_attempts:
                post_attempt += 1
                try:
                    r2 = session.post(str(r.url), data=data, allow_redirects=True, timeout=30)
                    r2.raise_for_status()
                    html = r2.text
                except Exception as pe:
                    logger.debug(f"1fichier: POST attempt {post_attempt} failed: {pe}")
                    if post_attempt >= max_post_attempts:
                        raise
                    time.sleep(1)
                    continue

                # Vérifier si la page de réponse contient un nouveau compteur d'attente
                extra_wait = extract_wait_seconds_1f(html)
                if extra_wait and extra_wait > 0:
                    logger.info(f"1fichier: Response requests extra wait: {extra_wait}s (attempt {post_attempt})")
                    # Attendre proprement en appelant le callback si fourni
                    for remaining in range(extra_wait, 0, -1):
                        if cancel_event and cancel_event.is_set():
                            return (False, None, "Annulé")
                        _wait(remaining, extra_wait)
                        time.sleep(1)
                    # essayer de soumettre à nouveau après la temporisation
                    continue
                # Pas d'attente supplémentaire demandée, on peut continuer
                break

            if html is None:
                return (False, None, "Erreur lors de la soumission du formulaire")
        
        # 4. Chercher lien de téléchargement
        if cancel_event and cancel_event.is_set():
            return (False, None, "Annulé")
            
        patterns = [
            r'href=[\"\']([^\"\']+)[\"\'][^>]*>(?:cliquer|click|télécharger|download)',
            r'href=[\"\']([^\"\']*/dl/[^\"\']+)',
            r'(https?://[a-z0-9.-]*1fichier\.com/[A-Za-z0-9]{8,})'
        ]
        
        direct_link = None
        # Examine each pattern and validate the candidate link via HEAD/GET to avoid landing pages (/register, /login)
        for idx, pattern in enumerate(patterns):
            match = re.search(pattern, html, re.IGNORECASE)
            if not match:
                continue
            try:
                captured_link = match.group(1)
            except IndexError:
                logger.warning(f"1fichier: Pattern {idx} matched but no capture group(1)")
                continue

            # Resolve relative links
            candidate = captured_link if captured_link.startswith(('http://', 'https://')) else urljoin(str(r.url), captured_link)
            logger.debug(f"1fichier: Pattern {idx} matched, candidate link: {candidate}")

            # Quick heuristic: skip known non-download endpoints
            lower = candidate.lower()
            if any(x in lower for x in ['/register', '/login', '/inscription', '/compte', '/subscribe']):
                logger.debug(f"1fichier: Skipping candidate because it looks like a landing page: {candidate}")
                continue

            # Validate with HEAD first to check content-type and status
            try:
                head = session.head(candidate, allow_redirects=True, timeout=10)
                if head.status_code >= 400:
                    logger.debug(f"1fichier: HEAD returned status {head.status_code} for {candidate}, skipping")
                    continue
                ctype = head.headers.get('content-type', '')
                if 'text/html' in ctype.lower():
                    logger.debug(f"1fichier: HEAD content-type is HTML for {candidate}, skipping")
                    # as fallback we'll try a quick GET below
                    raise ValueError('HTML content')
                # Looks like a direct file
                direct_link = candidate
                logger.debug(f"1fichier: Direct link validated via HEAD: {direct_link}")
                break
            except Exception as he:
                # HEAD may be blocked; try a quick GET without streaming
                try:
                    logger.debug(f"1fichier: HEAD failed ({he}), trying quick GET for candidate {candidate}")
                    rtest = session.get(candidate, allow_redirects=True, timeout=10)
                    if rtest.status_code >= 400:
                        logger.debug(f"1fichier: quick GET returned status {rtest.status_code} for {candidate}, skipping")
                        continue
                    ctype = rtest.headers.get('content-type', '')
                    if 'text/html' in ctype.lower() or '<html' in (rtest.text or '').lower():
                        logger.debug(f"1fichier: quick GET appears to be HTML/landing for {candidate}, skipping")
                        continue
                    direct_link = candidate
                    logger.debug(f"1fichier: Direct link validated via quick GET: {direct_link}")
                    break
                except Exception as ge:
                    logger.debug(f"1fichier: quick GET also failed for {candidate}: {ge}")
                    continue

        if not direct_link:
            logger.error(f"1fichier: No valid download link found. HTML preview (first 700 chars): {html[:700]}")
            return (False, None, "Lien de téléchargement introuvable")
        
        _log(_("free_mode_link_found").format(direct_link[:60]))
        
        # 5. HEAD pour infos fichier
        if cancel_event and cancel_event.is_set():
            return (False, None, "Annulé")
            
        head = session.head(direct_link, allow_redirects=True, timeout=30)
        
        # Nom fichier
        filename = 'downloaded_file'
        cd = head.headers.get('content-disposition', '')
        if cd:
            fn_match = re.search(r'filename\*?=[\"\']?([^\"\';]+)', cd, re.IGNORECASE)
            if fn_match:
                filename = unquote(fn_match.group(1))
        
        filename = sanitize_filename(filename)
        filepath = os.path.join(dest_dir, filename)
        
        # 6. Téléchargement
        _log(_("free_mode_download").format(filename))
        
        with session.get(direct_link, stream=True, allow_redirects=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('content-length', 0))
            
            with open(filepath, 'wb') as f:
                downloaded = 0
                for chunk in resp.iter_content(chunk_size=128*1024):
                    if cancel_event and cancel_event.is_set():
                        return (False, None, "Annulé")
                    
                    f.write(chunk)
                    downloaded += len(chunk)
                    
                    if total:
                        pct = downloaded / total * 100
                        _progress(filename, downloaded, total, pct)
        
        _log(_("free_mode_completed").format(filepath))
        return (True, filepath, None)
        
    except Exception as e:
        error_msg = f"Error Downloading with free mode: {str(e)}"
        _log(error_msg)
        logger.error(error_msg, exc_info=True)
        return (False, None, error_msg)

# ==================== FIN TÉLÉCHARGEMENT GRATUIT ====================

# Plus besoin de web_progress.json - l'interface web lit directement history.json
# Les fonctions update_web_progress() et remove_web_progress() sont supprimées

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

        # Liste des endpoints à essayer (GitHub principal, puis fallback)
        endpoints = [
            OTA_VERSION_ENDPOINT,
            "https://retrogamesets.fr/softs/version.json"
        ]
        
        response = None
        last_error = None
        
        for endpoint_index, endpoint in enumerate(endpoints):
            is_fallback = endpoint_index > 0
            if is_fallback:
                logger.info(f"Tentative sur endpoint de secours : {endpoint}")
            
            # Gestion des erreurs de rate limit GitHub (429) avec retry
            max_retries = 3 if not is_fallback else 1  # Moins de retries sur fallback
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    response = requests.get(endpoint, timeout=10)
                    
                    # Gestion spécifique des erreurs 429 (Too Many Requests) - surtout pour GitHub
                    if response.status_code == 429:
                        retry_after = response.headers.get('retry-after')
                        x_ratelimit_remaining = response.headers.get('x-ratelimit-remaining', '1')
                        x_ratelimit_reset = response.headers.get('x-ratelimit-reset')
                        
                        if retry_after:
                            # En-tête retry-after présent : attendre le nombre de secondes spécifié
                            wait_time = int(retry_after)
                            logger.warning(f"Rate limit atteint (429) sur {endpoint}. Attente de {wait_time}s (retry-after header)")
                        elif x_ratelimit_remaining == '0' and x_ratelimit_reset:
                            # x-ratelimit-remaining est 0 : attendre jusqu'à x-ratelimit-reset
                            import time
                            reset_time = int(x_ratelimit_reset)
                            current_time = int(time.time())
                            wait_time = max(reset_time - current_time, 60)  # Minimum 60s
                            logger.warning(f"Rate limit atteint (429) sur {endpoint}. Attente de {wait_time}s (x-ratelimit-reset)")
                        else:
                            # Pas d'en-têtes spécifiques : attendre au moins 60s
                            wait_time = 60
                            logger.warning(f"Rate limit atteint (429) sur {endpoint}. Attente de {wait_time}s par défaut")
                        
                        if retry_count < max_retries - 1:
                            logger.info(f"Nouvelle tentative dans {wait_time}s... ({retry_count + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            retry_count += 1
                            continue
                        else:
                            # Si rate limit persistant et qu'on est sur GitHub, essayer le fallback
                            if not is_fallback:
                                logger.warning(f"Rate limit GitHub persistant, passage au serveur de secours")
                                break  # Sortir de la boucle retry pour essayer le prochain endpoint
                            raise requests.exceptions.HTTPError(
                                f"Limite de débit atteinte (429). Veuillez réessayer plus tard."
                            )
                    
                    response.raise_for_status()
                    # Succès, sortir de toutes les boucles
                    logger.debug(f"Version récupérée avec succès depuis : {endpoint}")
                    break
                    
                except requests.exceptions.HTTPError as e:
                    last_error = e
                    if response and response.status_code == 429:
                        # 429 géré au-dessus, continuer la boucle ou passer au fallback
                        retry_count += 1
                        if retry_count >= max_retries:
                            break  # Passer au prochain endpoint
                    else:
                        # Erreur HTTP autre que 429
                        logger.warning(f"Erreur HTTP {response.status_code if response else 'inconnue'} sur {endpoint}")
                        break  # Passer au prochain endpoint
                        
                except requests.exceptions.RequestException as e:
                    last_error = e
                    if retry_count < max_retries - 1:
                        # Erreur réseau, réessayer avec backoff exponentiel
                        wait_time = 2 ** retry_count  # 1s, 2s, 4s
                        logger.warning(f"Erreur réseau sur {endpoint}. Nouvelle tentative dans {wait_time}s...")
                        await asyncio.sleep(wait_time)
                        retry_count += 1
                    else:
                        logger.warning(f"Erreur réseau persistante sur {endpoint} : {e}")
                        break  # Passer au prochain endpoint
            
            # Si on a une réponse valide, sortir de la boucle des endpoints
            if response and response.status_code == 200:
                break
        
        # Si aucun endpoint n'a fonctionné
        if not response or response.status_code != 200:
            raise last_error if last_error else requests.exceptions.RequestException(
                "Impossible de vérifier les mises à jour sur tous les serveurs"
            )
        
        # Accepter différents content-types (application/json, text/plain, text/html)
        content_type = response.headers.get("content-type", "")
        allowed_types = ["application/json", "text/plain", "text/html"]
        if not any(allowed in content_type for allowed in allowed_types):
            raise ValueError(
                f"Le fichier version.json n'est pas un JSON valide (type de contenu : {content_type})"
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
        # Utiliser l'URL RGSX_latest.zip qui pointe toujours vers la dernière version sur GitHub
        UPDATE_ZIP = OTA_UPDATE_ZIP
        logger.debug(f"URL de mise à jour : {UPDATE_ZIP} (version {latest_version})")

        if latest_version != config.app_version:
            config.current_loading_system = _("network_update_available").format(latest_version)
            config.loading_progress = 10.0
            config.needs_redraw = True
            logger.debug(f"Téléchargement du ZIP de mise à jour : {UPDATE_ZIP}")

            # Créer le dossier UPDATE_FOLDER s'il n'existe pas
            os.makedirs(UPDATE_FOLDER, exist_ok=True)
            update_zip_path = os.path.join(UPDATE_FOLDER, f"RGSX_update_v{latest_version}.zip")
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
# Pause events for downloads
pause_events = {}  # {task_id: threading.Event} - Event is set when paused
download_threads = {}
# URLs actuellement en cours de téléchargement (pour éviter les doublons)
urls_in_progress = set()
urls_lock = threading.Lock()
# Résultats des URLs en cours de téléchargement (pour les doublons)
url_results = {}  # {url: (success, message)}
# Événements pour synchroniser les appels doublons (attendre la fin du premier)
url_done_events = {}  # {url: threading.Event}

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

def toggle_pause_download(task_id: str) -> bool:
    """Toggle pause state for a running download task. Returns True if now paused, False if resumed."""
    ev = pause_events.get(task_id)
    if ev is None:
        # Créer l'événement de pause s'il n'existe pas
        pause_events[task_id] = threading.Event()
        ev = pause_events[task_id]
    
    if ev.is_set():
        # Actuellement en pause, reprendre
        ev.clear()
        logger.debug(f"Download resumed for task_id={task_id}")
        return False  # Retourne False = pas en pause (repris)
    else:
        # Actuellement actif, mettre en pause
        ev.set()
        logger.debug(f"Download paused for task_id={task_id}")
        return True  # Retourne True = en pause

def is_download_paused(task_id: str) -> bool:
    """Check if a download is currently paused."""
    ev = pause_events.get(task_id)
    if ev is not None:
        return ev.is_set()
    return False

def cancel_all_downloads():
    """Cancel all active downloads and queued downloads, and attempt to stop threads quickly."""
    # Annuler tous les téléchargements actifs via cancel_events
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
    
    # Vider la file d'attente des téléchargements
    config.download_queue.clear()
    config.download_active = False
    
    # Mettre à jour l'historique pour annuler les téléchargements en statut "Queued"
    try:
        history = load_history()
        for entry in history:
            if entry.get("status") == "Queued":
                entry["status"] = "Canceled"
                entry["message"] = _("download_canceled")
                logger.info(f"Téléchargement en attente annulé : {entry.get('game_name', '?')}")
        save_history(history)
    except Exception as e:
        logger.error(f"Erreur lors de l'annulation des téléchargements en attente : {e}")



async def download_rom(url, platform, game_name, is_zip_non_supported=False, task_id=None):
    logger.debug(f"Début téléchargement: {game_name} depuis {url}, zip non supporté={is_zip_non_supported}, task_id={task_id}")
    result = [None, None]
    
    # Vérifier si cette URL est déjà en cours de téléchargement (prévenir les doublons)
    with urls_lock:
        if url in urls_in_progress:
            logger.warning(f"⚠️ Un téléchargement pour cette URL est déjà en cours, attente du résultat: {url}")
            # Créer un événement d'attente si ce n'est pas déjà fait
            if url not in url_done_events:
                url_done_events[url] = threading.Event()
            done_event = url_done_events[url]
        else:
            # Ajouter l'URL au set en cours
            urls_in_progress.add(url)
            done_event = None
    
    # Si on attendait un doublon, on attend ici
    if done_event is not None:
        logger.debug(f"Attente de la fin du téléchargement en doublon pour {url}")
        # Attendre de manière asynchrone l'événement (timeout de 30 minutes pour les gros fichiers)
        start_wait = time.time()
        while not done_event.is_set():
            if time.time() - start_wait > 1800:  # 30 minutes timeout
                logger.warning(f"Timeout d'attente pour le doublon de {url}")
                break
            await asyncio.sleep(0.1)
        # Vérifier si on a un résultat en cache
        if url in url_results:
            logger.info(f"Résultat en cache pour {url}: {url_results[url]}")
            return url_results[url]
        else:
            # Fallback: retourner un message de succès (le premier téléchargement a probablement réussi)
            return (True, _("network_download_ok").format(game_name))
    
    # Créer une queue/cancel spécifique pour cette tâche
    if task_id not in progress_queues:
        progress_queues[task_id] = queue.Queue()
    if task_id not in cancel_events:
        cancel_events[task_id] = threading.Event()
    
    def download_thread():
        try:
            # IMPORTANT: Créer l'entrée dans config.history dès le début avec status "Downloading"
            # pour que l'interface web puisse afficher le téléchargement en cours
            
            # TOUJOURS charger l'historique existant depuis le fichier pour éviter d'écraser les anciennes entrées
            config.history = load_history()
            
            # Vérifier si l'entrée existe déjà
            entry_exists = False
            for entry in config.history:
                if entry.get("url") == url:
                    entry_exists = True
                    # Réinitialiser le status à "Downloading"
                    entry["status"] = "Downloading"
                    entry["progress"] = 0
                    entry["downloaded_size"] = 0
                    entry["platform"] = platform
                    entry["game_name"] = game_name
                    entry["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    entry["task_id"] = task_id
                    break
            
            # Si l'entrée n'existe pas, la créer
            if not entry_exists:
                config.history.append({
                    "platform": platform,
                    "game_name": game_name,
                    "url": url,
                    "status": "Downloading",
                    "progress": 0,
                    "downloaded_size": 0,
                    "total_size": 0,
                    "speed": 0,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "message": f"Téléchargement de {game_name}",
                    "task_id": task_id
                })
            
            # Sauvegarder history.json immédiatement
            save_history(config.history)
            
            cancel_ev = cancel_events.get(task_id)
            # Use symlink path if enabled
            from rgsx_settings import apply_symlink_path, get_platform_custom_path
            
            # Vérifier si un dossier personnalisé est configuré pour cette plateforme
            custom_path = get_platform_custom_path(platform)
            if custom_path and os.path.isdir(custom_path):
                dest_dir = custom_path
                platform_folder = os.path.basename(dest_dir)
                logger.debug(f"Utilisation du dossier personnalisé pour {platform}: {dest_dir}")
            else:
                dest_dir = None
                platform_folder = None
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
            
            # Créer la session AVANT la vérification du fichier existant
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
            
            # Vérifier si le fichier existe déjà (exact ou avec autre extension)
            file_found = False
            if os.path.exists(dest_path):
                logger.info(f"Le fichier {dest_path} existe déjà, vérification de la taille...")
                
                # Vérifier la taille du fichier local
                local_size = os.path.getsize(dest_path)
                logger.debug(f"Taille du fichier local: {local_size} octets")
                
                # Essayer de récupérer la taille du serveur via HEAD request
                remote_size = None
                try:
                    head_response = session.head(url, timeout=10, allow_redirects=True)
                    if head_response.status_code == 200:
                        content_length = head_response.headers.get('content-length')
                        if content_length:
                            remote_size = int(content_length)
                            logger.debug(f"Taille du fichier serveur: {remote_size} octets")
                except Exception as e:
                    logger.debug(f"Impossible de vérifier la taille serveur: {e}")
                
                # Comparer les tailles si on a obtenu la taille distante
                if remote_size is not None and local_size != remote_size:
                    logger.warning(f"Taille mismatch! Local: {local_size}, Remote: {remote_size} - le fichier sera re-téléchargé")
                    # Les tailles ne correspondent pas, il faut re-télécharger
                    try:
                        if os.path.exists(dest_path):
                            os.remove(dest_path)
                            logger.info(f"Fichier incomplet supprimé: {dest_path}")
                        else:
                            logger.debug(f"Fichier déjà supprimé par un autre thread: {dest_path}")
                    except FileNotFoundError:
                        logger.debug(f"Fichier déjà supprimé (ou n'existe plus): {dest_path}")
                    except Exception as e:
                        logger.error(f"Impossible de supprimer le fichier incomplet: {e}")
                        result[0] = False
                        result[1] = f"Erreur suppression fichier incomplet: {str(e)}"
                        with urls_lock:
                            urls_in_progress.discard(url)
                            logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                        return
                    # Continuer le téléchargement normal (ne pas faire return)
                else:
                    # Les tailles correspondent ou on ne peut pas vérifier, considérer comme déjà téléchargé
                    logger.info(f"Le fichier {dest_path} existe déjà et la taille est correcte, téléchargement ignoré")
                    result[0] = True
                    result[1] = _("network_download_ok").format(game_name) + _("download_already_present")
                    
                    # Mettre à jour l'historique
                    for entry in config.history:
                        if entry.get("url") == url:
                            entry["status"] = "Download_OK"
                            entry["progress"] = 100
                            entry["message"] = result[1]
                            save_history(config.history)
                            break
                    
                    # Afficher un toast au lieu d'ouvrir l'historique
                    try:
                        show_toast(result[1])
                    except Exception as e:
                        logger.debug(f"Impossible d'afficher le toast: {e}")
                    with urls_lock:
                        urls_in_progress.discard(url)
                        logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                    
                    # Libérer le slot de la queue
                    try:
                        notify_download_finished()
                    except Exception:
                        pass
                    
                    return result[0], result[1]
                file_found = True
            
            # Vérifier si un fichier avec le même nom de base mais extension différente existe (SEULEMENT si fichier exact non trouvé)
            if not file_found:
                base_name_no_ext = os.path.splitext(sanitized_name)[0]
                if base_name_no_ext != sanitized_name:  # Seulement si une extension était présente
                    try:
                        # Lister tous les fichiers dans le répertoire de destination
                        if os.path.exists(dest_dir):
                            for existing_file in os.listdir(dest_dir):
                                existing_base = os.path.splitext(existing_file)[0]
                                if existing_base == base_name_no_ext:
                                    existing_path = os.path.join(dest_dir, existing_file)
                                    logger.info(f"Un fichier avec le même nom de base existe: {existing_path}, vérification de la taille...")
                                    
                                    # Vérifier la taille du fichier local
                                    local_size = os.path.getsize(existing_path)
                                    logger.debug(f"Taille du fichier local (extension différente): {local_size} octets")
                                    
                                    # Essayer de récupérer la taille du serveur via HEAD request
                                    remote_size = None
                                    try:
                                        head_response = session.head(url, timeout=10, allow_redirects=True)
                                        if head_response.status_code == 200:
                                            content_length = head_response.headers.get('content-length')
                                            if content_length:
                                                remote_size = int(content_length)
                                                logger.debug(f"Taille du fichier serveur: {remote_size} octets")
                                    except Exception as e:
                                        logger.debug(f"Impossible de vérifier la taille serveur: {e}")
                                    
                                    # Comparer les tailles si on a obtenu la taille distante
                                    if remote_size is not None and local_size != remote_size:
                                        logger.warning(f"Taille mismatch (extension différente)! Local: {local_size}, Remote: {remote_size} - re-téléchargement")
                                        # Continuer le téléchargement normal
                                        break
                                    else:
                                        # Les tailles correspondent, fichier complet
                                        logger.info(f"Un fichier avec le même nom de base existe déjà: {existing_path}, téléchargement ignoré")
                                        result[0] = True
                                        result[1] = _("network_download_ok").format(game_name) + _("download_already_extracted")
                                        
                                        # Mettre à jour l'historique
                                        for entry in config.history:
                                            if entry.get("url") == url:
                                                entry["status"] = "Download_OK"
                                                entry["progress"] = 100
                                                entry["message"] = result[1]
                                                save_history(config.history)
                                                break
                                        
                                        # Afficher un toast au lieu d'ouvrir l'historique
                                        try:
                                            show_toast(result[1])
                                        except Exception as e:
                                            logger.debug(f"Impossible d'afficher le toast: {e}")
                                        with urls_lock:
                                            urls_in_progress.discard(url)
                                            logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                                        
                                        # Libérer le slot de la queue
                                        try:
                                            notify_download_finished()
                                        except Exception:
                                            pass
                                        
                                        return result[0], result[1]
                    except Exception as e:
                        logger.debug(f"Erreur lors de la vérification des fichiers existants: {e}")
            
            download_headers = headers.copy()
            download_headers['Accept'] = 'application/octet-stream, */*'
            download_headers['Referer'] = 'https://myrient.erista.me/'

            # Préparation spécifique archive.org : récupérer quelques pages pour obtenir cookies éventuels
            if 'archive.org/download/' in url:
                try:
                    pre_id = url.split('/download/')[1].split('/')[0]
                    session.get('https://archive.org/robots.txt', timeout=20)
                    session.get(f'https://archive.org/metadata/{pre_id}', timeout=20)
                    logger.debug(f"Pré-chargement cookies/metadata archive.org pour {pre_id}")
                except Exception as e:
                    logger.debug(f"Pré-chargement archive.org ignoré: {e}")
            
            # Initialiser la progression pour afficher les tentatives
            if url not in config.download_progress:
                config.download_progress[url] = {
                    "downloaded_size": 0,
                    "total_size": 0,
                    "status": "Connecting",
                    "progress_percent": 0,
                    "speed": 0,
                    "game_name": game_name,
                    "platform": platform
                }
                # Plus besoin d'update_web_progress - history.json est mis à jour automatiquement
            
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
            last_error = None
            last_error_type = None
            
            for attempt, hv in enumerate(header_variants, start=1):
                try:
                    # Mettre à jour la progression pour afficher la tentative en cours
                    if url in config.download_progress:
                        config.download_progress[url]["status"] = f"Try {attempt}/{len(header_variants)}"
                        config.download_progress[url]["progress_percent"] = 0
                        config.needs_redraw = True
                        # Mettre à jour le fichier web
                # Plus besoin de update_web_progress
                    
                    logger.debug(f"Tentative téléchargement {attempt}/{len(header_variants)} avec headers: {hv}")
                    # Timeout plus long pour archive.org, avec tuple (connect_timeout, read_timeout)
                    timeout_val = (60, 90) if 'archive.org' in url else 30
                    r = session.get(url, stream=True, timeout=timeout_val, allow_redirects=True, headers=hv)
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
                except requests.Timeout as e:
                    last_error = str(e)
                    last_error_type = "timeout"
                    logger.debug(f"Timeout tentative {attempt}: {e}")
                except requests.ConnectionError as e:
                    last_error = str(e)
                    last_error_type = "connection"
                    logger.debug(f"Erreur connexion tentative {attempt}: {e}")
                except requests.HTTPError as e:
                    last_error = str(e)
                    last_error_type = "http"
                    logger.debug(f"Erreur HTTP tentative {attempt}: {e}")
                    # Si ce n'est pas une erreur auth explicite et qu'on a un code => on sort
                    if last_status not in (401, 403):
                        break
                except requests.RequestException as e:
                    last_error = str(e)
                    last_error_type = "request"
                    logger.debug(f"Erreur requête tentative {attempt}: {e}")
                    # Si ce n'est pas une erreur auth explicite et qu'on a un code => on sort
                    if isinstance(e, requests.HTTPError) and last_status not in (401, 403):
                        break
                    # Délai entre tentatives pour archive.org (éviter saturation)
                    if 'archive.org' in url and attempt < len(header_variants):
                        time.sleep(2)
            
            if response is None:
                # Fallback metadata archive.org pour message clair
                if 'archive.org/download/' in url:
                    try:
                        identifier = url.split('/download/')[1].split('/')[0]
                        meta_resp = session.get(f'https://archive.org/metadata/{identifier}', timeout=30)
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
                
                # Construire un message d'erreur détaillé et traduit
                error_msg = None
                if last_status:
                    # Erreurs HTTP avec codes spécifiques
                    if last_status == 401:
                        error_msg = _("network_auth_required").format(last_status) if _ else f"Authentication required (HTTP {last_status})"
                    elif last_status == 403:
                        error_msg = _("network_access_denied").format(last_status) if _ else f"Access denied (HTTP {last_status})"
                    elif last_status >= 500:
                        error_msg = _("network_server_error").format(last_status) if _ else f"Server error (HTTP {last_status})"
                    else:
                        error_msg = _("network_http_error").format(last_status) if _ else f"HTTP error {last_status}"
                elif last_error_type == "timeout":
                    error_msg = _("network_timeout_error") if _ else "Connection timeout"
                elif last_error_type == "connection":
                    error_msg = _("network_connection_error") if _ else "Network connection error"
                else:
                    error_msg = _("network_no_response") if _ else "No response from server"
                
                # Ajouter le nombre de tentatives
                attempts_count = len(header_variants)
                full_error_msg = _("network_connection_failed").format(attempts_count) if _ else f"Connection failed after {attempts_count} attempts"
                full_error_msg += f" - {error_msg}"
                
                # Ajouter les détails techniques en log
                if last_error:
                    logger.error(f"Détails de l'erreur: {last_error}")
                
                raise requests.HTTPError(full_error_msg)
            
            # Mettre à jour le statut: connexion réussie, début du téléchargement
            if url in config.download_progress:
                config.download_progress[url]["status"] = "Downloading"
                config.needs_redraw = True
            
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
            download_canceled = False
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    # Vérifier la pause (dynamiquement car l'événement peut être créé après le début)
                    while True:
                        pause_ev = pause_events.get(task_id)
                        if pause_ev is None or not pause_ev.is_set():
                            break  # Pas en pause, continuer le téléchargement
                        if cancel_ev is not None and cancel_ev.is_set():
                            break  # Sortir de la boucle de pause si annulation demandée
                        time.sleep(0.1)  # Attendre en pause
                    
                    if cancel_ev is not None and cancel_ev.is_set():
                        logger.debug(f"Annulation détectée, arrêt du téléchargement pour task_id={task_id}")
                        result[0] = False
                        result[1] = _("download_canceled") if _ else "Download canceled"
                        download_canceled = True
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
            
            # Forcer une dernière mise à jour de progression pour les petits fichiers
            # (au cas où aucune mise à jour n'a été envoyée pendant la boucle)
            if downloaded > 0 and downloaded != last_downloaded:
                current_time = time.time()
                delta = downloaded - last_downloaded
                elapsed = current_time - last_update_time
                speed = delta / elapsed / (1024 * 1024) if elapsed > 0 else 0
                progress_queues[task_id].put((task_id, downloaded, total_size, speed))
                logger.debug(f"Mise à jour finale de progression: {downloaded}/{total_size} octets")

            # Si annulé, ne pas continuer avec extraction
            if download_canceled:
                # Libérer le slot de la queue
                try:
                    notify_download_finished()
                except Exception:
                    pass
                return
            
            os.chmod(dest_path, 0o644)
            logger.debug(f"Téléchargement terminé: {dest_path}")
            
            # Vérifier si l'extraction automatique est activée dans les paramètres
            from rgsx_settings import get_auto_extract
            auto_extract_enabled = get_auto_extract()
            
            # Forcer extraction si plateforme BIOS même si le pré-check ne l'avait pas marqué
            force_extract = is_zip_non_supported and auto_extract_enabled
            if not force_extract and auto_extract_enabled:
                try:
                    bios_like = {"BIOS", "- BIOS by TMCTV -", "- BIOS"}
                    if platform_folder == "bios" or platform in bios_like:
                        force_extract = True
                        logger.debug("Extraction forcée activée pour BIOS")
                except Exception:
                    pass
            
            # Forcer extraction pour PS3 Redump (déchiffrement et extraction ISO obligatoire)
            if not force_extract:
                try:
                    ps3_platforms = {"ps3", "PlayStation 3"}
                    if platform_folder == "ps3" or platform in ps3_platforms:
                        force_extract = True
                        logger.debug("Extraction forcée activée pour PS3 Redump (déchiffrement ISO)")
                except Exception:
                    pass

            if force_extract:
                logger.debug(f"Extraction automatique nécessaire pour {dest_path}")
                extension = os.path.splitext(dest_path)[1].lower()
                if extension == ".zip":
                    try:
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
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
        
        # AVANT le finally : Mettre à jour la progression à 100% si succès
        if result[0] and url in config.download_progress:
            logger.info(f"[WEB PROGRESS] Mise à jour finale à 100% pour {game_name}")
            config.download_progress[url]["progress_percent"] = 100
            config.download_progress[url]["status"] = "Completed"
            config.download_progress[url]["downloaded_size"] = config.download_progress[url].get("total_size", 0)
                # Plus besoin de update_web_progress
            logger.info(f"[WEB PROGRESS] Attente 1.5s pour affichage...")
            time.sleep(1.5)  # Laisser l'interface afficher 100% pendant 1.5 secondes
            logger.info(f"[WEB PROGRESS] Fin de l'attente, envoi signal de fin")
        
        # Maintenant on peut envoyer le signal de fin à la boucle
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
                        
                        # Nettoyer download_progress et web_progress
                        if url in config.download_progress:
                            del config.download_progress[url]
                        # Plus besoin de remove_web_progress
                        
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement", "Extracting"]:
                                    entry["status"] = "Download_OK" if success else "Erreur"
                                    entry["progress"] = 100 if success else 0
                                    entry["message"] = message
                                    save_history(config.history)
                                    # Marquer le jeu comme téléchargé si succès
                                    if success:
                                        logger.debug(f"[WHILE_LOOP] Marking game as downloaded: platform={platform}, game={game_name}")
                                        from history import mark_game_as_downloaded
                                        file_size = entry.get("size", "N/A")
                                        mark_game_as_downloaded(platform, game_name, file_size)
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
                        
                        # Mettre à jour config.download_progress pour compatibilité
                        if url in config.download_progress:
                            config.download_progress[url]["downloaded_size"] = downloaded
                            config.download_progress[url]["total_size"] = total_size
                            config.download_progress[url]["speed"] = speed
                            config.download_progress[url]["progress_percent"] = progress_percent
                            # Si 100%, afficher "Completed" au lieu de "Downloading"
                            config.download_progress[url]["status"] = "Completed" if progress_percent >= 100 else "Downloading"
                            
                            # Mettre à jour le fichier web
                # Plus besoin de update_web_progress
                        
                        # IMPORTANT: Mettre à jour config.history PENDANT le téléchargement aussi
                        # pour que l'interface web affiche la progression en temps réel
                        # NOTE: On ne touche PAS au timestamp qui doit rester celui de création
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
                                    entry["downloaded_size"] = downloaded
                                    entry["total_size"] = total_size
                                    entry["speed"] = speed
                                    entry["progress"] = progress_percent
                                    entry["status"] = "Téléchargement"
                                    # Sauvegarder toutes les 5% pour éviter trop d'I/O
                                    if progress_percent % 5 == 0 or progress_percent >= 99:
                                        save_history(config.history)
                                    break
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
                    logger.debug(f"[DRAIN_QUEUE] Processing final message: success={success}, message={message[:100] if message else 'None'}")
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                entry["message"] = message
                                save_history(config.history)
                                # Marquer le jeu comme téléchargé si succès
                                if success:
                                    logger.debug(f"[DRAIN_QUEUE] Marking game as downloaded: platform={platform}, game={game_name}")
                                    from history import mark_game_as_downloaded
                                    file_size = entry.get("size", "N/A")
                                    mark_game_as_downloaded(platform, game_name, file_size)
                                break
    except Exception as e:
        logger.error(f"[DRAIN_QUEUE] Error processing final message: {e}")


    # Nettoyer la queue
    if task_id in progress_queues:
        del progress_queues[task_id]
    cancel_events.pop(task_id, None)
    
    # Sauvegarder le résultat AVANT de retirer l'URL du set (pour les doublons)
    with urls_lock:
        url_results[url] = (result[0], result[1])
        urls_in_progress.discard(url)
        logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
        # Signaler l'événement pour les appels doublons en attente
        if url in url_done_events:
            url_done_events[url].set()
    
    # Libérer le slot de la queue
    try:
        notify_download_finished()
    except Exception:
        pass
    
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
    
    # Vérifier si cette URL est déjà en cours de téléchargement (prévenir les doublons)
    with urls_lock:
        if url in urls_in_progress:
            logger.warning(f"⚠️ Un téléchargement pour cette URL est déjà en cours, attente du résultat: {url}")
            # Créer un événement d'attente si ce n'est pas déjà fait
            if url not in url_done_events:
                url_done_events[url] = threading.Event()
            done_event = url_done_events[url]
        else:
            # Ajouter l'URL au set en cours
            urls_in_progress.add(url)
            done_event = None
    
    # Si on attendait un doublon, on attend ici
    if done_event is not None:
        logger.debug(f"Attente de la fin du téléchargement en doublon pour {url}")
        # Attendre de manière asynchrone l'événement (timeout de 30 minutes pour les gros fichiers)
        start_wait = time.time()
        while not done_event.is_set():
            if time.time() - start_wait > 1800:  # 30 minutes timeout
                logger.warning(f"Timeout d'attente pour le doublon de {url}")
                break
            await asyncio.sleep(0.1)
        # Vérifier si on a un résultat en cache
        if url in url_results:
            logger.info(f"Résultat en cache pour {url}: {url_results[url]}")
            return url_results[url]
        else:
            # Fallback: retourner un message de succès (le premier téléchargement a probablement réussi)
            return (True, _("network_download_ok").format(game_name))

        # Ajouter l'URL au set en cours
        urls_in_progress.add(url)

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
            
            # IMPORTANT: Créer l'entrée dans config.history dès le début avec status "Downloading"
            # pour que l'interface web puisse afficher le téléchargement en cours

            # Charger l'historique existant depuis le fichier
            if not isinstance(config.history, list):
                config.history = load_history()
            
            # Vérifier si l'entrée existe déjà
            entry_exists = False
            for entry in config.history:
                if entry.get("url") == url:
                    entry_exists = True
                    # Réinitialiser le status à "Downloading"
                    entry["status"] = "Downloading"
                    entry["progress"] = 0
                    entry["downloaded_size"] = 0
                    entry["platform"] = platform
                    entry["game_name"] = game_name
                    entry["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    entry["task_id"] = task_id
                    break
            
            # Si l'entrée n'existe pas, la créer
            if not entry_exists:
                config.history.append({
                    "platform": platform,
                    "game_name": game_name,
                    "url": url,
                    "status": "Downloading",
                    "progress": 0,
                    "downloaded_size": 0,
                    "total_size": 0,
                    "speed": 0,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "message": f"Téléchargement 1fichier de {game_name}",
                    "task_id": task_id
                })
            
            # Sauvegarder history.json immédiatement
            save_history(config.history)
            
            # Use symlink path if enabled
            from rgsx_settings import apply_symlink_path, get_platform_custom_path
            
            # Vérifier si un dossier personnalisé est configuré pour cette plateforme
            custom_path = get_platform_custom_path(platform)
            if custom_path and os.path.isdir(custom_path):
                dest_dir = custom_path
                logger.debug(f"Utilisation du dossier personnalisé pour {platform}: {dest_dir}")
                platform_folder = os.path.basename(dest_dir)
            else:
                dest_dir = None
                platform_folder = None
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
                
                # Récupérer la taille du serveur depuis l'API 1fichier
                remote_size = None
                try:
                    remote_size = file_info.get("size")
                    if isinstance(remote_size, str):
                        remote_size = int(remote_size)
                    logger.debug(f"Taille du fichier 1fichier: {remote_size} octets")
                except Exception as e:
                    logger.debug(f"Impossible de récupérer la taille 1fichier: {e}")
                
                # Vérifier si le fichier existe déjà (exact ou avec autre extension)
                file_found = False
                if os.path.exists(dest_path):
                    logger.info(f"Le fichier {dest_path} existe déjà, vérification de la taille...")
                    
                    # Vérifier la taille du fichier local
                    local_size = os.path.getsize(dest_path)
                    logger.debug(f"Taille du fichier local: {local_size} octets")
                    
                    # Comparer les tailles si on a obtenu la taille distante
                    if remote_size is not None and local_size != remote_size:
                        logger.warning(f"Taille mismatch! Local: {local_size}, Remote: {remote_size} - le fichier sera re-téléchargé")
                        # Les tailles ne correspondent pas, il faut re-télécharger
                        try:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                                logger.info(f"Fichier incomplet supprimé: {dest_path}")
                            else:
                                logger.debug(f"Fichier déjà supprimé par un autre thread: {dest_path}")
                        except FileNotFoundError:
                            logger.debug(f"Fichier déjà supprimé (ou n'existe plus): {dest_path}")
                        except Exception as e:
                            logger.error(f"Impossible de supprimer le fichier incomplet: {e}")
                            result[0] = False
                            result[1] = f"Erreur suppression fichier incomplet: {str(e)}"
                            return
                        # Continuer le téléchargement normal (ne pas faire return)
                    else:
                        # Les tailles correspondent ou on ne peut pas vérifier, considérer comme déjà téléchargé
                        logger.info(f"Le fichier {dest_path} existe déjà et la taille est correcte, téléchargement ignoré")
                        result[0] = True
                        result[1] = _("network_download_ok").format(game_name) + _("download_already_present")
                        # Afficher un toast au lieu d'ouvrir l'historique
                        try:
                            show_toast(result[1])
                        except Exception as e:
                            logger.debug(f"Impossible d'afficher le toast: {e}")
                        with urls_lock:
                            urls_in_progress.discard(url)
                            logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                        return result[0], result[1]
                    file_found = True
                
                # Vérifier si un fichier avec le même nom de base mais extension différente existe (SEULEMENT si fichier exact non trouvé)
                if not file_found:
                    base_name_no_ext = os.path.splitext(sanitized_filename)[0]
                    if base_name_no_ext != sanitized_filename:  # Seulement si une extension était présente
                        try:
                            # Lister tous les fichiers dans le répertoire de destination
                            if os.path.exists(dest_dir):
                                for existing_file in os.listdir(dest_dir):
                                    existing_base = os.path.splitext(existing_file)[0]
                                    if existing_base == base_name_no_ext:
                                        existing_path = os.path.join(dest_dir, existing_file)
                                        logger.info(f"Un fichier avec le même nom de base existe: {existing_path}, vérification de la taille...")
                                        
                                        # Vérifier la taille du fichier local
                                        local_size = os.path.getsize(existing_path)
                                        logger.debug(f"Taille du fichier local (extension différente): {local_size} octets")
                                        
                                        # Comparer les tailles si on a obtenu la taille distante
                                        if remote_size is not None and local_size != remote_size:
                                            logger.warning(f"Taille mismatch (extension différente)! Local: {local_size}, Remote: {remote_size} - re-téléchargement")
                                            # Continuer le téléchargement normal
                                            break
                                        else:
                                            # Les tailles correspondent, fichier complet
                                            logger.info(f"Un fichier avec le même nom de base existe déjà: {existing_path}, téléchargement ignoré")
                                            result[0] = True
                                            result[1] = _("network_download_ok").format(game_name) + _("download_already_extracted")
                                            # Afficher un toast au lieu d'ouvrir l'historique
                                            try:
                                                show_toast(result[1])
                                            except Exception as e:
                                                logger.debug(f"Impossible d'afficher le toast: {e}")
                                            with urls_lock:
                                                urls_in_progress.discard(url)
                                                logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                                            return result[0], result[1]
                        except Exception as e:
                            logger.debug(f"Erreur lors de la vérification des fichiers existants: {e}")
                
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
                    # NOUVEAU: Fallback mode gratuit 1fichier si aucune clé API disponible
                    logger.warning("Aucune URL directe obtenue via API - Tentative mode gratuit 1fichier")
                    
                    # Créer un lock pour ce téléchargement
                    free_lock = threading.Lock()
                    
                    try:
                        # Créer une session requests pour le mode gratuit
                        free_session = requests.Session()
                        free_session.headers.update({'User-Agent': 'Mozilla/5.0'})
                        
                        # Callbacks pour le mode gratuit
                        def log_cb(msg):
                            logger.info(msg)
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url:
                                        entry["message"] = msg
                                        config.needs_redraw = True
                                        break
                        
                        def progress_cb(filename, downloaded, total, pct):
                            with free_lock:
                                if isinstance(config.history, list):
                                    for entry in config.history:
                                        if "url" in entry and entry["url"] == url and entry["status"] == "Downloading":
                                            entry["progress"] = int(pct) if pct else 0
                                            entry["downloaded_size"] = downloaded
                                            entry["total_size"] = total
                                            # Effacer le message personnalisé pour afficher le pourcentage
                                            entry["message"] = ""
                                            config.needs_redraw = True
                                            save_history(config.history)
                                            break
                                progress_queues[task_id].put((task_id, downloaded, total))
                        
                        def wait_cb(remaining, total_wait):
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url:
                                        entry["message"] = _("free_mode_waiting").format(remaining, total_wait)
                                        config.needs_redraw = True
                                        save_history(config.history)
                                        break
                        
                        # Lancer le téléchargement gratuit
                        success, filepath, error_msg = download_1fichier_free_mode(
                            url=link,
                            dest_dir=dest_dir,
                            session=free_session,
                            log_callback=log_cb,
                            progress_callback=progress_cb,
                            wait_callback=wait_cb,
                            cancel_event=cancel_ev
                        )
                        
                        if success:
                            logger.info(f"Téléchargement gratuit réussi: {filepath}")
                            result[0] = True
                            result[1] = _("network_download_ok").format(game_name) if _ else f"Download successful: {game_name}"
                            provider_used = 'FREE'
                            _set_provider_in_history(provider_used)
                            
                            # Mettre à jour l'historique
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    if "url" in entry and entry["url"] == url:
                                        entry["status"] = "Completed"
                                        entry["progress"] = 100
                                        entry["message"] = result[1]
                                        entry["provider"] = "FREE"
                                        entry["provider_prefix"] = "FREE:"
                                        save_history(config.history)
                                        config.needs_redraw = True
                                        break
                            
                            # Traiter le fichier (extraction si nécessaire)
                            if not is_zip_non_supported:
                                try:
                                    if filepath.lower().endswith('.zip'):
                                        logger.info(f"Extraction ZIP: {filepath}")
                                        extract_zip(filepath, dest_dir)
                                        os.remove(filepath)
                                        logger.info("ZIP extrait et supprimé")
                                    elif filepath.lower().endswith('.rar'):
                                        logger.info(f"Extraction RAR: {filepath}")
                                        extract_rar(filepath, dest_dir)
                                        os.remove(filepath)
                                        logger.info("RAR extrait et supprimé")
                                except Exception as e:
                                    logger.error(f"Erreur extraction: {e}")
                            
                            return
                        else:
                            logger.error(f"Échec téléchargement gratuit: {error_msg}")
                            result[0] = False
                            result[1] = f"Error Downloading with free mode: {error_msg}"
                            return
                    
                    except Exception as e:
                        logger.error(f"Exception mode gratuit: {e}", exc_info=True)
                    
                    # Si le mode gratuit a échoué aussi
                    logger.error("Échec de tous les providers (API + mode gratuit)")
                    result[0] = False
                    if result[1] is None:
                        result[1] = _("network_api_error").format("No provider available") if _ else "No provider available"
                    return
                if not filename:
                    filename = game_name
                sanitized_filename = sanitize_filename(filename)
                dest_path = os.path.join(dest_dir, sanitized_filename)
                
                # Essayer de récupérer la taille du serveur via HEAD request
                remote_size = None
                try:
                    if final_url:
                        head_response = requests.head(final_url, timeout=10, allow_redirects=True)
                        if head_response.status_code == 200:
                            content_length = head_response.headers.get('content-length')
                            if content_length:
                                remote_size = int(content_length)
                                logger.debug(f"Taille du fichier serveur (AllDebrid/RealDebrid): {remote_size} octets")
                except Exception as e:
                    logger.debug(f"Impossible de vérifier la taille serveur (AllDebrid/RealDebrid): {e}")
                
                # Vérifier si le fichier existe déjà (exact ou avec autre extension)
                file_found = False
                if os.path.exists(dest_path):
                    logger.info(f"Le fichier {dest_path} existe déjà, vérification de la taille...")
                    
                    # Vérifier la taille du fichier local
                    local_size = os.path.getsize(dest_path)
                    logger.debug(f"Taille du fichier local: {local_size} octets")
                    
                    # Comparer les tailles si on a obtenu la taille distante
                    if remote_size is not None and local_size != remote_size:
                        logger.warning(f"Taille mismatch! Local: {local_size}, Remote: {remote_size} - le fichier sera re-téléchargé")
                        # Les tailles ne correspondent pas, il faut re-télécharger
                        try:
                            if os.path.exists(dest_path):
                                os.remove(dest_path)
                                logger.info(f"Fichier incomplet supprimé: {dest_path}")
                            else:
                                logger.debug(f"Fichier déjà supprimé par un autre thread: {dest_path}")
                        except FileNotFoundError:
                            logger.debug(f"Fichier déjà supprimé (ou n'existe plus): {dest_path}")
                        except Exception as e:
                            logger.error(f"Impossible de supprimer le fichier incomplet: {e}")
                            result[0] = False
                            result[1] = f"Erreur suppression fichier incomplet: {str(e)}"
                            return
                        # Continuer le téléchargement normal (ne pas faire return)
                    else:
                        # Les tailles correspondent ou on ne peut pas vérifier, considérer comme déjà téléchargé
                        logger.info(f"Le fichier {dest_path} existe déjà et la taille est correcte, téléchargement ignoré")
                        result[0] = True
                        result[1] = _("network_download_ok").format(game_name) + _("download_already_present")
                        # Afficher un toast au lieu d'ouvrir l'historique
                        try:
                            show_toast(result[1])
                        except Exception as e:
                            logger.debug(f"Impossible d'afficher le toast: {e}")
                        with urls_lock:
                            urls_in_progress.discard(url)
                            logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                        return result[0], result[1]
                    file_found = True
                
                # Vérifier si un fichier avec le même nom de base mais extension différente existe (SEULEMENT si fichier exact non trouvé)
                if not file_found:
                    base_name_no_ext = os.path.splitext(sanitized_filename)[0]
                    if base_name_no_ext != sanitized_filename:  # Seulement si une extension était présente
                        try:
                            # Lister tous les fichiers dans le répertoire de destination
                            if os.path.exists(dest_dir):
                                for existing_file in os.listdir(dest_dir):
                                    existing_base = os.path.splitext(existing_file)[0]
                                    if existing_base == base_name_no_ext:
                                        existing_path = os.path.join(dest_dir, existing_file)
                                        logger.info(f"Un fichier avec le même nom de base existe: {existing_path}, vérification de la taille...")
                                        
                                        # Vérifier la taille du fichier local
                                        local_size = os.path.getsize(existing_path)
                                        logger.debug(f"Taille du fichier local (extension différente): {local_size} octets")
                                        
                                        # Comparer les tailles si on a obtenu la taille distante
                                        if remote_size is not None and local_size != remote_size:
                                            logger.warning(f"Taille mismatch (extension différente)! Local: {local_size}, Remote: {remote_size} - re-téléchargement")
                                            # Continuer le téléchargement normal
                                            break
                                        else:
                                            # Les tailles correspondent, fichier complet
                                            logger.info(f"Un fichier avec le même nom de base existe déjà: {existing_path}, téléchargement ignoré")
                                            result[0] = True
                                            result[1] = _("network_download_ok").format(game_name) + _("download_already_extracted")
                                            # Afficher un toast au lieu d'ouvrir l'historique
                                            try:
                                                show_toast(result[1])
                                            except Exception as e:
                                                logger.debug(f"Impossible d'afficher le toast: {e}")
                                            with urls_lock:
                                                urls_in_progress.discard(url)
                                                logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
                                            return result[0], result[1]
                        except Exception as e:
                            logger.debug(f"Erreur lors de la vérification des fichiers existants: {e}")
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
                                    if "url" in entry and entry["url"] == url and entry["status"] == "Downloading":
                                        entry["total_size"] = total_size
                                        config.needs_redraw = True
                                        break
                            progress_queues[task_id].put((task_id, 0, total_size))  # Mettre à jour la taille totale

                        downloaded = 0
                        chunk_size = 8192
                        last_update_time = time.time()
                        last_downloaded = 0
                        update_interval = 0.1  # Mettre à jour toutes les 0,1 secondes
                        download_canceled = False
                        logger.debug(f"Ouverture fichier: {dest_path}")
                        with open(dest_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=chunk_size):
                                # Vérifier la pause (dynamiquement car l'événement peut être créé après le début)
                                while True:
                                    pause_ev = pause_events.get(task_id)
                                    if pause_ev is None or not pause_ev.is_set():
                                        break  # Pas en pause, continuer le téléchargement
                                    if cancel_ev is not None and cancel_ev.is_set():
                                        break  # Sortir de la boucle de pause si annulation demandée
                                    time.sleep(0.1)  # Attendre en pause
                                
                                if cancel_ev is not None and cancel_ev.is_set():
                                    logger.debug(f"Annulation détectée, arrêt du téléchargement 1fichier pour task_id={task_id}")
                                    result[0] = False
                                    result[1] = _("download_canceled") if _ else "Download canceled"
                                    download_canceled = True
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
                                                    if "url" in entry and entry["url"] == url and entry["status"] == "Downloading":
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

                    # Si annulé, ne pas continuer avec extraction
                    if download_canceled:
                        return
                    
                    # Vérifier si l'extraction automatique est activée dans les paramètres
                    from rgsx_settings import get_auto_extract
                    auto_extract_enabled = get_auto_extract()
                    
                    # Déterminer si extraction est nécessaire
                    force_extract = is_zip_non_supported and auto_extract_enabled
                    if not force_extract and auto_extract_enabled:
                        try:
                            ps3_platforms = {"ps3", "PlayStation 3"}
                            if platform_folder == "ps3" or platform in ps3_platforms:
                                force_extract = True
                                logger.debug("Extraction forcée activée pour PS3 Redump (déchiffrement ISO)")
                        except Exception:
                            pass
                    
                    if force_extract:
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
            # Nettoyer l'URL du set en cours de téléchargement
            with urls_lock:
                urls_in_progress.discard(url)
                logger.debug(f"URL supprimée du set des téléchargements en cours (finally): {url} (URLs restantes: {len(urls_in_progress)})")

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
                                if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement", "Extracting"]:
                                    entry["status"] = "Download_OK" if success else "Erreur"
                                    entry["progress"] = 100 if success else 0
                                    entry["message"] = message
                                    save_history(config.history)
                                    # Marquer le jeu comme téléchargé si succès
                                    if success:
                                        logger.debug(f"[1F_WHILE_LOOP] Marking game as downloaded: platform={platform}, game={game_name}")
                                        from history import mark_game_as_downloaded
                                        file_size = entry.get("size", "N/A")
                                        mark_game_as_downloaded(platform, game_name, file_size)
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
                                if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
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
                    logger.debug(f"[1F_DRAIN_QUEUE] Processing final message: success={success}, message={message[:100] if message else 'None'}")
                    if isinstance(config.history, list):
                        for entry in config.history:
                            if "url" in entry and entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                entry["message"] = message
                                save_history(config.history)
                                # Marquer le jeu comme téléchargé si succès
                                if success:
                                    logger.debug(f"[1F_DRAIN_QUEUE] Marking game as downloaded: platform={platform}, game={game_name}")
                                    from history import mark_game_as_downloaded
                                    file_size = entry.get("size", "N/A")
                                    mark_game_as_downloaded(platform, game_name, file_size)
                                break
    except Exception as e:
        logger.error(f"[1F_DRAIN_QUEUE] Error processing final message: {e}")
    # Nettoyer la queue
    if task_id in progress_queues:
        del progress_queues[task_id]
    cancel_events.pop(task_id, None)
    logger.debug(f"Fin download_from_1fichier, résultat: success={result[0]}, message={result[1]}")
    
    # Sauvegarder le résultat AVANT de retirer l'URL du set (pour les doublons)
    with urls_lock:
        url_results[url] = (result[0], result[1])
        urls_in_progress.discard(url)
        logger.debug(f"URL supprimée du set des téléchargements en cours: {url} (URLs restantes: {len(urls_in_progress)})")
        # Signaler l'événement pour les appels doublons en attente
        if url in url_done_events:
            url_done_events[url].set()
    
    try:
        notify_download_finished()
    except Exception:
        pass
    return result[0], result[1]

def is_1fichier_url(url):
    """Détecte si l'URL est un lien 1fichier."""
    return "1fichier.com" in url

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import urllib.parse
import urllib.request
import os
import sys
import logging
import time
import threading
import asyncio
import shutil
import tempfile
import socket
import argparse
import config
from history import load_history
from utils import load_sources, load_games, extract_data
from network import download_rom, download_from_1fichier
from pathlib import Path
from rgsx_settings import get_language

# Ajouter le dossier parent au path pour imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Charger les traductions au démarrage du serveur
def load_translations():
    """Charge les traductions depuis le fichier de langue configuré"""
    language = get_language()  # Lit depuis rgsx_settings.json
    lang_file = os.path.join(os.path.dirname(__file__), 'languages', f'{language}.json')
    
    try:
        with open(lang_file, 'r', encoding='utf-8') as f:
            translations = json.load(f)
            logging.info(f"Traductions chargées : {language} ({len(translations)} clés)")
            return translations
    except FileNotFoundError:
        logging.warning(f"Fichier de langue non trouvé : {lang_file}, utilisation de l'anglais par défaut")
        # Fallback sur l'anglais
        fallback_file = os.path.join(os.path.dirname(__file__), 'languages', 'en.json')
        with open(fallback_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Erreur lors du chargement des traductions : {e}")
        return {}

# Charger les traductions globalement
TRANSLATIONS = load_translations()

# Fonction d'aide pour obtenir une traduction
def get_translation(key, default=None):
    """Obtient une traduction depuis le dictionnaire global TRANSLATIONS"""
    if key in TRANSLATIONS:
        return TRANSLATIONS[key]
    if default is not None:
        return default
    return key

# Fonction pour normaliser les tailles de fichier
def normalize_size(size_str):
    """
    Normalise une taille de fichier dans différents formats (Ko, KiB, Mo, MiB, Go, GiB)
    en un format uniforme (Mo ou Go).
    Exemples: "150 Mo" -> "150 Mo", "1.5 Go" -> "1.5 Go", "500 Ko" -> "0.5 Mo", "2 GiB" -> "2.15 Go"
    """
    if not size_str:
        return None
    
    import re
    
    # Utiliser regex pour extraire le nombre et l'unité
    match = re.match(r'([0-9.]+)\s*(ko|kio|kib|kb|mo|mio|mib|mb|go|gio|gib|gb)', 
                     str(size_str).lower().strip())
    
    if not match:
        return size_str  # Retourner original si ne correspond pas au format
    
    try:
        value = float(match.group(1))
        unit = match.group(2).lower()
        
        # Convertir tout en Mo
        if unit in ['ko', 'kb']:
            value = value / 1024  # Ko en Mo
        elif unit in ['kio', 'kib']:
            value = value / 1024  # KiB en Mo
        elif unit in ['mo', 'mb']:
            pass  # Déjà en Mo
        elif unit in ['mio', 'mib']:
            pass  # MiB ≈ Mo
        elif unit in ['go', 'gb']:
            value = value * 1024  # Go en Mo
        elif unit in ['gio', 'gib']:
            value = value * 1024  # GiB en Mo
        
        # Afficher en Go si > 1024 Mo, sinon en Mo
        if value >= 1024:
            return f"{value / 1024:.2f} Go".rstrip('0').rstrip('.')
        else:
            # Arrondir à 1 décimale pour Mo
            rounded = round(value, 1)
            if rounded == int(rounded):
                return f"{int(rounded)} Mo"
            else:
                return f"{rounded} Mo".rstrip('0').rstrip('.')
    except (ValueError, TypeError):
        return size_str  # Retourner original si conversion échoue


# Configuration logging - Enregistrer dans rgsx_web.log
os.makedirs(config.log_dir, exist_ok=True)


# Supprimer les handlers existants pour éviter les doublons
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

# Créer le handler de fichier avec mode 'a' (append) et force flush
file_handler = logging.FileHandler(config.log_file_web, mode='a', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# IMPORTANT: Forcer le flush après chaque log
class FlushFileHandler(logging.FileHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

# Recréer le handler avec la classe qui flush automatiquement
file_handler = FlushFileHandler(config.log_file_web, mode='a', encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Créer le handler console
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# Configurer le logger racine
logging.root.setLevel(logging.DEBUG)
logging.root.addHandler(file_handler)
logging.root.addHandler(console_handler)

logger = logging.getLogger(__name__)

logger.info("=" * 60)
logger.info("RGSX Web Server - Démarrage du logging")
logger.info(f"Fichier de log: {config.log_file_web}")
logger.info(f"Répertoire de log: {config.log_dir}")
logger.info(f"Python version: {sys.version}")
logger.info(f"Plateforme: {sys.platform}")
logger.info(f"Répertoire de travail: {os.getcwd()}")
logger.info(f"Script: {__file__}")
logger.info("=" * 60)

# Force flush pour être sûr que ces logs sont écrits
for handler in logging.root.handlers:
    handler.flush()

# Test d'écriture pour vérifier que le fichier fonctionne
try:
    with open(config.log_file_web, 'a', encoding='utf-8') as test_file:
        test_file.write(f"\n{'='*60}\n")
        test_file.write(f"Test d'écriture directe - {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        test_file.write(f"{'='*60}\n")
        test_file.flush()
    logger.info("Test d'écriture dans le fichier de log réussi")
except Exception as e:
    logger.error(f"Erreur lors du test d'écriture : {e}")
    print(f"ERREUR: Impossible d'écrire dans {config.log_file_web}: {e}", file=sys.stderr)

# Initialiser les données au démarrage
logger.info("Chargement initial des données...")
try:
    load_sources()  # Initialise config.games_count
    logger.info(f"{len(getattr(config, 'platforms', []))} plateformes chargées")
    # Force flush
    for handler in logging.root.handlers:
        handler.flush()
except Exception as e:
    logger.error(f"Erreur lors du chargement initial: {e}")
    # Force flush
    for handler in logging.root.handlers:
        handler.flush()


class RGSXHandler(BaseHTTPRequestHandler):
    """Handler HTTP pour les requêtes RGSX"""
    
    def log_message(self, format, *args):
        """Override pour logger proprement"""
        logger.info("%s - %s" % (self.address_string(), format % args))
    
    def _set_headers(self, content_type='application/json', status=200):
        """Définit les headers de réponse"""
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')  # CORS pour dev
        self.end_headers()
    
    def _send_json(self, data, status=200):
        """Envoie une réponse JSON"""
        self._set_headers('application/json', status)
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def _send_html(self, html, status=200):
        """Envoie une réponse HTML"""
        self._set_headers('text/html; charset=utf-8', status)
        self.wfile.write(html.encode('utf-8'))
    
    def do_GET(self):
        """Traite les requêtes GET"""
        # Parser l'URL
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        
        # DEBUG: Log immédiat avec flush forcé
        print(f"[DEBUG] Requête: {path}", flush=True)
        # logger.info(f"GET {path}")
        
        try:
            # Route: Page d'accueil (avec ou sans paramètres pour navigation)
            if path == '/' or path == '/index.html' or path.startswith('/platform/') or path in ['/downloads', '/history', '/settings']:
                self._send_html(self._get_index_html())
            
            # Route: API - Liste des plateformes
            elif path == '/api/platforms':
                platforms = load_sources()
                # Ajouter le nombre de jeux depuis config.games_count
                games_count_dict = getattr(config, 'games_count', {})
                for platform in platforms:
                    platform_name = platform.get('platform_name', '')
                    platform['games_count'] = games_count_dict.get(platform_name, 0)
                
                self._send_json({
                    'success': True,
                    'count': len(platforms),
                    'platforms': platforms
                })
            
            # Route: API - Recherche universelle (systèmes + jeux)
            elif path == '/api/search':
                try:
                    query_params = urllib.parse.parse_qs(parsed_path.query)
                    search_term = query_params.get('q', [''])[0].lower().strip()
                    search_words = [w for w in search_term.split() if w]
                    
                    if not search_term:
                        self._send_json({
                            'success': True,
                            'search_term': '',
                            'results': {'platforms': [], 'games': []}
                        })
                        return
                    
                    # Charger toutes les plateformes
                    platforms = load_sources()
                    games_count_dict = getattr(config, 'games_count', {})
                    
                    matching_platforms = []
                    matching_games = []
                    
                    # Rechercher dans les plateformes et leurs jeux
                    for platform in platforms:
                        platform_name = platform.get('platform_name', '')
                        platform_name_lower = platform_name.lower()
                        
                        # Vérifier si le système correspond
                        platform_matches = search_term in platform_name_lower
                        
                        if platform_matches:
                            matching_platforms.append({
                                'platform_name': platform_name,
                                'folder': platform.get('folder', ''),
                                'platform_image': platform.get('platform_image', ''),
                                'games_count': games_count_dict.get(platform_name, 0)
                            })
                        
                        # Rechercher dans les jeux de cette plateforme
                        try:
                            games = load_games(platform_name)
                            for game in games:
                                game_name = game[0] if isinstance(game, (list, tuple)) else str(game)
                                game_name_lower = game_name.lower()
                                if all(word in game_name_lower for word in search_words):
                                    matching_games.append({
                                        'game_name': game_name,
                                        'platform': platform_name,
                                        'url': game[1] if len(game) > 1 and isinstance(game, (list, tuple)) else None,
                                        'size': normalize_size(game[2] if len(game) > 2 and isinstance(game, (list, tuple)) else None)
                                    })
                        except Exception as e:
                            logger.debug(f"Erreur lors de la recherche dans {platform_name}: {e}")
                            continue
                    
                    self._send_json({
                        'success': True,
                        'search_term': search_term,
                        'results': {
                            'platforms': matching_platforms,
                            'games': matching_games
                        }
                    })
                    
                except Exception as e:
                    logger.error(f"Erreur lors de la recherche: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: API - Traductions
            elif path == '/api/translations':
                self._send_json({
                    'success': True,
                    'language': get_language(),
                    'translations': TRANSLATIONS
                })
            
            # Route: API - Liste des jeux d'une plateforme
            elif path.startswith('/api/games/'):
                platform_name = path.split('/api/games/')[-1]
                platform_name = urllib.parse.unquote(platform_name)
                
                games = load_games(platform_name)
                games_formatted = [
                    {
                        'name': g[0],
                        'url': g[1] if len(g) > 1 else None,
                        'size': normalize_size(g[2] if len(g) > 2 else None)
                    }
                    for g in games
                ]
                
                self._send_json({
                    'success': True,
                    'platform': platform_name,
                    'count': len(games_formatted),
                    'games': games_formatted
                })
            
            # Route: API - Progression des téléchargements (en cours seulement)
            elif path == '/api/progress':
                # Lire depuis history.json - filtrer seulement les téléchargements en cours
                history = load_history() or []
                
                print(f"\n[DEBUG PROGRESS] history.json chargé avec {len(history)} entrées totales")
                
                # Filtrer les entrées avec status "downloading", "Téléchargement", "Connecting", "Try X/Y"
                in_progress_statuses = ["downloading", "Téléchargement", "Downloading", "Connecting", "Extracting"]
                
                downloads = {}
                for entry in history:
                    status = entry.get('status', '')
                    # Inclure aussi les status qui commencent par "Try" (ex: "Try 1/4")
                    if status in in_progress_statuses or status.startswith('Try '):
                        url = entry.get('url', '')
                        if url:
                            downloads[url] = {
                                'downloaded_size': entry.get('downloaded_size', 0),
                                'total_size': entry.get('total_size', 0),
                                'status': status,
                                'progress_percent': entry.get('progress', 0),
                                'speed': entry.get('speed', 0),
                                'game_name': entry.get('game_name', ''),
                                'platform': entry.get('platform', ''),
                                'timestamp': entry.get('timestamp', '')
                            }
                    else:
                        # Debug: afficher les premiers status qui ne matchent pas
                        if len(downloads) < 3:
                            print(f"  [DEBUG] Ignoré - Status: '{status}', Game: {entry.get('game_name', '')[:50]}")
                
                print(f"[DEBUG PROGRESS] {len(downloads)} téléchargements en cours trouvés")
                if downloads:
                    for url, data in list(downloads.items())[:2]:
                        print(f"  - URL: {url[:80]}...")
                        print(f"    Status: {data.get('status')}, Progress: {data.get('progress_percent')}%")
                
                self._send_json({
                    'success': True,
                    'downloads': downloads
                })
            
            # Route: API - Historique (téléchargements terminés ET en queue/cours)
            elif path == '/api/history':
                # Lire depuis history.json - filtrer pour inclure en cours ET terminés
                history = load_history() or []
                
                print(f"\n[DEBUG HISTORY] history.json chargé avec {len(history)} entrées totales")
                
                # Inclure: statuts terminés + en queue + en cours
                included_statuses = [
                    "Download_OK", "Erreur", "error", "Canceled", "Already_Present",  # Terminés
                    "queued", "downloading", "Téléchargement", "Downloading", "Connecting", "Extracting",  # En cours
                ]
                # Inclure aussi les statuts "Try X/Y" (tentatives)
                visible_history = [
                    entry for entry in history
                    if entry.get('status', '') in included_statuses or 
                       str(entry.get('status', '')).startswith('Try ')
                ]
                
                print(f"[DEBUG HISTORY] {len(visible_history)} téléchargements (terminés + en queue + en cours) trouvés")
                if visible_history:
                    print(f"  Premier: {visible_history[0].get('game_name', '')[:50]} - Status: {visible_history[0].get('status')}")
                
                # Trier par timestamp (plus récent en premier)
                visible_history.sort(
                    key=lambda x: x.get('timestamp', ''),
                    reverse=True
                )
                
                self._send_json({
                    'success': True,
                    'count': len(visible_history),
                    'history': visible_history
                })
            
            # Route: API - Queue (lecture)
            elif path == '/api/queue':
                try:
                    queue_status = {
                        'success': True,
                        'active': config.download_active,
                        'queue': config.download_queue,
                        'queue_size': len(config.download_queue)
                    }
                    self._send_json(queue_status)
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération de la queue: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: API - Settings (lecture)
            elif path == '/api/settings':
                try:
                    from rgsx_settings import load_rgsx_settings
                    settings = load_rgsx_settings()
                    
                    self._send_json({
                        'success': True,
                        'settings': settings,
                        'system_info': {
                            'system': config.OPERATING_SYSTEM,
                            'roms_folder': config.ROMS_FOLDER,
                            'platforms_count': len(config.platforms) if hasattr(config, 'platforms') else 0
                        }
                    })
                except Exception as e:
                    logger.error(f"Erreur lors de la lecture des settings: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: API - System Info (informations système Batocera)
            elif path == '/api/system_info':
                try:
                    # Rafraîchir les informations système avant de les renvoyer
                    config.get_batocera_system_info()
                    
                    self._send_json({
                        'success': True,
                        'system_info': config.SYSTEM_INFO
                    })
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération des infos système: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: API - Update games list (clear cache)
            elif path == '/api/update-cache':
                try:
                    # Chemins à supprimer (utiliser les constantes de config)
                    sources_file = config.SOURCES_FILE  # systems_list.json
                    games_folder = config.GAMES_FOLDER
                    images_folder = config.IMAGES_FOLDER
                    
                    deleted = []
                    
                    # Supprimer systems_list.json
                    if os.path.exists(sources_file):
                        os.remove(sources_file)
                        deleted.append('systems_list.json')
                        logger.info(f"✅ Fichier systems_list.json supprimé")
                    
                    # Supprimer dossier games/
                    if os.path.exists(games_folder):
                        shutil.rmtree(games_folder)
                        deleted.append('games/')
                        logger.info(f"✅ Dossier games/ supprimé")
                    
                    # Supprimer dossier images/
                    if os.path.exists(images_folder):
                        shutil.rmtree(images_folder)
                        deleted.append('images/')
                        logger.info(f"✅ Dossier images/ supprimé")
                    
                    # IMPORTANT: Télécharger et extraire games.zip depuis le serveur OTA
                    logger.info("🔄 Téléchargement de games.zip depuis le serveur...")
                    try:
                        # URL du ZIP
                        games_zip_url = config.OTA_data_ZIP  # https://retrogamesets.fr/softs/games.zip
                        
                        # Télécharger dans un fichier temporaire
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
                            zip_path = tmp_file.name
                        
                        # Télécharger le ZIP
                        logger.info(f"Téléchargement depuis {games_zip_url}...")
                        urllib.request.urlretrieve(games_zip_url, zip_path)
                        logger.info(f"✅ ZIP téléchargé: {os.path.getsize(zip_path)} octets")
                        
                        # Extraire dans SAVE_FOLDER
                        logger.info(f"📂 Extraction vers {config.SAVE_FOLDER}...")
                        success, message = extract_data(zip_path, config.SAVE_FOLDER, games_zip_url)
                        
                        # Supprimer le ZIP temporaire
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                        
                        if success:
                            logger.info(f"✅ Extraction réussie: {message}")
                            deleted.append(f'extracted: {message}')
                            
                            # Maintenant charger les sources
                            logger.info("🔄 Chargement des plateformes...")
                            load_sources()
                            platforms_count = len(getattr(config, 'platforms', []))
                            logger.info(f"✅ {platforms_count} plateformes chargées")
                            deleted.append(f'loaded: {platforms_count} platforms')
                        else:
                            raise Exception(f"Échec extraction: {message}")
                        
                    except Exception as reload_error:
                        logger.error(f"❌ Erreur lors du téléchargement/extraction: {reload_error}")
                        deleted.append(f'error: {str(reload_error)}')
                    
                    if deleted:
                        self._send_json({
                            'success': True,
                            'message': 'Cache cleared and data reloaded successfully.',
                            'deleted': deleted
                        })
                    else:
                        self._send_json({
                            'success': True,
                            'message': 'No cache found.',
                            'deleted': []
                        })
                
                except Exception as e:
                    logger.error(f"❌ Erreur lors du nettoyage du cache: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Images des plateformes
            elif path.startswith('/api/image/'):
                platform_name = path.split('/api/image/')[-1]
                platform_name = urllib.parse.unquote(platform_name)
                self._serve_platform_image(platform_name)
            
            # Route: Favicon
            elif path == '/api/favicon':
                self._serve_favicon()
            
            # Route: Browse directories
            elif path == '/api/browse-directories':
                parsed_qs = urllib.parse.parse_qs(parsed_path.query)
                current_path = parsed_qs.get('path', [''])[0]
                self._list_directories(current_path)
            
            # Route inconnue
            else:
                self._send_json({
                    'success': False,
                    'error': 'Route non trouvée',
                    'path': path
                }, status=404)
        
        except Exception as e:
            print(f"[ERROR] Exception: {e}", flush=True)  # DEBUG
            logger.error(f"Erreur lors du traitement de {path}: {e}", exc_info=True)
            try:
                self._send_json({
                    'success': False,
                    'error': str(e)
                }, status=500)
            except:
                pass  # Éviter le crash si la réponse échoue
    
    def _process_queued_download(self, queue_item):
        """Traite un élément de la queue de téléchargement"""
        game_url = queue_item['url']
        platform = queue_item['platform']
        game_name = queue_item['game_name']
        is_zip_non_supported = queue_item['is_zip_non_supported']
        is_1fichier = queue_item['is_1fichier']
        task_id = queue_item['task_id']
        
        config.download_active = True
        
        # Mettre à jour l'historique: queued -> downloading
        from history import load_history, save_history
        config.history = load_history()
        for entry in config.history:
            if entry.get('task_id') == task_id and entry.get('status') == 'queued':
                entry['status'] = 'downloading'
                entry['message'] = get_translation('download_in_progress')
                save_history(config.history)
                logger.info(f"📋 Statut mis à jour de 'queued' à 'downloading' pour {game_name} (task_id={task_id})")
                break
        
        if is_1fichier:
            download_func = download_from_1fichier
            logger.info(f"🔗 Queue: download_from_1fichier() pour {game_name}, extraction={is_zip_non_supported}")
        else:
            download_func = download_rom
            logger.info(f"📦 Queue: Téléchargement {game_name}, extraction={is_zip_non_supported}")
        
        def run_download():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    download_func(game_url, platform, game_name, is_zip_non_supported, task_id)
                )
            finally:
                loop.close()
                # Après le téléchargement, traiter la queue
                config.download_active = False
                if config.download_queue:
                    next_item = config.download_queue.pop(0)
                    logger.info(f"📋 Traitement du prochain élément de la queue: {next_item['game_name']}")
                    # Relancer de manière asynchrone
                    threading.Thread(target=lambda: self._process_queued_download(next_item), daemon=True).start()
        
        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()
    
    def do_POST(self):
        """Traite les requêtes POST"""
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        
        print(f"[DEBUG] POST Requête: {path}", flush=True)
        logger.info(f"POST {path}")
        
        try:
            # Lire le corps de la requête
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode('utf-8')) if content_length > 0 else {}
            
            # Route: Lancer un téléchargement
            if path == '/api/download':
                platform = data.get('platform')
                game_index = data.get('game_index')
                game_name_param = data.get('game_name')  # Nouveau: chercher par nom
                mode = data.get('mode', 'now')  # 'now' ou 'queue'
                
                if not platform or (game_index is None and not game_name_param):
                    self._send_json({
                        'success': False,
                        'error': 'Paramètres manquants: platform et (game_index ou game_name) requis'
                    }, status=400)
                    return
                
                # Charger les jeux de la plateforme
                games = load_games(platform)
                
                # Si game_name est fourni, chercher l'index correspondant
                if game_name_param and game_index is None:
                    game_index = None
                    for idx, game in enumerate(games):
                        current_game_name = game[0] if isinstance(game, (list, tuple)) else str(game)
                        if current_game_name == game_name_param:
                            game_index = idx
                            break
                    
                    if game_index is None:
                        self._send_json({
                            'success': False,
                            'error': f'Jeu non trouvé: {game_name_param}'
                        }, status=400)
                        return
                
                # Vérifier que game_index est valide (après recherche ou direct)
                if game_index is None or game_index < 0 or game_index >= len(games):
                    self._send_json({
                        'success': False,
                        'error': f'Index de jeu invalide: {game_index}'
                    }, status=400)
                    return
                
                game = games[game_index]
                game_name = game[0]
                game_url = game[1] if len(game) > 1 else None
                
                if not game_url:
                    self._send_json({
                        'success': False,
                        'error': 'URL de téléchargement non disponible'
                    }, status=400)
                    return
                
                # Vérifier l'extension et déterminer si extraction nécessaire
                from utils import check_extension_before_download
                check_result = check_extension_before_download(game_url, platform, game_name)
                
                if not check_result:
                    self._send_json({
                        'success': False,
                        'error': 'Extension non supportée ou erreur de vérification'
                    }, status=400)
                    return
                
                # check_result est un tuple: (url, platform, game_name, is_zip_non_supported)
                is_zip_non_supported = check_result[3] if len(check_result) > 3 else False
                
                # Détecter si c'est un lien 1fichier et utiliser la fonction appropriée
                is_1fichier = "1fichier.com" in game_url
                
                task_id = f"web_{int(time.time() * 1000)}"
                
                # Déterminer si on doit ajouter à la queue ou télécharger immédiatement
                # - mode='now' : toujours télécharger immédiatement (parallèle autorisé) - JAMAIS addé à la queue
                # - mode='queue' : ajouter à la queue SEULEMENT s'il y a un téléchargement actif (serial)
                should_queue = mode == 'queue' and config.download_active
                
                if mode == 'now':
                    # mode='now' = toujours lancer immédiatement en parallèle, indépendamment de download_active
                    logger.info(f"⚡ Téléchargement immédiat lancé en parallèle (mode=now): {game_name}")
                    
                    if is_1fichier:
                        download_func = download_from_1fichier
                        logger.info(f"🔗 Détection 1fichier, utilisation de download_from_1fichier() pour {game_name}, extraction={is_zip_non_supported}")
                    else:
                        download_func = download_rom
                        logger.info(f"📦 Téléchargement {game_name}, extraction={is_zip_non_supported}")
                    
                    def run_download_now():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                download_func(game_url, platform, game_name, is_zip_non_supported, task_id)
                            )
                        finally:
                            loop.close()
                            # mode='now' n'affecte pas download_active - il peut y avoir plusieurs téléchargements en parallèle
                    
                    thread = threading.Thread(target=run_download_now, daemon=True)
                    thread.start()
                    
                    self._send_json({
                        'success': True,
                        'message': f'Téléchargement de {game_name} lancé',
                        'task_id': task_id,
                        'game_name': game_name,
                        'platform': platform,
                        'is_1fichier': is_1fichier
                    })
                    
                elif should_queue:
                    # mode='queue' ET un téléchargement est actif -> ajouter à la queue
                    queue_item = {
                        'url': game_url,
                        'platform': platform,
                        'game_name': game_name,
                        'is_zip_non_supported': is_zip_non_supported,
                        'is_1fichier': is_1fichier,
                        'task_id': task_id,
                        'status': 'queued'
                    }
                    config.download_queue.append(queue_item)
                    
                    # Ajouter une entrée à l'historique avec status "queued"
                    import datetime
                    queue_history_entry = {
                        'platform': platform,
                        'game_name': game_name,
                        'status': 'queued',
                        'url': game_url,
                        'progress': 0,
                        'message': get_translation('download_queued'),
                        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'downloaded_size': 0,
                        'total_size': 0,
                        'task_id': task_id
                    }
                    config.history.append(queue_history_entry)
                    
                    # Sauvegarder l'historique
                    from history import save_history
                    save_history(config.history)
                    
                    logger.info(f"📋 {game_name} ajouté à la file d'attente (mode=queue, active={config.download_active})")
                    
                    self._send_json({
                        'success': True,
                        'message': f'{game_name} ajouté à la file d\'attente',
                        'task_id': task_id,
                        'game_name': game_name,
                        'platform': platform,
                        'queued': True,
                        'queue_position': len(config.download_queue)
                    })
                else:
                    # mode='queue' MAIS pas de téléchargement actif -> lancer immédiatement (premier élément)
                    config.download_active = True
                    logger.info(f"🚀 Lancement du premier élément de la queue: {game_name}")
                    
                    # Ajouter une entrée à l'historique avec status "downloading"
                    # (pas "queued" car on lance immédiatement)
                    import datetime
                    download_history_entry = {
                        'platform': platform,
                        'game_name': game_name,
                        'status': 'downloading',
                        'url': game_url,
                        'progress': 0,
                        'message': get_translation('download_in_progress'),
                        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        'downloaded_size': 0,
                        'total_size': 0,
                        'task_id': task_id
                    }
                    config.history.append(download_history_entry)
                    from history import save_history
                    save_history(config.history)
                    
                    if is_1fichier:
                        download_func = download_from_1fichier
                        logger.info(f"🔗 Détection 1fichier, utilisation de download_from_1fichier() pour {game_name}, extraction={is_zip_non_supported}")
                    else:
                        download_func = download_rom
                        logger.info(f"📦 Téléchargement {game_name}, extraction={is_zip_non_supported}")
                    
                    def run_download_queue():
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                download_func(game_url, platform, game_name, is_zip_non_supported, task_id)
                            )
                        finally:
                            loop.close()
                            # Mode queue: marquer comme inactif et traiter le suivant
                            config.download_active = False
                            if config.download_queue:
                                next_item = config.download_queue.pop(0)
                                logger.info(f"📋 Traitement du prochain élément de la queue: {next_item['game_name']}")
                                # Relancer de manière asynchrone
                                threading.Thread(target=lambda: self._process_queued_download(next_item), daemon=True).start()
                    
                    thread = threading.Thread(target=run_download_queue, daemon=True)
                    thread.start()
                    
                    self._send_json({
                        'success': True,
                        'message': f'Téléchargement de {game_name} lancé',
                        'task_id': task_id,
                        'game_name': game_name,
                        'platform': platform,
                        'is_1fichier': is_1fichier
                    })
            
            # Route: Annuler un téléchargement
            elif path == '/api/cancel':
                url = data.get('url')
                
                if not url:
                    self._send_json({
                        'success': False,
                        'error': 'Paramètre manquant: url requis'
                    }, status=400)
                    return
                
                try:
                    from network import request_cancel
                    from history import load_history, save_history
                    
                    # Trouver le task_id correspondant à l'URL dans l'historique
                    history = load_history() or []
                    task_id = None
                    
                    for entry in history:
                        if entry.get('url') == url and entry.get('status') in ['downloading', 'Téléchargement', 'Downloading', 'Connecting']:
                            # Mettre à jour le statut dans l'historique
                            entry['status'] = 'Canceled'
                            entry['progress'] = 0
                            entry['message'] = get_translation('web_download_canceled')
                            
                            # Récupérer le task_id depuis l'entrée (il a été sauvegardé lors du démarrage du téléchargement)
                            task_id = entry.get('task_id')
                            break
                    
                    if task_id:
                        # Tenter d'annuler le téléchargement
                        cancel_success = request_cancel(task_id)
                        logger.info(f"Annulation demandée pour task_id={task_id}, success={cancel_success}")
                    else:
                        logger.warning(f"Impossible de trouver task_id pour l'URL: {url}")
                    
                    # Sauvegarder l'historique modifié
                    save_history(history)
                    
                    # Réinitialiser le flag de téléchargement actif et lancer le prochain
                    config.download_active = False
                    if config.download_queue:
                        next_item = config.download_queue.pop(0)
                        logger.info(f"📋 Traitement du prochain élément de la queue après annulation: {next_item['game_name']}")
                        # Relancer de manière asynchrone
                        # Créer une référence à self pour utiliser dans la lambda
                        handler = self
                        threading.Thread(target=lambda: handler._process_queued_download(next_item), daemon=True).start()
                    
                    self._send_json({
                        'success': True,
                        'message': 'Téléchargement annulé',
                        'url': url,
                        'task_id': task_id
                    })
                    
                except Exception as e:
                    logger.error(f"Erreur lors de l\\'annulation du téléchargement: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Obtenir l'état de la queue
            elif path == '/api/queue':
                try:
                    queue_status = {
                        'success': True,
                        'active': config.download_active,
                        'queue': config.download_queue,
                        'queue_size': len(config.download_queue)
                    }
                    self._send_json(queue_status)
                except Exception as e:
                    logger.error(f"Erreur lors de la récupération de la queue: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Vider la queue (sauf le premier élément en cours)
            elif path == '/api/queue/clear':
                try:
                    cleared_count = len(config.download_queue)
                    config.download_queue.clear()
                    logger.info(f"📋 Queue vidée ({cleared_count} éléments supprimés)")
                    self._send_json({
                        'success': True,
                        'message': f'{cleared_count} éléments supprimés de la queue',
                        'cleared_count': cleared_count
                    })
                except Exception as e:
                    logger.error(f"Erreur lors du nettoyage de la queue: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Supprimer un élément de la queue
            elif path == '/api/queue/remove':
                try:
                    task_id = data.get('task_id')
                    if not task_id:
                        self._send_json({
                            'success': False,
                            'error': 'Paramètre manquant: task_id requis'
                        }, status=400)
                        return
                    
                    # Chercher et supprimer l'élément
                    found = False
                    for idx, item in enumerate(config.download_queue):
                        if item.get('task_id') == task_id:
                            removed_item = config.download_queue.pop(idx)
                            logger.info(f"📋 {removed_item['game_name']} supprimé de la queue")
                            found = True
                            break
                    
                    if found:
                        self._send_json({
                            'success': True,
                            'message': f'Élément supprimé de la queue',
                            'task_id': task_id
                        })
                    else:
                        self._send_json({
                            'success': False,
                            'error': f'Élément non trouvé: {task_id}'
                        }, status=404)
                except Exception as e:
                    logger.error(f"Erreur lors de la suppression d'un élément de la queue: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Sauvegarder les settings
            elif path == '/api/settings':
                try:
                    from rgsx_settings import save_rgsx_settings
                    
                    settings = data.get('settings')
                    if not settings:
                        self._send_json({
                            'success': False,
                            'error': 'Paramètre "settings" manquant'
                        }, status=400)
                        return
                    
                    save_rgsx_settings(settings)
                    
                    self._send_json({
                        'success': True,
                        'message': 'Paramètres sauvegardés avec succès'
                    })
                    
                except Exception as e:
                    logger.error(f"Erreur lors de la sauvegarde des settings: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Vider l'historique
            elif path == '/api/clear-history':
                try:
                    from history import clear_history
                    
                    clear_history()
                    config.history = []  # Vider aussi la liste en mémoire
                    
                    self._send_json({
                        'success': True,
                        'message': 'Historique vidé avec succès'
                    })
                    
                except Exception as e:
                    logger.error(f"Erreur lors du vidage de l\\'historique: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Redémarrer l'application
            elif path == '/api/restart':
                try:
                    logger.info("Demande de redémarrage via l'interface web")
                    
                    # Importer restart_application depuis utils
                    from utils import restart_application
                    
                    # Envoyer la réponse avant de redémarrer
                    self._send_json({
                        'success': True,
                        'message': 'Redémarrage en cours...'
                    })
                    
                    # Flush les logs
                    for handler in logging.root.handlers:
                        handler.flush()
                    
                    # Programmer le redémarrage dans 2 secondes
                    logger.info("Redémarrage programmé dans 2 secondes")
                    def delayed_restart():
                        time.sleep(2)
                        logger.info("Lancement du redémarrage...")
                        restart_application(0)
                    
                    restart_thread = threading.Thread(target=delayed_restart, daemon=True)
                    restart_thread.start()
                    
                except Exception as e:
                    logger.error(f"Erreur lors du redémarrage: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route: Générer un fichier ZIP de support
            elif path == '/api/support':
                try:
                    import zipfile
                    import tempfile
                    from datetime import datetime
                    
                    logger.info("Génération d'un fichier de support")
                    
                    # Créer un fichier ZIP temporaire
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    zip_filename = f"rgsx_support_{timestamp}.zip"
                    zip_path = os.path.join(tempfile.gettempdir(), zip_filename)
                    
                    # Liste des fichiers à inclure
                    files_to_include = []
                    
                    # Ajouter les fichiers de configuration
                    if hasattr(config, 'CONTROLS_CONFIG_PATH') and os.path.exists(config.CONTROLS_CONFIG_PATH):
                        files_to_include.append(('controls.json', config.CONTROLS_CONFIG_PATH))
                    
                    if hasattr(config, 'HISTORY_PATH') and os.path.exists(config.HISTORY_PATH):
                        files_to_include.append(('history.json', config.HISTORY_PATH))
                    
                    if hasattr(config, 'RGSX_SETTINGS_PATH') and os.path.exists(config.RGSX_SETTINGS_PATH):
                        files_to_include.append(('rgsx_settings.json', config.RGSX_SETTINGS_PATH))
                    
                    # Ajouter les fichiers de log
                    if hasattr(config, 'log_file') and os.path.exists(config.log_file):
                        files_to_include.append(('RGSX.log', config.log_file))
                    
                    # Log du serveur web
                    web_log = os.path.join(config.log_dir, 'rgsx_web.log')
                    if os.path.exists(web_log):
                        files_to_include.append(('rgsx_web.log', web_log))
                    
                    # Log de démarrage du serveur web
                    web_startup_log = os.path.join(config.log_dir, 'rgsx_web_startup.log')
                    if os.path.exists(web_startup_log):
                        files_to_include.append(('rgsx_web_startup.log', web_startup_log))
                    
                    # Créer le fichier ZIP
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for archive_name, file_path in files_to_include:
                            try:
                                zipf.write(file_path, archive_name)
                                logger.debug(f"Ajouté au ZIP: {archive_name}")
                            except Exception as e:
                                logger.warning(f"Impossible d'ajouter {archive_name}: {e}")
                        
                        # Ajouter un fichier README avec des informations système
                        readme_content = f"""RGSX Support Package
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

System Information:
- OS: {config.OPERATING_SYSTEM}
- Python: {sys.version}
- Platform: {sys.platform}

Included Files:
"""
                        for archive_name, _ in files_to_include:
                            readme_content += f"- {archive_name}\n"
                        
                        readme_content += """
Instructions:
1. Join RGSX Discord server
2. Describe your issue in the support channel
3. Upload this ZIP file to help the team diagnose your problem

DO NOT share this file publicly as it may contain sensitive information.
"""
                        zipf.writestr('README.txt', readme_content)
                    
                    # Lire le fichier ZIP pour l'envoyer
                    with open(zip_path, 'rb') as f:
                        zip_data = f.read()
                    
                    # Supprimer le fichier temporaire
                    os.remove(zip_path)
                    
                    # Envoyer le fichier ZIP
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Disposition', f'attachment; filename="{zip_filename}"')
                    self.send_header('Content-Length', str(len(zip_data)))
                    self.end_headers()
                    self.wfile.write(zip_data)
                    
                    logger.info(f"Fichier de support généré: {zip_filename} ({len(zip_data)} bytes)")
                    
                except Exception as e:
                    logger.error(f"Erreur lors de la génération du fichier de support: {e}")
                    self._send_json({
                        'success': False,
                        'error': str(e)
                    }, status=500)
            
            # Route inconnue
            else:
                self._send_json({
                    'success': False,
                    'error': 'Route non trouvée',
                    'path': path
                }, status=404)
        
        except Exception as e:
            print(f"[ERROR] POST Exception: {e}", flush=True)
            logger.error(f"Erreur POST {path}: {e}", exc_info=True)
            self._send_json({
                'success': False,
                'error': str(e)
            }, status=500)
    
    def _serve_platform_image(self, platform_name):
        """Sert l'image d'une plateforme en utilisant le mapping de systems_list.json"""
        print(f"[DEBUG] Image demandée pour: {platform_name}", flush=True)  # DEBUG
        try:
            # Trouver la plateforme dans platform_dicts pour obtenir le platform_image
            platform_dict = None
            for pd in config.platform_dicts:
                if pd.get('platform_name') == platform_name:
                    platform_dict = pd
                    break
            
            # Dossiers où chercher les images
            image_folders = [
                config.IMAGES_FOLDER,  # Dossier utilisateur (saves/ports/rgsx/images)
                os.path.join(config.APP_FOLDER, 'assets', 'images')  # Dossier app
            ]
            
            # Extensions possibles
            extensions = ['.png', '.jpg', '.jpeg', '.gif']
            
            # Construire la liste des noms de fichiers à chercher (ordre de priorité)
            candidates = []
            
            if platform_dict:
                # 1. platform_image explicite (priorité max)
                platform_image_field = (platform_dict.get('platform_image') or '').strip()
                if platform_image_field:
                    candidates.append(platform_image_field)
                
                # 2. platform_name.png
                candidates.append(platform_name)
                
                # 3. folder.png si disponible
                folder_name = platform_dict.get('folder')
                if folder_name:
                    candidates.append(folder_name)
            else:
                # Pas de platform_dict trouvé, juste essayer le nom
                candidates.append(platform_name)
            
            # Chercher le fichier image
            image_path = None
            for candidate in candidates:
                # Retirer l'extension si déjà présente
                candidate_base = os.path.splitext(candidate)[0]
                
                for folder in image_folders:
                    if not os.path.exists(folder):
                        continue
                    
                    # Essayer avec chaque extension
                    for ext in extensions:
                        test_path = os.path.join(folder, candidate_base + ext)
                        if os.path.exists(test_path):
                            image_path = test_path
                            break
                    
                    if image_path:
                        break
                
                if image_path:
                    break
            
            # Si pas trouvé, chercher default.png
            if not image_path:
                for folder in image_folders:
                    default_path = os.path.join(folder, 'default.png')
                    if os.path.exists(default_path):
                        image_path = default_path
                        break
            
            # Envoyer l'image
            if image_path and os.path.exists(image_path):
                # Déterminer le type MIME
                ext = os.path.splitext(image_path)[1].lower()
                mime_types = {
                    '.png': 'image/png',
                    '.jpg': 'image/jpeg',
                    '.jpeg': 'image/jpeg',
                    '.gif': 'image/gif'
                }
                content_type = mime_types.get(ext, 'image/png')
                
                # Lire et envoyer l'image avec headers de cache
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                # Ajouter les headers de cache (1 heure)
                self.send_response(200)
                self.send_header('Content-type', content_type)
                self.send_header('Cache-Control', 'public, max-age=3600')  # 1 heure
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(image_data)
            else:
                # Image par défaut (pixel transparent)
                logger.warning(f"Aucune image trouvée pour {platform_name}, envoi PNG transparent")
                self.send_response(404)
                self.send_header('Content-type', 'image/png')
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                # PNG transparent 1x1 pixel
                transparent_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
                self.wfile.write(transparent_png)
                
        except Exception as e:
            logger.error(f"Erreur lors du chargement de l'image {platform_name}: {e}", exc_info=True)
            self.send_response(500)
            self.send_header('Content-type', 'image/png')
            self.send_header('Cache-Control', 'public, max-age=60')  # Cache court pour les erreurs
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            # PNG transparent en cas d'erreur
            transparent_png = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
            self.wfile.write(transparent_png)
    
    def _serve_favicon(self):
        """Sert le favicon de l'application"""
        try:
            favicon_path = os.path.join(config.APP_FOLDER, 'assets', 'images', 'favicon_rgsx.ico')
            
            if os.path.exists(favicon_path):
                with open(favicon_path, 'rb') as f:
                    favicon_data = f.read()
                
                self.send_response(200)
                self.send_header('Content-type', 'image/x-icon')
                self.send_header('Cache-Control', 'public, max-age=86400')  # Cache 24h
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(favicon_data)
            else:
                logger.warning(f"Favicon non trouvé: {favicon_path}")
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            logger.error(f"Erreur lors du chargement du favicon: {e}", exc_info=True)
            self.send_response(500)
            self.end_headers()
    
    def _list_directories(self, path: str):
        """Liste les répertoires pour le navigateur de fichiers"""
        try:
            # Si le chemin est vide, lister les lecteurs sur Windows ou / sur Linux
            if not path:
                if os.name == 'nt':
                    # Windows: lister les lecteurs
                    import string
                    drives = []
                    for letter in string.ascii_uppercase:
                        drive = f"{letter}:\\"
                        if os.path.exists(drive):
                            drives.append({
                                'name': drive,
                                'path': drive,
                                'is_drive': True
                            })
                    self._send_json({
                        'success': True,
                        'current_path': '',
                        'parent_path': None,
                        'directories': drives
                    })
                    return  # Important: arrêter ici pour Windows
                else:
                    # Linux/Mac: partir de la racine
                    path = '/'
            
            # Vérifier que le chemin existe
            if not os.path.isdir(path):
                self._send_json({
                    'success': False,
                    'error': 'Le chemin spécifié n\'existe pas'
                }, status=400)
                return
            
            # Lister les sous-répertoires
            directories = []
            try:
                for entry in os.listdir(path):
                    entry_path = os.path.join(path, entry)
                    if os.path.isdir(entry_path):
                        directories.append({
                            'name': entry,
                            'path': entry_path,
                            'is_drive': False
                        })
            except PermissionError:
                logger.warning(f"Accès refusé au répertoire: {path}")
            
            # Trier par nom
            directories.sort(key=lambda x: x['name'].lower())
            
            # Déterminer le chemin parent
            parent_path = None
            if path and path != '/':
                if os.name == 'nt':
                    # Sur Windows, si on est à la racine d'un lecteur (C:\), parent = ''
                    if len(path) == 3 and path[1] == ':' and path[2] == '\\':
                        parent_path = ''
                    else:
                        parent_path = os.path.dirname(path)
                else:
                    parent_path = os.path.dirname(path)
                    if not parent_path:
                        parent_path = '/'
            
            self._send_json({
                'success': True,
                'current_path': path,
                'parent_path': parent_path,
                'directories': directories
            })
            
        except Exception as e:
            logger.error(f"Erreur lors du listage des répertoires: {e}", exc_info=True)
            self._send_json({
                'success': False,
                'error': str(e)
            }, status=500)
    
    def _get_index_html(self):
        """Retourne la page HTML d'accueil"""
        return '''
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎮 RGSX Web Interface</title>
    <link rel="icon" type="image/x-icon" href="/api/favicon">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 90%;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
            position: relative;
        }
        header h1 { font-size: 2.5em; margin-bottom: 10px; }
        header p { opacity: 0.9; font-size: 1.1em; }
       
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        
        /* Navigation mobile dans le header */
        .mobile-tabs {
            display: none;
            justify-content: space-around;
            padding: 15px 10px 10px 10px;
            gap: 5px;
        }
        .mobile-tab {
            flex: 1;
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 12px 5px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 24px;
            transition: all 0.3s;
            backdrop-filter: blur(10px);
        }
        .mobile-tab:hover {
            background: rgba(255,255,255,0.3);
        }
        .mobile-tab.active {
            background: rgba(255,255,255,0.4);
            transform: scale(1.1);
        }
        
        .tabs {
            display: flex;
            background: #f5f5f5;
            border-bottom: 2px solid #ddd;
        }
        .tab {
            flex: 1;
            padding: 15px;
            text-align: center;
            cursor: pointer;
            background: #f5f5f5;
            border: none;
            font-size: 16px;
            transition: all 0.3s;
        }
        .tab:hover { background: #e0e0e0; }
        .tab.active {
            background: white;
            border-bottom: 3px solid #667eea;
            font-weight: bold;
        }
        .tab.support-btn {
            margin-left: auto;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border-radius: 20px;
            padding: 8px 20px;
        }
        .tab.support-btn:hover {
            background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
            transform: scale(1.05);
        }
        
        .content {
            padding: 30px;
            min-height: 400px;
        }
        .loading {
            text-align: center;
            padding: 50px;
            font-size: 1.2em;
            color: #666;
        }
        
        .platform-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
            gap: 20px;
        }
        .platform-card {
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            padding: 20px;
            border-radius: 12px;
            cursor: pointer;
            transition: transform 0.3s, box-shadow 0.3s;
            text-align: center;
        }
        .platform-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.4);
        }
        .platform-card img {
            width: 200px;
            height: 200px;
            object-fit: contain;
            margin-bottom: 15px;
            filter: drop-shadow(0 4px 6px rgba(0,0,0,0.3));
        }
        .platform-card h3 { 
            margin-bottom: 10px; 
            color: white;
            font-size: 1.1em;
            min-height: 2.5em;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .platform-card .count {
            background: #667eea;
            color: white;
            padding: 5px 15px;
            border-radius: 20px;
            display: inline-block;
            margin-top: 10px;
        }
        
        .search-box {
            margin-bottom: 20px;
            position: relative;
        }
        .search-box input {
            width: 100%;
            padding: 12px 45px 12px 15px;
            border: 2px solid #ddd;
            border-radius: 8px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
        }
        .search-box .search-icon {
            position: absolute;
            right: 15px;
            top: 50%;
            transform: translateY(-50%);
            color: #999;
            font-size: 18px;
        }
        .search-box .clear-search {
            position: absolute;
            right: 45px;
            top: 50%;
            transform: translateY(-50%);
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            cursor: pointer;
            display: none;
            font-size: 14px;
            line-height: 1;
        }
        .search-box .clear-search:hover {
            background: #c82333;
        }
        
        .sort-btn {
            background: #e0e0e0;
            color: #333;
            border: 2px solid #999;
            padding: 8px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9em;
            font-weight: 500;
            transition: all 0.2s;
        }
        .sort-btn:hover {
            background: #d0d0d0;
            border-color: #666;
        }
        .sort-btn.active {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        
        .games-list {
            max-height: 600px;
            overflow-y: auto;
        }
        .game-item {
            background: #f9f9f9;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: background 0.2s;
        }
        .game-item:hover { background: #f0f0f0; }
        .game-name { font-weight: 500; flex: 1; }
        .game-size {
            background: #667eea;
            color: white;
            padding: 5px 10px;
            border-radius: 5px;
            font-size: 0.9em;
            margin-right: 10px;
        }
        .download-btn {
            background: transparent;
            color: #28a745;
            border: none;
            padding: 8px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 1.5em;
            transition: all 0.2s;
            min-width: 40px;
        }
        .download-btn:hover { 
            background: rgba(40, 167, 69, 0.1);
            transform: scale(1.1);
        }
        .download-btn:disabled {
            color: #6c757d;
            cursor: not-allowed;
        }
        
        .back-btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            margin-bottom: 20px;
            font-size: 16px;
        }
        .back-btn:hover { background: #5568d3; }
        
        .info-grid {
            display: grid;
            gap: 15px;
        }
        .info-item {
            background: #f9f9f9;
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
        }
        .info-item strong { display: block; margin-bottom: 5px; color: #667eea; }
        
        .history-item {
            background: #f9f9f9;
            padding: 15px;
            margin-bottom: 10px;
            border-radius: 8px;
            border-left: 4px solid #28a745;
        }
        .history-item.error { border-left-color: #dc3545; }
        
        /* Media Queries pour responsive */
        @media (max-width: 768px) {
            body {
                padding: 10px;
            }
            
            .container {
                border-radius: 0;
            }
            
            header {
                padding: 20px 20px 10px 20px;
            }
            
            header h1 {
                font-size: 1.8em;
            }
            
            
            /* Masquer les tabs normaux sur mobile */
            .tabs {
                display: none;
            }
            
            /* Afficher la navigation mobile dans le header */
            .mobile-tabs {
                display: flex;
            }
            
            .content {
                padding: 15px;
            }
            
            .platform-grid {
                grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
                gap: 15px;
            }
            
            .platform-card {
                padding: 15px;
            }
            
            .platform-card img {
                width: 80px;
                height: 80px;
            }
            
            .platform-card h3 {
                font-size: 0.9em;
                min-height: 2em;
            }
            
            .game-item {
                flex-wrap: wrap;
                padding: 10px;
            }
            
            .game-name {
                font-size: 0.9em;
                flex: 1 1 100%;
                margin-bottom: 8px;
            }
            
            .download-btn-group {
                display: flex;
                gap: 4px;
            }
        }
        
        @media (max-width: 480px) {
            header h1 {
                font-size: 1.5em;
            }
            
            .platform-grid {
                grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
                gap: 10px;
            }
            
            .platform-card {
                padding: 10px;
            }
            
            .platform-card img {
                width: 60px;
                height: 60px;
            }
            
            .platform-card h3 {
                font-size: 0.85em;
            }
            
            .platform-card .count {
                font-size: 0.8em;
                padding: 3px 10px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1 data-translate="web_title">RGSX Web Interface</h1>
            <p style="font-size: 0.85em; opacity: 0.8; margin-top: 5px;">v{version}</p>
            
            
            <!-- Navigation mobile avec icônes uniquement -->
            <div class="mobile-tabs">
                <button class="mobile-tab active" onclick="showTab('platforms')" data-translate-title="web_tooltip_platforms" title="Platforms list">🎮</button>
                <button class="mobile-tab" onclick="showTab('downloads')" data-translate-title="web_tooltip_downloads" title="Downloads">⬇️</button>
                <button class="mobile-tab" onclick="showTab('queue')" data-translate-title="web_tooltip_queue" title="Queue">📋</button>
                <button class="mobile-tab" onclick="showTab('history')" data-translate-title="web_tooltip_history" title="History">📜</button>
                <button class="mobile-tab" onclick="showTab('settings')" data-translate-title="web_tooltip_settings" title="Settings">⚙️</button>                
                <button class="mobile-tab" onclick="updateGamesList()" data-translate-title="web_tooltip_update" title="Update games list">🔄</button>
                <button class="mobile-tab" onclick="generateSupportZip()" data-translate-title="web_support" title="Support">🆘</button>
            </div>
        </header>
        
        <div class="tabs">
            <button class="tab active" onclick="showTab('platforms')">🎮 <span data-translate="web_tab_platforms">Platforms List</span></button>
            <button class="tab" onclick="showTab('downloads')">⬇️ <span data-translate="web_tab_downloads">Downloads</span></button>
            <button class="tab" onclick="showTab('queue')">📋 <span data-translate="web_tab_queue">Queue</span></button>
            <button class="tab" onclick="showTab('history')">📜 <span data-translate="web_tab_history">History</span></button>
            <button class="tab" onclick="showTab('settings')">⚙️ <span data-translate="web_tab_settings">Settings</span></button>
            <button class="tab" onclick="updateGamesList()">🔄 <span data-translate="web_tab_update">Update games list</span></button>
            <button class="tab" onclick="generateSupportZip()">🆘 <span data-translate="web_support">Support</span></button>
        </div>
        
        <div class="content">
            <div id="platforms-content"></div>
            <div id="downloads-content" style="display:none;"></div>
            <div id="queue-content" style="display:none;"></div>
            <div id="history-content" style="display:none;"></div>
            <div id="settings-content" style="display:none;"></div>
        </div>
    </div>
    
    <script>
        // ===== VARIABLES GLOBALES =====
        let currentPlatform = null;
        let currentGameSort = 'name_asc';  // Type de tri actuel: 'name_asc', 'name_desc', 'size_asc', 'size_desc'
        let currentGames = [];  // Stocke les jeux actuels pour le tri
        let lastProgressUpdate = Date.now();
        let autoRefreshTimeout = null;
        let progressInterval = null;
        let queueInterval = null;
        let translations = {};  // Contiendra toutes les traductions
        
        // Charger les traductions au démarrage
        async function loadTranslations() {
            try {
                const response = await fetch('/api/translations');
                const data = await response.json();
                if (data.success) {
                    translations = data.translations;
                    console.log('Traductions chargées:', data.language, Object.keys(translations).length, 'clés');
                }
            } catch (error) {
                console.error('Erreur chargement traductions:', error);
            }
        }
        
        // Fonction helper pour obtenir une traduction avec paramètres
        function t(key, ...params) {
            let text = translations[key] || key;
            // Remplacer {0}, {1}, etc. par les paramètres (sans regex pour éviter les erreurs)
            params.forEach((param, index) => {
                text = text.split('{' + index + '}').join(param);
            });
            // Convertir les \\n en vrais sauts de ligne pour les alertes
            text = text.replace(/\\\\n/g, '\\n');
            return text;
        }
        
        // Appliquer les traductions à tous les éléments marqués
        function applyTranslations() {
            // Mettre à jour le titre de la page
            document.title = '🎮 ' + t('web_title');
            
            // Traduire tous les éléments avec data-translate
            document.querySelectorAll('[data-translate]').forEach(el => {
                const key = el.getAttribute('data-translate');
                el.textContent = t(key);
            });
            
            // Traduire tous les attributs title avec data-translate-title
            document.querySelectorAll('[data-translate-title]').forEach(el => {
                const key = el.getAttribute('data-translate-title');
                el.title = t(key);
            });
            
            // Traduire tous les placeholders avec data-translate-placeholder
            document.querySelectorAll('[data-translate-placeholder]').forEach(el => {
                const key = el.getAttribute('data-translate-placeholder');
                el.placeholder = t(key);
            });
        }
        
        // ===== FONCTIONS UTILITAIRES =====
               
        // Fonction pour mettre à jour la liste des jeux (clear cache)
        async function updateGamesList() {
            if (!confirm(t('web_update_title') + '\\n\\nThis will clear the cache and reload all games data.\\nThis may take a few moments.')) {
                return;
            }
            
            try {
                // Afficher un message de chargement
                const container = document.querySelector('.content');
                const originalContent = container.innerHTML;
                container.innerHTML = '<div class="loading" style="padding: 100px; text-align: center;"><h2>🔄 ' + t('web_update_title') + '</h2><p>' + t('web_update_message') + '</p><p style="margin-top: 20px; font-size: 0.9em; color: #666;">' + t('web_update_wait') + '</p></div>';
                
                const response = await fetch('/api/update-cache');
                const data = await response.json();
                
                if (data.success) {
                    // Attendre 2 secondes pour que le serveur se recharge
                    await new Promise(resolve => setTimeout(resolve, 2000));
                    
                    // Recharger la page
                    location.reload();
                } else {
                    alert(t('web_error') + ': ' + (data.error || t('web_error_unknown')));
                    container.innerHTML = originalContent;
                }
            } catch (error) {
                alert(t('web_error_update', error.message));
                location.reload();
            }
        }
        
        // Détecter les blocages de progression et rafraîchir automatiquement
        function checkProgressTimeout() {
            const now = Date.now();
            const timeSinceLastUpdate = now - lastProgressUpdate;
            
            // Si pas de mise à jour depuis 30 secondes et qu'on est sur l'onglet téléchargements
            const downloadsTab = document.getElementById('downloads-content');
            if (downloadsTab && downloadsTab.style.display !== 'none') {
                if (timeSinceLastUpdate > 30000) {
                    console.warn('[AUTO-REFRESH] Aucune mise à jour depuis 30s, rafraîchissement...');
                    location.reload();
                }
            }
        }
        
        // Restaurer un état
        function restoreState(state) {
            if (state.tab) {
                showTab(state.tab, false);
                
                if (state.tab === 'platforms' && state.platform) {
                    loadGames(state.platform, false);
                }
            }
        }
        
        // Afficher un onglet
        function showTab(tab, updateHistory = true) {
            // Arrêter les intervalles existants
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            if (queueInterval) {
                clearInterval(queueInterval);
                queueInterval = null;
            }
            
            // Mettre à jour l'UI - tabs desktop
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            const tabButtons = Array.from(document.querySelectorAll('.tab'));
            const tabNames = ['platforms', 'downloads', 'queue', 'history', 'settings'];
            const tabIndex = tabNames.indexOf(tab);
            if (tabIndex >= 0 && tabButtons[tabIndex]) {
                tabButtons[tabIndex].classList.add('active');
            }
            
            // Mettre à jour l'UI - tabs mobile
            document.querySelectorAll('.mobile-tab').forEach(t => t.classList.remove('active'));
            const mobileTabButtons = Array.from(document.querySelectorAll('.mobile-tab'));
            if (tabIndex >= 0 && mobileTabButtons[tabIndex]) {
                mobileTabButtons[tabIndex].classList.add('active');
            }
            
            document.querySelectorAll('.content > div').forEach(c => c.style.display = 'none');
            document.getElementById(tab + '-content').style.display = 'block';
            
            // Mettre à jour l'URL et l'historique du navigateur
            if (updateHistory) {
                const url = tab === 'platforms' ? '/' : `/${tab}`;
                const state = { tab: tab };
                window.history.pushState(state, '', url);
            }
            
            if (tab === 'platforms') loadPlatforms();
            else if (tab === 'downloads') loadProgress();
            else if (tab === 'queue') {
                loadQueue();
                // Rafraîchir la queue toutes les 2 secondes
                queueInterval = setInterval(loadQueue, 2000);
            }
            else if (tab === 'history') loadHistory();
            else if (tab === 'settings') loadSettings();
        }
        
        // ===== EVENT LISTENERS =====
        
        // Vérifier toutes les 5 secondes pour auto-refresh
        setInterval(checkProgressTimeout, 5000);
        
        // Gérer le bouton retour du navigateur
        window.addEventListener('popstate', function(event) {
            if (event.state) {
                restoreState(event.state);
            }
        });
        
        // Restaurer l'état depuis l'URL au chargement
        window.addEventListener('DOMContentLoaded', function() {
            const path = window.location.pathname;
            
            if (path.startsWith('/platform/')) {
                const platformName = decodeURIComponent(path.split('/platform/')[1]);
                loadGames(platformName, false);
            } else if (path === '/downloads') {
                showTab('downloads', false);
            } else if (path === '/history') {
                showTab('history', false);
            } else if (path === '/settings') {
                showTab('settings', false);
            } else {
                // État initial - définir l'historique sans recharger
                window.history.replaceState({ tab: 'platforms' }, '', '/');
                loadPlatforms();
            }
        });
        
        // ===== FONCTIONS PRINCIPALES =====
        
        // Variables globales pour la recherche
        let searchTimeout = null;
        let currentSearchTerm = '';
        
        // Filtrer les plateformes avec recherche universelle
        async function filterPlatforms(searchTerm) {
            currentSearchTerm = searchTerm.trim();
            const term = currentSearchTerm.toLowerCase();
            
            // Afficher/masquer le bouton clear
            const clearBtn = document.getElementById('clear-platforms-search');
            if (clearBtn) {
                clearBtn.style.display = searchTerm ? 'block' : 'none';
            }
            
            // Si la recherche est vide, afficher toutes les plateformes normalement
            if (!term) {
                const cards = document.querySelectorAll('.platform-card');
                cards.forEach(card => card.style.display = '');
                // Masquer les résultats de recherche
                const searchResults = document.getElementById('search-results');
                if (searchResults) searchResults.style.display = 'none';
                const platformGrid = document.querySelector('.platform-grid');
                if (platformGrid) platformGrid.style.display = 'grid';
                return;
            }
            
            // Debounce pour éviter trop de requêtes
            if (searchTimeout) clearTimeout(searchTimeout);
            
            searchTimeout = setTimeout(async () => {
                try {
                    // Appeler l'API de recherche universelle
                    const response = await fetch('/api/search?q=' + encodeURIComponent(term));
                    const data = await response.json();
                    
                    if (!data.success) throw new Error(data.error);
                    
                    const results = data.results;
                    const platformsMatch = results.platforms || [];
                    const gamesMatch = results.games || [];
                    
                    // Masquer la grille normale des plateformes
                    const platformGrid = document.querySelector('.platform-grid');
                    if (platformGrid) platformGrid.style.display = 'none';
                    
                    // Créer ou mettre à jour la zone de résultats
                    let searchResults = document.getElementById('search-results');
                    if (!searchResults) {
                        searchResults = document.createElement('div');
                        searchResults.id = 'search-results';
                        searchResults.style.cssText = 'margin-top: 20px;';
                        const container = document.getElementById('platforms-content');
                        container.appendChild(searchResults);
                    }
                    searchResults.style.display = 'block';
                    
                    // Construire le HTML des résultats
                    let html = '<div style="padding: 20px; background: #f9f9f9; border-radius: 8px;">';
                    
                    // Résumé
                    const totalResults = platformsMatch.length + gamesMatch.length;
                    html += `<h3 style="margin-bottom: 15px;">🔍 ${totalResults} ${t('web_search_results')} "${term}"</h3>`;
                    
                    if (totalResults === 0) {
                        html += `<p style="color: #666;">${t('web_no_results')}</p>`;
                    }
                    
                    // Afficher les systèmes correspondants
                    if (platformsMatch.length > 0) {
                        html += `<h4 style="margin-top: 20px; margin-bottom: 10px;">🎮 ${t('web_platforms')} (${platformsMatch.length})</h4>`;
                        html += '<div class="platform-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px;">';
                        
                        platformsMatch.forEach(platform => {
                            const imageUrl = '/api/platform-image/' + encodeURIComponent(platform.platform_name);
                            html += `
                                <div class="platform-card" onclick="loadGames('${platform.platform_name.replace(/'/g, "\\'")}')">
                                    <img src="${imageUrl}" alt="${platform.platform_name}" onerror="this.src='/favicon.ico'">
                                    <h3>${platform.platform_name}</h3>
                                    <p>${platform.games_count} ${t('web_games')}</p>
                                </div>
                            `;
                        });
                        
                        html += '</div>';
                    }
                    
                    // Afficher les jeux correspondants (groupés par système)
                    if (gamesMatch.length > 0) {
                        html += `<h4 style="margin-top: 20px; margin-bottom: 10px;">🎯 ${t('web_games')} (${gamesMatch.length})</h4>`;
                        
                        // Grouper les jeux par plateforme
                        const gamesByPlatform = {};
                        gamesMatch.forEach(game => {
                            if (!gamesByPlatform[game.platform]) {
                                gamesByPlatform[game.platform] = [];
                            }
                            gamesByPlatform[game.platform].push(game);
                        });
                        
                        // Afficher chaque groupe
                        for (const [platformName, games] of Object.entries(gamesByPlatform)) {
                            html += `
                                <div style="margin-bottom: 15px; background: white; padding: 15px; border-radius: 5px; border: 1px solid #ddd;">
                                    <h5 style="margin: 0 0 10px 0; color: #007bff; cursor: pointer;" onclick="loadGames('${platformName.replace(/'/g, "\\'")}')">
                                        📁 ${platformName} (${games.length})
                                    </h5>
                                    <div style="display: flex; flex-direction: column; gap: 8px;">
                            `;
                            
                            games.forEach((game, idx) => {
                                const downloadTitle = t('web_download');
                                html += `
                                    <div class="search-game-item" style="padding: 15px; background: #f9f9f9; border-radius: 8px; transition: background 0.2s;">
                                        <div class="search-game-name" style="font-weight: 500; margin-bottom: 10px; word-wrap: break-word; overflow-wrap: break-word;">${game.game_name}</div>
                                        <div style="display: flex; justify-content: space-between; align-items: center;">
                                            ${game.size ? `<span style="background: #667eea; color: white; padding: 5px 10px; border-radius: 5px; font-size: 0.9em; white-space: nowrap;">${game.size}</span>` : '<span></span>'}
                                            <div class="download-btn-group" style="display: flex; gap: 4px;">
                                                <button class="download-btn" title="${downloadTitle} (now)" onclick="downloadGame('${platformName.replace(/'/g, "\\'")}', '${game.game_name.replace(/'/g, "\\'")}', null, 'now')" style="background: transparent; color: #28a745; border: none; padding: 8px; border-radius: 5px; cursor: pointer; font-size: 1.5em; min-width: 40px;">⬇️</button>
                                                <button class="download-btn" title="${downloadTitle} (queue)" onclick="downloadGame('${platformName.replace(/'/g, "\\'")}', '${game.game_name.replace(/'/g, "\\'")}', null, 'queue')" style="background: transparent; color: #28a745; border: none; padding: 8px; border-radius: 5px; cursor: pointer; font-size: 1.5em; min-width: 40px;">➕</button>
                                            </div>
                                        </div>
                                    </div>
                                `;
                            });
                            
                            html += `
                                    </div>
                                </div>
                            `;
                        }
                    }
                    
                    html += '</div>';
                    searchResults.innerHTML = html;
                    
                } catch (error) {
                    console.error('Erreur recherche:', error);
                    const searchResults = document.getElementById('search-results');
                    if (searchResults) {
                        searchResults.innerHTML = `<p style="color: red;">❌ ${t('web_error_search')}: ${error.message}</p>`;
                    }
                }
            }, 300); // Attendre 300ms après la dernière frappe
        }
        
        // Filtrer les jeux
        function filterGames(searchTerm) {
            const items = document.querySelectorAll('.game-item');
            const term = searchTerm.toLowerCase();
            let visibleCount = 0;
            
            items.forEach(item => {
                const name = item.querySelector('.game-name').textContent.toLowerCase();
                if (name.includes(term)) {
                    item.style.display = '';
                    visibleCount++;
                } else {
                    item.style.display = 'none';
                }
            });
            
            // Afficher/masquer le bouton clear
            const clearBtn = document.getElementById('clear-games-search');
            if (clearBtn) {
                clearBtn.style.display = searchTerm ? 'block' : 'none';
            }
            
            return visibleCount;
        }
        
        // Trier les jeux
        function sortGames(sortType) {
            currentGameSort = sortType;
            const items = Array.from(document.querySelectorAll('.game-item'));
            const gamesList = document.querySelector('.games-list');
            
            // Trier les éléments
            items.sort((a, b) => {
                const nameA = a.querySelector('.game-name').textContent.toLowerCase();
                const nameB = b.querySelector('.game-name').textContent.toLowerCase();
                const sizeElemA = a.querySelector('.game-size');
                const sizeElemB = b.querySelector('.game-size');
                
                // Extraire la taille en Mo (normalisée)
                const getSizeInMo = (sizeElem) => {
                    if (!sizeElem) return 0;
                    const text = sizeElem.textContent;
                    // Les tailles sont maintenant normalisées: "100 Mo" ou "2.5 Go"
                    const match = text.match(/([0-9.]+)\\s*(Mo|Go)/i);
                    if (!match) return 0;
                    let size = parseFloat(match[1]);
                    // Convertir Go en Mo pour comparaison
                    if (match[2].toUpperCase() === 'GO') {
                        size *= 1024;
                    }
                    return size;
                };
                
                switch(sortType) {
                    case 'name_asc':
                        return nameA.localeCompare(nameB);
                    case 'name_desc':
                        return nameB.localeCompare(nameA);
                    case 'size_asc':
                        return getSizeInMo(sizeElemA) - getSizeInMo(sizeElemB);
                    case 'size_desc':
                        return getSizeInMo(sizeElemB) - getSizeInMo(sizeElemA);
                    default:
                        return 0;
                }
            });
            
            // Réafficher les éléments dans l'ordre
            gamesList.innerHTML = '';
            items.forEach(item => {
                gamesList.appendChild(item);
            });
            
            // Mettre à jour les boutons de tri
            document.querySelectorAll('.sort-btn').forEach(btn => {
                btn.classList.remove('active');
            });
            document.querySelector(`[data-sort="${sortType}"]`)?.classList.add('active');
        }
        
        // Charger les plateformes
        async function loadPlatforms() {
            const container = document.getElementById('platforms-content');
            container.innerHTML = '<div class="loading">⏳ ' + t('web_loading_platforms') + '</div>';
            
            try {
                const response = await fetch('/api/platforms');
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                if (data.platforms.length === 0) {
                    container.innerHTML = '<p>' + t('web_no_platforms') + '</p>';
                    return;
                }
                
                // Construire le HTML avec les traductions
                let searchPlaceholder = t('web_search_platform');
                let html = `
                    <div class="search-box">
                        <input type="text" id="platform-search" placeholder="🔍 ${searchPlaceholder}" 
                               oninput="filterPlatforms(this.value)">
                        <button class="clear-search" id="clear-platforms-search" onclick="document.getElementById('platform-search').value=''; filterPlatforms('');">✕</button>
                        <span class="search-icon">🔍</span>
                    </div>
                    <div class="platform-grid">`;
                
                // Ajouter chaque plateforme
                data.platforms.forEach(p => {
                    let gameCountText = t('web_game_count', '📦', p.games_count || 0);
                    html += `
                        <div class="platform-card" onclick="loadGames('${p.platform_name.replace(/'/g, "\\\\'")}')">
                            <img src="/api/image/${encodeURIComponent(p.platform_name)}" 
                                 alt="${p.platform_name}"
                                 onerror="this.src='/api/image/default'">
                            <h3>${p.platform_name}</h3>
                            <div class="count">${gameCountText}</div>
                        </div>
                    `;
                });
                
                html += '</div>';
                container.innerHTML = html;
                
            } catch (error) {
                let errorMsg = t('web_error');
                container.innerHTML = `<p style="color:red;">${errorMsg}: ${error.message}</p>`;
            }
        }
        
        // Charger les jeux d'une plateforme
        async function loadGames(platform, updateHistory = true) {
            currentPlatform = platform;
            const container = document.getElementById('platforms-content');
            container.innerHTML = '<div class="loading">⏳ ' + t('web_loading_games') + '</div>';
            
            // Mettre à jour l'URL et l'historique
            if (updateHistory) {
                const url = `/platform/${encodeURIComponent(platform)}`;
                const state = { tab: 'platforms', platform: platform };
                window.history.pushState(state, '', url);
            }
            
            try {
                const response = await fetch('/api/games/' + encodeURIComponent(platform));
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                // Construire le HTML avec les traductions
                let backText = t('web_back_platforms');
                let gameCountText = t('web_game_count', '', data.count);
                let searchPlaceholder = t('web_search_game');
                let downloadTitle = t('web_download');
                let sortLabel = t('web_sort');
                let sortNameAsc = t('web_sort_name_asc');
                let sortNameDesc = t('web_sort_name_desc');
                let sortSizeAsc = t('web_sort_size_asc');
                let sortSizeDesc = t('web_sort_size_desc');
                
                let html = `
                    <button class="back-btn" onclick="goBackToPlatforms()">← ${backText}</button>
                    <h2>${platform} ${gameCountText}</h2>
                    <div class="search-box">
                        <input type="text" id="game-search" placeholder="🔍 ${searchPlaceholder}" 
                               oninput="filterGames(this.value)">
                        <button class="clear-search" id="clear-games-search" onclick="document.getElementById('game-search').value=''; filterGames('');">✕</button>
                        <span class="search-icon">🔍</span>
                    </div>
                    <div style="margin-top: 12px; margin-bottom: 12px; display: flex; gap: 8px; flex-wrap: wrap;">
                        <span style="font-weight: bold; align-self: center;">${sortLabel}:</span>
                        <button class="sort-btn active" data-sort="name_asc" onclick="sortGames('name_asc')" title="${sortNameAsc}">${sortNameAsc}</button>
                        <button class="sort-btn" data-sort="name_desc" onclick="sortGames('name_desc')" title="${sortNameDesc}">${sortNameDesc}</button>
                        <button class="sort-btn" data-sort="size_asc" onclick="sortGames('size_asc')" title="${sortSizeAsc}">${sortSizeAsc}</button>
                        <button class="sort-btn" data-sort="size_desc" onclick="sortGames('size_desc')" title="${sortSizeDesc}">${sortSizeDesc}</button>
                    </div>
                    <div class="games-list">`;
                
                // Ajouter chaque jeu
                data.games.forEach((g, idx) => {
                    html += `
                        <div class="game-item">
                            <span class="game-name">${g.name}</span>
                            ${g.size ? `<span class="game-size">${g.size}</span>` : ''}
                            <div class="download-btn-group" style="display: flex; gap: 4px;">
                                <button class="download-btn" title="${downloadTitle} (now)" onclick="downloadGame('${platform.replace(/'/g, "\\'")}', '${g.name.replace(/'/g, "\\'")}', ${idx}, 'now')">⬇️</button>
                                <button class="download-btn" title="${downloadTitle} (queue)" onclick="downloadGame('${platform.replace(/'/g, "\\'")}', '${g.name.replace(/'/g, "\\'")}', ${idx}, 'queue')" style="background: #e0e0e0; color: #333;">➕</button>
                            </div>
                        </div>
                    `;
                });
                
                html += `
                    </div>
                `;
                container.innerHTML = html;
                
                // Appliquer le tri par défaut (A-Z)
                sortGames(currentGameSort);
                
            } catch (error) {
                let backText = t('web_back');
                let errorMsg = t('web_error');
                container.innerHTML = `
                    <button class="back-btn" onclick="goBackToPlatforms()">← ${backText}</button>
                    <p style="color:red;">${errorMsg}: ${error.message}</p>
                `;
            }
        }
        
        // Retour aux plateformes avec historique
        function goBackToPlatforms() {
            window.history.pushState({ tab: 'platforms' }, '', '/');
            loadPlatforms();
        }
        
        // Télécharger un jeu
        async function downloadGame(platform, gameName, gameIndex) {
            const btn = event.target;
            btn.disabled = true;
            btn.textContent = '⏳';
            btn.title = t('web_download') + '...';
            const mode = arguments.length > 3 ? arguments[3] : 'now';
            try {
                // Préparer le body de la requête
                const requestBody = { platform: platform };
                if (typeof gameIndex === 'number' && gameIndex >= 0) {
                    requestBody.game_index = gameIndex;
                } else {
                    requestBody.game_name = gameName;
                }
                requestBody.mode = mode;
                const response = await fetch('/api/download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });
                const data = await response.json();
                if (data.success) {
                    btn.textContent = '✅';
                    btn.title = t('web_download') + ' ✓';
                    btn.style.color = '#28a745';
                    // Rediriger vers downloads SEULEMENT si mode='now' (téléchargement immédiat)
                    // Si mode='queue', rester sur la page actuelle
                    if (mode === 'now') {
                        setTimeout(() => { showTab('downloads'); }, 1000);
                    }
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                btn.textContent = '❌';
                btn.title = t('web_error');
                btn.style.color = '#dc3545';
                alert(t('web_error_download', error.message));
            } finally {
                setTimeout(() => {
                    btn.disabled = false;
                    btn.textContent = '⬇️';
                    btn.title = t('web_download');
                    btn.style.color = '';
                }, 3000);
            }
        }
        
        // Annuler un téléchargement
        async function cancelDownload(url, btn) {
            if (!confirm(t('web_confirm_cancel'))) {
                return;
            }
            
            btn.disabled = true;
            btn.textContent = '⏳';
            
            try {
                const response = await fetch('/api/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    btn.textContent = '✅';
                    btn.style.color = '#28a745';
                    
                    // Recharger la liste après un court délai
                    setTimeout(() => {
                        loadProgress();
                    }, 500);
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                btn.textContent = '❌';
                btn.style.color = '#dc3545';
                alert(t('web_error_download', error.message));
                btn.disabled = false;
            }
        }
        
        // Charger la progression
        async function loadProgress(autoRefresh = true) {
            const container = document.getElementById('downloads-content');
            
            // Arrêter l'ancien interval si existant
            if (progressInterval) {
                clearInterval(progressInterval);
                progressInterval = null;
            }
            
            try {
                const response = await fetch('/api/progress');
                const data = await response.json();
                
                // Mettre à jour le timestamp de dernière mise à jour
                lastProgressUpdate = Date.now();
                
                console.log('[DEBUG] /api/progress response:', data);
                console.log('[DEBUG] downloads keys:', Object.keys(data.downloads || {}));
                
                if (!data.success) throw new Error(data.error);
                
                const downloads = Object.entries(data.downloads);
                
                if (downloads.length === 0) {
                    container.innerHTML = '<p>' + t('web_no_downloads') + '</p>';
                    return;
                }
                
                container.innerHTML = downloads.map(([url, info]) => {
                    const percent = info.progress_percent || 0;
                    const downloaded = info.downloaded_size || 0;
                    const total = info.total_size || 0;
                    const status = info.status || 'En cours';
                    const speed = info.speed || 0;
                    
                    // Utiliser game_name si disponible, sinon extraire de l'URL
                    let fileName = info.game_name || 'Téléchargement';
                    if (!info.game_name) {
                        try {
                            fileName = decodeURIComponent(url.split('/').pop());
                        } catch (e) {
                            fileName = url.split('/').pop();
                        }
                    }
                    
                    // Afficher la plateforme si disponible
                    const platformInfo = info.platform ? ' (' + info.platform + ')' : '';
                    
                    return `
                        <div class="info-item">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <strong>📥 ${fileName}${platformInfo}</strong>
                                <button class="btn-action" onclick="cancelDownload('${url.replace(/'/g, "\\\\'")}', this)" title="${t('web_cancel')}">
                                    ❌
                                </button>
                            </div>
                            <div style="margin-top: 10px;">
                                <div style="background: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden;">
                                    <div style="background: ${percent >= 100 ? '#28a745' : '#667eea'}; height: 100%; width: ${Math.min(percent, 100)}%; transition: width 0.3s;"></div>
                                </div>
                                <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size: 0.9em;">
                                    <span>${status} - ${percent.toFixed(1)}%</span>
                                    <span>${speed > 0 ? speed.toFixed(2) + ' Mo/s' : ''}</span>
                                </div>
                                ${total > 0 ? `<div style="font-size: 0.85em; color: #666;">${(downloaded / 1024 / 1024).toFixed(1)} Mo / ${(total / 1024 / 1024).toFixed(1)} Mo</div>` : ''}
                                <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                    📅 Démarré: ${info.timestamp || 'N/A'}
                                </div>
                            </div>
                        </div>
                    `;
                }).join('');
                
                // Rafraîchir automatiquement toutes les 500ms pour progression fluide
                // Créer le setInterval seulement si autoRefresh est true ET qu'il n'existe pas déjà
                if (autoRefresh && downloads.length > 0 && !progressInterval) {
                    progressInterval = setInterval(async () => {
                        const downloadsTab = document.getElementById('downloads-content');
                        if (downloadsTab && downloadsTab.style.display !== 'none') {
                            // Rafraîchir juste les données sans recréer le setInterval
                            try {
                                const response = await fetch('/api/progress');
                                const data = await response.json();
                                
                                // Mettre à jour le timestamp
                                lastProgressUpdate = Date.now();
                                
                                if (!data.success) throw new Error(data.error);
                                
                                const downloads = Object.entries(data.downloads);
                                
                                if (downloads.length === 0) {
                                    container.innerHTML = '<p>' + t('web_no_downloads') + '</p>';
                                    clearInterval(progressInterval);
                                    progressInterval = null;
                                    return;
                                }
                                
                                container.innerHTML = downloads.map(([url, info]) => {
                                    const percent = info.progress_percent || 0;
                                    const downloaded = info.downloaded_size || 0;
                                    const total = info.total_size || 0;
                                    const status = info.status || 'En cours';
                                    const speed = info.speed || 0;
                                    
                                    let fileName = info.game_name || 'Téléchargement';
                                    if (!info.game_name) {
                                        try {
                                            fileName = decodeURIComponent(url.split('/').pop());
                                        } catch (e) {
                                            fileName = url.split('/').pop();
                                        }
                                    }
                                    
                                    const platformInfo = info.platform ? ' (' + info.platform + ')' : '';
                                    
                                    return `
                                        <div class="info-item">
                                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                                <strong>📥 ${fileName}${platformInfo}</strong>
                                                <button class="btn-action" onclick="cancelDownload('${url.replace(/'/g, "\\\\'")}', this)" title="${t('web_cancel')}">
                                                    ❌
                                                </button>
                                            </div>
                                            <div style="margin-top: 10px;">
                                                <div style="background: #e0e0e0; border-radius: 10px; height: 20px; overflow: hidden;">
                                                    <div style="background: ${percent >= 100 ? '#28a745' : '#667eea'}; height: 100%; width: ${Math.min(percent, 100)}%; transition: width 0.3s;"></div>
                                                </div>
                                                <div style="display: flex; justify-content: space-between; margin-top: 5px; font-size: 0.9em;">
                                                    <span>${status} - ${percent.toFixed(1)}%</span>
                                                    <span>${speed > 0 ? speed.toFixed(2) + ' Mo/s' : ''}</span>
                                                </div>
                                                ${total > 0 ? `<div style="font-size: 0.85em; color: #666;">${(downloaded / 1024 / 1024).toFixed(1)} Mo / ${(total / 1024 / 1024).toFixed(1)} Mo</div>` : ''}
                                                <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                                    📅 Démarré: ${info.timestamp || 'N/A'}
                                                </div>
                                            </div>
                                        </div>
                                    `;
                                }).join('');
                            } catch (error) {
                                console.error('[ERROR] Rafraîchissement progression:', error);
                            }
                        } else {
                            clearInterval(progressInterval);
                            progressInterval = null;
                        }
                    }, 500);
                }
            } catch (error) {
                container.innerHTML = `<p style="color:red;">Erreur: ${error.message}</p>`;
            }
        }
        
        // Charger la file d'attente
        async function loadQueue() {
            const container = document.getElementById('queue-content');
            
            try {
                const response = await fetch('/api/queue');
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                const queue = data.queue || [];
                const isActive = data.active || false;
                
                let html = '<div>';
                
                // Afficher l'état actif
                if (isActive) {
                    html += '<div style="background: #e8f5e9; border: 1px solid #4caf50; padding: 15px; border-radius: 5px; margin-bottom: 15px;">';
                    html += '<strong style="color: #2e7d32;">⏳ ' + t('web_queue_active_download') + '</strong>';
                    html += '</div>';
                } else {
                    html += '<div style="background: #f5f5f5; border: 1px solid #ccc; padding: 15px; border-radius: 5px; margin-bottom: 15px;">';
                    html += '<strong style="color: #666;">✓ ' + t('web_queue_no_active') + '</strong>';
                    html += '</div>';
                }
                
                // Afficher la queue
                if (queue.length === 0) {
                    html += '<p>' + t('web_queue_empty') + '</p>';
                } else {
                    html += '<h3>' + t('web_queue_title') + ' (' + queue.length + ')</h3>';
                    html += '<div>';
                    queue.forEach((item, idx) => {
                        const gameName = item.game_name || 'Unknown';
                        const platform = item.platform || 'N/A';
                        const status = item.status || 'queued';
                        html += `
                            <div class="info-item" style="display: flex; justify-content: space-between; align-items: center;">
                                <div style="flex: 1;">
                                    <strong>${idx + 1}. 📁 ${gameName}</strong>
                                    <div style="margin-top: 5px; font-size: 0.9em; color: #666;">
                                        Platform: ${platform} | Status: ${status}
                                    </div>
                                </div>
                                <button class="btn-action" onclick="removeFromQueue('${item.task_id.replace(/'/g, "\\\\'")}', this)" title="${t('web_remove')}">
                                    ❌
                                </button>
                            </div>
                        `;
                    });
                    html += '</div>';
                    
                    // Bouton pour vider la queue
                    html += '<button class="btn-action" onclick="clearQueue()" style="margin-top: 15px; background: #dc3545; color: white; padding: 10px 15px; border: none; border-radius: 5px; cursor: pointer;">';
                    html += t('web_queue_clear') + '</button>';
                }
                
                html += '</div>';
                container.innerHTML = html;
                
            } catch (error) {
                container.innerHTML = `<p style="color:red;">❌ ${t('web_error')}: ${error.message}</p>`;
            }
        }
        
        // Supprimer un élément de la queue
        async function removeFromQueue(taskId, btn) {
            if (!confirm(t('web_confirm_remove_queue'))) {
                return;
            }
            
            try {
                const response = await fetch('/api/queue/remove', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ task_id: taskId })
                });
                const data = await response.json();
                if (data.success) {
                    btn.style.color = '#28a745';
                    btn.textContent = '✅';
                    setTimeout(() => { loadQueue(); }, 500);
                } else {
                    alert(t('web_error') + ': ' + data.error);
                }
            } catch (error) {
                alert(t('web_error') + ': ' + error.message);
            }
        }
        
        // Vider la queue
        async function clearQueue() {
            if (!confirm(t('web_confirm_clear_queue'))) {
                return;
            }
            
            try {
                const response = await fetch('/api/queue/clear', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                const data = await response.json();
                if (data.success) {
                    alert(t('web_queue_cleared'));
                    loadQueue();
                } else {
                    alert(t('web_error') + ': ' + data.error);
                }
            } catch (error) {
                alert(t('web_error') + ': ' + error.message);
            }
        }
        
        // Charger l'historique
        async function loadHistory() {
            const container = document.getElementById('history-content');
            container.innerHTML = '<div class="loading">⏳ Chargement...</div>';
            
            try {
                const response = await fetch('/api/history');
                const data = await response.json();
                
                if (!data.success) throw new Error(data.error);
                
                if (data.history.length === 0) {
                    container.innerHTML = '<p>' + t('web_history_empty') + '</p>';
                    return;
                }
                
                // Pré-charger les traductions
                const platformLabel = t('web_history_platform');
                const sizeLabel = t('web_history_size');
                const statusCompleted = t('web_history_status_completed');
                const statusError = t('web_history_status_error');
                const statusCanceled = t('history_status_canceled');
                const statusAlreadyPresent = t('status_already_present');
                const statusQueued = t('download_queued');
                const statusDownloading = t('download_in_progress');
                
                container.innerHTML = data.history.map(h => {
                    const status = h.status || '';
                    const isError = status === 'Erreur' || status === 'error';
                    const isCanceled = status === 'Canceled';
                    const isAlreadyPresent = status === 'Already_Present';
                    const isQueued = status === 'queued';
                    const isDownloading = status === 'downloading' || status === 'Téléchargement' || status === 'Downloading' || 
                                         status === 'Connecting' || status === 'Extracting' || status.startsWith('Try ');
                    const isSuccess = status === 'Download_OK' || status === 'Completed';
                    
                    // Déterminer l'icône et la couleur
                    let statusIcon = '✅';  // par défaut succès
                    let statusColor = '#28a745';  // vert
                    let statusText = statusCompleted;
                    
                    if (isError) {
                        statusIcon = '❌';
                        statusColor = '#dc3545';  // rouge
                        statusText = statusError;
                    } else if (isCanceled) {
                        statusIcon = '⏸️';
                        statusColor = '#ffc107';  // orange
                        statusText = statusCanceled;
                    } else if (isAlreadyPresent) {
                        statusIcon = 'ℹ️';
                        statusColor = '#17a2b8';  // bleu clair
                        statusText = statusAlreadyPresent;
                    } else if (isQueued) {
                        statusIcon = '📋';
                        statusColor = '#6c757d';  // gris (en attente)
                        statusText = statusQueued;
                    } else if (isDownloading) {
                        statusIcon = '⬇️';
                        statusColor = '#007bff';  // bleu (en cours)
                        statusText = statusDownloading;
                    }
                    
                    const totalMo = h.total_size ? (h.total_size / 1024 / 1024).toFixed(1) : 'N/A';
                    const platform = h.platform || 'N/A';
                    const timestamp = h.timestamp || 'N/A';
                    
                    // Debug: log le timestamp pour vérifier
                    if (!h.timestamp) {
                        console.log('[DEBUG] Timestamp manquant pour:', h.game_name, 'Object:', h);
                    }
                    
                    return `
                        <div class="history-item ${isError ? 'error' : ''}">
                            <div style="display: flex; justify-content: space-between; align-items: start;">
                                <div style="flex: 1;">
                                    <strong>${statusIcon} ${h.game_name || 'Inconnu'}</strong>
                                    <div style="margin-top: 5px; font-size: 0.9em; color: #666;">
                                        📦 ${platformLabel}: ${platform}
                                    </div>
                                    <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                        💾 ${sizeLabel}: ${totalMo} Mo
                                    </div>
                                    <div style="margin-top: 3px; font-size: 0.85em; color: #666;">
                                        📅 Date: ${timestamp}
                                    </div>
                                </div>
                                <div style="text-align: right; min-width: 100px;">
                                    <span style="background: ${statusColor}; color: white; padding: 4px 10px; border-radius: 5px; font-size: 0.85em;">
                                        ${statusText}
                                    </span>
                                </div>
                            </div>
                            ${h.message ? `<div style="margin-top: 8px; padding-top: 8px; border-top: 1px solid #e0e0e0; font-size: 0.85em; color: #666;">${h.message}</div>` : ''}
                        </div>
                    `;
                }).join('') + `
                    <div style="margin-top: 30px; text-align: center;">
                        <button onclick="clearHistory()" style="background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); color: white; border: none; padding: 12px 30px; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer;">
                            🗑️ ${t('web_history_clear')}
                        </button>
                    </div>
                `;
            } catch (error) {
                container.innerHTML = `<p style="color:red;">${t('web_error')}: ${error.message}</p>`;
            }
        }
        
        // Vider l'historique
        async function clearHistory() {
            if (!confirm(t('web_history_clear') + '?\\n\\nThis action cannot be undone.')) {
                return;
            }
            
            try {
                const response = await fetch('/api/clear-history', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert('✅ ' + t('web_history_cleared'));
                    loadHistory(); // Recharger l\\'historique
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                alert('❌ ' + t('web_error_clear_history', error.message));
            }
        }
        
        // Charger les settings
        async function loadSettings() {
            const container = document.getElementById('settings-content');
            container.innerHTML = '<div class="loading">⏳ Chargement...</div>';
            
            try {
                // Charger les settings et les infos système en parallèle
                const [settingsResponse, systemInfoResponse] = await Promise.all([
                    fetch('/api/settings'),
                    fetch('/api/system_info')
                ]);
                
                const settingsData = await settingsResponse.json();
                const systemInfoData = await systemInfoResponse.json();
                
                if (!settingsData.success) throw new Error(settingsData.error);
                
                const settings = settingsData.settings;
                const info = settingsData.system_info;
                const systemInfo = systemInfoData.success ? systemInfoData.system_info : null;
                
                // Pré-charger les traductions
                const osLabel = t('web_settings_os');
                const platformsCountLabel = t('web_settings_platforms_count');
                const showUnsupportedLabel = t('web_settings_show_unsupported');
                const allowUnknownLabel = t('web_settings_allow_unknown');
                
                // Construire la section d'informations système détaillées
                let systemInfoHTML = '';
                if (systemInfo && (systemInfo.model || systemInfo.cpu_model)) {
                    systemInfoHTML = `
                        <h3 style="margin-top: 20px; margin-bottom: 15px;">🖥️ System Information</h3>
                        <div class="info-grid" style="margin-bottom: 20px; background: #f0f8ff; padding: 15px; border-radius: 8px; border: 2px solid #007bff;">
                            ${systemInfo.model ? `
                                <div class="info-item">
                                    <strong>💻 Model</strong>
                                    ${systemInfo.model}
                                </div>
                            ` : ''}
                            ${systemInfo.system ? `
                                <div class="info-item">
                                    <strong>🐧 System</strong>
                                    ${systemInfo.system}
                                </div>
                            ` : ''}
                            ${systemInfo.architecture ? `
                                <div class="info-item">
                                    <strong>⚙️ Architecture</strong>
                                    ${systemInfo.architecture}
                                </div>
                            ` : ''}
                            ${systemInfo.cpu_model ? `
                                <div class="info-item">
                                    <strong>🔧 CPU Model</strong>
                                    ${systemInfo.cpu_model}
                                </div>
                            ` : ''}
                            ${systemInfo.cpu_cores ? `
                                <div class="info-item">
                                    <strong>🧮 CPU Cores</strong>
                                    ${systemInfo.cpu_cores}
                                </div>
                            ` : ''}
                            ${systemInfo.cpu_max_frequency ? `
                                <div class="info-item">
                                    <strong>⚡ CPU Frequency</strong>
                                    ${systemInfo.cpu_max_frequency}
                                </div>
                            ` : ''}
                            ${systemInfo.cpu_features ? `
                                <div class="info-item">
                                    <strong>✨ CPU Features</strong>
                                    ${systemInfo.cpu_features}
                                </div>
                            ` : ''}
                            ${systemInfo.temperature ? `
                                <div class="info-item">
                                    <strong>🌡️ Temperature</strong>
                                    ${systemInfo.temperature}
                                </div>
                            ` : ''}
                            ${systemInfo.available_memory && systemInfo.total_memory ? `
                                <div class="info-item">
                                    <strong>💾 Memory</strong>
                                    ${systemInfo.available_memory} / ${systemInfo.total_memory}
                                </div>
                            ` : ''}
                            ${systemInfo.display_resolution ? `
                                <div class="info-item">
                                    <strong>🖥️ Display Resolution</strong>
                                    ${systemInfo.display_resolution}
                                </div>
                            ` : ''}
                            ${systemInfo.display_refresh_rate ? `
                                <div class="info-item">
                                    <strong>🔄 Refresh Rate</strong>
                                    ${systemInfo.display_refresh_rate}
                                </div>
                            ` : ''}
                            ${systemInfo.data_partition_format ? `
                                <div class="info-item">
                                    <strong>💽 Partition Format</strong>
                                    ${systemInfo.data_partition_format}
                                </div>
                            ` : ''}
                            ${systemInfo.data_partition_space ? `
                                <div class="info-item">
                                    <strong>💿 Available Space</strong>
                                    ${systemInfo.data_partition_space}
                                </div>
                            ` : ''}
                            ${systemInfo.network_ip ? `
                                <div class="info-item">
                                    <strong>🌐 Network IP</strong>
                                    ${systemInfo.network_ip}
                                </div>
                            ` : ''}
                            <div class="info-item">
                                <strong>🎮 ${platformsCountLabel}</strong>
                                ${info.platforms_count}
                            </div>
                        </div>
                    `;
                }
                
                container.innerHTML = `
                    <h2 data-translate="web_settings_title">ℹ️ ${t('web_settings_title')}</h2>
                    
                    ${systemInfoHTML}
                    
                    <h3 style="margin-top: 30px; margin-bottom: 15px;">RGSX Configuration ⚙️</h3>
                    
                    <div style="margin-bottom: 20px; background: #f0f8ff; padding: 15px; border-radius: 8px; border: 2px solid #007bff;">
                        <label style="display: block; font-weight: bold; margin-bottom: 10px; font-size: 1.1em;">📁 ${t('web_settings_roms_folder')}</label>
                        <div style="display: flex; gap: 10px; margin-bottom: 8px; flex-wrap: wrap;">
                            <input type="text" id="setting-roms-folder" value="${settings.roms_folder || ''}" 
                                   data-translate-placeholder="web_settings_roms_placeholder"
                                   placeholder="${t('web_settings_roms_placeholder')}"
                                   style="flex: 1; min-width: 200px; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px;">
                            <button onclick="browseRomsFolder()" 
                                    style="background: linear-gradient(135deg, #007bff 0%, #0056b3 100%); color: white; border: none; padding: 10px 20px; border-radius: 5px; font-weight: bold; cursor: pointer; white-space: nowrap; flex-shrink: 0;">
                                📂 ${t('web_settings_browse')}
                            </button>
                        </div>
                        <small style="color: #666; display: block;">
                            Current: <strong>${info.roms_folder}</strong> ${settings.roms_folder ? '(custom)' : '(default)'}
                        </small>
                    </div>
                    
                
                    
                    <div style="background: #f9f9f9; padding: 20px; border-radius: 8px;">
                        <div style="margin-bottom: 20px;">
                            <label style="display: block; font-weight: bold; margin-bottom: 5px;">🌍 ${t('web_settings_language')}</label>
                            <select id="setting-language" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px;">
                                <option value="en" ${settings.language === 'en' ? 'selected' : ''}>English</option>
                                <option value="fr" ${settings.language === 'fr' ? 'selected' : ''}>Français</option>
                                <option value="es" ${settings.language === 'es' ? 'selected' : ''}>Español</option>
                                <option value="de" ${settings.language === 'de' ? 'selected' : ''}>Deutsch</option>
                                <option value="it" ${settings.language === 'it' ? 'selected' : ''}>Italiano</option>
                                <option value="pt" ${settings.language === 'pt' ? 'selected' : ''}>Português</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: flex; align-items: center; cursor: pointer;">
                                <input type="checkbox" id="setting-music" ${settings.music_enabled ? 'checked' : ''} 
                                       style="width: 20px; height: 20px; margin-right: 10px;">
                                <span style="font-weight: bold;">🎵 ${t('web_settings_music')}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: block; font-weight: bold; margin-bottom: 5px;">🔤 ${t('web_settings_font_scale')} (${settings.accessibility?.font_scale || 1.0})</label>
                            <input type="range" id="setting-font-scale" min="0.5" max="2.0" step="0.1" 
                                   value="${settings.accessibility?.font_scale || 1.0}"
                                   style="width: 100%;">
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: block; font-weight: bold; margin-bottom: 5px;">📐 ${t('web_settings_grid')}</label>
                            <select id="setting-grid" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px;">
                                <option value="3x3" ${settings.display?.grid === '3x3' ? 'selected' : ''}>3x3</option>
                                <option value="3x4" ${settings.display?.grid === '3x4' ? 'selected' : ''}>3x4</option>
                                <option value="4x3" ${settings.display?.grid === '4x3' ? 'selected' : ''}>4x3</option>
                                <option value="4x4" ${settings.display?.grid === '4x4' ? 'selected' : ''}>4x4</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: block; font-weight: bold; margin-bottom: 5px;">🖋️ ${t('web_settings_font_family')}</label>
                            <select id="setting-font-family" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px;">
                                <option value="pixel" ${settings.display?.font_family === 'pixel' ? 'selected' : ''}>Pixel</option>
                                <option value="dejavu" ${settings.display?.font_family === 'dejavu' ? 'selected' : ''}>DejaVu</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: flex; align-items: center; cursor: pointer;">
                                <input type="checkbox" id="setting-symlink" ${settings.symlink?.enabled ? 'checked' : ''} 
                                       style="width: 20px; height: 20px; margin-right: 10px;">
                                <span style="font-weight: bold;">🔗 ${t('web_settings_symlink')}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: block; font-weight: bold; margin-bottom: 5px;">📦 ${t('web_settings_source_mode')}</label>
                            <select id="setting-sources-mode" style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px;">
                                <option value="rgsx" ${settings.sources?.mode === 'rgsx' ? 'selected' : ''}>RGSX (default)</option>
                                <option value="custom" ${settings.sources?.mode === 'custom' ? 'selected' : ''}>Custom</option>
                            </select>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: block; font-weight: bold; margin-bottom: 5px;">🔗 ${t('web_settings_custom_url')}</label>
                            <input type="text" id="setting-custom-url" value="${settings.sources?.custom_url || ''}" 
                                   data-translate-placeholder="web_settings_custom_url_placeholder"
                                   placeholder="${t('web_settings_custom_url_placeholder')}"
                                   style="width: 100%; padding: 10px; border: 2px solid #ddd; border-radius: 5px; font-size: 16px;">
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: flex; align-items: center; cursor: pointer;">
                                <input type="checkbox" id="setting-show-unsupported" ${settings.show_unsupported_platforms ? 'checked' : ''} 
                                       style="width: 20px; height: 20px; margin-right: 10px;">
                                <span style="font-weight: bold;">👀 ${showUnsupportedLabel}</span>
                            </label>
                        </div>
                        
                        <div style="margin-bottom: 20px;">
                            <label style="display: flex; align-items: center; cursor: pointer;">
                                <input type="checkbox" id="setting-allow-unknown" ${settings.allow_unknown_extensions ? 'checked' : ''} 
                                       style="width: 20px; height: 20px; margin-right: 10px;">
                                <span style="font-weight: bold;">⚠️ ${allowUnknownLabel}</span>
                            </label>
                        </div>
                        
                        <button onclick="saveSettings()" style="width: 100%; background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; border: none; padding: 15px; border-radius: 8px; font-size: 18px; font-weight: bold; cursor: pointer; margin-top: 10px;">
                            💾 ${t('web_settings_save')}
                        </button>
                    </div>
                `;
                
                // Mettre à jour l'affichage de la valeur du font scale en temps réel
                document.getElementById('setting-font-scale').addEventListener('input', function(e) {
                    const label = e.target.previousElementSibling;
                    label.textContent = `🔤 ${t('web_settings_font_scale')} (${e.target.value})`;
                });
                
            } catch (error) {
                container.innerHTML = `<p style="color:red;">${t('web_error')}: ${error.message}</p>`;
            }
        }
        
        // Sauvegarder les settings
        async function saveSettings() {
            try {
                const settings = {
                    language: document.getElementById('setting-language').value,
                    music_enabled: document.getElementById('setting-music').checked,
                    accessibility: {
                        font_scale: parseFloat(document.getElementById('setting-font-scale').value)
                    },
                    display: {
                        grid: document.getElementById('setting-grid').value,
                        font_family: document.getElementById('setting-font-family').value
                    },
                    symlink: {
                        enabled: document.getElementById('setting-symlink').checked
                    },
                    sources: {
                        mode: document.getElementById('setting-sources-mode').value,
                        custom_url: document.getElementById('setting-custom-url').value
                    },
                    show_unsupported_platforms: document.getElementById('setting-show-unsupported').checked,
                    allow_unknown_extensions: document.getElementById('setting-allow-unknown').checked,
                    roms_folder: document.getElementById('setting-roms-folder').value.trim()
                };
                
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings: settings })
                });
                
                const data = await response.json();
                
                if (data.success) {
                    // Afficher le dialogue de confirmation de redémarrage
                    showRestartDialog();
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                alert('❌ ' + t('web_error_save_settings', error.message));
            }
        }
        
        // Afficher le dialogue de confirmation de redémarrage
        function showRestartDialog() {
            // Créer le dialogue modal
            const modal = document.createElement('div');
            modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; z-index: 10000;';
            
            const dialog = document.createElement('div');
            dialog.style.cssText = 'background: white; padding: 30px; border-radius: 10px; max-width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,0.3);';
            
            const title = document.createElement('h2');
            title.textContent = t('web_restart_confirm_title');
            title.style.cssText = 'margin: 0 0 20px 0; color: #333;';
            
            const message = document.createElement('p');
            message.textContent = t('web_restart_confirm_message');
            message.style.cssText = 'margin: 0 0 30px 0; color: #666; line-height: 1.5;';
            
            const buttonContainer = document.createElement('div');
            buttonContainer.style.cssText = 'display: flex; gap: 10px; justify-content: flex-end;';
            
            const btnNo = document.createElement('button');
            btnNo.textContent = t('web_restart_no');
            btnNo.style.cssText = 'padding: 10px 20px; background: #6c757d; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px;';
            btnNo.onclick = () => {
                modal.remove();
                alert('✅ ' + t('web_settings_saved'));
            };
            
            const btnYes = document.createElement('button');
            btnYes.textContent = t('web_restart_yes');
            btnYes.style.cssText = 'padding: 10px 20px; background: #667eea; color: white; border: none; border-radius: 5px; cursor: pointer; font-size: 14px;';
            btnYes.onclick = async () => {
                modal.remove();
                await restartApplication();
            };
            
            buttonContainer.appendChild(btnNo);
            buttonContainer.appendChild(btnYes);
            
            dialog.appendChild(title);
            dialog.appendChild(message);
            dialog.appendChild(buttonContainer);
            modal.appendChild(dialog);
            document.body.appendChild(modal);
        }
        
        // Redémarrer l'application
        async function restartApplication() {
            try {
                const response = await fetch('/api/restart', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                const data = await response.json();
                
                if (data.success) {
                    alert('✅ ' + t('web_restart_success'));
                } else {
                    throw new Error(data.error || t('web_error_unknown'));
                }
            } catch (error) {
                alert('❌ ' + t('web_restart_error', error.message));
            }
        }
        
        // Générer un fichier ZIP de support
        async function generateSupportZip() {
            try {
                // Afficher un message de chargement
                const loadingMsg = t('web_support_generating');
                const originalButton = event ? event.target : null;
                if (originalButton) {
                    originalButton.disabled = true;
                    originalButton.innerHTML = '⏳ ' + loadingMsg;
                }
                
                // Appeler l'API pour générer le ZIP
                const response = await fetch('/api/support', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });
                
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.error || t('web_error_unknown'));
                }
                
                // Télécharger le fichier
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                
                // Extraire le nom du fichier depuis les headers
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = 'rgsx_support.zip';
                if (contentDisposition) {
                    const matches = /filename="?([^"]+)"?/.exec(contentDisposition);
                    if (matches && matches[1]) {
                        filename = matches[1];
                    }
                }
                
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(url);
                document.body.removeChild(a);
                
                // Afficher le message d'instructions
                alert(t('web_support_title') + '\\n\\n' + t('web_support_message'));
                
                // Restaurer le bouton
                if (originalButton) {
                    originalButton.disabled = false;
                    originalButton.innerHTML = '🆘 ' + t('web_support');
                }
                
            } catch (error) {
                console.error('Erreur génération support:', error);
                alert('❌ ' + t('web_support_error', error.message));
                
                // Restaurer le bouton en cas d'erreur
                const originalButton = event ? event.target : null;
                if (originalButton) {
                    originalButton.disabled = false;
                    originalButton.innerHTML = '🆘 ' + t('web_support');
                }
            }
        }
        
        // Navigateur de répertoires pour ROMs folder
        let currentBrowsePath = '';
        let browseInitialized = false;
        
        async function browseRomsFolder() {
            try {
                // Récupérer le chemin actuel de l'input SEULEMENT au premier appel
                if (!browseInitialized) {
                    const inputValue = document.getElementById('setting-roms-folder').value.trim();
                    if (inputValue) {
                        currentBrowsePath = inputValue;
                    }
                    browseInitialized = true;
                }
                
                const response = await fetch(`/api/browse-directories?path=${encodeURIComponent(currentBrowsePath)}`);
                const data = await response.json();
                
                if (!data.success) {
                    throw new Error(data.error || 'Erreur lors du listage des répertoires');
                }
                
                // Créer une modal pour afficher les répertoires
                const modal = document.createElement('div');
                modal.style.cssText = 'position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 9999; display: flex; align-items: center; justify-content: center; padding: 20px;';
                
                const content = document.createElement('div');
                content.style.cssText = 'background: white; border-radius: 10px; padding: 20px; max-width: 600px; width: 100%; max-height: 80vh; overflow-y: auto;';
                
                // Titre avec chemin actuel
                const title = document.createElement('h2');
                title.textContent = '📂 ' + t('web_browse_title');
                title.style.marginBottom = '10px';
                content.appendChild(title);
                
                const pathDisplay = document.createElement('div');
                pathDisplay.style.cssText = 'background: #f0f0f0; padding: 10px; border-radius: 5px; margin-bottom: 15px; word-break: break-all; font-family: monospace; font-size: 14px;';
                pathDisplay.textContent = data.current_path || t('web_browse_select_drive');
                content.appendChild(pathDisplay);
                
                // Boutons d'action
                const buttonContainer = document.createElement('div');
                buttonContainer.style.cssText = 'display: flex; gap: 10px; justify-content: flex-end;';
                
                // Bouton parent - afficher si parent_path n'est pas null (même si c'est une chaîne vide pour revenir aux lecteurs)
                if (data.parent_path !== null && data.parent_path !== undefined) {
                    const parentBtn = document.createElement('button');
                    parentBtn.textContent = data.parent_path === '' ? '💾 ' + t('web_browse_drives') : '⬆️ ' + t('web_browse_parent');
                    parentBtn.style.cssText = 'flex: 1; padding: 10px; background: #6c757d; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;';
                    parentBtn.onclick = () => {
                        currentBrowsePath = data.parent_path;
                        modal.remove();
                        browseRomsFolder();
                    };
                    buttonContainer.appendChild(parentBtn);
                }
                
                // Bouton sélectionner ce dossier
                if (data.current_path) {
                    const selectBtn = document.createElement('button');
                    selectBtn.textContent = '✅ ' + t('web_browse_select');
                    selectBtn.style.cssText = 'flex: 2; padding: 10px; background: #28a745; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;';
                    selectBtn.onclick = () => {
                        document.getElementById('setting-roms-folder').value = data.current_path;
                        currentBrowsePath = '';
                        browseInitialized = false;
                        modal.remove();
                        
                        // Afficher une alerte informant qu'il faut redémarrer
                        alert('⚠️ ' + t('web_browse_alert_restart', data.current_path));
                    };
                    buttonContainer.appendChild(selectBtn);
                }
                
                // Bouton annuler
                const cancelBtn = document.createElement('button');
                cancelBtn.textContent = '❌ ' + t('web_browse_cancel');
                cancelBtn.style.cssText = 'flex: 1; padding: 10px; background: #dc3545; color: white; border: none; border-radius: 5px; cursor: pointer; font-weight: bold;';
                cancelBtn.onclick = () => {
                    currentBrowsePath = '';
                    browseInitialized = false;
                    modal.remove();
                };
                buttonContainer.appendChild(cancelBtn);
                
                content.appendChild(buttonContainer);
                
                // Liste des répertoires
                const dirList = document.createElement('div');
                dirList.style.cssText = 'max-height: 400px; overflow-y: auto; border: 2px solid #ddd; border-radius: 5px;';
                
                if (data.directories.length === 0) {
                    const emptyMsg = document.createElement('div');
                    emptyMsg.style.cssText = 'padding: 20px; text-align: center; color: #666;';
                    emptyMsg.textContent = t('web_browse_empty');
                    dirList.appendChild(emptyMsg);
                } else {
                    data.directories.forEach(dir => {
                        const dirItem = document.createElement('div');
                        dirItem.style.cssText = 'padding: 12px; border-bottom: 1px solid #eee; cursor: pointer; display: flex; align-items: center; gap: 10px; transition: background 0.2s;';
                        dirItem.onmouseover = () => dirItem.style.background = '#f0f0f0';
                        dirItem.onmouseout = () => dirItem.style.background = 'white';
                        
                        const icon = document.createElement('span');
                        icon.textContent = dir.is_drive ? '💾' : '📁';
                        icon.style.fontSize = '20px';
                        
                        const name = document.createElement('span');
                        name.textContent = dir.name;
                        name.style.flex = '1';
                        
                        dirItem.appendChild(icon);
                        dirItem.appendChild(name);
                        
                        dirItem.onclick = () => {
                            currentBrowsePath = dir.path;
                            modal.remove();
                            browseRomsFolder();
                        };
                        
                        dirList.appendChild(dirItem);
                    });
                }
                
                content.appendChild(dirList);
                modal.appendChild(content);
                document.body.appendChild(modal);
                
                // Fermer avec clic en dehors
                modal.onclick = (e) => {
                    if (e.target === modal) {
                        currentBrowsePath = '';
                        browseInitialized = false;
                        modal.remove();
                    }
                };
                
            } catch (error) {
                alert('❌ ' + t('web_error_browse', error.message));
            }
        }
        
        // Initialisation au démarrage
        async function init() {
            await loadTranslations();  // Charger les traductions
            applyTranslations();         // Appliquer les traductions à l'interface
            loadPlatforms();            // Charger les plateformes
        }
        
        // Lancer l'initialisation
        init();
    </script>
</body>
</html>
        '''.replace('{version}', config.app_version)


def run_server(host='0.0.0.0', port=5000):
    """Démarre le serveur HTTP"""
    server_address = (host, port)
    
    # Créer une classe HTTPServer personnalisée qui réutilise le port
    class ReuseAddrHTTPServer(HTTPServer):
        allow_reuse_address = True
    
    # Tuer les processus existants utilisant le port
    try:
        import subprocess
        result = subprocess.run(['lsof', '-ti', f':{port}'], capture_output=True, text=True, timeout=2)
        pids = result.stdout.strip().split('\n')
        for pid in pids:
            if pid:
                try:
                    subprocess.run(['kill', '-9', pid], timeout=2)
                    logger.info(f"Processus {pid} tué (port {port} libéré)")
                except Exception as e:
                    logger.warning(f"Impossible de tuer le processus {pid}: {e}")
    except Exception as e:
        logger.warning(f"Impossible de libérer le port {port}: {e}")
    
    # Attendre un peu pour que le port se libère
    time.sleep(1)
    
    httpd = ReuseAddrHTTPServer(server_address, RGSXHandler)
    
    logger.info("=" * 60)
    logger.info("RGSX Web Server démarré !")
    logger.info("=" * 60)
    logger.info(f"Accès local: http://localhost:{port}")
    
    # Force flush
    for handler in logging.root.handlers:
        handler.flush()
    
    # Afficher l'IP locale pour accès réseau (éviter les cartes virtuelles)
    try:
        # Méthode 1: Créer une connexion UDP pour trouver l'IP réelle (sans envoyer de données)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        logger.info(f"Accès réseau: http://{local_ip}:{port}")
    except Exception as e:
        # Fallback: méthode classique
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            logger.info(f"🌍 Accès réseau: http://{local_ip}:{port}")
        except:
            logger.warning("⚠️ Impossible de déterminer l'IP locale")
    
    logger.info("=" * 60)
    logger.info("Appuyez sur Ctrl+C pour arrêter le serveur")
    logger.info("=" * 60)
    
    # Force flush final avant de commencer à servir
    for handler in logging.root.handlers:
        handler.flush()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("\n🛑 Arrêt du serveur...")
        for handler in logging.root.handlers:
            handler.flush()
        httpd.shutdown()
        logger.info("✅ Serveur arrêté proprement")
        for handler in logging.root.handlers:
            handler.flush()


if __name__ == '__main__':
    print("="*60, flush=True)
    print("Demarrage du serveur RGSX Web...", flush=True)
    print(f"Fichier de log prévu: {config.log_file_web}", flush=True)
    print("="*60, flush=True)
    
    parser = argparse.ArgumentParser(description='RGSX Web Server')
    parser.add_argument('--host', default='0.0.0.0', help='Adresse IP (défaut: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=5000, help='Port (défaut: 5000)')
    
    args = parser.parse_args()
    
    print(f"Lancement sur {args.host}:{args.port}...", flush=True)
    run_server(host=args.host, port=args.port)

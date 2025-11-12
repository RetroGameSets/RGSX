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
import copy
import hashlib
import mimetypes
from datetime import datetime, timezone
from email.utils import formatdate, parsedate_to_datetime
import config
from history import load_history, save_history
from utils import load_sources, load_games, extract_data
from network import download_rom, download_from_1fichier
from pathlib import Path
from rgsx_settings import get_language

try:
    from watchdog.observers import Observer  # type: ignore
    from watchdog.events import FileSystemEventHandler  # type: ignore
    WATCHDOG_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    WATCHDOG_AVAILABLE = False

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

# Cache configuration
CACHE_TTL_SECONDS = 60  # seconds

cache_lock = threading.RLock()

source_cache = {
    'data': None,
    'timestamp': 0.0,
    'etag': None,
    'last_modified': None,
}

games_cache = {}

watchdog_observer = None
watchdog_started = False


def _now_utc() -> datetime:
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _httpdate(dt: datetime | None) -> str | None:
    """Convert datetime to an HTTP-date string."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return formatdate(dt.timestamp(), usegmt=True)


def generate_etag(payload: object) -> str:
    """Generate a stable ETag for JSON-serialisable payloads."""
    try:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'), default=str)
    except TypeError:
        serialized = repr(payload)
    return hashlib.md5(serialized.encode('utf-8')).hexdigest()


def _ensure_datetime(value: datetime | str | None) -> datetime | None:
    """Return a timezone-aware datetime from mixed input."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def invalidate_all_caches(reason: str | None = None) -> None:
    """Drop all cached datasets."""
    with cache_lock:
        source_cache.update({'data': None, 'timestamp': 0.0, 'etag': None, 'last_modified': None})
        games_cache.clear()
    if reason and 'logger' in globals():
        logger.debug(f"Caches invalidated ({reason})")


def invalidate_games_cache(platform: str | None = None, reason: str | None = None) -> None:
    """Invalidate either a specific platform cache or all game caches."""
    with cache_lock:
        if platform is None:
            games_cache.clear()
        else:
            games_cache.pop(platform, None)
    if reason and 'logger' in globals():
        logger.debug(f"Games cache invalidated for {platform or 'ALL'} ({reason})")


def get_cached_sources() -> tuple[list[dict], str, datetime]:
    """Return cached platforms data with ETag and last modified timestamp."""
    now = time.time()
    with cache_lock:
        entry_data = source_cache['data']
        if entry_data is not None and now - source_cache['timestamp'] <= CACHE_TTL_SECONDS:
            return copy.deepcopy(entry_data), source_cache['etag'], source_cache['last_modified']

    platforms = load_sources()
    last_modified = _now_utc()
    etag = generate_etag(platforms)

    with cache_lock:
        source_cache.update({
            'data': copy.deepcopy(platforms),
            'timestamp': now,
            'etag': etag,
            'last_modified': last_modified,
        })

    return copy.deepcopy(platforms), etag, last_modified


def get_cached_games(platform: str) -> tuple[list[tuple], str, datetime]:
    """Return cached games list for platform with metadata."""
    now = time.time()
    with cache_lock:
        entry = games_cache.get(platform)
        if entry and now - entry['timestamp'] <= CACHE_TTL_SECONDS:
            return copy.deepcopy(entry['data']), entry['etag'], entry['last_modified']

    games = load_games(platform)
    last_modified = _now_utc()
    etag = generate_etag(games)

    with cache_lock:
        games_cache[platform] = {
            'data': copy.deepcopy(games),
            'timestamp': now,
            'etag': etag,
            'last_modified': last_modified,
        }

    return copy.deepcopy(games), etag, last_modified


if WATCHDOG_AVAILABLE:

    class _CacheInvalidationHandler(FileSystemEventHandler):
        """Watchdog handler to invalidate caches when files change."""

        def on_any_event(self, event):  # type: ignore[override]
            if event.is_directory:
                return
            invalidate_all_caches(reason=f"filesystem event: {getattr(event, 'src_path', '')}")

else:

    class _CacheInvalidationHandler:  # pragma: no cover - fallback stub
        def __init__(self, *_, **__):
            pass


def start_cache_invalidation_watchdog() -> None:
    """Start filesystem watcher to keep caches in sync."""
    global watchdog_observer, watchdog_started

    if watchdog_started:
        return
    if not WATCHDOG_AVAILABLE:
        logger.info("watchdog package not available; relying on TTL cache invalidation")
        return

    observer = Observer()
    watched_paths = {
        os.path.dirname(config.SOURCES_FILE),
        config.GAMES_FOLDER,
        config.ROMS_FOLDER,
    }

    handler = _CacheInvalidationHandler()

    scheduled = False

    for path in watched_paths:
        if path and os.path.isdir(path):
            observer.schedule(handler, path=path, recursive=True)
            scheduled = True

    if scheduled:
        observer.daemon = True
        observer.start()
        watchdog_observer = observer
        watchdog_started = True
        logger.info("Cache invalidation watchdog started")
    else:
        logger.debug("No valid paths for cache watchdog; skipping watcher startup")

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
    initial_sources = load_sources()  # Initialise config.games_count
    logger.info(f"{len(getattr(config, 'platforms', []))} plateformes chargées")
    
    # Initialiser filter_platforms_selection depuis les settings (pour filtrer les plateformes)
    from rgsx_settings import load_rgsx_settings
    settings = load_rgsx_settings()
    hidden = set(settings.get("hidden_platforms", [])) if isinstance(settings, dict) else set()
    
    if initial_sources is not None:
        with cache_lock:
            source_cache.update({
                'data': copy.deepcopy(initial_sources),
                'timestamp': time.time(),
                'etag': generate_etag(initial_sources),
                'last_modified': _now_utc(),
            })

    if not hasattr(config, 'filter_platforms_selection') or not config.filter_platforms_selection:
        all_platform_names = []
        for platform_entry in getattr(config, 'platforms', []):
            if isinstance(platform_entry, str):
                name = platform_entry
            elif isinstance(platform_entry, dict):
                name = platform_entry.get("platform_name", "")
            else:
                name = str(platform_entry)
            name = name.strip()
            if name:
                all_platform_names.append(name)
        all_platform_names = sorted(set(all_platform_names))
        config.filter_platforms_selection = [(name, name in hidden) for name in all_platform_names]
        logger.info(f"Filter platforms initialisé: {len(hidden)} plateformes cachées sur {len(all_platform_names)}")
    
    # Force flush
    for handler in logging.root.handlers:
        handler.flush()
except Exception as e:
    logger.error(f"Erreur lors du chargement initial: {e}")
    # Force flush
    for handler in logging.root.handlers:
        handler.flush()

# Lancer le watcher de cache si disponible
try:
    start_cache_invalidation_watchdog()
except Exception as watcher_error:  # pragma: no cover - watcher errors shouldn't crash server
    logger.warning(f"Cache watchdog startup failed: {watcher_error}")
    watchdog_started = False


class RGSXHandler(BaseHTTPRequestHandler):
    """Handler HTTP pour les requêtes RGSX"""
    
    def log_message(self, format, *args):
        """Override pour logger proprement (désactivé pour réduire verbosité)"""
        pass  # Logs désactivés pour éviter la pollution des logs
    
    def _set_headers(self, content_type='application/json', status=200, etag=None, last_modified=None, extra_headers=None):
        """Définit les headers de réponse"""
        self.send_response(status)
        self.send_header('Content-type', content_type)
        self.send_header('Access-Control-Allow-Origin', '*')  # CORS pour dev
        if etag:
            self.send_header('ETag', etag)
        if last_modified:
            http_date = _httpdate(_ensure_datetime(last_modified)) if not isinstance(last_modified, str) else last_modified
            if http_date:
                self.send_header('Last-Modified', http_date)
        if extra_headers:
            for header, value in extra_headers.items():
                self.send_header(header, value)
        self.end_headers()
    
    def _send_json(self, data, status=200, etag=None, last_modified=None):
        """Envoie une réponse JSON"""
        cached_dt = _ensure_datetime(last_modified)
        client_etag = self.headers.get('If-None-Match') if etag else None
        client_ims = self.headers.get('If-Modified-Since') if cached_dt else None

        if etag and client_etag == etag:
            self._set_headers('application/json', status=304, etag=etag, last_modified=cached_dt)
            return

        if cached_dt and client_ims:
            try:
                client_dt = parsedate_to_datetime(client_ims)
                if client_dt.tzinfo is None:
                    client_dt = client_dt.replace(tzinfo=timezone.utc)
                if client_dt >= cached_dt:
                    self._set_headers('application/json', status=304, etag=etag, last_modified=cached_dt)
                    return
            except (TypeError, ValueError):
                pass

        self._set_headers('application/json', status, etag=etag, last_modified=cached_dt)
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    
    def _send_html(self, html, status=200, etag=None, last_modified=None):
        """Envoie une réponse HTML"""
        self._set_headers('text/html; charset=utf-8', status, etag=etag, last_modified=last_modified)
        self.wfile.write(html.encode('utf-8'))

    def _send_not_found(self):
        """Répond avec un 404 générique."""
        self._set_headers('text/plain; charset=utf-8', status=404)
        self.wfile.write(b'Not found')

    def _asset_version(self, relative_path: str) -> str:
        """Retourne un identifiant de version basé sur la date de modification du fichier statique."""
        static_root = Path(__file__).resolve().parent / 'static'
        asset_path = static_root / relative_path
        try:
            return str(int(asset_path.stat().st_mtime))
        except OSError:
            return str(int(time.time()))

    def _serve_static_file(self, path: str) -> None:
        """Servez un fichier statique avec gestion du cache HTTP."""
        if not path.startswith('/static/'):
            self._send_not_found()
            return

        relative_path = path[len('/static/'):]
        safe_relative = os.path.normpath(relative_path).replace('\\', '/')

        if safe_relative.startswith('../') or safe_relative.startswith('..') or safe_relative.startswith('/'):
            self._send_not_found()
            return

        static_root = Path(__file__).resolve().parent / 'static'
        asset_path = static_root / safe_relative

        if not asset_path.is_file():
            self._send_not_found()
            return

        mime_type, _ = mimetypes.guess_type(str(asset_path))
        if not mime_type:
            mime_type = 'application/octet-stream'

        stat_result = asset_path.stat()
        last_modified = datetime.fromtimestamp(stat_result.st_mtime, timezone.utc)
        etag = f'W/"{stat_result.st_mtime_ns}-{stat_result.st_size}"'

        cache_headers = {'Cache-Control': 'public, max-age=86400'}

        client_etag = self.headers.get('If-None-Match')
        if client_etag == etag:
            self._set_headers(mime_type, status=304, etag=etag, last_modified=last_modified, extra_headers=cache_headers)
            return

        client_ims = self.headers.get('If-Modified-Since')
        if client_ims:
            try:
                client_dt = parsedate_to_datetime(client_ims)
                if client_dt.tzinfo is None:
                    client_dt = client_dt.replace(tzinfo=timezone.utc)
                if client_dt >= last_modified:
                    self._set_headers(mime_type, status=304, etag=etag, last_modified=last_modified, extra_headers=cache_headers)
                    return
            except (TypeError, ValueError):
                pass

        data = asset_path.read_bytes()
        payload_headers = {
            'Cache-Control': 'public, max-age=86400',
            'Content-Length': str(len(data)),
        }
        self._set_headers(mime_type, status=200, etag=etag, last_modified=last_modified, extra_headers=payload_headers)
        self.wfile.write(data)
    
    def do_GET(self):
        """Traite les requêtes GET"""
        # Parser l'URL
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        
        # Logs de requêtes désactivés pour réduire verbosité
        # print(f"[DEBUG] Requête: {path}", flush=True)
        # logger.info(f"GET {path}")
        
        try:
            if path.startswith('/static/'):
                self._serve_static_file(path)
                return

            # Route: Page d'accueil (avec ou sans paramètres pour navigation)
            if path == '/' or path == '/index.html' or path.startswith('/platform/') or path in ['/downloads', '/history', '/settings']:
                self._send_html(self._get_index_html())
            
            # Route: API - Liste des plateformes
            elif path == '/api/platforms':
                platforms, _, source_last_modified = get_cached_sources()
                # Ajouter le nombre de jeux depuis config.games_count
                games_count_dict = getattr(config, 'games_count', {})

                # Filtrer les plateformes cachées selon config.filter_platforms_selection
                hidden_platforms = set()
                if hasattr(config, 'filter_platforms_selection') and config.filter_platforms_selection:
                    hidden_platforms = {name for name, is_hidden in config.filter_platforms_selection if is_hidden}

                # Ajouter aussi les plateformes sans dossier ROM (si show_unsupported_platforms = False)
                from rgsx_settings import load_rgsx_settings, get_show_unsupported_platforms
                settings = load_rgsx_settings()
                show_unsupported = get_show_unsupported_platforms(settings)

                if not show_unsupported:
                    # Masquer les plateformes dont le dossier ROM n'existe pas
                    for platform in platforms:
                        platform_name = platform.get('platform_name', '')
                        folder = platform.get('folder', '')
                        # Garder BIOS même sans dossier
                        if platform_name and folder and platform_name not in ["- BIOS by TMCTV -", "- BIOS"]:
                            expected_dir = os.path.join(config.ROMS_FOLDER, folder)
                            if not os.path.isdir(expected_dir):
                                hidden_platforms.add(platform_name)

                filtered_platforms = []
                for platform in platforms:
                    platform_name = platform.get('platform_name', '')
                    if platform_name in hidden_platforms:
                        continue
                    platform_copy = dict(platform)
                    platform_copy['games_count'] = games_count_dict.get(platform_name, 0)
                    filtered_platforms.append(platform_copy)

                response_payload = {
                    'success': True,
                    'count': len(filtered_platforms),
                    'platforms': filtered_platforms
                }
                response_etag = generate_etag(response_payload)

                self._send_json(response_payload, etag=response_etag, last_modified=source_last_modified)
            
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
                    
                    # Charger toutes les plateformes (avec cache)
                    platforms, _, source_last_modified = get_cached_sources()
                    games_count_dict = getattr(config, 'games_count', {})
                    
                    # Filtrer les plateformes cachées selon config.filter_platforms_selection
                    hidden_platforms = set()
                    if hasattr(config, 'filter_platforms_selection') and config.filter_platforms_selection:
                        hidden_platforms = {name for name, is_hidden in config.filter_platforms_selection if is_hidden}
                    
                    # Ajouter aussi les plateformes sans dossier ROM (si show_unsupported_platforms = False)
                    from rgsx_settings import load_rgsx_settings, get_show_unsupported_platforms
                    settings = load_rgsx_settings()
                    show_unsupported = get_show_unsupported_platforms(settings)
                    
                    if not show_unsupported:
                        # Masquer les plateformes dont le dossier ROM n'existe pas
                        for platform in platforms:
                            platform_name = platform.get('platform_name', '')
                            folder = platform.get('folder', '')
                            # Garder BIOS même sans dossier
                            if platform_name and folder and platform_name not in ["- BIOS by TMCTV -", "- BIOS"]:
                                expected_dir = os.path.join(config.ROMS_FOLDER, folder)
                                if not os.path.isdir(expected_dir):
                                    hidden_platforms.add(platform_name)
                    
                    matching_platforms = []
                    matching_games = []
                    latest_modified = source_last_modified
                    
                    # Rechercher dans les plateformes et leurs jeux
                    for platform in platforms:
                        platform_name = platform.get('platform_name', '')
                        
                        # Exclure les plateformes cachées
                        if platform_name in hidden_platforms:
                            continue
                        
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
                            games, _, games_last_modified = get_cached_games(platform_name)
                            if games_last_modified and latest_modified:
                                latest_modified = max(latest_modified, games_last_modified)
                            elif games_last_modified:
                                latest_modified = games_last_modified
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
                    
                    response_payload = {
                        'success': True,
                        'search_term': search_term,
                        'results': {
                            'platforms': matching_platforms,
                            'games': matching_games
                        }
                    }
                    response_etag = generate_etag(response_payload)

                    self._send_json(response_payload, etag=response_etag, last_modified=latest_modified)
                    
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
                
                games, _, games_last_modified = get_cached_games(platform_name)
                games_formatted = [
                    {
                        'name': g[0],
                        'url': g[1] if len(g) > 1 else None,
                        'size': normalize_size(g[2] if len(g) > 2 else None)
                    }
                    for g in games
                ]
                
                response_payload = {
                    'success': True,
                    'platform': platform_name,
                    'count': len(games_formatted),
                    'games': games_formatted
                }
                response_etag = generate_etag(response_payload)

                self._send_json(response_payload, etag=response_etag, last_modified=games_last_modified)
            
            # Route: API - Progression des téléchargements (en cours seulement)
            elif path == '/api/progress':
                # Lire depuis history.json - filtrer seulement les téléchargements en cours
                history = load_history() or []
                
                print(f"\n[DEBUG PROGRESS] history.json chargé avec {len(history)} entrées totales")
                
                # Filtrer les entrées avec status "Downloading", "Téléchargement", "Connecting", "Try X/Y"
                in_progress_statuses = ["Downloading", "Téléchargement", "Downloading", "Connecting", "Extracting"]
                
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
                
                # print(f"\n[DEBUG HISTORY] history.json chargé avec {len(history)} entrées totales")
                
                # Inclure: statuts terminés + en queue + en cours
                included_statuses = [
                    "Download_OK", "Erreur", "error", "Canceled", "Already_Present",  # Terminés
                    "Queued", "Downloading", "Téléchargement", "Downloading", "Connecting", "Extracting",  # En cours
                ]
                # Inclure aussi les statuts "Try X/Y" (tentatives)
                visible_history = [
                    entry for entry in history
                    if entry.get('status', '') in included_statuses or 
                       str(entry.get('status', '')).startswith('Try ')
                ]
                
                # print(f"[DEBUG HISTORY] {len(visible_history)} téléchargements (terminés + en queue + en cours) trouvés")
                # if visible_history:
                #     print(f"  Premier: {visible_history[0].get('game_name', '')[:50]} - Status: {visible_history[0].get('status')}")
                
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
                            invalidate_all_caches(reason='update-cache refresh')
                            logger.info("🔄 Chargement des plateformes...")
                            refreshed_sources = load_sources()
                            if refreshed_sources is not None:
                                with cache_lock:
                                    source_cache.update({
                                        'data': copy.deepcopy(refreshed_sources),
                                        'timestamp': time.time(),
                                        'etag': generate_etag(refreshed_sources),
                                        'last_modified': _now_utc(),
                                    })
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
        
        # Mettre à jour l'historique: queued -> Downloading
        from history import load_history, save_history
        config.history = load_history()
        for entry in config.history:
            if entry.get('task_id') == task_id and entry.get('status') == 'Queued':
                entry['status'] = 'Downloading'
                entry['message'] = get_translation('download_in_progress')
                save_history(config.history)
                logger.info(f"📋 Statut mis à jour de 'queued' à 'Downloading' pour {game_name} (task_id={task_id})")
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
                
                # Charger les jeux de la plateforme (cache)
                games, _, _ = get_cached_games(platform)
                
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
                        'status': 'Queued'
                    }
                    config.download_queue.append(queue_item)
                    
                    # Ajouter une entrée à l'historique avec status "queued"
                    import datetime
                    queue_history_entry = {
                        'platform': platform,
                        'game_name': game_name,
                        'status': 'Queued',
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
                    
                    # Ajouter une entrée à l'historique avec status "Downloading"
                    # (pas "queued" car on lance immédiatement)
                    import datetime
                    download_history_entry = {
                        'platform': platform,
                        'game_name': game_name,
                        'status': 'Downloading',
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
                        if entry.get('url') == url and entry.get('status') in ['Downloading', 'Téléchargement', 'Downloading', 'Connecting']:
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
                    
                    # Mettre à jour l'historique pour annuler les téléchargements en statut "Queued"
                    history = load_history()
                    for entry in history:
                        if entry.get("status") == "Queued":
                            entry["status"] = "Canceled"
                            entry["message"] = get_translation('download_canceled')
                            logger.info(f"Téléchargement en attente annulé : {entry.get('game_name', '?')}")
                    save_history(history)
                    
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
                            
                            # Mettre à jour l'historique pour cet élément
                            history = load_history()
                            for entry in history:
                                if entry.get('task_id') == task_id and entry.get('status') == 'Queued':
                                    entry['status'] = 'Canceled'
                                    entry['message'] = get_translation('download_canceled')
                                    logger.info(f"Téléchargement en attente annulé dans l'historique : {entry.get('game_name', '?')}")
                                    break
                            save_history(history)
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
        css_version = self._asset_version('css/app.css')
        js_version = self._asset_version('js/app.js')
        html = '''
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="theme-color" content="#667eea">
    <meta name="color-scheme" content="light dark">
    <title>🎮 RGSX Web Interface</title>
    <link rel="icon" type="image/x-icon" href="/api/favicon">
    <link rel="stylesheet" href="/static/css/theme.css?v=__CSS_VERSION__">
    <link rel="stylesheet" href="/static/css/app.css?v=__CSS_VERSION__">
    <link rel="stylesheet" href="/static/css/accessibility.css?v=__CSS_VERSION__">
</head>
<body>
    <!-- Skip to main content link for keyboard users -->
    <a href="#main-content" class="skip-to-main">Skip to main content</a>
    
    <!-- Live region for screen reader announcements -->
    <div id="sr-announcements" role="status" aria-live="polite" aria-atomic="true" class="sr-only"></div>
    
    <div class="container" role="application" aria-label="RGSX Game Manager">
        <header role="banner">
            <h1 data-translate="web_title">RGSX Web Interface</h1>
            <p style="font-size: 0.85em; opacity: 0.8; margin-top: 5px;">v{version}</p>
            
            
            <!-- Navigation mobile avec icônes uniquement -->
            <nav class="mobile-tabs" role="navigation" aria-label="Main navigation (mobile)">
                <button class="mobile-tab active" onclick="showTab('platforms')" data-translate-title="web_tooltip_platforms" title="Platforms list" aria-current="page">🎮</button>
                <button class="mobile-tab" onclick="showTab('downloads')" data-translate-title="web_tooltip_downloads" title="Downloads">⬇️</button>
                <button class="mobile-tab" onclick="showTab('queue')" data-translate-title="web_tooltip_queue" title="Queue">📋</button>
                <button class="mobile-tab" onclick="showTab('history')" data-translate-title="web_tooltip_history" title="History">📜</button>
                <button class="mobile-tab" onclick="showTab('settings')" data-translate-title="web_tooltip_settings" title="Settings">⚙️</button>                
                <button class="mobile-tab" onclick="updateGamesList()" data-translate-title="web_tooltip_update" title="Update games list">🔄</button>
                <button class="mobile-tab" onclick="generateSupportZip()" data-translate-title="web_support" title="Support">🆘</button>
            </nav>
        </header>
        
        <nav class="tabs" role="navigation" aria-label="Main navigation (desktop)">
            <button class="tab active" onclick="showTab('platforms')" aria-current="page">🎮 <span data-translate="web_tab_platforms">Platforms List</span></button>
            <button class="tab" onclick="showTab('downloads')">⬇️ <span data-translate="web_tab_downloads">Downloads</span></button>
            <button class="tab" onclick="showTab('queue')">📋 <span data-translate="web_tab_queue">Queue</span></button>
            <button class="tab" onclick="showTab('history')">📜 <span data-translate="web_tab_history">History</span></button>
            <button class="tab" onclick="showTab('settings')">⚙️ <span data-translate="web_tab_settings">Settings</span></button>
            <button class="tab" onclick="updateGamesList()">🔄 <span data-translate="web_tab_update">Update games list</span></button>
            <button class="tab" onclick="generateSupportZip()">🆘 <span data-translate="web_support">Support</span></button>
        </nav>
        
        <main class="content" id="main-content" role="main">
            <div id="platforms-content" role="region" aria-label="Platforms section"></div>
            <div id="downloads-content" style="display:none;" role="region" aria-label="Downloads section"></div>
            <div id="queue-content" style="display:none;" role="region" aria-label="Queue section"></div>
            <div id="history-content" style="display:none;" role="region" aria-label="History section"></div>
            <div id="settings-content" style="display:none;" role="region" aria-label="Settings section"></div>
        </main>
    </div>
    
    <script src="/static/js/accessibility.js?v=__JS_VERSION__" defer></script>
    <script src="/static/js/app.js?v=__JS_VERSION__" defer></script>
    
    <!-- Region Priority Configuration Modal -->
    <div id="region-priority-modal" style="display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 10000; justify-content: center; align-items: center;">
        <div style="background: white; padding: 20px; border-radius: 8px; max-width: 500px; width: 90%; max-height: 80vh; overflow-y: auto;">
            <h3 style="margin-top: 0;">Region Priority Configuration</h3>
            <p style="color: #666; font-size: 0.9em; margin-bottom: 15px;">
                Configure the priority order for "One ROM Per Game" filter. 
                Higher priority regions will be selected first when multiple versions exist.
            </p>
            <div id="region-priority-config"></div>
        </div>
    </div>
</body>
</html>
        '''
        return (html
                .replace('__CSS_VERSION__', css_version)
                .replace('__JS_VERSION__', js_version)
                .replace('{version}', config.app_version))


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

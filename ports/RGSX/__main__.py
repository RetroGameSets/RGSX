import os
import platform
import warnings


def _enable_windows_dpi_awareness_early():
    """Enable DPI awareness before importing pygame so SDL sees physical monitor sizes."""
    if platform.system() != "Windows":
        return

    try:
        os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")
    except Exception:
        pass

    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            for awareness in (-4, -3):
                try:
                    if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(awareness)):
                        return
                except Exception:
                    continue
    except Exception:
        pass

    try:
        import ctypes

        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        if hasattr(shcore, "SetProcessDpiAwareness"):
            shcore.SetProcessDpiAwareness(2)
            return
    except Exception:
        pass

    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        if hasattr(user32, "SetProcessDPIAware"):
            user32.SetProcessDPIAware()
    except Exception:
        pass


_enable_windows_dpi_awareness_early()

# Ignorer le warning de deprecation de pkg_resources dans pygame
warnings.filterwarnings("ignore", category=UserWarning, module="pygame.pkgdata")
warnings.filterwarnings("ignore", message="pkg_resources is deprecated")


import pygame # type: ignore
import time
import asyncio
import logging
import requests # type: ignore
import queue
import datetime
import subprocess
import sys
import threading
import config
import database
import catalog_sync
import qbittorrent_backend

from display import (
    init_display, draw_loading_screen, draw_error_screen, draw_platform_grid,
    draw_progress_screen, draw_controls, draw_virtual_keyboard,
    draw_extension_warning, draw_pause_menu, draw_controls_help, draw_game_list,
    draw_global_search_list, draw_global_sort_menu,
        draw_display_menu, draw_filter_menu_choice, draw_filter_advanced, draw_filter_priority_config,
    draw_history_list, draw_clear_history_dialog, draw_cancel_download_dialog,
    draw_confirm_dialog, draw_reload_games_data_dialog, draw_popup, draw_app_background,
    draw_toast, show_toast, sync_display_metrics, draw_platform_source_menu
)
from language import _
from network import is_1fichier_url, check_for_updates, apply_pending_update, cancel_all_downloads, shutdown_downloads, get_network_adapter_status
from controls import handle_controls, validate_menu_state, process_key_repeats, get_emergency_controls, clear_joystick_repeat_states, start_or_queue_download, should_open_pause_menu
from controls_mapper import map_controls, draw_controls_mapping, get_actions
from controls import load_controls_config
from utils import (
    load_sources, check_extension_before_download,
    play_random_music, load_music_config, load_api_keys, _refresh_loading_feedback, get_disk_usage,
    parse_torrent_download_url
)
from history import load_history, save_history, load_downloaded_games, check_history_write_access, get_history_write_status
from rgsx_settings import get_display_fullscreen, is_screenscraper_disabled
from accessibility import  load_accessibility_settings

# Configuration du logging
# RotatingFileHandler : 20 MB max par fichier, 2 backups → 60 MB total maximum.
# Évite les fichiers RGSX.log de 1.5 GB causés par un flood de logs torrent, la rotation
# servant de garde-fou.
try:
    os.makedirs(config.log_dir, exist_ok=True)
    from logging.handlers import RotatingFileHandler as _RotatingFileHandler
    _log_handler = _RotatingFileHandler(
        config.log_file,
        maxBytes=20 * 1024 * 1024,  # 20 MB
        backupCount=2,
        encoding='utf-8',
    )
    _log_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logging.root.setLevel(logging.DEBUG)
    logging.root.addHandler(_log_handler)
except Exception as e:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.error(f"Échec de la configuration du logging dans {config.log_file}: {str(e)}")

logger = logging.getLogger(__name__)

try:
    startup_disk_path = getattr(config, "ROMS_FOLDER", None) or getattr(config, "APP_FOLDER", None) or os.getcwd()
    get_disk_usage(startup_disk_path, log=True)
except Exception as exc:
    logger.debug(f"Impossible de journaliser l'espace disque au démarrage: {exc}")

# Ensure API key files (1Fichier, AllDebrid, Debrid-Link, RealDebrid) exist at startup so user can fill them before any download
if not config.INSTALLATION_PATH_WARNING:
    try:  # pragma: no cover
        load_api_keys(False)
    except Exception as _e:
        logger.warning(f"Cannot prepare API key files early: {_e}")

# Mise à jour de la gamelist Windows avant toute initialisation graphique (évite les conflits avec ES)
def _run_windows_gamelist_update():
    try:
        if config.OPERATING_SYSTEM != "Windows":
            return
        script_path = os.path.join(config.APP_FOLDER, "update_gamelist_windows.py")
        if not os.path.exists(script_path):
            return
        exe = sys.executable or "python"
        # Exécuter rapidement avec capture sortie pour journaliser tout message utile
        result = subprocess.run(
            [exe, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=config.APP_FOLDER,
            text=True,
            timeout=30,
        )
        logger.info(f"update_gamelist_windows.py terminé avec code {result.returncode}")
        if result.stdout:
            logger.debug(result.stdout.strip())
    except Exception as e:
        logger.exception(f"Échec lors de l'exécution de update_gamelist_windows.py: {e}")

if not config.INSTALLATION_PATH_WARNING:
    _run_windows_gamelist_update()

try:
    config.update_checked = False
    config.gamelist_refreshed_this_session = False
    config.pending_update_version = ""
    config.startup_update_confirmed = False
    config.text_file_mode = ""
except Exception:
    pass


# Initialisation de Pygame
pygame.init()
pygame.joystick.init()
logger.debug("--------------------------------------------------------------------")
logger.debug("---------------------------DEBUT LOG--------------------------------")
logger.debug("--------------------------------------------------------------------")

# Nettoyage des anciens fichiers de paramètres au démarrage
try:
    from rgsx_settings import delete_old_files
    delete_old_files()
    logger.info("Nettoyage des anciens fichiers effectué au démarrage")
except Exception as e:
    logger.exception(f"Échec du nettoyage des anciens fichiers: {e}")


          
# Chargement des paramètres d'accessibilité
config.accessibility_settings = load_accessibility_settings()
# Appliquer la grille d'affichage depuis les paramètres
try:
    from rgsx_settings import get_display_grid
    gcols, grows = get_display_grid()
    config.GRID_COLS, config.GRID_ROWS = gcols, grows
    logger.debug(f"Grille d'affichage initiale: {gcols}x{grows}")
except Exception as e:
    logger.error(f"Erreur chargement grille d'affichage initiale: {e}")
for i, scale in enumerate(config.font_scale_options):
    if scale == config.accessibility_settings.get("font_scale", 1.0):
        config.current_font_scale_index = i
        break

# Charger le footer_font_scale
for i, scale in enumerate(config.footer_font_scale_options):
    if scale == config.accessibility_settings.get("footer_font_scale", 1.0):
        config.current_footer_font_scale_index = i
        break

# Chargement et initialisation de la langue
from language import initialize_language
initialize_language()
# Charger l'option nintendo_layout depuis les settings
try:
    from rgsx_settings import get_nintendo_layout
    config.nintendo_layout = get_nintendo_layout()
    logger.debug(f"nintendo_layout initial: {config.nintendo_layout}")
except Exception:
    # fallback: si l'import ou la lecture échoue, conserver la valeur par défaut dans config
    logger.debug("Impossible de charger nintendo_layout depuis rgsx_settings")

# Charger la limite de téléchargements simultanés depuis les settings
try:
    from rgsx_settings import get_max_simultaneous_downloads
    config.max_simultaneous_downloads = get_max_simultaneous_downloads()
    logger.debug(f"max_simultaneous_downloads initial: {config.max_simultaneous_downloads}")
except Exception:
    logger.debug("Impossible de charger max_simultaneous_downloads depuis rgsx_settings")

# Détection du système grace a une commande windows / linux (on oublie is non-pc c'est juste pour connaitre le materiel et le systeme d'exploitation)
def detect_system_info():
    """Détecte les informations système (OS, architecture) via des commandes appropriées."""
    try:
        if config.OPERATING_SYSTEM == "Windows":
            # Commande pour Windows
            result = subprocess.run(["wmic", "os", "get", "caption"], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Système détecté (Windows): {result.stdout.strip()}")
        else:
            # Commande pour Linux
            result = subprocess.run(["lsb_release", "-d"], capture_output=True, text=True)
            if result.returncode == 0:
                logger.info(f"Système détecté (Linux): {result.stdout.strip()}")
    except Exception as e:
        logger.error(f"Erreur lors de la détection du système: {e}")

# Initialisation de l’écran
screen = init_display()
clock = pygame.time.Clock()

pygame.display.set_caption("RGSX")

# Initialisation des polices via config
config.init_font()
config.init_footer_font()

# Mise à jour de la résolution dans config
config.screen_width, config.screen_height = pygame.display.get_surface().get_size()
print(f"Resolution ecran validee: {config.screen_width}x{config.screen_height}")

if config.INSTALLATION_PATH_WARNING:
    logger.warning(
        "Installation RGSX dans un chemin inattendu: APP_FOLDER=%s, USERDATA_FOLDER calculé=%s",
        config.APP_FOLDER,
        config.USERDATA_FOLDER,
    )
    config.error_message = _("warning_installation_path")
    warning_confirmed = False
    while not warning_confirmed:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit(0)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    raise SystemExit(0)
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                    warning_confirmed = True
            elif event.type in (pygame.JOYBUTTONDOWN, pygame.MOUSEBUTTONDOWN):
                warning_confirmed = True

        if warning_confirmed:
            break
        screen.fill((0, 0, 0))
        draw_error_screen(screen)
        pygame.display.flip()
        clock.tick(30)

    config.error_message = ""
    config.needs_redraw = True
    try:  # pragma: no cover
        load_api_keys(False)
    except Exception as _e:
        logger.warning(f"Cannot prepare API key files after path warning: {_e}")
    _run_windows_gamelist_update()

# Afficher un premier écran de chargement immédiatement pour éviter un écran noir
try:
    if config.menu_state not in ("loading", "error", "pause_menu"):
        config.menu_state = "loading"
    # Afficher le premier statut du parcours DB/OTA sans texte réseau générique.
    config.current_loading_system = _("loading_check_updates")
    config.loading_progress = 0.0
    draw_loading_screen(screen)
    pygame.display.flip()
    pygame.event.pump()
except Exception as e:
    logger.debug(f"Impossible d'afficher l'ecran de chargement initial: {e}")

# Détection des joysticks après init_display (plus stable sur Batocera)
try:
    if config.OPERATING_SYSTEM != "Windows":
        time.sleep(0.05)  # petite latence pour stabiliser SDL sur certains builds
    count = pygame.joystick.get_count()
except Exception:
    count = 0
    
joystick_names = []
for i in range(count):
    try:
        j = pygame.joystick.Joystick(i)
        joystick_names.append(j.get_name())
    except Exception as e:
        logger.debug(f"Impossible de lire le nom du joystick {i}: {e}")
    
# Enregistrer le nom du premier joystick détecté pour l'auto-préréglage
try:
    if joystick_names:
        config.controller_device_name = joystick_names[0]
    else:
        config.controller_device_name = ""
except Exception:
    pass
normalized_names = [n.lower() for n in joystick_names]
if not joystick_names:
    joystick_names = ["Clavier"]
    print("Aucun joystick detecte, utilisation du clavier par defaut")
    logger.debug("Aucun joystick détecté, utilisation du clavier par défaut.")
    config.joystick = False
    config.keyboard = True
else:
    # Des joysticks sont présents: activer le mode joystick et mémoriser le nom pour l'auto-préréglage
    config.joystick = True
    config.keyboard = False
    print("Joystick detecte:", ", ".join(joystick_names))
    logger.debug(f"Joysticks detectes: {joystick_names}")



# Initialisation des variables de grille
config.current_page = 0
config.selected_platform = 0

# Charger la configuration musique AVANT d'initialiser le mixer pour respecter le paramètre music_enabled
try:
    load_music_config()
except Exception as e:
    logger.warning(f"Impossible de charger la configuration musique avant init mixer: {e}")

# Initialisation du mixer Pygame (déférée/évitable si musique désactivée)
if getattr(config, 'music_enabled', True):
    try:
        pygame.mixer.pre_init(44100, -16, 2, 4096)
        pygame.mixer.init()
    except (NotImplementedError, AttributeError, Exception) as e:
        logger.warning(f"Mixer non disponible ou échec init: {e}")
        config.music_enabled = False  # Désactiver la musique si mixer non disponible

# Dossier musique Batocera
music_folder = os.path.join(config.APP_FOLDER, "assets", "music")
music_files = [f for f in os.listdir(music_folder) if f.lower().endswith(('.ogg', '.mp3'))]
current_music = None  # Variable pour suivre la musique en cours
config.music_folder = music_folder
config.music_files = music_files
config.current_music = current_music

# Lancer la musique seulement si elle est activée dans la configuration
if music_files and config.music_enabled:
    current_music = play_random_music(music_files, music_folder, current_music)
    logger.debug("Musique lancée car activée dans la configuration")
elif music_files and not config.music_enabled:
    logger.debug("Musique désactivée dans la configuration, pas de lecture")
else:
    logger.debug("Aucune musique trouvée dans config.APP_FOLDER/assets/music")

config.current_music = current_music  # Met à jour la musique en cours dans config

# Migrer les anciennes données JSON avant que l'existence de SQLite ne masque ces fichiers.
try:
    legacy_migration = database.migrate_legacy_data(config.SAVE_FOLDER, config.DB_PATH)
    if legacy_migration.get("migrated"):
        logger.info(
            "Migration des anciennes données RGSX terminée : "
            "%s plateformes, %s jeux, %s historiques, %s téléchargements",
            legacy_migration.get("platforms", 0),
            legacy_migration.get("games", 0),
            legacy_migration.get("history", 0),
            legacy_migration.get("downloaded_games", 0),
        )
except Exception as exc:
    logger.exception("Migration des anciennes données RGSX impossible : %s", exc)

# Chargement de l'historique
config.history = load_history()
logger.debug(f"Historique de téléchargement : {len(config.history)} entrées")

# Vérifier explicitement la capacité d'écriture de history.json
history_write_ok, history_write_error_probe = check_history_write_access(force=True)
if not history_write_ok:
    history_write_status = get_history_write_status() or {}
    history_write_message = history_write_status.get("message") or (
        "Erreur ecriture history.json. "
        "Le telechargement continue sans historique temps reel."
    )
    logger.error(history_write_message)
    config.popup_message = history_write_message
    config.popup_timer = max(int(getattr(config, 'popup_timer', 0) or 0), 5000)
    config.needs_redraw = True
    try:
        show_toast(history_write_message, duration=5000)
    except Exception:
        pass

# R36S has no built-in WiFi: tell the user to plug a USB dongle or connect it.
if config.IS_DARKOS:
    network_adapter_status = get_network_adapter_status()
    logger.info("dArkOS network adapter status: %s", network_adapter_status)
    if network_adapter_status != "connected":
        network_message = _(f"darkos_network_{network_adapter_status}")
        config.popup_message = network_message
        config.popup_timer = max(int(getattr(config, 'popup_timer', 0) or 0), 8000)
        config.needs_redraw = True

# Chargement des jeux téléchargés
config.downloaded_games = load_downloaded_games()

# Vérification et chargement de la configuration des contrôles (après mises à jour et détection manette)
config.controls_config = load_controls_config()

# S'assurer que config.controls_config n'est jamais None
if config.controls_config is None:
    config.controls_config = {}
    logger.debug("Initialisation de config.controls_config avec un dictionnaire vide")

# Vérifier si une configuration utilisateur est absente ET qu'aucune config n'a été chargée (préréglage)
if (not os.path.exists(config.CONTROLS_CONFIG_PATH)) and (not config.controls_config):
    logger.warning("Fichier controls.json manquant ou vide, configuration manuelle nécessaire")
    # Ajouter une configuration minimale de secours pour pouvoir naviguer
    config.controls_config = get_emergency_controls()
    config.menu_state = "controls_mapping"
    config.needs_redraw = True
else:
    config.menu_state = "loading"
    logger.debug("Configuration des contrôles trouvée, chargement normal")

# Log de diagnostic: résumé des mappages actifs (type/valeur par action)
try:
    if config.controls_config:
        summary = {}
        for action, mapping in config.controls_config.items():
            # Vérifier que mapping est bien un dictionnaire
            if not isinstance(mapping, dict):
                continue
            mtype = mapping.get("type")
            val = None
            if mtype == "key":
                val = mapping.get("key")
            elif mtype == "button":
                val = mapping.get("button")
            elif mtype == "axis":
                val = (mapping.get("axis"), mapping.get("direction"))
            elif mtype == "hat":
                v = mapping.get("value")
                if isinstance(v, list):
                    v = tuple(v)
                val = v
            elif mtype == "mouse":
                val = mapping.get("button")
            summary[action] = {"type": mtype, "value": val, "display": mapping.get("display")}
        logger.debug(f"Contrôles actifs: {summary}")
except Exception as e:
    logger.warning(f"Impossible de journaliser le résumé des contrôles: {e}")

# Initialisation du gamepad
joystick = None
if pygame.joystick.get_count() > 0:
    try:
        joystick = pygame.joystick.Joystick(0)
        joystick.init()
        logger.debug("Gamepad initialisé")
    except Exception as e:
        logger.warning(f"Échec initialisation gamepad: {e}")


def _is_joystick_valid(js) -> bool:
    if js is None:
        return False
    try:
        js.get_instance_id()
        js.get_name()
        return True
    except Exception:
        return False


def _apply_keyboard_controls(reason: str) -> None:
    config.joystick = False
    config.keyboard = True
    config.controller_device_name = ""
    clear_joystick_repeat_states()
    try:
        config.controls_config = load_controls_config()
    except Exception as e:
        logger.warning(f"Impossible de charger les contrôles clavier: {e}")
    logger.info(reason)


def _apply_joystick_controls(js, reason: str) -> None:
    config.joystick = True
    config.keyboard = False
    try:
        config.controller_device_name = js.get_name()
    except Exception:
        config.controller_device_name = ""
    clear_joystick_repeat_states()
    try:
        config.controls_config = load_controls_config()
    except Exception as e:
        logger.warning(f"Impossible de charger les contrôles joystick: {e}")
    logger.info(reason)


# ===== GESTION DU SERVEUR WEB =====
web_server_process = None

def start_web_server():
    """Démarre le serveur web en arrière-plan dans un processus séparé."""
    global web_server_process
    try:
        if config.IS_DARKOS:
            from utils import is_darkos_web_service_active
            # The boot service already owns port 5000; a second server would fail to bind.
            if is_darkos_web_service_active():
                logger.info("dArkOS: rgsx-web.service already serves the web interface")
                return True

        web_server_script = os.path.join(config.APP_FOLDER, "rgsx_web.py")

        if not os.path.exists(web_server_script):
            logger.warning(f"Script serveur web introuvable: {web_server_script}")
            return False
        
        exe = sys.executable or "python"
        logger.info(f"Exécutable Python: {exe}")
        logger.info(f"Répertoire de travail: {config.APP_FOLDER}")
        logger.info(f"Système: {config.OPERATING_SYSTEM}")
        
        # Créer un fichier de log pour les erreurs du serveur web
        web_server_log = os.path.join(config.log_dir, "rgsx_web_startup.log")
        
        # Démarrer le processus en arrière-plan sans fenêtre console sur Windows
        if config.OPERATING_SYSTEM == "Windows":
            # Utiliser DETACHED_PROCESS pour cacher la console sur Windows
            CREATE_NO_WINDOW = 0x08000000
            logger.info(f"🚀 Lancement du serveur web (mode Windows CREATE_NO_WINDOW)...")
            
            # Rediriger stdout/stderr vers un fichier de log pour capturer les erreurs
            with open(web_server_log, 'w', encoding='utf-8') as log_file:
                web_server_process = subprocess.Popen(
                    [exe, web_server_script],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=config.APP_FOLDER,
                    creationflags=CREATE_NO_WINDOW
                )
        else:
            logger.info(f"🚀 Lancement du serveur web (mode Linux/Unix)...")
            with open(web_server_log, 'w', encoding='utf-8') as log_file:
                web_server_process = subprocess.Popen(
                    [exe, web_server_script],
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    cwd=config.APP_FOLDER
                )
        
        logger.info(f"✅ Serveur web démarré (PID: {web_server_process.pid})")
        logger.info(f"🌐 Serveur accessible sur http://localhost:5000")
        
        # Attendre un peu pour voir si le processus crash immédiatement
        import time
        time.sleep(0.5)
        if web_server_process.poll() is not None:
            logger.error(f"❌ Le serveur web s'est arrêté immédiatement (code: {web_server_process.returncode})")
            logger.error(f"📝 Vérifiez les logs: {web_server_log}")
            return False
        
        return True
    except Exception as e:
        logger.error(f"❌ Erreur lors du démarrage du serveur web: {e}")
        logger.exception("Détails de l'exception:")
        return False

def stop_web_server():
    """Arrête proprement le serveur web."""
    global web_server_process
    if web_server_process is not None:
        try:
            logger.info("Arrêt du serveur web...")
            web_server_process.terminate()
            # Attendre jusqu'à 5 secondes que le processus se termine
            try:
                web_server_process.wait(timeout=5)
                logger.info("Serveur web arrêté proprement")
            except subprocess.TimeoutExpired:
                logger.warning("Serveur web ne répond pas, forçage de l'arrêt...")
                web_server_process.kill()
                web_server_process.wait()
                logger.info("Serveur web forcé à l'arrêt")
            web_server_process = None
        except Exception as e:
            logger.error(f"Erreur lors de l'arrêt du serveur web: {e}")


def _is_arm_machine() -> bool:
    machine = (platform.machine() or "").lower()
    return ("arm" in machine) or ("aarch64" in machine)


def _prewarm_qbittorrent_startup() -> None:
    """Lance qBittorrent en parallèle du boot RGSX pour faciliter la reprise torrent."""
    try:
        if _is_arm_machine():
            logger.info("Pré-lancement qBittorrent ignoré sur architecture ARM")
            return
        qbittorrent_backend.prewarm_startup_async()
        logger.info("Pré-lancement qBittorrent déclenché")
    except Exception as e:
        logger.debug(f"Pré-lancement qBittorrent non disponible: {e}")


def _is_torrent_resume_entry(entry: dict) -> bool:
    """True si l'entrée d'historique correspond à une reprise torrent."""
    try:
        url = str(entry.get("url") or "").strip()
        if not url:
            return False
        return parse_torrent_download_url(url) is not None
    except Exception:
        return False


# Boucle principale
async def main():
    global current_music, music_files, music_folder, joystick, screen
    logger.debug("Début main")
    
    # Charger les filtres de jeux sauvegardés
    try:
        from game_filters import GameFilters
        from rgsx_settings import get_global_sort_option, load_game_filters
        config.global_sort_option = get_global_sort_option()
        config.game_filter_obj = GameFilters()
        filter_dict = load_game_filters()
        if filter_dict:
            config.game_filter_obj.load_from_dict(filter_dict)
            if config.game_filter_obj.is_active():
                config.filter_active = True
                logger.info("Filtres de jeux chargés et actifs")
        logger.info(f"Tri global chargé: {config.global_sort_option}")
    except Exception as e:
        logger.error(f"Erreur lors du chargement des filtres: {e}")
        config.game_filter_obj = None
    
    # Démarrer le serveur web en arrière-plan
    start_web_server()
    _prewarm_qbittorrent_startup()

    # Reprendre les téléchargements interrompus (statut "Téléchargement"/"Downloading")
    # Ces entrées proviennent d'une session précédente fermée proprement sans annulation.
    try:
        interrupted = [
            e for e in config.history
            if e.get("status") in ("Téléchargement", "Downloading") and e.get("url")
        ]

        # Pré-lance qB seulement si une reprise torrent est réellement détectée.
        interrupted_torrents = [e for e in interrupted if _is_torrent_resume_entry(e)]
        if interrupted_torrents:
            logger.info(
                f"[RESUME] {len(interrupted_torrents)} reprise(s) torrent détectée(s): qBittorrent préchauffé au démarrage"
            )

        if interrupted:
            logger.info(f"[RESUME] {len(interrupted)} téléchargement(s) interrompu(s) détecté(s), reprise...")
        for entry in interrupted:
            _url = entry["url"]
            _platform = entry.get("platform", "")
            _game_name = entry.get("game_name", "")
            _is_zip = entry.get("is_zip_non_supported", False)
            _state, _task_id = start_or_queue_download(_url, _platform, _game_name, _is_zip)
            logger.info(f"[RESUME] Reprise: {_game_name} ({_platform}) task_id={_task_id} state={_state}")
            if _state == "queued":
                entry["status"] = "Queued"
                entry["message"] = _("download_queued") if _ else "Queued"
                save_history(config.history)
    except Exception as _e:
        logger.error(f"[RESUME] Erreur lors de la reprise des téléchargements: {_e}")

    running = True
    loading_step = "none"
    ota_update_task = None
    catalog_rows = None
    sources = []
    config.last_state_change_time = 0
    config.debounce_delay = 50
    config.update_triggered = False
    last_redraw_time = pygame.time.get_ticks()
    config.last_frame_time = pygame.time.get_ticks()  # Initialisation pour éviter erreur


    while running:
        clock.tick(60)  # Limite à 60 FPS pour une meilleure réactivité
        if config.update_triggered:
            logger.debug("Mise à jour déclenchée, arrêt de la boucle principale")
            break

        current_time = pygame.time.get_ticks()

        # Déclenchement d'un redémarrage planifié (permet d'afficher une popup avant)
        try:
            pending = getattr(config, 'pending_restart_at', 0)
            if pending and pygame.time.get_ticks() >= pending:
                logger.info("Redémarrage planifié déclenché")
                # Clear the flag to avoid repeated triggers in case restart fails
                config.pending_restart_at = 0
                from utils import restart_application
                restart_application(0)
        except Exception as e:
            logger.error(f"Erreur lors du déclenchement du redémarrage planifié: {e}")

        # Forcer redraw toutes les 100 ms dans download_progress
        if config.menu_state == "download_progress" and current_time - last_redraw_time >= 100:
            config.needs_redraw = True
            last_redraw_time = current_time
        if config.menu_state == "loading" and current_time - last_redraw_time >= 100:
            config.needs_redraw = True
            last_redraw_time = current_time
        # Forcer redraw toutes les 100 ms dans history avec téléchargement actif
        if config.menu_state == "history" and any(entry["status"] in ["Downloading", "Téléchargement"] for entry in config.history):
            if current_time - last_redraw_time >= 100:
                config.needs_redraw = True
                last_redraw_time = current_time
                # logger.debug("Forcing redraw in history state due to active download")

        # Gestion de la fin du popup
        if config.menu_state == "restart_popup" and config.popup_timer > 0:
            config.popup_timer -= (current_time - config.last_frame_time)
            config.needs_redraw = True
            if config.popup_timer <= 0:
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.popup_message = ""
                config.popup_timer = 0
                config.needs_redraw = True
                logger.debug(f"Fermeture automatique du popup, retour à {config.menu_state}")
       
        # Gestion de la fin du popup update_result
        if config.menu_state == "update_result" and current_time - config.update_result_start_time > 5000:
            config.menu_state = "platform"  # Retour à l'écran des plateformes
            config.update_result_message = ""
            config.update_result_error = False
            config.needs_redraw = True
            logger.debug("Fin popup update_result, retour à platform")

        # Gestion de la répétition automatique des actions
        process_key_repeats(sources, joystick, screen)
        
        # A long confirm press opens ScreenScraper game details.
        if (config.menu_state == "game" and 
            config.confirm_press_start_time > 0 and 
            not config.confirm_long_press_triggered and
            not is_screenscraper_disabled()):
            press_duration = current_time - config.confirm_press_start_time
            if press_duration >= config.confirm_long_press_threshold:
                games = config.filtered_games if config.filter_active or config.search_mode else config.games
                if games:
                    game = games[config.current_game]
                    game_name = game.name
                    platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                    from game_info import open_game_info
                    open_game_info(game.name, game.display_name, platform, "game")
                    config.confirm_long_press_triggered = True
                    logger.debug("Long confirm press opened ScreenScraper details for %s", game_name)
        
        # Gestion de l'appui long sur confirm dans le menu platform pour configurer le dossier de destination
        if (config.menu_state == "platform" and 
            getattr(config, 'platform_confirm_press_start_time', 0) > 0 and 
            not getattr(config, 'platform_confirm_long_press_triggered', False)):
            press_duration = current_time - config.platform_confirm_press_start_time
            if press_duration >= config.confirm_long_press_threshold:
                # Appui long détecté, ouvrir le dialogue de configuration du dossier
                if config.platforms:
                    groups = getattr(config, "platform_groups", [])
                    if groups and 0 <= config.selected_platform < len(groups):
                        platform_name = groups[config.selected_platform].get("platforms", [""])[0]
                    else:
                        platform = config.platforms[config.selected_platform]
                        platform_name = platform["name"] if isinstance(platform, dict) else platform
                    if platform_name:
                        config.platform_config_name = platform_name
                        config.previous_menu_state = "platform"
                        config.menu_state = "platform_folder_config"
                        config.platform_folder_selection = 0  # 0=Current, 1=Browse, 2=Reset, 3=Cancel
                        config.needs_redraw = True
                        config.platform_confirm_long_press_triggered = True
                        logger.debug(f"Appui long détecté ({press_duration}ms), ouverture config dossier pour {platform_name}")
        
        # Gestion des événements
        events = pygame.event.get()
        for event in events:            
            if event.type == pygame.USEREVENT + 1:  # Événement de fin de musique
                logger.debug("Fin de la musique détectée, lecture d'une nouvelle musique aléatoire")
                current_music = play_random_music(music_files, music_folder, current_music)
                continue

            resize_events = {
                getattr(pygame, 'VIDEORESIZE', -1),
                getattr(pygame, 'WINDOWSIZECHANGED', -2),
                getattr(pygame, 'WINDOWRESIZED', -3),
            }
            if event.type in resize_events and not get_display_fullscreen():
                try:
                    if event.type == getattr(pygame, 'VIDEORESIZE', -1):
                        new_width = max(640, int(getattr(event, 'w', config.screen_width)))
                        new_height = max(360, int(getattr(event, 'h', config.screen_height)))
                        screen = pygame.display.set_mode((new_width, new_height), pygame.RESIZABLE)
                    else:
                        screen = pygame.display.get_surface() or screen

                    sync_display_metrics(screen)
                    config.needs_redraw = True
                    logger.debug(f"Fenêtre redimensionnée: {config.screen_width}x{config.screen_height}")
                except Exception as e:
                    logger.error(f"Erreur lors du redimensionnement de la fenêtre: {e}")
                continue

            if event.type == pygame.QUIT:
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0
                config.needs_redraw = True
                logger.debug("Événement QUIT détecté, passage à confirm_exit")
                continue

            # Gestion de la reconnexion/déconnexion de manettes (Bluetooth)
            if event.type == pygame.JOYDEVICEADDED:
                try:
                    device_index = event.device_index
                    new_joystick = pygame.joystick.Joystick(device_index)
                    new_joystick.init()

                    # Si la manette active est absente/invalide, prendre la nouvelle.
                    if joystick is None or not _is_joystick_valid(joystick):
                        joystick = new_joystick
                        _apply_joystick_controls(
                            new_joystick,
                            f"Manette connectée et activée: {new_joystick.get_name()} (index {device_index})",
                        )
                    else:
                        logger.info(f"Manette connectée: {new_joystick.get_name()} (index {device_index})")
                    config.needs_redraw = True
                except Exception as e:
                    logger.error(f"Erreur lors de la connexion de la manette: {e}")
                continue

            if event.type == pygame.JOYDEVICEREMOVED:
                try:
                    # Pour JOYDEVICEREMOVED, utiliser instance_id pas device_index
                    instance_id = event.instance_id
                    logger.info(f"Manette déconnectée (instance_id {instance_id})")

                    # Nettoyer immédiatement les répétitions joystick pour éviter
                    # les événements fantômes après déconnexion Bluetooth.
                    clear_joystick_repeat_states()

                    active_removed = False
                    if joystick is not None:
                        try:
                            active_removed = joystick.get_instance_id() == instance_id
                        except Exception:
                            # Référence SDL potentiellement invalide après coupure BT.
                            active_removed = True

                    # Si c'était notre manette active, essayer de trouver une autre.
                    if active_removed:
                        joystick = None

                        # Chercher une autre manette disponible
                        if pygame.joystick.get_count() > 0:
                            try:
                                joystick = pygame.joystick.Joystick(0)
                                joystick.init()
                                _apply_joystick_controls(
                                    joystick,
                                    f"Basculement vers la manette: {joystick.get_name()}",
                                )
                            except Exception as e:
                                logger.warning(f"Impossible de basculer vers une autre manette: {e}")
                                _apply_keyboard_controls("Aucune manette active, basculement automatique sur clavier")
                        else:
                            _apply_keyboard_controls("Aucune manette détectée, utilisation du clavier")
                    config.needs_redraw = True
                except Exception as e:
                    logger.error(f"Erreur lors de la déconnexion de la manette: {e}")
                continue

            start_config = config.controls_config.get("start", {})
            if start_config and (
                (event.type == pygame.KEYDOWN and start_config.get("type") == "key" and event.key == start_config.get("key")) or
                (event.type == pygame.JOYBUTTONDOWN and start_config.get("type") == "button" and event.button == start_config.get("button")) or
                (event.type == pygame.JOYAXISMOTION and start_config.get("type") == "axis" and event.axis == start_config.get("axis") and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == start_config.get("direction")) or
                (event.type == pygame.JOYHATMOTION and start_config.get("type") == "hat" and event.value == tuple(start_config.get("value") if isinstance(start_config.get("value"), list) else start_config.get("value"))) or
                (event.type == pygame.MOUSEBUTTONDOWN and start_config.get("type") == "mouse" and event.button == start_config.get("button"))
            ):
                if should_open_pause_menu(config.menu_state):
                    config.previous_menu_state = config.menu_state
                    # Capturer l'état d'origine pour une sortie fiable du menu pause
                    config.pause_origin_state = config.menu_state
                    config.menu_state = "pause_menu"
                    config.selected_option = 0
                    config.needs_redraw = True
                    logger.debug(f"Ouverture menu pause depuis {config.previous_menu_state}")
                    continue
         
            if config.menu_state == "pause_menu":
                # Rien de spécifique ici, capturé par SIMPLE_HANDLE_STATES ci-dessous
                pass

            # États simples factorisés (déclenchent juste handle_controls + redraw)
            SIMPLE_HANDLE_STATES = {
                "pause_menu",
                "pause_controls_menu",
                "pause_display_menu",
                "pause_display_layout_menu",
                "pause_display_font_menu",
                "pause_games_menu",
                "pause_scrap_menu",
                "pause_settings_menu",
                "pause_api_keys_status",
                "pause_connection_status",
                "media_manager",
                "screenscraper_input",
                "game_info",
                "filter_platforms",
                "display_menu",
                "language_select",
                "controls_help",
                "confirm_cancel_download",
                "reload_games_data",
                "reset_settings_confirm",
                # Menus historique
                "history_game_options",
                "history_show_folder",
                "history_error_details",
                "history_confirm_delete",
                "history_extract_archive",
                "text_file_viewer",
                # Menus filtrage avancé
                "filter_menu_choice",
                "filter_advanced",
                "filter_priority_config",
                "global_sort_menu",
                "platform_search",
            }
            if config.menu_state in SIMPLE_HANDLE_STATES:
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "accessibility_menu":
                from accessibility import handle_accessibility_events
                if handle_accessibility_events(event):
                    config.needs_redraw = True
                continue
            if config.menu_state == "confirm_clear_history":
                action = handle_controls(event, sources, joystick, screen)
                if action == "confirm":
                    config.history.clear()
                    save_history(config.history)
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug("Historique effacé")
                elif action == "cancel":
                    config.menu_state = "history"
                    config.needs_redraw = True
                continue

            if config.menu_state == "confirm_cancel_download":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "reload_games_data":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "gamelist_update_prompt":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "platform_folder_config":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "folder_browser":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "folder_browser_new_folder":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "extension_warning":
                logger.debug(f"[EXTENSION_WARNING] Processing extension_warning, previous_menu_state={config.previous_menu_state}, pending_download={bool(config.pending_download)}")
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                if action == "confirm":
                    logger.debug(f"[EXTENSION_WARNING] Confirm pressed, selection={config.extension_confirm_selection}")
                    if config.pending_download and config.extension_confirm_selection == 0:  # Oui
                        url, platform_name, game_name, is_zip_non_supported = config.pending_download
                        logger.debug(f"[EXTENSION_WARNING] Téléchargement confirmé après avertissement: {game_name} pour {platform_name}")
                        task_id = str(pygame.time.get_ticks())
                        config.history.append({
                            "platform": platform_name,
                            "game_name": game_name,
                            "status": "Downloading",
                            "progress": 0,
                            "url": url,
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        config.current_history_item = len(config.history) - 1
                        save_history(config.history)
                        start_or_queue_download(url, platform_name, game_name, is_zip_non_supported)
                        old_state = config.menu_state
                        config.menu_state = config.previous_menu_state if config.previous_menu_state else "game"
                        logger.debug(f"[EXTENSION_WARNING] Menu state changed: {old_state} -> {config.menu_state}")
                        config.pending_download = None
                        config.extension_confirm_selection = 0  # Réinitialiser la sélection
                        config.needs_redraw = True
                        # Afficher toast de téléchargement en cours
                        config.toast_message = f"Downloading: {game_name}..."
                        config.toast_start_time = pygame.time.get_ticks()
                        config.toast_duration = 3000  # 3 secondes
                        logger.debug(f"[EXTENSION_WARNING] Download started for {game_name}, task_id={task_id}, menu_state={config.menu_state}, needs_redraw={config.needs_redraw}")
                    elif config.extension_confirm_selection == 1:  # Non
                        logger.debug(f"[EXTENSION_WARNING] Download rejected by user")
                        config.menu_state = config.previous_menu_state
                        config.pending_download = None
                        config.extension_confirm_selection = 0  # Réinitialiser la sélection
                        config.needs_redraw = True
                        logger.debug(f"[EXTENSION_WARNING] Returning to {config.menu_state}")
                continue

            if config.menu_state in ["platform", "platform_source", "game", "error", "confirm_exit", "history"]:
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                if action == "quit":
                    running = False
                    logger.debug("Action quit détectée, arrêt de l'application")
                elif action == "download" and config.menu_state == "game" and config.filtered_games:
                    game = config.filtered_games[config.current_game]
                    game_name = game.name
                    url = game.url

                    # Nouveau schéma: config.platforms contient déjà platform_name (string)
                    platform_name = config.platforms[config.current_platform]
                    if url:
                        logger.debug(f"Vérification pour {game_name}, URL: {url}")
                        if is_1fichier_url(url):
                            # Utilisation helpers centralisés (utils)
                            try:
                                from utils import ensure_download_provider_keys, missing_all_provider_keys, build_provider_paths_string
                                keys_info = ensure_download_provider_keys(False)
                            except Exception as e:
                                logger.error(f"Impossible de charger les clés via helpers: {e}")
                                keys_info = {
                                    '1fichier': getattr(config,'API_KEY_1FICHIER',''),
                                    'alldebrid': getattr(config,'API_KEY_ALLDEBRID',''),
                                    'debridlink': getattr(config,'API_KEY_DEBRIDLINK',''),
                                    'realdebrid': getattr(config,'API_KEY_REALDEBRID','')
                                }
                            
                            # SUPPRIMÉ: Vérification clés API obligatoires
                            # Maintenant on a le mode gratuit en fallback automatique
                            # if missing_all_provider_keys():
                            #     config.previous_menu_state = config.menu_state
                            #     config.menu_state = "error"
                            #     try:
                            #         config.error_message = _("error_api_key").format(build_provider_paths_string())
                            #     except Exception:
                            #         config.error_message = "Please enter API key (1fichier or AllDebrid or RealDebrid)"
                            #     # Mise à jour historique
                            #     config.history[-1]["status"] = "Erreur"
                            #     config.history[-1]["progress"] = 0
                            #     config.history[-1]["message"] = "API NOT FOUND"
                            #     save_history(config.history)
                            #     config.needs_redraw = True
                            #     logger.error("Aucune clé fournisseur (1fichier/AllDebrid/RealDebrid) disponible")
                            #     config.pending_download = None
                            #     continue
                            
                            # Avertissement si pas de clé (utilisation mode gratuit)
                            if missing_all_provider_keys():
                                logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
                            
                            pending = check_extension_before_download(url, platform_name, game_name)
                            if not pending:
                                config.menu_state = "error"
                                config.error_message = _("error_invalid_download_data") if _ else "Invalid download data"
                                config.needs_redraw = True
                                logger.error(f"check_extension_before_download a échoué pour {game_name}")
                            else:
                                from utils import is_extension_supported, load_extensions_json, sanitize_filename
                                from rgsx_settings import get_allow_unknown_extensions
                                is_supported = is_extension_supported(sanitize_filename(game_name), platform_name, load_extensions_json())
                                zip_ok = bool(pending[3])
                                allow_unknown = False
                                try:
                                    allow_unknown = get_allow_unknown_extensions()
                                except Exception:
                                    allow_unknown = False
                                if (not is_supported and not zip_ok) and not allow_unknown:
                                    config.pending_download = pending
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non reconnue pour lien 1fichier, passage à extension_warning pour {game_name}")
                                else:
                                    config.previous_menu_state = config.menu_state
                                    logger.debug(f"Previous menu state défini: {config.previous_menu_state}")
                                    start_or_queue_download(url, platform_name, game_name, zip_ok)
                                    config.needs_redraw = True
                                    logger.debug(f"Téléchargement 1fichier planifié pour {game_name}")
                        else:
                            pending = check_extension_before_download(url, platform_name, game_name)
                            if not pending:
                                config.menu_state = "error"
                                config.error_message = _("error_invalid_download_data") if _ else "Invalid download data"
                                config.needs_redraw = True
                                logger.error(f"check_extension_before_download a échoué pour {game_name}")
                            else:
                                from utils import is_extension_supported, load_extensions_json, sanitize_filename
                                from rgsx_settings import get_allow_unknown_extensions
                                is_supported = is_extension_supported(sanitize_filename(game_name), platform_name, load_extensions_json())
                                zip_ok = bool(pending[3])
                                allow_unknown = False
                                try:
                                    allow_unknown = get_allow_unknown_extensions()
                                except Exception:
                                    allow_unknown = False
                                if (not is_supported and not zip_ok) and not allow_unknown:
                                    config.pending_download = pending
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non reconnue, passage à extension_warning pour {game_name}")
                                else:
                                    config.previous_menu_state = config.menu_state
                                    logger.debug(f"Previous menu state défini: {config.previous_menu_state}")
                                    start_or_queue_download(url, platform_name, game_name, zip_ok)
                                    config.needs_redraw = True
                                    logger.debug(f"Téléchargement planifié pour {game_name}")
                
                elif action in ("clear_history", "delete_history") and config.menu_state == "history":
                    # Ouvrir le dialogue de confirmation
                    config.previous_menu_state = config.menu_state
                    config.menu_state = "confirm_clear_history"
                    config.confirm_selection = 0
                    config.needs_redraw = True
                    continue
        
        
        
        # Gestion des téléchargements
        if config.download_tasks:
            for task_id, (task, url, game_name, platform_name) in list(config.download_tasks.items()):
                #logger.debug(f"[DOWNLOAD_CHECK] Checking task {task_id}: done={task.done()}, game={game_name}")
                if task.done():
                    logger.debug(f"[DOWNLOAD_COMPLETE] Task {task_id} is done, processing result for {game_name}")
                    try:
                        success, message = await task
                        logger.debug(f"[DOWNLOAD_RESULT] Task {task_id} returned: success={success}, message={message[:100]}")
                        if "http" in message:
                            message = message.split("https://")[0].strip()
                        logger.debug(f"[HISTORY_SEARCH] Searching in {len(config.history)} history entries for url={url[:50]}...")
                        for entry in config.history:
                            #logger.debug(f"[HISTORY_ENTRY] Checking: url_match={entry['url'] == url}, status={entry['status']}, game={entry.get('game_name')}")
                            if entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
                                #logger.debug(f"[HISTORY_MATCH] Found matching entry for {game_name}, updating status")
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                entry["message"] = message
                                save_history(config.history)
                                # Marquer le jeu comme téléchargé si succès
                                if success:
                                    logger.debug(f"[MARKING_DOWNLOAD] Marking game as downloaded: platform={platform_name}, game={game_name}")
                                    from history import mark_game_as_downloaded
                                    file_size = entry.get("size", "N/A")
                                    mark_game_as_downloaded(platform_name, game_name, file_size)
                                config.needs_redraw = True
                                logger.debug(f"Téléchargement terminé: {game_name}, succès={success}, message={message}, task_id={task_id}")
                                break
                        config.download_result_message = message
                        config.download_result_error = not success
                        config.download_progress.clear()
                        config.pending_download = None
                        # Afficher un toast au lieu de changer de page
                        if success:
                            toast_msg = f"[OK] {game_name}\n{_('download_completed') if _ else 'Download completed'}"
                        else:
                            toast_body = message or (_('download_failed') if _ else 'Download failed')
                            toast_msg = f"[ERROR] {game_name}\n{toast_body}"
                        show_toast(toast_msg, 3000)
                        config.needs_redraw = True
                        del config.download_tasks[task_id]
                    except Exception as e:
                        message = f"Erreur lors du téléchargement: {str(e)}"
                        if "http" in message:
                            message = message.split("https://")[0].strip()
                        for entry in config.history:
                            if entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
                                entry["status"] = "Erreur"
                                entry["progress"] = 0
                                entry["message"] = message
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.debug(f"Erreur téléchargement: {game_name}, message={message}, task_id={task_id}")
                                break
                        config.download_result_message = message
                        config.download_result_error = True
                        config.download_progress.clear()
                        config.pending_download = None
                        # Afficher un toast au lieu de changer de page
                        toast_body = message or (_('download_failed') if _ else 'Download failed')
                        toast_msg = f"[ERROR] {game_name}\n{toast_body}"
                        show_toast(toast_msg, 3000)
                        config.needs_redraw = True
                        del config.download_tasks[task_id]
                else:
                    # Traiter les mises à jour de progression
                    
                    progress_queue = queue.Queue()
                    while not progress_queue.empty():
                        data = progress_queue.get()
                        # logger.debug(f"Progress queue data received: {data}, task_id={task_id}")
                        if len(data) != 3 or data[0] != task_id:  # Ignorer les données d'une autre tâche
                            logger.debug(f"Ignoring queue data for task_id={data[0]}, expected={task_id}")
                            continue
                        if isinstance(data[1], bool):  # Fin du téléchargement
                            success, message = data[1], data[2]
                            logger.debug(f"[DOWNLOAD_TASK] Download task done - success={success}, message={message}, task_id={task_id}")
                            for entry in config.history:
                                if entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
                                    entry["status"] = "Download_OK" if success else "Erreur"
                                    entry["progress"] = 100 if success else 0
                                    entry["message"] = message
                                    save_history(config.history)
                                    # Marquer le jeu comme téléchargé si succès
                                    if success:
                                        from history import mark_game_as_downloaded
                                        file_size = entry.get("size", "N/A")
                                        mark_game_as_downloaded(platform_name, game_name, file_size)
                                    config.needs_redraw = True
                                    logger.debug(f"Final update in history: status={entry['status']}, progress={entry['progress']}%, message={message}, task_id={task_id}")
                                    break
                            config.download_result_message = message
                            config.download_result_error = not success
                            config.download_progress.clear()
                            config.pending_download = None
                            # Afficher un toast au lieu de changer de page
                            if success:
                                toast_msg = f"[OK] {game_name}\n{_('download_completed') if _ else 'Download completed'}"
                            else:
                                toast_body = message or (_('download_failed') if _ else 'Download failed')
                                toast_msg = f"[ERROR] {game_name}\n{toast_body}"
                            show_toast(toast_msg, 3000)
                            config.needs_redraw = True
                            logger.debug(f"[DOWNLOAD_TASK] Toast displayed after completion, task_id={task_id}")
                            del config.download_tasks[task_id]
                        else:
                            downloaded, total_size = data[1], data[2]
                            progress = (downloaded / total_size * 100) if total_size > 0 else 0
                            for entry in config.history:
                                if entry["url"] == url and entry["status"] in ["Downloading", "Téléchargement"]:
                                    entry["progress"] = progress
                                    entry["status"] = "Téléchargement"
                                    config.needs_redraw = True
                                    logger.debug(f"Progress updated in history: {progress:.1f}% for {game_name}, task_id={task_id}")
                                    break


        # Affichage
        if config.needs_redraw:
          try:
            #logger.debug(f"[RENDER_LOOP] Frame render - menu_state={config.menu_state}, needs_redraw={config.needs_redraw}")
            draw_app_background(screen)
            
            
            if config.menu_state == "controls_mapping":
                # Ne rien faire ici, la gestion est faite dans la section spécifique
                pass
            elif config.menu_state == "loading":
                draw_loading_screen(screen)
            elif config.menu_state == "error":
                draw_error_screen(screen)
            elif config.menu_state == "update_result":
                draw_popup(screen)
            elif config.menu_state == "platform":
                draw_platform_grid(screen)
            elif config.menu_state == "platform_source":
                draw_platform_grid(screen)
                draw_platform_source_menu(screen)
            elif config.menu_state == "game":
                #logger.debug(f"[RENDER_GAME] Rendering game state - search_mode={config.search_mode}, filtered_games={len(config.filtered_games) if config.filtered_games else 0}, current_game={config.current_game}")
                if not config.search_mode:
                    draw_game_list(screen)
                if config.search_mode:
                    draw_game_list(screen)
                    if getattr(config, 'joystick', False):
                        draw_virtual_keyboard(screen)
            elif config.menu_state == "platform_search":
                draw_global_search_list(screen)
                if getattr(config, 'joystick', False) and getattr(config, 'global_search_editing', False):
                    draw_virtual_keyboard(screen)
            elif config.menu_state == "download_progress":
                draw_progress_screen(screen)
            # État download_result supprimé
            elif config.menu_state == "confirm_exit":
                draw_confirm_dialog(screen)
            elif config.menu_state == "extension_warning":
                logger.debug(f"[RENDER_EXT_WARNING] Drawing extension warning dialog")
                draw_extension_warning(screen)
            elif config.menu_state == "pause_menu":
                draw_pause_menu(screen, config.selected_option)
            elif config.menu_state == "pause_controls_menu":
                from display import draw_pause_controls_menu
                draw_pause_controls_menu(screen, getattr(config, 'pause_controls_selection', 0))
            elif config.menu_state == "pause_display_menu":
                from display import draw_pause_display_menu
                draw_pause_display_menu(screen, getattr(config, 'pause_display_selection', 0))
            elif config.menu_state == "pause_display_layout_menu":
                from display import draw_pause_display_layout_menu
                draw_pause_display_layout_menu(screen, getattr(config, 'pause_display_layout_selection', 0))
            elif config.menu_state == "pause_display_font_menu":
                from display import draw_pause_display_font_menu
                draw_pause_display_font_menu(screen, getattr(config, 'pause_display_font_selection', 0))
            elif config.menu_state == "pause_games_menu":
                from display import draw_pause_games_menu
                draw_pause_games_menu(screen, getattr(config, 'pause_games_selection', 0))
            elif config.menu_state == "pause_scrap_menu":
                from display import draw_pause_scrap_menu
                draw_pause_scrap_menu(screen, getattr(config, 'pause_scrap_selection', 0))
            elif config.menu_state == "pause_settings_menu":
                from display import draw_pause_settings_menu
                draw_pause_settings_menu(screen, getattr(config, 'pause_settings_selection', 0))
            elif config.menu_state == "pause_api_keys_status":
                from display import draw_pause_api_keys_status
                draw_pause_api_keys_status(screen)
            elif config.menu_state == "pause_connection_status":
                from display import draw_pause_connection_status
                draw_pause_connection_status(screen)
            elif config.menu_state == "media_manager":
                from display import draw_media_manager
                draw_media_manager(screen)
            elif config.menu_state == "screenscraper_input":
                from display import draw_screenscraper_input
                draw_screenscraper_input(screen)
            elif config.menu_state == "filter_platforms":
                from display import draw_filter_platforms_menu
                draw_filter_platforms_menu(screen)
            elif config.menu_state == "filter_menu_choice":
                draw_filter_menu_choice(screen)
            elif config.menu_state == "global_sort_menu":
                draw_global_sort_menu(screen)
            elif config.menu_state == "filter_advanced":
                draw_filter_advanced(screen)
            elif config.menu_state == "filter_priority_config":
                draw_filter_priority_config(screen)
            elif config.menu_state == "controls_help":
                draw_controls_help(screen, config.previous_menu_state)
            elif config.menu_state == "history":
                draw_history_list(screen)                
                # logger.debug("Screen updated with draw_history_list")
            elif config.menu_state == "history_game_options":
                from display import draw_history_game_options
                draw_history_game_options(screen)
            elif config.menu_state == "history_show_folder":
                from display import draw_history_show_folder
                draw_history_show_folder(screen)
            elif config.menu_state == "game_info":
                from display import draw_game_info_screen
                draw_game_info_screen(screen)
            elif config.menu_state == "history_error_details":
                from display import draw_history_error_details
                draw_history_error_details(screen)
            elif config.menu_state == "text_file_viewer":
                from display import draw_text_file_viewer
                draw_text_file_viewer(screen)
            elif config.menu_state == "history_confirm_delete":
                from display import draw_history_confirm_delete
                draw_history_confirm_delete(screen)
            elif config.menu_state == "history_extract_archive":
                from display import draw_history_extract_archive
                draw_history_extract_archive(screen)
            elif config.menu_state == "confirm_clear_history":
                draw_clear_history_dialog(screen)
            elif config.menu_state == "support_dialog":
                from display import draw_support_dialog
                draw_support_dialog(screen)
            elif config.menu_state == "confirm_cancel_download":
                draw_cancel_download_dialog(screen)
            elif config.menu_state == "reload_games_data":
                draw_reload_games_data_dialog(screen)
            elif config.menu_state == "reset_settings_confirm":
                from display import draw_reset_settings_confirm_dialog
                draw_reset_settings_confirm_dialog(screen)
            elif config.menu_state == "gamelist_update_prompt":
                from display import draw_gamelist_update_prompt
                draw_gamelist_update_prompt(screen)
            elif config.menu_state == "platform_folder_config":
                from display import draw_platform_folder_config_dialog
                draw_platform_folder_config_dialog(screen)
            elif config.menu_state == "folder_browser":
                from display import draw_folder_browser
                draw_folder_browser(screen)
            elif config.menu_state == "folder_browser_new_folder":
                from display import draw_folder_browser_new_folder
                draw_folder_browser_new_folder(screen)
            elif config.menu_state == "restart_popup":
                draw_popup(screen)
            elif config.menu_state == "accessibility_menu":
                from accessibility import draw_accessibility_menu
                draw_accessibility_menu(screen)
            elif config.menu_state == "display_menu":
                draw_display_menu(screen)
            elif config.menu_state == "language_select":
                from display import draw_language_menu
                draw_language_menu(screen)
            else:
                config.menu_state = "platform"
                draw_platform_grid(screen)
                config.needs_redraw = True
                logger.error(f"État de menu non valide détecté: {config.menu_state}, retour à platform")
            draw_controls(screen, config.menu_state, getattr(config, 'current_music_name', None), getattr(config, 'music_popup_start_time', 0))

            # Popup générique (affiché dans n'importe quel état si timer actif), sauf si un état popup dédié déjà l'affiche
            if config.popup_timer > 0 and config.popup_message and config.menu_state not in ["update_result", "restart_popup"]:
                draw_popup(screen)
            
            # Toast notification (dans le coin inférieur droit)
            draw_toast(screen)
            
            pygame.display.flip()
            
            config.needs_redraw = False
          except (pygame.error, ValueError) as render_exc:
            # Surface d'affichage temporairement invalide (ex: RetroBat masque/restaure la fenetre): on tente de la recreer plutot que de planter.
            logger.error(f"Erreur de rendu, tentative de recuperation de l'affichage: {render_exc}")
            try:
                screen = pygame.display.set_mode(screen.get_size(), screen.get_flags())
                screen = sync_display_metrics(screen)
            except Exception as recover_exc:
                logger.error(f"Echec de la recuperation de l'affichage: {recover_exc}")
            config.needs_redraw = True

        # Gestion de l'état controls_mapping
        if config.menu_state == "controls_mapping":
            logger.debug("Avant appel de map_controls")
            try:
                # Vérifier si le fichier de contrôles existe déjà
                controls_file_exists = os.path.exists(config.CONTROLS_CONFIG_PATH)
                logger.debug(f"Vérification du fichier controls.json: {controls_file_exists} à {config.CONTROLS_CONFIG_PATH}")
                
                if controls_file_exists:
                    # Si le fichier existe déjà, passer directement à l'état loading
                    config.menu_state = "loading"
                    logger.debug("Fichier controls.json existe déjà, passage direct à l'état loading")
                    config.needs_redraw = True
                else:
                    # Initialiser config.controls_config avec un dictionnaire vide s'il est None
                    if config.controls_config is None:
                        config.controls_config = {}
                        logger.debug("Initialisation de config.controls_config avec un dictionnaire vide")
                    
                    # Forcer l'affichage de l'interface de mappage des contrôles
                    action = get_actions()[0]
                    draw_controls_mapping(screen, action, None, True, 0.0)
                    pygame.display.flip()
                    logger.debug("Interface de mappage des contrôles affichée")
                    
                    # Appeler map_controls pour gérer la configuration
                    success = map_controls(screen)
                    logger.debug(f"map_controls terminé, succès={success}")
                    if success:
                        config.controls_config = load_controls_config()
                        # Toujours passer à l'état loading après la configuration des contrôles
                        config.menu_state = "loading"
                        logger.debug("Passage à l'état loading après mappage")
                        config.needs_redraw = True
                    else:
                        config.menu_state = "error"
                        config.error_message = "Échec du mappage des contrôles"
                        config.needs_redraw = True
                        logger.debug("Échec du mappage, passage à l'état error")
            except Exception as e:
                logger.error(f"Erreur lors de l'appel de map_controls : {str(e)}")
                config.menu_state = "error"
                config.error_message = f"Erreur dans map_controls: {str(e)}"
                config.needs_redraw = True

        # Gestion de l'état loading
        elif config.menu_state == "loading":
            if loading_step == "none":
                loading_step = "check_ota"
                config.current_loading_system = _("loading_check_updates")
                config.loading_progress = 5.0
                config.needs_redraw = True
                logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "check_ota":
                # Si mise à jour déjà vérifiée au pré-boot, sauter cette étape
                if getattr(config, "update_checked", False):
                    logger.debug("Mises à jour déjà vérifiées au pré-boot, on saute check_for_updates()")
                    loading_step = "check_data"
                    config.current_loading_system = _("loading_connect_catalog")
                    config.loading_progress = 35.0
                    config.needs_redraw = True
                    continue
                logger.debug("Exécution de check_for_updates()")
                success, message = await check_for_updates()
                logger.debug(f"Résultat de check_for_updates : success={success}, message={message}")
                if not success:
                    logger.warning("Échec non bloquant de la vérification OTA: %s", message)
                    config.current_loading_system = _("loading_update_check_skipped")
                    config.loading_detail_lines = [str(message)] if message else []
                    loading_step = "check_data"
                    config.loading_progress = 35.0
                    config.needs_redraw = True
                    continue
                elif getattr(config, "pending_update_version", ""):
                    loading_step = "await_ota_confirmation"
                    config.needs_redraw = True
                    continue
                else:
                    loading_step = "check_data"
                    config.current_loading_system = _("loading_connect_catalog")
                    config.loading_progress = 35.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                    continue  # Passer immédiatement à check_data
            elif loading_step == "await_ota_confirmation":
                if not getattr(config, "pending_update_version", ""):
                    # Update skipped with Cancel in the OTA viewer
                    logger.info("OTA update skipped by the user")
                    loading_step = "check_data"
                    config.current_loading_system = _("loading_connect_catalog")
                    config.loading_progress = 35.0
                    config.needs_redraw = True
                    continue
                if not getattr(config, "startup_update_confirmed", False):
                    await asyncio.sleep(0.01)
                    continue

                latest_version = getattr(config, "pending_update_version", "")
                config.startup_update_confirmed = False
                ota_update_task = asyncio.create_task(apply_pending_update(latest_version))
                loading_step = "apply_ota_update"
                config.needs_redraw = True
                continue
            elif loading_step == "apply_ota_update":
                if ota_update_task is None:
                    loading_step = "check_data"
                    continue
                if not ota_update_task.done():
                    await asyncio.sleep(0.01)
                    continue

                success, message = await ota_update_task
                ota_update_task = None
                if not success:
                    config.menu_state = "error"
                    config.error_message = message or _("error_check_updates_failed")
                    config.needs_redraw = True
                else:
                    config.pending_update_version = ""
                    config.text_file_mode = ""
                    config.text_file_content = ""
                    config.loading_detail_lines = []
                    config.needs_redraw = True
                continue
            elif loading_step == "check_data":
                config.current_loading_system = _("loading_connect_catalog")
                config.loading_progress = 40.0
                config.loading_detail_lines = []
                config.needs_redraw = True
                catalog_sync_error = None
                catalog_sync_result = None
                try:
                    def _report_catalog_sync_progress(stage, progress, detail):
                        step_title = None
                        detail_lines = []
                        name, separator, value = str(detail or "").partition(":")
                        if stage == "sync_step":
                            if name == "changes" and "/" in value:
                                current_seq, total_seq = value.split("/", 1)
                                step_title = _("loading_sync_step_changes").format(current_seq, total_seq)
                            elif name == "visibility_platform" and "/" in value:
                                done, total = value.split("/", 1)
                                step_title = _("loading_sync_step_visibility_platform").format(done, total)
                            else:
                                step_keys = {
                                    "db_open": "loading_sync_step_db_open",
                                    "manifest": "loading_sync_step_manifest",
                                    "full": "loading_sync_step_full",
                                    "visibility": "loading_sync_step_visibility",
                                    "visibility_write": "loading_sync_step_visibility_write",
                                    "recheck": "loading_sync_step_recheck",
                                    "cursor": "loading_sync_step_cursor",
                                }
                                if name in step_keys:
                                    step_title = _(step_keys[name])
                        elif stage == "sync_snapshot":
                            if name == "platforms" or name == "games":
                                step_title = _("loading_sync_snapshot_platforms" if name == "platforms" else "loading_sync_snapshot_games")
                                loaded, _sep, total = value.partition("/")
                                if name == "games" and total:
                                    detail_lines.append(_("loading_catalog_games_progress").format(loaded, total))
                                elif name == "platforms" and total:
                                    detail_lines.append(_("loading_platform_counter").format(loaded, total))
                            elif name == "platform_assets":
                                step_title = _("loading_sync_snapshot_assets")
                                detail_lines.append(_("loading_catalog_assets_progress").format(value.partition("/")[0]))
                        if step_title is None:
                            step_title = _("loading_sync_catalog")
                        _refresh_loading_feedback(
                            current_system=step_title,
                            progress=40.0 + (max(0.0, min(100.0, float(progress))) * 0.18),
                            detail_lines=detail_lines,
                            force=True,
                        )

                    catalog_sync_result = catalog_sync.sync_catalog(
                        config.DB_PATH,
                        progress_callback=_report_catalog_sync_progress,
                    )
                    logger.info("Synchronisation du catalogue: %s", catalog_sync_result)
                except Exception as sync_error:
                    catalog_sync_error = sync_error
                    logger.warning("API catalogue indisponible: %s", sync_error)
                try:
                    catalog_rows = database.list_platforms_with_game_counts(config.DB_PATH)
                except Exception as database_error:
                    logger.exception("Connexion ou lecture du catalogue impossible")
                    config.previous_menu_state = "loading"
                    config.menu_state = "error"
                    config.error_message = _("error_catalog_connection")
                    config.needs_redraw = True
                    continue
                if not catalog_rows:
                    if catalog_sync_error is not None:
                        logger.error("API catalogue indisponible et aucun cache local utilisable")
                        config.error_message = _("error_catalog_connection")
                    else:
                        logger.error("Le catalogue DB est joignable mais ne contient aucune plateforme")
                        config.error_message = _("error_catalog_empty")
                    config.previous_menu_state = "loading"
                    config.menu_state = "error"
                    config.needs_redraw = True
                    continue

                config.current_loading_system = _("loading_catalog_connected").format(len(catalog_rows))
                config.loading_progress = 60.0
                sync_mode = str((catalog_sync_result or {}).get("mode") or "local")
                if catalog_sync_error is not None or sync_mode == "local":
                    config.loading_detail_lines = [_ ("loading_catalog_offline_cache")]
                else:
                    applied_changes = int((catalog_sync_result or {}).get("applied") or 0)
                    if sync_mode == "https-full":
                        mode_line = _("loading_catalog_mode_full")
                    elif sync_mode == "https-visibility":
                        mode_line = _("loading_catalog_mode_visibility")
                    elif applied_changes > 0:
                        mode_line = _("loading_catalog_mode_incremental").format(applied_changes)
                    else:
                        mode_line = _("loading_catalog_mode_up_to_date")
                    config.loading_detail_lines = [_ ("loading_catalog_source_api"), mode_line]
                config.needs_redraw = True
                loading_step = "load_sources"
                continue
            elif loading_step == "load_sources":
                logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                config.current_loading_system = _("loading_catalog_loading")
                config.loading_progress = 65.0
                config.needs_redraw = True
                sources = load_sources(allow_torrent_manifest_fetch=True, catalog_rows=catalog_rows)
                if not sources:
                    logger.error("Le catalogue est connecté mais les plateformes n'ont pas pu être chargées")
                    config.previous_menu_state = "loading"
                    config.menu_state = "error"
                    config.error_message = _("error_catalog_load")
                    config.needs_redraw = True
                    continue
                catalog_rows = None
                config.loading_progress = 100.0
                config.current_loading_system = ""
                config.loading_detail_lines = []
                config.menu_state = "platform"
                logger.info(
                    "Catalogue DB chargé : %s plateformes, %s visibles",
                    len(sources),
                    len(config.platforms),
                )
                config.needs_redraw = True

        # Gestion de l'état de transition
        if config.transition_state == "to_game":
            config.transition_progress += 1
            if config.transition_progress >= config.transition_duration:
                config.menu_state = "game"
                config.transition_state = "idle"
                config.transition_progress = 0.0
                config.needs_redraw = True
                logger.debug("Transition terminée, passage à game")

        # Mise à jour du timer popup générique (en dehors des états spéciaux) AVANT mise à jour last_frame_time
        if config.popup_timer > 0 and config.popup_message and config.menu_state not in ["update_result", "restart_popup"]:
            delta = current_time - config.last_frame_time
            if delta > 0:
                config.popup_timer -= delta
            # Forcer redraw pour mettre à jour le compte à rebours
            config.needs_redraw = True
            if config.popup_timer <= 0:
                config.popup_timer = 0
                config.popup_message = ""
        # Mettre à jour last_frame_time après tous les calculs dépendants
        config.last_frame_time = current_time
        clock.tick(60)
        await asyncio.sleep(0.01)

    try:
        if pygame.mixer.get_init() is not None:
            pygame.mixer.music.stop()
    except (AttributeError, NotImplementedError):
        pass
    # Quitter proprement : vider la queue sans annuler les téléchargements actifs
    # (les threads daemon s'arrêtent avec Python, l'historique reste en 'Téléchargement')
    try:
        shutdown_downloads()
    except Exception as e:
        logger.debug(f"Erreur lors du shutdown des téléchargements: {e}")
    
    # Arrêter le serveur web
    stop_web_server()
    
   
    
    if config.OPERATING_SYSTEM == "Windows":
        logger.debug(f"Mise à jour liste des jeux ignorée sur {config.OPERATING_SYSTEM}")
        try:
            result = subprocess.run(["taskkill", "/f", "/im", "emulatorLauncher.exe"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            result2 = subprocess.run(["taskkill", "/f", "/im", "python.exe"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if getattr(result, "returncode", 1) == 0:
                logger.debug("Quitté avec succès: emulatorLauncher.exe")
                print(f"Arret Emulatorlauncher ok")
            else:
                logger.debug("Erreur lors de la tentative d'arrêt d'emulatorLauncher.exe")
                print(f"Arret Emulatorlauncher ko")
            if getattr(result2, "returncode", 1) == 0:
                logger.debug("Quitté avec succès: Python.Exe")
                print(f"Arret Python ok")
            else:
                logger.debug("Erreur lors de la tentative d'arrêt de Python.exe ")
                print(f"Arret Python ko")
        except FileNotFoundError:
            logger.debug("taskkill introuvable, saut de l'étape d'arrêt d'emulatorLauncher.exe")
    elif config.IS_DARKOS:
        # dArkOS EmulationStation has no reload API; RGSX.sh restarts it after exit when ROM folders changed.
        logger.debug("dArkOS: EmulationStation refresh delegated to RGSX.sh")
    else:
        # Exécuter la mise à jour de la liste des jeux d'EmulationStation UNIQUEMENT sur Batocera
        resp = requests.get("http://127.0.0.1:1234/reloadgames", timeout=2)
        content = (resp.text or "").strip()
        logger.debug(f"Résultat mise à jour liste des jeux: HTTP {resp.status_code} - {content}")
        try:
            result2 = subprocess.run(["batocera-es-swissknife", "--emukill"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if getattr(result2, "returncode", 1) == 0:
                logger.debug("Arrêt demandé via batocera-es-swissknife --emukill")
            else:
                logger.debug("Erreur lors de la tentative d'arrêt via batocera-es-swissknife")
        except FileNotFoundError:
            logger.debug("batocera-es-swissknife introuvable, saut de l'étape d'arrêt (environnement non Batocera)")
    pygame.quit()
    logger.debug("Application terminée")

if config.OPERATING_SYSTEM == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())
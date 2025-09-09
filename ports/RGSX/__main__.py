import os
import platform
# Ne pas forcer SDL_FBDEV ici; si déjà défini par l'environnement, on le garde
try:
    if "SDL_FBDEV" in os.environ:
        pass  # respecter la configuration existante
except Exception:
    pass
import pygame # type: ignore
import time
import asyncio
import logging
import requests
import queue
import datetime
import subprocess
import sys
import config
import shutil

from display import (
    init_display, draw_loading_screen, draw_error_screen, draw_platform_grid,
    draw_progress_screen, draw_controls, draw_virtual_keyboard,
    draw_extension_warning, draw_pause_menu, draw_controls_help, draw_game_list,
        draw_display_menu,
    draw_history_list, draw_clear_history_dialog, draw_cancel_download_dialog,
    draw_confirm_dialog, draw_redownload_game_cache_dialog, draw_popup, draw_gradient,
    THEME_COLORS
)
from language import handle_language_menu_events, _
from network import test_internet, download_rom, is_1fichier_url, download_from_1fichier, check_for_updates
from controls import handle_controls, validate_menu_state, process_key_repeats, get_emergency_controls
from controls_mapper import map_controls, draw_controls_mapping, get_actions
from controls import load_controls_config
from utils import (
    load_sources, check_extension_before_download, extract_zip_data,
    play_random_music, load_music_config
)
from history import load_history, save_history
from config import OTA_data_ZIP
from rgsx_settings import get_sources_mode, get_custom_sources_url, get_sources_zip_url
from accessibility import  load_accessibility_settings

# Configuration du logging
try:
    os.makedirs(config.log_dir, exist_ok=True)
    logging.basicConfig(
        filename=config.log_file,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
except Exception as e:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.error(f"Échec de la configuration du logging dans {config.log_file}: {str(e)}")

logger = logging.getLogger(__name__)

# Mise à jour de la gamelist Windows avant toute initialisation graphique (évite les conflits avec ES)
def _run_windows_gamelist_update():
    try:
        if platform.system() != "Windows":
            return
        script_path = os.path.join(config.APP_FOLDER, "update_gamelist_windows.py")
        if not os.path.exists(script_path):
            return
        logger.info("Lancement de update_gamelist_windows.py depuis __main__ (pré-init)")
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

_run_windows_gamelist_update()

# Pré-boot: Désactivé — pas de test Internet ni de mise à jour avant l'init
try:
    logger.debug("Pré-boot: vérification des mises à jour désactivée")
    config.update_checked = False
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

# Chargement et initialisation de la langue
from language import initialize_language
initialize_language()
# Initialiser le mode sources et URL personnalisée
config.sources_mode = get_sources_mode()
config.custom_sources_url = get_custom_sources_url()
logger.debug(f"Mode sources initial: {config.sources_mode}, URL custom: {config.custom_sources_url}")

# Détection du système grace a une commande windows / linux (on oublie is non-pc c'est juste pour connaitre le materiel et le systeme d'exploitation)
def detect_system_info():
    """Détecte les informations système (OS, architecture) via des commandes appropriées."""
    try:
        if platform.system() == "Windows":
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

# Mise à jour de la résolution dans config
config.screen_width, config.screen_height = pygame.display.get_surface().get_size()
logger.debug(f"Résolution d'écran : {config.screen_width}x{config.screen_height}")

# Afficher un premier écran de chargement immédiatement pour éviter un écran noir
try:
    if config.menu_state not in ("loading", "error", "pause_menu"):
        config.menu_state = "loading"
    config.current_loading_system = _("loading_startup") if _ else "Chargement..."
    config.loading_progress = 1.0
    draw_loading_screen(screen)
    pygame.display.flip()
    pygame.event.pump()
except Exception as e:
    logger.debug(f"Impossible d'afficher l'écran de chargement initial: {e}")

# Détection des joysticks après init_display (plus stable sur Batocera)
try:
    if platform.system() != "Windows":
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
normalized_names = [n.lower() for n in joystick_names]
if not joystick_names:
    joystick_names = ["Clavier"]
    print("Aucun joystick détecté, utilisation du clavier par défaut")
    logger.debug("Aucun joystick détecté, utilisation du clavier par défaut.")
    config.joystick = False
    config.keyboard = True
else:
    config.joystick = True
    config.keyboard = False
    print(f"Joysticks détectés: {joystick_names}")
    logger.debug(f"Joysticks détectés: {joystick_names}, utilisation du joystick par défaut.")
    for idx, name in enumerate(joystick_names):
        lname = name.lower()
        if ("xbox" in lname) or ("x-box" in lname) or ("xinput" in lname) or ("microsoft x-box" in lname) or ("x-box 360" in lname) or ("360" in lname):
            config.xbox_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
            break
        elif "playstation" in lname:
            config.playstation_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
            break
        elif "nintendo" in lname:
            config.nintendo_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
        elif "trimui" in lname:
            config.trimui_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
        elif "logitech" in lname:
            config.logitech_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
        elif "8bitdo" in lname or "8-bitdo" in lname:
            config.eightbitdo_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
        elif "steam" in lname:
            config.steam_controller = True
            logger.debug(f"Controller detected : {name}")
            print(f"Controller detected : {name}")
        # Note: virtual keyboard display now depends on controller presence (config.joystick)
    logger.debug(f"Flags contrôleur: xbox={config.xbox_controller}, ps={config.playstation_controller}, nintendo={config.nintendo_controller}, eightbitdo={config.eightbitdo_controller}, steam={config.steam_controller}, trimui={config.trimui_controller}, logitech={config.logitech_controller}, generic={config.generic_controller}")

    # Si aucune marque spécifique détectée mais un joystick est présent, marquer comme générique
    if not any([config.xbox_controller, config.playstation_controller, config.nintendo_controller,
                config.eightbitdo_controller, config.steam_controller, config.trimui_controller,
                config.logitech_controller]):
        config.generic_controller = True
        logger.debug("Aucun contrôleur spécifique détecté, utilisation du profil générique")


# Vérification des dossiers pour le débogage
logger.debug(f"SYSTEM_FOLDER: {config.SYSTEM_FOLDER}")
logger.debug(f"ROMS_FOLDER: {config.ROMS_FOLDER}")
logger.debug(f"SAVE_FOLDER: {config.SAVE_FOLDER}")
logger.debug(f"APP_FOLDER: {config.APP_FOLDER}")


# Initialisation des variables de grille
config.current_page = 0
config.selected_platform = 0
config.selected_key = (0, 0)
config.transition_state = "none"

# Initialisation des variables de répétition
config.repeat_action = None
config.repeat_key = None
config.repeat_start_time = 0
config.repeat_last_action = 0

# Charger la configuration de la musique AVANT d'initialiser l'audio
load_music_config()

# Initialisation du mixer Pygame (déférée/évitable si musique désactivée)
if getattr(config, 'music_enabled', True):
    pygame.mixer.pre_init(44100, -16, 2, 4096)
    try:
        pygame.mixer.init()
    except Exception as e:
        logger.warning(f"Échec init mixer: {e}")
else:
    logger.debug("Musique désactivée, on saute l'initialisation du mixer")

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

# Chargement de l'historique
config.history = load_history()
logger.debug(f"Historique de téléchargement : {len(config.history)} entrées")

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


# Boucle principale
async def main():
    global current_music, music_files, music_folder
    logger.debug("Début main")
    running = True
    loading_step = "none"
    sources = []
    config.last_state_change_time = 0
    config.debounce_delay = 50
    config.update_triggered = False
    last_redraw_time = pygame.time.get_ticks()
    config.last_frame_time = pygame.time.get_ticks()  # Initialisation pour éviter erreur


    while running:
        clock.tick(30)  # Limite à 60 FPS
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
        # Forcer redraw toutes les 100 ms dans history avec téléchargement actif
        if config.menu_state == "history" and any(entry["status"] == "Téléchargement" for entry in config.history):
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
        
        # Gestion des événements
        events = pygame.event.get()
        for event in events:            
            if event.type == pygame.USEREVENT + 1:  # Événement de fin de musique
                logger.debug("Fin de la musique détectée, lecture d'une nouvelle musique aléatoire")
                current_music = play_random_music(music_files, music_folder, current_music)
                continue

            if event.type == pygame.QUIT:
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0
                config.needs_redraw = True
                logger.debug("Événement QUIT détecté, passage à confirm_exit")
                continue

            start_config = config.controls_config.get("start", {})
            if start_config and (
                (event.type == pygame.KEYDOWN and start_config.get("type") == "key" and event.key == start_config.get("key")) or
                (event.type == pygame.JOYBUTTONDOWN and start_config.get("type") == "button" and event.button == start_config.get("button")) or
                (event.type == pygame.JOYAXISMOTION and start_config.get("type") == "axis" and event.axis == start_config.get("axis") and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == start_config.get("direction")) or
                (event.type == pygame.JOYHATMOTION and start_config.get("type") == "hat" and event.value == tuple(start_config.get("value") if isinstance(start_config.get("value"), list) else start_config.get("value"))) or
                (event.type == pygame.MOUSEBUTTONDOWN and start_config.get("type") == "mouse" and event.button == start_config.get("button"))
            ):
                if config.menu_state not in ["pause_menu", "controls_help", "controls_mapping", "history", "confirm_clear_history"]:
                    config.previous_menu_state = config.menu_state
                    config.menu_state = "pause_menu"
                    config.selected_option = 0
                    config.needs_redraw = True
                    logger.debug(f"Ouverture menu pause depuis {config.previous_menu_state}")
                    continue
         
            if config.menu_state == "pause_menu":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                #logger.debug(f"Événement transmis à handle_controls dans pause_menu: {event.type}")
                continue

            # Gestion des événements pour le menu de filtrage des plateformes
            if config.menu_state == "filter_platforms":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "accessibility_menu":
                from accessibility import handle_accessibility_events
                if handle_accessibility_events(event):
                    config.needs_redraw = True
                continue
            if config.menu_state == "display_menu":
                # Les événements sont gérés dans controls.handle_controls
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "language_select":
                # Gérer les événements du sélecteur de langue via le système unifié
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                continue

            if config.menu_state == "controls_help":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                #logger.debug(f"Événement transmis à handle_controls dans controls_help: {event.type}")
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

            if config.menu_state == "redownload_game_cache":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                #logger.debug(f"Événement transmis à handle_controls dans redownload_game_cache: {event.type}")
                continue

            if config.menu_state == "extension_warning":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                if action == "confirm":
                    if config.pending_download and config.extension_confirm_selection == 0:  # Oui
                        url, platform, game_name, is_zip_non_supported = config.pending_download
                        logger.debug(f"Téléchargement confirmé après avertissement: {game_name} pour {platform} depuis {url}")
                        task_id = str(pygame.time.get_ticks())
                        config.history.append({
                            "platform": platform,
                            "game_name": game_name,
                            "status": "downloading",
                            "progress": 0,
                            "url": url,
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        config.current_history_item = len(config.history) - 1
                        save_history(config.history)
                        config.download_tasks[task_id] = (
                            asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id)),
                            url, game_name, platform
                        )
                        config.menu_state = "history"
                        config.pending_download = None
                        config.needs_redraw = True
                        logger.debug(f"Téléchargement démarré pour {game_name}, task_id={task_id}")
                    elif config.extension_confirm_selection == 1:  # Non
                        config.menu_state = config.previous_menu_state
                        config.pending_download = None
                        config.needs_redraw = True
                        logger.debug("Téléchargement annulé, retour à l'état précédent")
                continue

            if config.menu_state in ["platform", "game", "error", "confirm_exit", "history"]:
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                if action == "quit":
                    running = False
                    logger.debug("Action quit détectée, arrêt de l'application")
                elif action == "download" and config.menu_state == "game" and config.filtered_games:
                    game = config.filtered_games[config.current_game]
                    if isinstance(game, (list, tuple)):
                        game_name = game[0]
                        url = game[1] if len(game) > 1 else None
                    else:  # fallback str
                        game_name = str(game)
                        url = None
                    # Nouveau schéma: config.platforms contient déjà platform_name (string)
                    platform = config.platforms[config.current_platform]
                    if url:
                        logger.debug(f"Vérification pour {game_name}, URL: {url}")
                        # Ajouter une entrée temporaire à l'historique
                        config.history.append({
                            "platform": platform,
                            "game_name": game_name,
                            "status": "downloading",
                            "progress": 0,
                            "message": _("download_initializing"),
                            "url": url,
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        config.current_history_item = len(config.history) - 1  # Sélectionner l'entrée en cours
                        if is_1fichier_url(url):
                            if not config.API_KEY_1FICHIER:
                                config.previous_menu_state = config.menu_state
                                config.menu_state = "error"
                                config.error_message = (
                                    f"Attention il faut renseigner sa clé API (premium only) dans le fichier {os.path.join(config.SAVE_FOLDER, '1fichierAPI.txt')}"
                                )
                                # Mettre à jour l'entrée temporaire avec l'erreur
                                config.history[-1]["status"] = "Erreur"
                                config.history[-1]["progress"] = 0
                                config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.error("Clé API 1fichier absente")
                                config.pending_download = None
                                continue
                            is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game_name)
                            if not is_supported:
                                config.pending_download = (url, platform, game_name, is_zip_non_supported)
                                config.menu_state = "extension_warning"
                                config.extension_confirm_selection = 0
                                config.needs_redraw = True
                                logger.debug(f"Extension non reconnue pour lien 1fichier, passage à extension_warning pour {game_name}")
                                # Supprimer l'entrée temporaire si erreur
                                config.history.pop()
                            else:
                                config.previous_menu_state = config.menu_state
                                logger.debug(f"Previous menu state défini: {config.previous_menu_state}")
                                # Lancer le téléchargement dans une tâche asynchrone
                                task_id = str(pygame.time.get_ticks())
                                config.download_tasks[task_id] = (
                                    asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported)),
                                    url, game_name, platform
                                )
                                config.menu_state = "history"  # Passer à l'historique
                                config.needs_redraw = True
                                logger.debug(f"Téléchargement 1fichier démarré pour {game_name}, passage à l'historique")
                        else:
                            is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game_name)
                            if not is_supported:
                                config.pending_download = (url, platform, game_name, is_zip_non_supported)
                                config.menu_state = "extension_warning"
                                config.extension_confirm_selection = 0
                                config.needs_redraw = True
                                logger.debug(f"Extension non reconnue, passage à extension_warning pour {game_name}")
                                # Supprimer l'entrée temporaire si erreur
                                config.history.pop()
                            else:
                                config.previous_menu_state = config.menu_state
                                logger.debug(f"Previous menu state défini: {config.previous_menu_state}")
                                # Lancer le téléchargement dans une tâche asynchrone
                                task_id = str(pygame.time.get_ticks())
                                config.download_tasks[task_id] = (
                                    asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported)),
                                    url, game_name, platform
                                )
                                config.menu_state = "history"  # Passer à l'historique
                                config.needs_redraw = True
                                logger.debug(f"Téléchargement démarré pour {game_name}, passage à l'historique")
                elif action == "redownload" and config.menu_state == "history" and config.history:
                    entry = config.history[config.current_history_item]
                    platform = entry["platform"]
                    game_name = entry["game_name"]
                    for game in config.games:
                        if isinstance(game, (list, tuple)) and game and game[0] == game_name and config.platforms[config.current_platform] == platform:
                            url = game[1] if len(game) > 1 else None
                        else:
                            continue
                        if not url:
                            logger.debug(f"Vérification pour retéléchargement de {game_name}, URL: {url}")
                            if is_1fichier_url(url):
                                if not config.API_KEY_1FICHIER:
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "error"
                                    config.error_message = (
                                        f"Attention il faut renseigner sa clé API (premium only) dans le fichier {os.path.join(config.SAVE_FOLDER, '1fichierAPI.txt')}"
                                    )
                                    config.needs_redraw = True
                                    logger.error("Clé API 1fichier absente")
                                    config.pending_download = None
                                    continue
                                is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game_name)
                                if not is_supported:
                                    config.pending_download = (url, platform, game_name, is_zip_non_supported)
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non reconnue pour lien 1fichier, passage à extension_warning pour {game_name}")
                                else:
                                    config.previous_menu_state = config.menu_state
                                    logger.debug(f"Previous menu state défini: {config.previous_menu_state}")
                                    success, message = download_from_1fichier(url, platform, game_name, is_zip_non_supported)
                                    # Ancien popup download_result supprimé : retour direct à l'historique
                                    config.download_result_message = message
                                    config.download_result_error = not success
                                    config.download_progress.clear()
                                    config.pending_download = None
                                    config.menu_state = "history"
                                    config.needs_redraw = True
                                    logger.debug(f"Retéléchargement 1fichier terminé pour {game_name}, succès={success}, message={message}, retour direct history")
                            else:
                                is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game_name)
                                if not is_supported:
                                    config.pending_download = (url, platform, game_name, is_zip_non_supported)
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non reconnue pour retéléchargement, passage à extension_warning pour {game_name}")
                                else:
                                    config.previous_menu_state = config.menu_state
                                    logger.debug(f"Previous menu state défini: {config.previous_menu_state}")
                                    success, message = download_rom(url, platform, game_name, is_zip_non_supported)
                                    config.download_result_message = message
                                    config.download_result_error = not success
                                    config.download_progress.clear()
                                    config.pending_download = None
                                    config.menu_state = "history"
                                    config.needs_redraw = True
                                    logger.debug(f"Retéléchargement terminé pour {game_name}, succès={success}, message={message}, retour direct history")
                            break
                elif action in ("clear_history", "delete_history") and config.menu_state == "history":
                    # Ouvrir le dialogue de confirmation
                    config.previous_menu_state = config.menu_state
                    config.menu_state = "confirm_clear_history"
                    config.confirm_selection = 0
                    config.needs_redraw = True
                    continue
        
        
        
        # Gestion des téléchargements
        if config.download_tasks:
            for task_id, (task, url, game_name, platform) in list(config.download_tasks.items()):
                if task.done():
                    try:
                        success, message = await task
                        if "http" in message:
                            message = message.split("https://")[0].strip()
                        for entry in config.history:
                            if entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
                                entry["status"] = "Download_OK" if success else "Erreur"
                                entry["progress"] = 100 if success else 0
                                entry["message"] = message
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.debug(f"Téléchargement terminé: {game_name}, succès={success}, message={message}, task_id={task_id}")
                                break
                        config.download_result_message = message
                        config.download_result_error = not success
                        config.download_progress.clear()
                        config.pending_download = None
                        config.menu_state = "history"
                        config.needs_redraw = True
                        del config.download_tasks[task_id]
                    except Exception as e:
                        message = f"Erreur lors du téléchargement: {str(e)}"
                        if "http" in message:
                            message = message.split("https://")[0].strip()
                        for entry in config.history:
                            if entry["url"] == url and entry["status"] in ["downloading", "Téléchargement"]:
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
                        config.menu_state = "history"
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
                        config.download_result_message = message
                        config.download_result_error = True
                        config.download_result_start_time = pygame.time.get_ticks()
                        config.menu_state = "download_result"
                        config.download_progress.clear()
                        config.pending_download = None
                        config.needs_redraw = True
                        del config.download_tasks[task_id]


        # Affichage
        if config.needs_redraw:
            draw_gradient(screen, THEME_COLORS["background_top"], THEME_COLORS["background_bottom"])
            
            
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
            elif config.menu_state == "game":
                if not config.search_mode:
                    draw_game_list(screen)
                if config.search_mode:
                    draw_game_list(screen)
                    if getattr(config, 'joystick', False):
                        draw_virtual_keyboard(screen)
            elif config.menu_state == "download_progress":
                draw_progress_screen(screen)
            # État download_result supprimé
            elif config.menu_state == "confirm_exit":
                draw_confirm_dialog(screen)
            elif config.menu_state == "extension_warning":
                draw_extension_warning(screen)
            elif config.menu_state == "pause_menu":
                draw_pause_menu(screen, config.selected_option)
                #logger.debug("Rendu de draw_pause_menu")
            elif config.menu_state == "filter_platforms":
                from display import draw_filter_platforms_menu
                draw_filter_platforms_menu(screen)
            elif config.menu_state == "controls_help":
                draw_controls_help(screen, config.previous_menu_state)
            elif config.menu_state == "history":
                draw_history_list(screen)                
                # logger.debug("Screen updated with draw_history_list")
            elif config.menu_state == "confirm_clear_history":
                draw_clear_history_dialog(screen)
            elif config.menu_state == "confirm_cancel_download":
                draw_cancel_download_dialog(screen)
            elif config.menu_state == "redownload_game_cache":
                draw_redownload_game_cache_dialog(screen)
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
            
            pygame.display.flip()
            
            config.needs_redraw = False
            # logger.debug("Screen flipped with pygame.display.flip()")

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
                loading_step = "test_internet"
                config.current_loading_system = _("loading_test_connection")
                config.loading_progress = 0.0
                config.needs_redraw = True
                logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "test_internet":
                #logger.debug("Exécution de test_internet()")
                if test_internet():
                    loading_step = "check_ota"
                    config.current_loading_system = _("loading_check_updates")
                    config.loading_progress = 20.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                else:
                    config.menu_state = "error"
                    config.error_message = _("error_no_internet")
                    config.needs_redraw = True
                    logger.debug(f"Erreur : {config.error_message}")
            elif loading_step == "check_ota":
                # Si mise à jour déjà vérifiée au pré-boot, sauter cette étape
                if getattr(config, "update_checked", False):
                    logger.debug("Mises à jour déjà vérifiées au pré-boot, on saute check_for_updates()")
                    loading_step = "check_data"
                    config.current_loading_system = _("loading_downloading_games_images")
                    config.loading_progress = max(config.loading_progress, 50.0)
                    config.needs_redraw = True
                    continue
                logger.debug("Exécution de check_for_updates()")
                success, message = await check_for_updates()
                logger.debug(f"Résultat de check_for_updates : success={success}, message={message}")
                if not success:
                    config.menu_state = "error"
                    # Garder message (déjà fourni par check_for_updates), sinon fallback
                    config.error_message = message or _("error_check_updates_failed")
                    config.needs_redraw = True
                    logger.debug(f"Erreur OTA : {message}")
                else:
                    loading_step = "check_data"
                    config.current_loading_system = _("loading_downloading_games_images")
                    config.loading_progress = 50.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "check_data":
                is_data_empty = not os.path.exists(config.GAMES_FOLDER) or not any(os.scandir(config.GAMES_FOLDER))
                if is_data_empty:
                    config.current_loading_system = _("loading_download_data")
                    config.loading_progress = 30.0
                    config.needs_redraw = True
                    logger.debug("Dossier Data vide, début du téléchargement du ZIP")
                    try:
                        zip_path = os.path.join(config.SAVE_FOLDER, "data_download.zip")
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        # Déterminer l'URL à utiliser selon le mode (RGSX ou custom)
                        sources_zip_url = get_sources_zip_url(OTA_data_ZIP)
                        if sources_zip_url is None:
                            # Mode custom sans URL valide -> pas de téléchargement, jeux vides
                            logger.warning("Mode custom actif mais aucune URL valide fournie. Liste de jeux vide.")
                            config.popup_message = _("sources_mode_custom_missing_url").format(config.RGSX_SETTINGS_PATH)
                            config.popup_timer = 5000
                        else:
                            try:
                                with requests.get(sources_zip_url, stream=True, headers=headers, timeout=30) as response:
                                    response.raise_for_status()
                                    total_size = int(response.headers.get('content-length', 0))
                                    logger.debug(f"Taille totale du ZIP : {total_size} octets")
                                    downloaded = 0
                                    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
                                    with open(zip_path, 'wb') as f:
                                        for chunk in response.iter_content(chunk_size=8192):
                                            if chunk:
                                                f.write(chunk)
                                                downloaded += len(chunk)
                                                config.download_progress[sources_zip_url] = {
                                                    "downloaded_size": downloaded,
                                                    "total_size": total_size,
                                                    "status": "Téléchargement",
                                                    "progress_percent": (downloaded / total_size * 100) if total_size > 0 else 0
                                                }
                                                config.loading_progress = 15.0 + (35.0 * downloaded / total_size) if total_size > 0 else 15.0
                                                config.needs_redraw = True
                                                await asyncio.sleep(0)
                                    logger.debug(f"ZIP téléchargé : {zip_path}")

                                config.current_loading_system = _("loading_extracting_data")
                                config.loading_progress = 60.0
                                config.needs_redraw = True
                                dest_dir = config.SAVE_FOLDER
                                success, message = extract_zip_data(zip_path, dest_dir, sources_zip_url)
                                if success:
                                    logger.debug(f"Extraction réussie : {message}")
                                    config.loading_progress = 70.0
                                    config.needs_redraw = True
                                else:
                                    raise Exception(f"Échec de l'extraction : {message}")
                            except Exception as de:
                                logger.error(f"Erreur téléchargement custom source: {de}")
                                config.popup_message = _("sources_mode_custom_download_error")
                                config.popup_timer = 5000
                                # Pas d'arrêt : continuer avec jeux vides
                    except Exception as e:
                        logger.error(f"Erreur lors du téléchargement/extraction du Dossier Data : {str(e)}")
                        # En mode custom on ne bloque pas le chargement ; en mode RGSX (sources_zip_url non None et OTA) on affiche une erreur
                        if sources_zip_url is not None:
                            config.menu_state = "error"
                            config.error_message = _("error_extract_data_failed")
                            config.needs_redraw = True
                        loading_step = "load_sources"
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                        continue
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                        logger.debug(f"Fichier ZIP {zip_path} supprimé")
                    loading_step = "load_sources"
                    config.current_loading_system = _("loading_load_systems")
                    config.loading_progress = 80.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                else:
                    loading_step = "load_sources"
                    config.current_loading_system = _("loading_load_systems")
                    config.loading_progress = 80.0
                    config.needs_redraw = True
                    logger.debug(f"Dossier Data non vide, passage à {loading_step}")
            elif loading_step == "load_sources":
                sources = load_sources()
                config.menu_state = "platform"
                config.loading_progress = 100.0
                config.current_loading_system = ""
                config.needs_redraw = True
                logger.debug(f"Fin chargement, passage à platform, progress={config.loading_progress}")

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

    pygame.mixer.music.stop()
    result = subprocess.run(["taskkill", "/f", "/im", "emulatorLauncher.exe"])
    if result == 0:
        logger.debug(f"Quitté avec succès: emulatorLauncher.exe")
    else:
        logger.debug("Error en essayant de quitter emulatorlauncher.")
    pygame.quit()
    logger.debug("Application terminée")

    try:
        if platform.system() != "Windows":
            result2 = subprocess.run(["batocera-es-swissknife", "--emukill"])
            if result2 == 0:
                logger.debug(f"Quitté avec succès")
            else:
                logger.debug("Error en essayant de quitter batocera-es-swissknife.")
    except FileNotFoundError:
        logger.debug("batocera-es-swissknife introuvable, saut de l'étape d'arrêt (environnement non Batocera)")

    

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())
import os
os.environ["SDL_FBDEV"] = "/dev/fb0"
import pygame # type: ignore
import asyncio
import platform
import logging
import requests
import queue
import datetime
from display import init_display, draw_loading_screen, draw_error_screen, draw_platform_grid, draw_progress_screen, draw_controls, draw_virtual_keyboard, draw_popup_result_download, draw_extension_warning, draw_pause_menu, draw_controls_help, draw_game_list, draw_history_list, draw_clear_history_dialog, draw_confirm_dialog, draw_redownload_game_cache_dialog, draw_popup, draw_gradient, THEME_COLORS
from network import test_internet, download_rom, is_1fichier_url, download_from_1fichier, check_for_updates
from controls import handle_controls, validate_menu_state
from controls_mapper import load_controls_config, map_controls, draw_controls_mapping, ACTIONS
from utils import detect_non_pc, load_sources, check_extension_before_download, extract_zip, play_random_music
from history import load_history, save_history
import config
from config import OTA_VERSION_ENDPOINT, OTA_UPDATE_SCRIPT, OTA_data_ZIP

# Configuration du logging
log_dir = "/userdata/roms/ports/RGSX/logs"
log_file = os.path.join(log_dir, "RGSX.log")
try:
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        filename=log_file,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
except Exception as e:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.error(f"Échec de la configuration du logging dans {log_file}: {str(e)}")

logger = logging.getLogger(__name__)

# Initialisation de Pygame et des polices
pygame.init()
config.init_font()
pygame.joystick.init()
pygame.mouse.set_visible(True)

# Détection du système non-PC
config.is_non_pc = detect_non_pc()

# Initialisation de l’écran
screen = init_display()
pygame.display.set_caption("RGSX")
clock = pygame.time.Clock()

# Initialisation des polices
try:
    config.font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 36) # Police principale
    config.title_font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 48) # Police pour les titres
    config.search_font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 48) # Police pour la recherche
    config.progress_font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 36)  # Police pour l'affichage de la progression
    config.small_font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 28)  # Police pour les petits textes
    logger.debug("Police Pixel-UniCode chargée")
except:
    config.font = pygame.font.SysFont("arial", 48) # Police fallback
    config.title_font = pygame.font.SysFont("arial", 60) # Police fallback pour les titres
    config.search_font = pygame.font.SysFont("arial", 60)   # Police fallback pour la recherche
    config.progress_font = pygame.font.SysFont("arial", 36)  # Police fallback pour l'affichage de la progression
    config.small_font = pygame.font.SysFont("arial", 28)  # Police fallback pour les petits textes
    logger.debug("Police Arial chargée")

# Mise à jour de la résolution dans config
config.screen_width, config.screen_height = pygame.display.get_surface().get_size()
logger.debug(f"Résolution réelle : {config.screen_width}x{config.screen_height}")

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

# Initialisation des variables pour la popup de musique
current_music_name = None
music_popup_start_time = 0
# Dossier musique Batocera
music_folder = "/userdata/roms/ports/RGSX/assets/music"
music_files = [f for f in os.listdir(music_folder) if f.lower().endswith(('.ogg', '.mp3'))]
current_music = None  # Variable pour suivre la musique en cours
if music_files:
    current_music = play_random_music(music_files, music_folder, current_music)
else:
    logger.debug("Aucune musique trouvée dans /userdata/roms/ports/RGSX/assets/music")


# Chargement de l'historique
config.history = load_history()
logger.debug(f"Historique chargé: {len(config.history)} entrées")

# Vérification et chargement de la configuration des contrôles
config.controls_config = load_controls_config()
if not config.controls_config:
    config.menu_state = "controls_mapping"
else:
    config.menu_state = "loading"

# Initialisation du gamepad
joystick = None
if pygame.joystick.get_count() > 0:
    joystick = pygame.joystick.Joystick(0)
    joystick.init()
    logger.debug("Gamepad initialisé")

# Initialisation du mixer Pygame
pygame.mixer.pre_init(44100, -16, 2, 4096)
pygame.mixer.init()


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

    screen = init_display()
    clock = pygame.time.Clock()

    while running:
        clock.tick(30)  # Limite à 60 FPS
        if config.update_triggered:
            logger.debug("Mise à jour déclenchée, arrêt de la boucle principale")
            break

        current_time = pygame.time.get_ticks()

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
                (event.type == pygame.KEYDOWN and start_config.get("type") == "key" and event.key == start_config.get("value")) or
                (event.type == pygame.JOYBUTTONDOWN and start_config.get("type") == "button" and event.button == start_config.get("value")) or
                (event.type == pygame.JOYAXISMOTION and start_config.get("type") == "axis" and event.axis == start_config.get("value")[0] and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == start_config.get("value")[1]) or
                (event.type == pygame.JOYHATMOTION and start_config.get("type") == "hat" and event.value == tuple(start_config.get("value"))) or
                (event.type == pygame.MOUSEBUTTONDOWN and start_config.get("type") == "mouse" and event.button == start_config.get("value"))
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
                logger.debug(f"Événement transmis à handle_controls dans pause_menu: {event.type}")
                continue

            if config.menu_state == "controls_help":
                cancel_config = config.controls_config.get("cancel", {})
                if (
                    (event.type == pygame.KEYDOWN and cancel_config and event.key == cancel_config.get("value")) or
                    (event.type == pygame.JOYBUTTONDOWN and cancel_config and cancel_config.get("type") == "button" and event.button == cancel_config.get("value")) or
                    (event.type == pygame.JOYAXISMOTION and cancel_config and cancel_config.get("type") == "axis" and event.axis == cancel_config.get("value")[0] and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == cancel_config.get("value")[1]) or
                    (event.type == pygame.JOYHATMOTION and cancel_config and cancel_config.get("type") == "hat" and event.value == tuple(cancel_config.get("value")))
                ):
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "pause_menu"
                    config.needs_redraw = True
                    logger.debug("Controls_help: Annulation, retour à pause_menu")
                continue

            if config.menu_state == "confirm_clear_history":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                logger.debug(f"Événement transmis à handle_controls dans confirm_clear_history: {event.type}")
                continue

            if config.menu_state == "redownload_game_cache":
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                logger.debug(f"Événement transmis à handle_controls dans redownload_game_cache: {event.type}")
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

            if config.menu_state in ["platform", "game", "error", "confirm_exit", "download_progress", "download_result", "history"]:
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                if action == "quit":
                    running = False
                    logger.debug("Action quit détectée, arrêt de l'application")
                elif action == "download" and config.menu_state == "game" and config.filtered_games:
                    game = config.filtered_games[config.current_game]
                    game_name = game[0] if isinstance(game, (list, tuple)) else game
                    platform = config.platforms[config.current_platform]["name"]  # Utiliser le nom de la plateforme
                    url = game[1] if isinstance(game, (list, tuple)) and len(game) > 1 else None
                    if url:
                        logger.debug(f"Vérification pour {game_name}, URL: {url}")
                        # Ajouter une entrée temporaire à l'historique
                        config.history.append({
                            "platform": platform,
                            "game_name": game_name,
                            "status": "downloading",
                            "progress": 0,
                            "url": url,
                            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                        config.current_history_item = len(config.history) - 1  # Sélectionner l'entrée en cours
                        if is_1fichier_url(url):
                            if not config.API_KEY_1FICHIER:
                                config.previous_menu_state = config.menu_state
                                config.menu_state = "error"
                                config.error_message = (
                                    "Attention il faut renseigner sa clé API (premium only) dans le fichier /userdata/saves/ports/rgsx/1fichierAPI.txt"
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
                        if game[0] == game_name and config.platforms[config.current_platform] == platform:
                            url = game[1]
                            logger.debug(f"Vérification pour retéléchargement de {game_name}, URL: {url}")
                            if is_1fichier_url(url):
                                if not config.API_KEY_1FICHIER:
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "error"
                                    config.error_message = (
                                        "Attention il faut renseigner sa clé API (premium only) dans le fichier /userdata/saves/ports/rgsx/1fichierAPI.txt"
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
                                    config.download_result_message = message
                                    config.download_result_error = not success
                                    config.download_result_start_time = pygame.time.get_ticks()
                                    config.menu_state = "download_result"
                                    config.download_progress.clear()
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.debug(f"Retéléchargement 1fichier terminé pour {game_name}, succès={success}, message={message}")
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
                                    config.download_result_start_time = pygame.time.get_ticks()
                                    config.menu_state = "download_result"
                                    config.download_progress.clear()
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.debug(f"Retéléchargement terminé pour {game_name}, succès={success}, message={message}")
                            break
        
        
        
        
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
                        config.download_result_start_time = pygame.time.get_ticks()
                        config.menu_state = "download_result"
                        config.download_progress.clear()
                        config.pending_download = None
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
                        config.download_result_start_time = pygame.time.get_ticks()
                        config.menu_state = "download_result"
                        config.download_progress.clear()
                        config.pending_download = None
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

        # Gestion de la fin du popup download_result
        if config.menu_state == "download_result" and current_time - config.download_result_start_time > 3000:
            config.menu_state = "history"  # Rester dans l'historique après le popup
            config.download_progress.clear()
            config.pending_download = None
            config.needs_redraw = True
            logger.debug(f"Fin popup download_result, retour à history")

        # Affichage
        if config.needs_redraw:
            draw_gradient(screen, THEME_COLORS["background_top"], THEME_COLORS["background_bottom"])
            
            
            if config.menu_state == "controls_mapping":
                draw_controls_mapping(screen, ACTIONS[0], None, False, 0.0)
            elif config.menu_state == "loading":
                draw_loading_screen(screen)
            elif config.menu_state == "error":
                draw_error_screen(screen)
            elif config.menu_state == "platform":
                draw_platform_grid(screen)
            elif config.menu_state == "game":
                if not config.search_mode:
                    draw_game_list(screen)
                if config.search_mode:
                    draw_game_list(screen)
                    draw_virtual_keyboard(screen)
            elif config.menu_state == "download_progress":
                draw_progress_screen(screen)
            elif config.menu_state == "download_result":
                draw_popup_result_download(screen, config.download_result_message, config.download_result_error)
            elif config.menu_state == "confirm_exit":
                draw_confirm_dialog(screen)
            elif config.menu_state == "extension_warning":
                draw_extension_warning(screen)
            elif config.menu_state == "pause_menu":
                draw_pause_menu(screen, config.selected_option)
                logger.debug("Rendu de draw_pause_menu")
            elif config.menu_state == "controls_help":
                draw_controls_help(screen, config.previous_menu_state)
            elif config.menu_state == "history":
                draw_history_list(screen)                
                # logger.debug("Screen updated with draw_history_list")
            elif config.menu_state == "confirm_clear_history":
                draw_clear_history_dialog(screen)
            elif config.menu_state == "redownload_game_cache":
                draw_redownload_game_cache_dialog(screen)
            elif config.menu_state == "restart_popup":
                draw_popup(screen)
            else:
                config.menu_state = "platform"
                draw_platform_grid(screen)
                config.needs_redraw = True
                logger.error(f"État de menu non valide détecté: {config.menu_state}, retour à platform")
            draw_controls(screen, config.menu_state)
            pygame.display.flip()
            
            config.needs_redraw = False
            # logger.debug("Screen flipped with pygame.display.flip()")

        # Gestion de l'état controls_mapping
        if config.menu_state == "controls_mapping":
            logger.debug("Avant appel de map_controls")
            try:
                success = map_controls(screen)
                logger.debug(f"map_controls terminé, succès={success}")
                if success:
                    config.controls_config = load_controls_config()
                    config.menu_state = "loading"
                    config.needs_redraw = True
                    logger.debug("Passage à l'état loading après mappage")
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
                config.current_loading_system = "Test de connexion..."
                config.loading_progress = 0.0
                config.needs_redraw = True
                logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "test_internet":
                logger.debug("Exécution de test_internet()")
                if test_internet():
                    loading_step = "check_ota"
                    config.current_loading_system = "Mise à jour en cours... Patientez si l'ecran reste figé.. Puis relancer l'application une fois qu'elle est terminée."
                    config.loading_progress = 20.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                else:
                    config.menu_state = "error"
                    config.error_message = "Pas de connexion Internet. Vérifiez votre réseau."
                    config.needs_redraw = True
                    logger.debug(f"Erreur : {config.error_message}")
            elif loading_step == "check_ota":
                logger.debug("Exécution de check_for_updates()")
                success, message = await check_for_updates()
                logger.debug(f"Résultat de check_for_updates : success={success}, message={message}")
                if not success:
                    config.menu_state = "error"
                    config.error_message = message
                    config.needs_redraw = True
                    logger.debug(f"Erreur OTA : {message}")
                else:
                    loading_step = "check_data"
                    config.current_loading_system = "Téléchargement des jeux et images ..."
                    config.loading_progress = 50.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "check_data":
                games_data_dir = "/userdata/roms/ports/RGSX/games"
                is_data_empty = not os.path.exists(games_data_dir) or not any(os.scandir(games_data_dir))
                if is_data_empty:
                    config.current_loading_system = "Téléchargement du Dossier Data initial..."
                    config.loading_progress = 30.0
                    config.needs_redraw = True
                    logger.debug("Dossier Data vide, début du téléchargement du ZIP")
                    try:
                        zip_path = "/userdata/roms/ports/RGSX.zip"
                        headers = {'User-Agent': 'Mozilla/5.0'}
                        with requests.get(OTA_data_ZIP, stream=True, headers=headers, timeout=30) as response:
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
                                        config.download_progress[OTA_data_ZIP] = {
                                            "downloaded_size": downloaded,
                                            "total_size": total_size,
                                            "status": "Téléchargement",
                                            "progress_percent": (downloaded / total_size * 100) if total_size > 0 else 0
                                        }
                                        config.loading_progress = 15.0 + (35.0 * downloaded / total_size) if total_size > 0 else 15.0
                                        config.needs_redraw = True
                                        await asyncio.sleep(0)
                            logger.debug(f"ZIP téléchargé : {zip_path}")

                        config.current_loading_system = "Extraction du Dossier Data initial..."
                        config.loading_progress = 60.0
                        config.needs_redraw = True
                        dest_dir = "/userdata/roms/ports/RGSX"
                        success, message = extract_zip(zip_path, dest_dir, OTA_data_ZIP)
                        if success:
                            logger.debug(f"Extraction réussie : {message}")
                            config.loading_progress = 70.0
                            config.needs_redraw = True
                        else:
                            raise Exception(f"Échec de l'extraction : {message}")
                    except Exception as e:
                        logger.error(f"Erreur lors du téléchargement/extraction du Dossier Data : {str(e)}")
                        config.menu_state = "error"
                        config.error_message = f"Échec du téléchargement/extraction du Dossier Data : {str(e)}"
                        config.needs_redraw = True
                        loading_step = "load_sources"
                        if os.path.exists(zip_path):
                            os.remove(zip_path)
                        continue
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
                        logger.debug(f"Fichier ZIP {zip_path} supprimé")
                    loading_step = "load_sources"
                    config.current_loading_system = "Chargement des systèmes..."
                    config.loading_progress = 80.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                else:
                    loading_step = "load_sources"
                    config.current_loading_system = "Chargement des systèmes..."
                    config.loading_progress = 80.0
                    config.needs_redraw = True
                    logger.debug(f"Dossier Data non vide, passage à {loading_step}")
            elif loading_step == "load_sources":
                sources = load_sources()
                if not sources:
                    config.menu_state = "error"
                    config.error_message = "Échec du chargement de sources.json"
                    config.needs_redraw = True
                    logger.debug("Erreur : Échec du chargement de sources.json")
                else:
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

        config.last_frame_time = current_time
        clock.tick(60)
        await asyncio.sleep(0.01)

    pygame.mixer.music.stop()
    pygame.quit()
    logger.debug("Application terminée")

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())
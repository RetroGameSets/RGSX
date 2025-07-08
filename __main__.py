import os
os.environ["SDL_FBDEV"] = "/dev/fb0"
import pygame # type: ignore
import asyncio
import platform
import subprocess
import math
import logging
import requests
import sys
import json
from display import init_display, draw_loading_screen, draw_error_screen, draw_platform_grid, draw_progress_screen, draw_controls, draw_gradient, draw_virtual_keyboard, draw_popup_message, draw_extension_warning, draw_pause_menu, draw_controls_help, draw_game_list, draw_history_list, draw_clear_history_dialog, draw_confirm_dialog, draw_redownload_game_cache_dialog, draw_popup
from network import test_internet, download_rom, check_extension_before_download, extract_zip
from controls import handle_controls, validate_menu_state
from controls_mapper import load_controls_config, map_controls, draw_controls_mapping, ACTIONS
from utils import truncate_text_end, load_system_image, load_games
from history import load_history
import config

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

# URL du serveur OTA
OTA_SERVER_URL = "https://retrogamesets.fr/softs"
OTA_VERSION_ENDPOINT = f"{OTA_SERVER_URL}/version.json"
OTA_UPDATE_SCRIPT = f"{OTA_SERVER_URL}/rgsx-update.sh"
OTA_data_ZIP = f"{OTA_SERVER_URL}/rgsx-data.zip"

# Constantes pour la répétition automatique dans pause_menu
REPEAT_DELAY = 300  # Délai initial avant répétition (ms)
REPEAT_INTERVAL = 150  # Intervalle entre répétitions (ms), augmenté pour réduire la fréquence
REPEAT_ACTION_DEBOUNCE = 100  # Délai anti-rebond pour répétitions (ms), augmenté pour éviter les répétitions excessives

# Initialisation de Pygame et des polices
pygame.init()
config.init_font()
pygame.joystick.init()
pygame.mouse.set_visible(True)

# Détection système non-PC
def detect_non_pc():
    arch = platform.machine()
    try:
        result = subprocess.run(["batocera-es-swissknife", "--arch"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            arch = result.stdout.strip()
            logger.debug(f"Architecture via batocera-es-swissknife: {arch}")
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.debug(f"batocera-es-swissknife non disponible, utilisation de platform.machine(): {arch}")
    
    is_non_pc = arch not in ["x86_64", "amd64"]
    logger.debug(f"Système détecté: {platform.system()}, architecture: {arch}, is_non_pc={is_non_pc}")
    return is_non_pc

config.is_non_pc = detect_non_pc()

# Initialisation de l’écran
screen = init_display()
pygame.display.set_caption("RGSX")
clock = pygame.time.Clock()

# Initialisation des polices
try:
    config.font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 48)
    config.title_font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 60)
    config.search_font = pygame.font.Font("/userdata/roms/ports/RGSX/assets/Pixel-UniCode.ttf", 60)
    logger.debug("Police Pixel-UniCode chargée")
except:
    config.font = pygame.font.SysFont("arial", 48)
    config.title_font = pygame.font.SysFont("arial", 60)
    config.search_font = pygame.font.SysFont("arial", 60)
    logger.debug("Police Arial chargée")
config.progress_font = pygame.font.SysFont("arial", 36)
config.small_font = pygame.font.SysFont("arial", 24)

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

# Dossier musique Batocera
music_folder = "/userdata/roms/ports/RGSX/assets/music"
music_files = [f for f in os.listdir(music_folder) if f.lower().endswith(('.ogg', '.mp3'))]
if music_files:
    import random
    music_file = random.choice(music_files)
    music_path = os.path.join(music_folder, music_file)
    logger.debug(f"Lecture de la musique : {music_path}")
    pygame.mixer.music.load(music_path)
    pygame.mixer.music.set_volume(0.5)
    pygame.mixer.music.play(-1)
else:
    logger.debug("Aucune musique trouvée dans /userdata/roms/ports/RGSX/assets/music")

# Fonction pour charger sources.json
def load_sources():
    sources_path = "/userdata/roms/ports/RGSX/sources.json"
    logger.debug(f"Chargement de {sources_path}")
    try:
        with open(sources_path, 'r', encoding='utf-8') as f:
            sources = json.load(f)
        sources = sorted(sources, key=lambda x: x.get("nom", x.get("platform", "")).lower())
        config.platforms = [source["platform"] for source in sources]
        config.platform_dicts = sources
        config.platform_names = {source["platform"]: source["nom"] for source in sources}
        config.games_count = {platform: 0 for platform in config.platforms}  # Initialiser à 0
        # Charger les jeux pour chaque plateforme
        for platform in config.platforms:
            games = load_games(platform)
            config.games_count[platform] = len(games)
            logger.debug(f"Jeux chargés pour {platform}: {len(games)} jeux")
        logger.debug(f"load_sources: platforms={config.platforms}, platform_names={config.platform_names}, games_count={config.games_count}")
        return sources
    except Exception as e:
        logger.error(f"Erreur lors du chargement de sources.json : {str(e)}")
        return []

# Fonction pour vérifier et appliquer les mises à jour OTA
async def check_for_updates():
    try:
        logger.debug("Vérification de la version disponible sur le serveur")
        config.current_loading_system = "Mise à jour en cours... Patientez l'ecran reste figé..Puis relancer l'application"
        config.loading_progress = 5.0
        config.needs_redraw = True
        response = requests.get(OTA_VERSION_ENDPOINT, timeout=5)
        response.raise_for_status()
        if response.headers.get("content-type") != "application/json":
            raise ValueError(f"Le fichier version.json n'est pas un JSON valide (type de contenu : {response.headers.get('content-type')})")
        version_data = response.json()
        latest_version = version_data.get("version")
        logger.debug(f"Version distante : {latest_version}, version locale : {config.app_version}")

        if latest_version != config.app_version:
            config.current_loading_system = f"Mise à jour disponible : {latest_version}"
            config.loading_progress = 10.0
            config.needs_redraw = True
            logger.debug(f"Téléchargement du script de mise à jour : {OTA_UPDATE_SCRIPT}")

            update_script_path = "/userdata/roms/ports/rgsx-update.sh"
            logger.debug(f"Téléchargement de {OTA_UPDATE_SCRIPT} vers {update_script_path}")
            with requests.get(OTA_UPDATE_SCRIPT, stream=True, timeout=10) as r:
                r.raise_for_status()
                with open(update_script_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            config.loading_progress = min(50.0, config.loading_progress + 5.0)
                            config.needs_redraw = True
                            await asyncio.sleep(0)

            config.current_loading_system = "Préparation de la mise à jour..."
            config.loading_progress = 60.0
            config.needs_redraw = True
            logger.debug(f"Rendre {update_script_path} exécutable")
            subprocess.run(["chmod", "+x", update_script_path], check=True)
            logger.debug(f"Script {update_script_path} rendu exécutable")

            logger.debug(f"Vérification de l'existence et des permissions de {update_script_path}")
            if not os.path.isfile(update_script_path):
                logger.error(f"Le script {update_script_path} n'existe pas")
                return False, f"Erreur : le script {update_script_path} n'existe pas"
            if not os.access(update_script_path, os.X_OK):
                logger.error(f"Le script {update_script_path} n'est pas exécutable")
                return False, f"Erreur : le script {update_script_path} n'est pas exécutable"

            wrapper_script_path = "/userdata/roms/ports/RGSX/update/run.update"
            logger.debug(f"Vérification de l'existence et des permissions de {wrapper_script_path}")
            if not os.path.isfile(wrapper_script_path):
                logger.error(f"Le script wrapper {wrapper_script_path} n'existe pas")
                return False, f"Erreur : le script wrapper {wrapper_script_path} n'existe pas"
            if not os.access(wrapper_script_path, os.X_OK):
                logger.error(f"Le script wrapper {wrapper_script_path} n'est pas exécutable")
                subprocess.run(["chmod", "+x", wrapper_script_path], check=True)
                logger.debug(f"Script wrapper {wrapper_script_path} rendu exécutable")

            logger.debug("Désactivation des événements Pygame QUIT")
            pygame.event.set_blocked(pygame.QUIT)

            config.current_loading_system = "Application de la mise à jour..."
            config.loading_progress = 80.0
            config.needs_redraw = True
            logger.debug(f"Exécution du script wrapper : {wrapper_script_path}")
            result = os.system(f"{wrapper_script_path} &")
            logger.debug(f"Résultat de os.system : {result}")
            if result != 0:
                logger.error(f"Échec du lancement du script wrapper : code de retour {result}")
                return False, f"Échec du lancement du script wrapper : code de retour {result}"

            config.current_loading_system = "Mise à jour déclenchée, redémarrage..."
            config.loading_progress = 100.0
            config.needs_redraw = True
            logger.debug("Mise à jour déclenchée, arrêt de l'application")
            config.update_triggered = True
            pygame.quit()
            sys.exit(0)
        else:
            logger.debug("Aucune mise à jour logicielle disponible")
            return True, "Aucune mise à jour disponible"

    except Exception as e:
        logger.error(f"Erreur OTA : {str(e)}")
        return False, f"Erreur lors de la vérification des mises à jour : {str(e)}"

# Boucle principale
async def main():
    logger.debug("Début main")
    running = True
    loading_step = "none"
    sources = []
    config.last_state_change_time = 0
    config.debounce_delay = 50
    config.update_triggered = False
    last_redraw_time = pygame.time.get_ticks()
    
    screen = init_display()
    clock = pygame.time.Clock()

    while running:
        clock.tick(60)  # Limite à 60 FPS
        if config.update_triggered:
            logger.debug("Mise à jour déclenchée, arrêt de la boucle principale")
            break

        current_time = pygame.time.get_ticks()

        # Forcer redraw toutes les 100 ms dans download_progress
        if config.menu_state == "download_progress" and current_time - last_redraw_time >= 100:
            config.needs_redraw = True
            last_redraw_time = current_time
        
        # Dans __main__.py, dans la boucle principale
        current_time = pygame.time.get_ticks()
        delta_time = current_time - config.last_frame_time
        config.last_frame_time = current_time
        if config.menu_state == "restart_popup" and config.popup_timer > 0:
            config.popup_timer -= delta_time
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

            # Gérer confirm_clear_history explicitement
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

            if config.menu_state in ["platform", "game", "error", "confirm_exit", "download_progress", "download_result", "extension_warning", "history"]:
                action = handle_controls(event, sources, joystick, screen)
                config.needs_redraw = True
                if action == "quit":
                    running = False
                    logger.debug("Action quit détectée, arrêt de l'application")
                elif action == "download" and config.menu_state == "game" and config.filtered_games:
                    game = config.filtered_games[config.current_game]
                    game_name = game[0] if isinstance(game, (list, tuple)) else game
                    platform = config.platforms[config.current_platform]
                    url = game[1] if isinstance(game, (list, tuple)) and len(game) > 1 else None
                    if url:
                        logger.debug(f"Vérification de l'extension pour {game_name}, URL: {url}")
                        is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game_name)
                        if not is_supported:
                            config.pending_download = (url, platform, game_name, is_zip_non_supported)
                            config.menu_state = "extension_warning"
                            config.extension_confirm_selection = 0
                            config.needs_redraw = True
                            logger.debug(f"Extension non reconnue, passage à extension_warning pour {game_name}")
                        else:
                            task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported))
                            config.download_tasks[task] = (task, url, game_name, platform)
                            config.menu_state = "download_progress"
                            config.pending_download = None  # Réinitialiser après démarrage du téléchargement
                            config.needs_redraw = True
                            logger.debug(f"Téléchargement démarré pour {game_name}, passage à download_progress")
                elif action == "redownload" and config.menu_state == "history" and config.history:
                    entry = config.history[config.current_history_item]
                    platform = entry["platform"]
                    game_name = entry["game_name"]
                    for game in config.games:
                        if game[0] == game_name and config.platforms[config.current_platform] == platform:
                            url = game[1]
                            is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game_name)
                            if not is_supported:
                                config.pending_download = (url, platform, game_name, is_zip_non_supported)
                                config.menu_state = "extension_warning"
                                config.extension_confirm_selection = 0
                                config.needs_redraw = True
                                logger.debug(f"Extension non reconnue pour retéléchargement, passage à extension_warning pour {game_name}")
                            else:
                                task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported))
                                config.download_tasks[task] = (task, url, game_name, platform)
                                config.menu_state = "download_progress"
                                config.pending_download = None  # Réinitialiser après démarrage du téléchargement
                                config.needs_redraw = True
                                logger.debug(f"Retéléchargement démarré pour {game_name}, passage à download_progress")
                            break

        # Gestion des téléchargements
        if config.download_tasks:
            for task_id, (task, url, game_name, platform) in list(config.download_tasks.items()):
                if task.done():
                    try:
                        success, message = await task
                        config.download_result_message = message
                        config.download_result_error = not success
                        config.download_result_start_time = pygame.time.get_ticks()
                        config.menu_state = "download_result"
                        config.download_progress.clear()  # Réinitialiser download_progress
                        config.pending_download = None  # Réinitialiser après téléchargement
                        config.needs_redraw = True
                        del config.download_tasks[task_id]
                        logger.debug(f"Téléchargement terminé: {game_name}, succès={success}, message={message}")
                    except Exception as e:
                        config.download_result_message = f"Erreur lors du téléchargement : {str(e)}"
                        config.download_result_error = True
                        config.download_result_start_time = pygame.time.get_ticks()
                        config.menu_state = "download_result"
                        config.download_progress.clear()  # Réinitialiser download_progress
                        config.pending_download = None  # Réinitialiser après téléchargement
                        config.needs_redraw = True
                        del config.download_tasks[task_id]
                        logger.error(f"Erreur dans tâche de téléchargement: {str(e)}")

        # Gestion de la fin du popup download_result
        if config.menu_state == "download_result" and current_time - config.download_result_start_time > 3000:
            config.menu_state = config.previous_menu_state if config.previous_menu_state in ["platform", "game", "history"] else "game"
            config.download_progress.clear()  # Réinitialiser download_progress
            config.pending_download = None  # Réinitialiser après affichage du résultat
            config.needs_redraw = True
            logger.debug(f"Fin popup download_result, retour à {config.menu_state}")

        # Affichage
        if config.needs_redraw:
            draw_gradient(screen, (28, 37, 38), (47, 59, 61))
            if config.menu_state == "controls_mapping":
                draw_controls_mapping(screen, ACTIONS[0], None, False, 0.0)
               # logger.debug("Rendu initial de draw_controls_mapping")
            elif config.menu_state == "loading":
                draw_loading_screen(screen)
               # logger.debug("Rendu de draw_loading_screen")
            elif config.menu_state == "error":
                draw_error_screen(screen)
               # logger.debug("Rendu de draw_error_screen")
            elif config.menu_state == "platform":
                draw_platform_grid(screen)
               # logger.debug("Rendu de draw_platform_grid")
            elif config.menu_state == "game":
                draw_game_list(screen)
               # logger.debug("Rendu de draw_game_list")
            elif config.menu_state == "download_progress":
                draw_progress_screen(screen)
               # logger.debug("Rendu de draw_progress_screen")
            elif config.menu_state == "download_result":
                draw_popup_message(screen, config.download_result_message, config.download_result_error)
               # logger.debug("Rendu de draw_popup_message")
            elif config.menu_state == "confirm_exit":
                draw_confirm_dialog(screen)
               # logger.debug("Rendu de draw_confirm_dialog")
            elif config.menu_state == "extension_warning":
                draw_extension_warning(screen)
               # logger.debug("Rendu de draw_extension_warning")
            elif config.menu_state == "pause_menu":
                draw_pause_menu(screen, config.selected_option)
                logger.debug("Rendu de draw_pause_menu")
            elif config.menu_state == "controls_help":
                draw_controls_help(screen, config.previous_menu_state)
               # logger.debug("Rendu de draw_controls_help")
            elif config.menu_state == "history":
                draw_history_list(screen)
               # logger.debug("Rendu de draw_history_list")
            elif config.menu_state == "confirm_clear_history":
                draw_clear_history_dialog(screen)
               # logger.debug("Rendu de confirm_clear_history")
            elif config.menu_state == "redownload_game_cache":
                draw_redownload_game_cache_dialog(screen)  # Fonction existante
            elif config.menu_state == "restart_popup":
                draw_popup(screen)  # Nouvelle fonction
            elif config.menu_state == "confirm_clear_history":
                draw_clear_history_dialog(screen)  # Fonction existante

            else:
                # Gestion des états non valides
                config.menu_state = "platform"
                draw_platform_grid(screen)
                config.needs_redraw = True
                logger.error(f"État de menu non valide détecté: {config.menu_state}, retour à platform")
            draw_controls(screen, config.menu_state)
            pygame.display.flip()
            config.needs_redraw = False

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
            logger.debug(f"Étape chargement : {loading_step}")
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
                    config.current_loading_system = "Mise à jour en cours... Patientez l'ecran reste figé.. Puis relancer l'application"
                    config.loading_progress = 100
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
                    config.loading_progress = 10.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "check_data":
                games_data_dir = "/userdata/roms/ports/RGSX/games"
                is_data_empty = not os.path.exists(games_data_dir) or not any(os.scandir(games_data_dir))
                #logger.debug(f"Dossier Data directory {games_data_dir} is {'empty' if is_data_empty else 'not empty'}")
                
                if is_data_empty:
                    config.current_loading_system = "Téléchargement du Dossier Data initial..."
                    config.loading_progress = 15.0
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
                        config.loading_progress = 50.0
                        config.needs_redraw = True
                        dest_dir = "/userdata/roms/ports/RGSX"
                        success, message = extract_zip(zip_path, dest_dir, OTA_data_ZIP)
                        if success:
                            logger.debug(f"Extraction réussie : {message}")
                            config.loading_progress = 60.0
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
                    config.loading_progress = 60.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                else:
                    loading_step = "load_sources"
                    config.current_loading_system = "Chargement des systèmes..."
                    config.loading_progress = 60.0
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
                    config.loading_progress = 0.0
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

        clock.tick(60)
        await asyncio.sleep(0.01)

    pygame.mixer.music.stop()
    pygame.quit()
    logger.debug("Application terminée")

# Fonction pour vérifier si un événement correspond à une action
def is_input_matched(event, action_name):
    if not config.controls_config.get(action_name):
        return False
    mapping = config.controls_config[action_name]
    input_type = mapping["type"]
    input_value = mapping["value"]

    if input_type == "key" and event.type == pygame.KEYDOWN:
        return event.key == input_value
    elif input_type == "button" and event.type == pygame.JOYBUTTONDOWN:
        return event.button == input_value
    elif input_type == "axis" and event.type == pygame.JOYAXISMOTION:
        axis, direction = input_value
        return event.axis == axis and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == direction
    elif input_type == "hat" and event.type == pygame.JOYHATMOTION:
        return event.value == input_value
    elif input_type == "mouse" and event.type == pygame.MOUSEBUTTONDOWN:
        return event.button == input_value
    return False

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())
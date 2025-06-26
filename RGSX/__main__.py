import os
os.environ["SDL_FBDEV"] = "/dev/fb0"
import pygame
import asyncio
import platform
import subprocess
import math
import logging
from display import init_display, draw_loading_screen, draw_error_screen, draw_platform_grid, draw_progress_screen, draw_scrollbar, draw_confirm_dialog, draw_controls, draw_gradient, draw_virtual_keyboard, draw_popup_message, draw_extension_warning
from network import test_internet, download_rom, check_extension_before_download
from cache import load_sources, cache_system_image, cache_games_list, load_games, get_system_image, load_image
from controls import handle_controls
from utils import truncate_text_end
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

# Initialisation de Pygame
pygame.init()
pygame.joystick.init()

# Détection système non-PC basée sur l'architecture
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
config.selected_key = (0, 0)  # Pour le clavier virtuel
config.transition_state = "none"

# Initialisation des variables de répétition
config.repeat_action = None
config.repeat_start_time = 0
config.repeat_last_action = 0

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

# Recherche des fichiers .ogg et .mp3
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

# Boucle principale
async def main():
    logger.debug("Début main")
    running = True
    loading_step = "none"
    loading_index = 0
    sources = []
    config.last_state_change_time = 0
    config.debounce_delay = 200
    config.menu_state = "loading"  # Commencer directement en loading

    while running:
        current_time = pygame.time.get_ticks()
        config.needs_redraw = False

        # Gestion de l’état de chargement
        if config.menu_state == "loading":
            if loading_step == "none":
                loading_step = "test_internet"
                config.current_loading_system = "Test de connexion..."
                config.loading_progress = 0.0
                config.needs_redraw = True
                logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
            elif loading_step == "test_internet":
                if test_internet():
                    loading_step = "load_sources"
                    config.current_loading_system = "des systèmes... la 1ère fois peut être longue.."
                    config.loading_progress = 5.0
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, progress={config.loading_progress}")
                else:
                    config.menu_state = "error"
                    config.error_message = "Pas de connexion Internet. Vérifiez votre réseau."
                    config.needs_redraw = True
                    logger.debug(f"Erreur : {config.error_message}")
            elif loading_step == "load_sources":
                sources = load_sources()
                config.games_count = {platform: None for platform in config.platforms}
                config.loading_games_count = {platform: False for platform in config.platforms}
                loading_step = "cache_images"
                config.current_loading_system = config.platforms[0] if config.platforms else ""
                loading_index = 0
                config.loading_progress = 10.0
                config.needs_redraw = True
                logger.debug(f"Étape chargement : {loading_step}, system={config.current_loading_system}, progress={config.loading_progress}")
            elif loading_step == "cache_images":
                if loading_index < len(config.platforms):
                    platform = config.platforms[loading_index]
                    config.current_loading_system = f"des images : {platform} ({loading_index + 1}/{len(config.platforms)})"
                    for source in sources:
                        if source["platform"] == platform and source.get("system_image"):
                            cache_system_image(platform, source["system_image"])
                            break
                    config.loading_progress = 10.0 + (40.0 * (loading_index + 1) / len(config.platforms))
                    loading_index += 1
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, system={config.current_loading_system}, progress={config.loading_progress}")
                else:
                    loading_step = "cache_games"
                    loading_index = 0
                    config.current_loading_system = config.platforms[0] if config.platforms else ""
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, system={config.current_loading_system}, progress={config.loading_progress}")
            elif loading_step == "cache_games":
                if loading_index < len(config.platforms):
                    platform = config.platforms[loading_index]
                    config.current_loading_system = f"des jeux : {platform} ({loading_index + 1}/{len(config.platforms)})"
                    games_list = cache_games_list(platform, sources)
                    config.games_count[platform] = len(games_list)
                    config.loading_progress = 50.0 + (50.0 * (loading_index + 1) / len(config.platforms))
                    loading_index += 1
                    config.needs_redraw = True
                    logger.debug(f"Étape chargement : {loading_step}, system={config.current_loading_system}, progress={config.loading_progress}")
                else:
                    config.menu_state = "platform"
                    config.loading_progress = 0.0
                    config.current_loading_system = ""
                    config.needs_redraw = True
                    logger.debug(f"Fin chargement, passage à platform, progress={config.loading_progress}")

        # Gestion des événements
        events = pygame.event.get()
        action = handle_controls(events, current_time, joystick, screen)
        if action == "quit":
            running = False
            break
        if action == "download" and config.menu_state == "game":
            game, url, _ = config.filtered_games[config.current_game]
            platform = config.platforms[config.current_platform]
            is_supported, message, is_zip_non_supported = check_extension_before_download(url, platform, game)
            if is_supported:
                logger.debug(f"Extension supportée, lancement téléchargement: url={url}, game_name={game}")
                task = asyncio.create_task(download_rom(url, platform, game, is_zip_non_supported=False))
                config.download_tasks[task] = (task, url, game, platform)
                config.menu_state = "download_progress"
                config.needs_redraw = True
                logger.debug(f"Passage à download_progress pour {game}")
            else:
                logger.debug(f"Extension non supportée pour {game}, passage à extension_warning")
                config.pending_download = (url, platform, game, is_zip_non_supported)
                config.extension_confirm_selection = 0
                config.menu_state = "extension_warning"
                config.download_result_message = message
                config.download_result_error = True
                config.needs_redraw = True
        elif action == "confirm" and config.menu_state == "extension_warning" and config.extension_confirm_selection == 0:
            if config.pending_download:
                url, platform, game, is_zip_non_supported = config.pending_download
                logger.debug(f"Confirmation téléchargement non supporté: url={url}, game_name={game}, is_zip_non_supported={is_zip_non_supported}")
                task = asyncio.create_task(download_rom(url, platform, game, is_zip_non_supported=is_zip_non_supported))
                config.download_tasks[task] = (task, url, game, platform)
                config.menu_state = "download_progress"
                config.pending_download = None
                config.needs_redraw = True
                logger.debug(f"Passage à download_progress pour {game}")
        elif action == "cancel" and config.menu_state == "extension_warning":
            config.menu_state = "game"
            config.pending_download = None
            config.needs_redraw = True
            logger.debug("Annulation téléchargement, retour à game")

        # Vérifier les téléchargements terminés
        completed = []
        for task, (task_obj, url, game_name, platform) in list(config.download_tasks.items()):
            if task.done():
                try:
                    success, msg = task.result()
                    config.download_result_message = f"Téléchargement terminé : {game_name}" if success else f"Erreur : {msg}"
                    config.download_result_error = not success
                    config.menu_state = "download_result"
                    config.download_result_start_time = current_time
                    config.needs_redraw = True
                    logger.debug(f"Téléchargement terminé pour {game_name}, succès={success}, message={msg}")
                except Exception as e:
                    config.download_result_message = f"Erreur inattendue : {str(e)}"
                    config.download_result_error = True
                    config.menu_state = "download_result"
                    config.download_result_start_time = current_time
                    config.needs_redraw = True
                    logger.error(f"Erreur dans tâche téléchargement pour {game_name}: {str(e)}")
                completed.append(task)
                if url in config.download_progress:
                    del config.download_progress[url]
        for task in completed:
            del config.download_tasks[task]
            logger.debug(f"Tâche supprimée : {task}")

        # Rendu
        if config.needs_redraw or config.menu_state == "loading" or (config.menu_state == "download_progress" and current_time - config.last_progress_update >= 50) or (config.download_tasks and config.menu_state in ["platform", "game"] and current_time - config.last_progress_update >= 100):
            draw_gradient(screen, (28, 37, 38), (47, 59, 61))
            if config.menu_state == "loading":
                draw_loading_screen(screen)
            elif config.menu_state == "error":
                draw_error_screen(screen)
            elif config.menu_state == "platform":
                platform = config.platforms[config.selected_platform] if config.platforms else "Aucune plateforme"
                games_count = config.games_count.get(platform, 0)
                platform_name = config.platform_names.get(platform, platform)
                title = f"{platform_name.upper()} : {games_count} jeux"
                text = config.title_font.render(title, True, (255, 255, 255))
                text_rect = text.get_rect(center=(config.screen_width // 2, 50))
                pygame.draw.rect(screen, (50, 50, 50, 200), text_rect.inflate(20, 10))
                pygame.draw.rect(screen, (255, 255, 255), text_rect.inflate(20, 10), 2)
                screen.blit(text, text_rect)
                draw_platform_grid(screen)
                total_pages = max(1, math.ceil(len(config.platforms) / 9))
                page_text = config.font.render(f"Page {config.current_page + 1}/{total_pages}", True, (255, 255, 255))
                screen.blit(page_text, (50, config.screen_height - 50))
                draw_controls(screen, config.menu_state)
            
            elif config.menu_state == "game":
                platform = config.platforms[config.current_platform] if config.platforms else None
                platform_name = config.platform_names.get(platform, platform) if platform else "Aucun jeu"
                title = f"{config.games_count.get(platform, 0)} Jeux - {platform_name.upper()}" if config.platforms else "Aucun jeu"
                text = config.title_font.render(title, True, (255, 255, 255))
                text_rect = text.get_rect(center=(config.screen_width // 2, 50))
                pygame.draw.rect(screen, (50, 50, 50, 200), text_rect.inflate(20, 10))
                pygame.draw.rect(screen, (255, 255, 255), text_rect.inflate(20, 10), 2)
                screen.blit(text, text_rect)
                game_area_height = config.screen_height - 150
                line_spacing = 50
                start_index = config.scroll_offset
                config.visible_games = max(1, game_area_height // line_spacing)
                end_index = min(config.scroll_offset + config.visible_games, len(config.filtered_games))
                for i, (game, _, image_url) in enumerate(config.filtered_games[start_index:end_index]):
                    y_pos = 120 + i * line_spacing
                    if (i + start_index) == config.current_game:
                        pygame.draw.rect(screen, (0, 150, 255, 80), (20, y_pos - 5, config.screen_width - 40, line_spacing), border_radius=5)
                    if image_url:
                        image = load_image(image_url, width=40, height=40)
                        if image:
                            screen.blit(image, (30, y_pos))
                    color = (255, 255, 0) if (i + start_index) == config.current_game else (255, 255, 255)
                    truncated_game = truncate_text_end(game, config.font, config.screen_width - 150)
                    text = config.font.render(truncated_game, True, color)
                    screen.blit(text, (80, y_pos))
                    if i < end_index - start_index - 1:
                        pygame.draw.line(screen, (100, 100, 100), (20, y_pos + line_spacing - 5), (config.screen_width - 40, y_pos + line_spacing - 5))

                pygame.draw.rect(screen, (255, 255, 255), (config.screen_width - 25, 120, 15, game_area_height), 2)
                draw_scrollbar(screen)

                if config.search_mode:
                    logger.debug("Rendu champ de recherche")
                    pygame.draw.rect(screen, (0, 0, 0, 150), (0, 0, config.screen_width, config.screen_height))
                    search_text = f"Filtre: {config.search_query}_"
                    search_render = config.search_font.render(search_text, True, (255, 255, 255))
                    search_rect = search_render.get_rect(center=(config.screen_width // 2, 120))
                    pygame.draw.rect(screen, (0, 0, 0, 150), search_rect.inflate(40, 20).move(5, 5))
                    pygame.draw.rect(screen, (80, 80, 80, 255), search_rect.inflate(40, 20))
                    pygame.draw.rect(screen, (255, 255, 255), search_rect.inflate(40, 20), 2)
                    screen.blit(search_render, search_rect)
                    if config.is_non_pc:
                        draw_virtual_keyboard(screen)

                draw_controls(screen, config.menu_state)
            elif config.menu_state == "download_progress":
                logger.debug(f"Menu state : download_progress, tasks={len(config.download_tasks)}")
                if config.download_tasks:
                    task = list(config.download_tasks.keys())[0]
                    url = config.download_tasks[task][1]
                    progress = config.download_progress.get(url, {"downloaded_size": 0, "total_size": 0, "status": "Downloading"})
                    status = progress.get("status", "Downloading")
                    if current_time - config.last_progress_update >= 50 or status == "Extracting":
                        draw_gradient(screen, (28, 37, 38), (47, 59, 61))
                        draw_progress_screen(screen)
                        config.last_progress_update = current_time
                        draw_controls(screen, config.menu_state)
                        pygame.display.flip()
                        logger.debug(f"Écran rafraîchi pour download_progress, status={status}")
                else:
                    logger.debug("Aucun téléchargement actif, retour à game")
                    draw_gradient(screen, (28, 37, 38), (47, 59, 61))
                    text = config.font.render("Aucun téléchargement", True, (255, 255, 255))
                    screen.blit(text, (50, config.screen_height // 2))
                    config.menu_state = "game"
                    config.needs_redraw = True
                    draw_controls(screen, config.menu_state)
                    pygame.display.flip()
            elif config.menu_state == "confirm_exit":
                draw_platform_grid(screen)
                draw_confirm_dialog(screen)
            elif config.menu_state == "download_result":
                draw_popup_message(screen, config.download_result_message, config.download_result_error)
                if current_time - config.download_result_start_time > 3000:
                    config.menu_state = "game"
                    config.needs_redraw = True
            elif config.menu_state == "extension_warning":
                draw_gradient(screen, (28, 37, 38), (47, 59, 61))
                draw_extension_warning(screen)
                draw_controls(screen, config.menu_state)

            # Afficher la notification de téléchargement en haut à droite sur deux lignes
            if config.download_tasks and config.menu_state in ["platform", "game"]:
                task = list(config.download_tasks.keys())[0]
                game_name = config.download_tasks[task][2]
                url = config.download_tasks[task][1]
                progress = config.download_progress.get(url, {"downloaded_size": 0, "total_size": 0, "status": "Downloading"})
                progress_percent = progress.get("progress_percent", 0)
                percent_text = f"Téléchargement : {int(progress_percent)}%"
                percent_text_truncated = truncate_text_end(percent_text, config.small_font, 400)
                percent_text_render = config.small_font.render(percent_text_truncated, True, (200, 200, 200))
                percent_width, percent_height = percent_text_render.get_size()
                game_text = f"{game_name}"
                game_text_truncated = truncate_text_end(game_text, config.small_font, 400)
                game_text_render = config.small_font.render(game_text_truncated, True, (200, 200, 200))
                game_width, game_height = game_text_render.get_size()
                text_width = max(0, percent_width, game_width)
                text_height = percent_height + game_height + 5
                rect_x = config.screen_width - text_width - 20
                rect_y = 50
                pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x - 5, rect_y - 5, text_width + 10, text_height + 10))
                screen.blit(percent_text_render, (rect_x, rect_y))
                screen.blit(game_text_render, (rect_x, rect_y + percent_height + 5))
                config.last_progress_update = current_time

            pygame.display.flip()
        clock.tick(60)
        await asyncio.sleep(1.0 / 60)

    for task, (_, _, _, _) in config.download_tasks.items():
        task.cancel()
    pygame.quit()
    logger.debug("Fin main")

def start_transition(event255):
    logger.info(f"Début start_transition : {event255}")
    config.current_platform = config.selected_platform
    config.needs_redraw = True

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())
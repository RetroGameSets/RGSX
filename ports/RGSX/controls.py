import pygame # type: ignore
import shutil
import asyncio
import json
import re
import os
import datetime
import threading
import logging
import config
from config import REPEAT_DELAY, REPEAT_INTERVAL, REPEAT_ACTION_DEBOUNCE, CONTROLS_CONFIG_PATH
from display import draw_validation_transition, show_toast
from network import download_rom, download_from_1fichier, is_1fichier_url, request_cancel
from utils import (
    load_games, check_extension_before_download, is_extension_supported,
    load_extensions_json, play_random_music, sanitize_filename,
    save_music_config, load_api_keys, _get_dest_folder_name,
    extract_zip, extract_rar, find_file_with_or_without_extension, toggle_web_service_at_boot, check_web_service_status,
    restart_application, generate_support_zip, load_sources,
    ensure_download_provider_keys, missing_all_provider_keys, build_provider_paths_string
)
from history import load_history, clear_history, add_to_history, save_history
from language import _, get_available_languages, set_language  
from rgsx_settings import (
    get_allow_unknown_extensions, set_display_grid, get_font_family, set_font_family,
    get_show_unsupported_platforms, set_show_unsupported_platforms,
    set_allow_unknown_extensions, get_hide_premium_systems, set_hide_premium_systems,
    get_sources_mode, set_sources_mode, set_symlink_option, get_symlink_option, load_rgsx_settings, save_rgsx_settings
)
from accessibility import save_accessibility_settings
from scraper import get_game_metadata, download_image_to_surface

logger = logging.getLogger(__name__)

# Extensions d'archives pour lesquelles on ignore l'avertissement d'extension non supportée
ARCHIVE_EXTENSIONS = {'.zip', '.7z', '.rar', '.tar', '.gz', '.xz', '.bz2'}


# Variables globales pour la répétition
key_states = {}  # Dictionnaire pour suivre l'état des touches

# Liste des états valides
VALID_STATES = [
    "platform", "game", "confirm_exit",
    "extension_warning", "pause_menu", "controls_help", "history", "controls_mapping",
    "reload_games_data", "restart_popup", "error", "loading", "confirm_clear_history",
    "language_select", "filter_platforms", "display_menu", "confirm_cancel_download",
    "gamelist_update_prompt", "platform_folder_config",
    # Nouveaux sous-menus hiérarchiques (refonte pause menu)
    "pause_controls_menu",      # sous-menu Controls (aide, remap)
    "pause_display_menu",       # sous-menu Display (layout, font size, unsupported, unknown ext, filter)
    "pause_display_layout_menu",# sous-menu Display > Layout (disposition avec visualisation)
    "pause_display_font_menu",  # sous-menu Display > Font (taille police + footer)
    "pause_games_menu",         # sous-menu Games (source mode, update/redownload cache)
    "pause_settings_menu",      # sous-menu Settings (music on/off, symlink toggle, api keys status)
    "pause_api_keys_status",    # sous-menu API Keys (affichage statut des clés)
    # Nouveaux menus historique
    "history_game_options",     # menu options pour un jeu de l'historique
    "history_show_folder",      # afficher le dossier de téléchargement
    "history_scraper_info",     # info scraper non implémenté
    "scraper",                  # écran du scraper avec métadonnées
    "history_error_details",    # détails de l'erreur
    "history_confirm_delete",   # confirmation suppression jeu
    "history_extract_archive",  # extraction d'archive
    "text_file_viewer",         # visualiseur de fichiers texte
    # Nouveaux menus filtrage avancé
    "filter_menu_choice",       # menu de choix entre recherche et filtrage avancé
    "filter_search",            # recherche par nom (existant, mais renommé)
    "filter_advanced",          # filtrage avancé par région, etc.
    "filter_priority_config",   # configuration priorité régions pour one-rom-per-game
    "platform_folder_config",   # configuration du dossier personnalisé pour une plateforme
    "folder_browser",           # navigateur de dossiers intégré
    "folder_browser_new_folder", # création d'un nouveau dossier
]

def validate_menu_state(state):
    if state not in VALID_STATES:
        logger.debug(f"État invalide {state}, retour à platform")
        return "platform"
    return state


def load_controls_config(path=CONTROLS_CONFIG_PATH):
    """Charge la configuration des contrôles.
    Priorité:
    1) Fichier utilisateur dans SAVE_FOLDER (controls.json)
    2) Préréglage correspondant dans PRECONF_CONTROLS_PATH (sans copie)
    3) Configuration clavier par défaut
    """
    default_config = {
        "confirm": {"type": "key", "key": pygame.K_RETURN},
        "cancel": {"type": "key", "key": pygame.K_ESCAPE},
        "left": {"type": "key", "key": pygame.K_LEFT},
        "right": {"type": "key", "key": pygame.K_RIGHT},
        "up": {"type": "key", "key": pygame.K_UP},
        "down": {"type": "key", "key": pygame.K_DOWN},
        "start": {"type": "key", "key": pygame.K_p},
        "clear_history": {"type": "key", "key": pygame.K_x},
        "history": {"type": "key", "key": pygame.K_h},
        "page_up": {"type": "key", "key": pygame.K_PAGEUP},
        "page_down": {"type": "key", "key": pygame.K_PAGEDOWN},
        "filter": {"type": "key", "key": pygame.K_f},
        "delete": {"type": "key", "key": pygame.K_BACKSPACE},
        "space": {"type": "key", "key": pygame.K_SPACE}
    }
    
    try:
        # 1) Fichier utilisateur
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            # Compléter les actions manquantes, et sauve seulement si le fichier utilisateur existe
            changed = False
            for k, v in default_config.items():
                if k not in data:
                    data[k] = v
                    changed = True
            if changed:
                try:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2)
                    logging.getLogger(__name__).debug(f"controls.json complété avec les actions manquantes: {path}")
                except Exception as e:
                    logging.getLogger(__name__).warning(f"Impossible d'écrire les actions manquantes dans {path}: {e}")
            return data

        # 2) Préréglages sans copie si aucun fichier utilisateur
        try:
            # --- Auto-match par nom de périphérique détecté ---
            def _sanitize(s: str) -> str:
                s = (s or "").strip().lower()
                s = re.sub(r"[^a-z0-9]+", "_", s)
                s = re.sub(r"_+", "_", s).strip("_")
                return s

            def _extract_device_from_comment(val: str) -> str:
                try:
                    if not isinstance(val, str):
                        return ""
                    # Expect formats like "# Device: NAME" or just NAME
                    if "Device:" in val:
                        part = val.split("Device:", 1)[1]
                        return part.strip().lstrip('#').strip()
                    return val.strip().lstrip('#').strip()
                except Exception:
                    return ""

            device_name = getattr(config, 'controller_device_name', '') or ''
            if getattr(config, 'joystick', False) and device_name:
                target_norm = _sanitize(device_name)
                try:
                    for fname in os.listdir(config.PRECONF_CONTROLS_PATH):
                        if not fname.lower().endswith('.json'):
                            continue
                        src = os.path.join(config.PRECONF_CONTROLS_PATH, fname)
                        try:
                            with open(src, 'r', encoding='utf-8') as f:
                                preset = json.load(f)
                        except Exception:
                            continue
                        # Match by explicit device field
                        dev_field = preset.get('device') if isinstance(preset, dict) else None
                        if isinstance(dev_field, str) and _sanitize(dev_field) == target_norm:
                            logging.getLogger(__name__).info(f"Chargement préréglage (device) depuis le fichier: {fname}")
                            print(f"Chargement prereglage (device) depuis le fichier: {fname}")
                            return preset
                except Exception as e:
                    logging.getLogger(__name__).warning(f"Échec scan préréglages par device: {e}")

            # Fallback préréglage explicite clavier si pas de joystick
            if not getattr(config, 'joystick', False) or getattr(config, 'keyboard', False):
                src = os.path.join(config.PRECONF_CONTROLS_PATH, 'keyboard.json')
                if os.path.exists(src):
                    with open(src, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, dict) and data:
                            logging.getLogger(__name__).info("Chargement des contrôles préréglés: keyboard.json")
                            return data
        except Exception as e:
            logging.getLogger(__name__).warning(f"Échec du chargement des contrôles préréglés: {e}")

        # 3) Fallback: si joystick présent mais aucun préréglage trouvé, retourner {} pour déclencher le remap
        if getattr(config, 'joystick', False):
            logging.getLogger(__name__).info("Aucun préréglage trouvé pour le joystick connecté, ouverture du remap")
            return {}
        # Sinon, fallback clavier par défaut
        logging.getLogger(__name__).info("Aucun fichier utilisateur ou préréglage trouvé, utilisation des contrôles clavier par défaut")
        return default_config.copy()
    
    except Exception as e:
        logging.getLogger(__name__).error(f"Erreur load_controls_config: {e}")
        return default_config.copy()

# Fonction pour vérifier si un événement correspond à une action
def is_input_matched(event, action_name):
    if not config.controls_config.get(action_name):
        return False
    mapping = config.controls_config[action_name]
    input_type = mapping["type"]
    
    if input_type == "key" and event.type == pygame.KEYDOWN:
        return event.key == mapping.get("key")
    elif input_type == "button" and event.type == pygame.JOYBUTTONDOWN:
        return event.button == mapping.get("button")
    elif input_type == "axis" and event.type == pygame.JOYAXISMOTION:
        axis = mapping.get("axis")
        direction = mapping.get("direction")
        threshold = 0.5
        # Pour les triggers Xbox (axes 4 et 5), la position de repos est -1.0
        # Il faut inverser la détection : direction -1 = trigger appuyé (vers +1.0)
        if axis in [4, 5]:
            # Triggers Xbox: repos à -1.0, appuyé vers +1.0
            # On inverse la direction configurée
            if direction == -1:
                # Direction -1 configurée = détecter quand trigger appuyé (valeur positive)
                return event.axis == axis and event.value > threshold
            else:
                # Direction +1 configurée = détecter aussi quand trigger appuyé
                return event.axis == axis and event.value > threshold
        else:
            # Autres axes: logique normale
            return event.axis == axis and abs(event.value) > threshold and (1 if event.value > 0 else -1) == direction
    elif input_type == "hat" and event.type == pygame.JOYHATMOTION:
        hat_value = mapping.get("value")
        if isinstance(hat_value, list):
            hat_value = tuple(hat_value)
        return event.value == hat_value
    elif input_type == "mouse" and event.type == pygame.MOUSEBUTTONDOWN:
        return event.button == mapping.get("button")
    
    # Fallback clavier pour dépannage (fonctionne toujours même avec manette configurée)
    if event.type == pygame.KEYDOWN:
        keyboard_fallback = {
            "up": pygame.K_UP,
            "down": pygame.K_DOWN,
            "left": pygame.K_LEFT,
            "right": pygame.K_RIGHT,
            "confirm": pygame.K_RETURN,
            "cancel": pygame.K_ESCAPE,
            "start": pygame.K_RALT,
            "filter": pygame.K_f,
            "history": pygame.K_h,
            "clear_history": pygame.K_DELETE,
            "delete": pygame.K_d,
            "space": pygame.K_SPACE,
            "page_up": pygame.K_PAGEUP,
            "page_down": pygame.K_PAGEDOWN,
        }
        if action_name in keyboard_fallback:
            return event.key == keyboard_fallback[action_name]
    
    return False

def _launch_next_queued_download():
    """Lance le prochain téléchargement de la queue si aucun n'est actif.
    Gère la liaison entre le système Desktop et le système de download_rom/download_from_1fichier.
    """
    if config.download_active or not config.download_queue:
        return
    
    queue_item = config.download_queue.pop(0)
    config.download_active = True
    
    url = queue_item['url']
    platform = queue_item['platform']
    game_name = queue_item['game_name']
    is_zip_non_supported = queue_item['is_zip_non_supported']
    is_1fichier = queue_item['is_1fichier']
    task_id = queue_item['task_id']
    
    # Mettre à jour le statut dans l'historique: queued -> Downloading
    for entry in config.history:
        if entry.get('task_id') == task_id and entry.get('status') == 'Queued':
            entry['status'] = 'Downloading'
            entry['message'] = _("download_in_progress")
            save_history(config.history)
            break
    
    logger.info(f"📋 Lancement du téléchargement de la queue: {game_name} (task_id={task_id})")
    
    # Lancer le téléchargement de manière asynchrone avec callback
    try:
        if is_1fichier:
            task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
        else:
            task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))
        
        config.download_tasks[task_id] = (task, url, game_name, platform)
        
        # Callback invoqué quand la tâche est terminée
        def on_task_done(t):
            try:
                # Récupérer le résultat (si erreur, elle sera levée ici)
                result = t.result()
            except asyncio.CancelledError:
                logger.info(f"Tâche annulée pour {game_name} (task_id={task_id})")
            except Exception as e:
                logger.error(f"Erreur tâche download {game_name}: {e}")
            finally:
                # Toujours marquer comme inactif et lancer le prochain
                config.download_active = False
                if config.download_queue:
                    _launch_next_queued_download()
        
        # Ajouter le callback à la tâche
        task.add_done_callback(on_task_done)
        
    except Exception as e:
        logger.error(f"Erreur lancement queue download: {e}")
        config.download_active = False
        # Mettre à jour l'historique en erreur
        for entry in config.history:
            if entry.get('task_id') == task_id:
                entry['status'] = 'Erreur'
                entry['message'] = str(e)
                save_history(config.history)
                break
        # Relancer le suivant
        if config.download_queue:
            _launch_next_queued_download()

def handle_controls(event, sources, joystick, screen):
    """Gère un événement clavier/joystick/souris et la répétition automatique.
    Retourne 'quit', 'download', 'redownload', ou None."""  
    action = None
    current_time = pygame.time.get_ticks()
    global _
    # Valider previous_menu_state avant tout traitement
    config.previous_menu_state = validate_menu_state(config.previous_menu_state)

    # Debounce général
    if current_time - config.last_state_change_time < config.debounce_delay:
        return action

    # --- CLAVIER, MANETTE, SOURIS ---
    if event.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION, pygame.JOYHATMOTION, pygame.MOUSEBUTTONDOWN):
        # Débouncer les événements JOYHATMOTION
        if event.type == pygame.JOYHATMOTION:
            if event.value == (0, 0):  # Ignorer les relâchements
                # Mettre à jour l'état des touches directionnelles
                for action in ["up", "down", "left", "right"]:
                    update_key_state(action, False)
                return action

        # Quitter l'appli
        if event.type == pygame.QUIT:
            logger.debug("Événement pygame.QUIT détecté")
            return "quit"
        
        # Menu pause
        if is_input_matched(event, "start") and config.menu_state not in ("pause_menu", "controls_mapping", "reload_games_data"):
            config.previous_menu_state = config.menu_state
            config.menu_state = "pause_menu"
            config.selected_option = 0
            config.needs_redraw = True
            logger.debug(f"Passage à pause_menu depuis {config.previous_menu_state}")
            return action

        # Erreur
        if config.menu_state == "error":
            if is_input_matched(event, "confirm"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug("Sortie du menu erreur avec Confirm")
                
        #Plateformes
        elif config.menu_state == "platform":
            systems_per_page = config.GRID_COLS * config.GRID_ROWS
            max_index = min(systems_per_page, len(config.platforms) - config.current_page * systems_per_page) - 1
            current_grid_index = config.selected_platform - config.current_page * systems_per_page
            row = current_grid_index // config.GRID_COLS
            col = current_grid_index % config.GRID_COLS
            
            # Espace réservé pour des fonctions helper si nécessaire

            if is_input_matched(event, "down"):
                # Navigation vers le bas avec gestion des limites de page
                if current_grid_index + config.GRID_COLS <= max_index:
                    # Déplacement normal vers le bas
                    config.selected_platform += config.GRID_COLS
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif (config.current_page + 1) * systems_per_page < len(config.platforms):
                    # Passage à la page suivante si on est en bas de la grille
                    config.current_page += 1
                    new_row = 0  # Première ligne de la nouvelle page
                    config.selected_platform = config.current_page * systems_per_page + new_row * config.GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "up"):
                # Navigation vers le haut avec gestion des limites de page
                if current_grid_index - config.GRID_COLS >= 0:
                    # Déplacement normal vers le haut
                    config.selected_platform -= config.GRID_COLS
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif config.current_page > 0:
                    # Passage à la page précédente si on est en haut de la grille
                    config.current_page -= 1
                    new_row = config.GRID_ROWS - 1  # Dernière ligne de la page précédente
                    config.selected_platform = config.current_page * systems_per_page + new_row * config.GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "left"):
                if col > 0:
                    # Déplacement normal vers la gauche
                    config.selected_platform -= 1
                    update_key_state("left", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif config.current_page > 0:
                    # Passage à la page précédente si on est à la première colonne
                    config.current_page -= 1
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS + (config.GRID_COLS - 1)
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    update_key_state("left", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "right"):
                if col < config.GRID_COLS - 1 and current_grid_index < max_index:
                    # Déplacement normal vers la droite
                    config.selected_platform += 1
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif (config.current_page + 1) * systems_per_page < len(config.platforms):
                    # Passage à la page suivante si on est à la dernière colonne
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "page_down"):
                # Navigation rapide vers la page suivante
                if (config.current_page + 1) * systems_per_page < len(config.platforms):
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    # Réinitialiser la répétition pour éviter des comportements inattendus
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
            elif is_input_matched(event, "page_up"):
                # Navigation rapide vers la page précédente
                if config.current_page > 0:
                    config.current_page -= 1
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    # Réinitialiser la répétition pour éviter des comportements inattendus
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
            elif is_input_matched(event, "history"):
                # Capturer l'origine si on vient directement des plateformes
                config.history_origin = "platform"
                config.menu_state = "history"
                config.needs_redraw = True
                logger.debug("Ouverture history depuis platform")
            elif is_input_matched(event, "confirm"):
                # Démarrer le chronomètre pour l'appui long - ne pas exécuter immédiatement
                # L'action sera exécutée au relâchement si appui court, ou config dossier si appui long
                if not hasattr(config, 'platform_confirm_press_start_time'):
                    config.platform_confirm_press_start_time = 0
                if not hasattr(config, 'platform_confirm_long_press_triggered'):
                    config.platform_confirm_long_press_triggered = False
                
                config.platform_confirm_press_start_time = current_time
                config.platform_confirm_long_press_triggered = False
                config.needs_redraw = True
                # Note: la navigation vers les jeux sera gérée au BUTTONUP/KEYUP si appui court
            elif is_input_matched(event, "cancel"):
                # Capturer l'origine (plateformes) pour un retour correct si l'utilisateur choisit "Non"
                config.confirm_exit_origin = "platform"
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0
                config.needs_redraw = True

        # Jeux
        elif config.menu_state == "game":
            games = config.filtered_games if config.filter_active or config.search_mode else config.games
            if config.search_mode and getattr(config, 'joystick', False):
                keyboard_layout = [
                    ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
                    ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
                    ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
                    ['W', 'X', 'C', 'V', 'B', 'N']
                ]
                row, col = config.selected_key
                max_row = len(keyboard_layout) - 1
                max_col = len(keyboard_layout[row]) - 1
                if is_input_matched(event, "up"):
                    if row == 0: # if you are in the first row and press UP jump to last row
                        row = max_row + (1 if col <= 5 else 0)
                    if row > 0:
                        config.selected_key = (row - 1, min(col, len(keyboard_layout[row - 1]) - 1))
                        config.repeat_action = "up"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    if (col <= 5 and row == max_row) or (col > 5 and row == max_row-1): # if you are in the last row and press DOWN jump to first row
                        row = -1
                    if row < max_row:
                        config.selected_key = (row + 1, min(col, len(keyboard_layout[row + 1]) - 1))
                        config.repeat_action = "down"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "left"):
                    if col == 0: # if you are in the first col and press LEFT jump to last col
                        col = max_col + 1
                    if col > 0:
                        config.selected_key = (row, col - 1)
                        config.repeat_action = "left"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "right"):
                    if col == max_col: # if you are in the last col and press RIGHT jump to first col
                        col = -1
                    if col < max_col:
                        config.selected_key = (row, col + 1)
                        config.repeat_action = "right"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "confirm"):
                    config.search_query += keyboard_layout[row][col]
                    # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                    base_games = config.games
                    if config.game_filter_obj and config.game_filter_obj.is_active():
                        base_games = config.game_filter_obj.apply_filters(config.games)
                    config.filtered_games = [game for game in base_games if config.search_query.lower() in game[0].lower()]
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug(f"Recherche mise à jour: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "delete"):
                    if config.search_query:
                        config.search_query = config.search_query[:-1]
                        # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                        base_games = config.games
                        if config.game_filter_obj and config.game_filter_obj.is_active():
                            base_games = config.game_filter_obj.apply_filters(config.games)
                        config.filtered_games = [game for game in base_games if config.search_query.lower() in game[0].lower()]
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        #logger.debug(f"Suppression caractère: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "space"):
                    config.search_query += " "
                    # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                    base_games = config.games
                    if config.game_filter_obj and config.game_filter_obj.is_active():
                        base_games = config.game_filter_obj.apply_filters(config.games)
                    config.filtered_games = [game for game in base_games if config.search_query.lower() in game[0].lower()]
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    #logger.debug(f"Espace ajouté: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "cancel"):
                    config.search_mode = False
                    config.search_query = ""
                    config.selected_key = (0, 0)
                    # Restaurer les jeux filtrés par les filtres avancés si actifs
                    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                        config.filtered_games = config.game_filter_obj.apply_filters(config.games)
                        config.filter_active = True
                    else:
                        config.filtered_games = config.games
                        config.filter_active = False
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Sortie du mode recherche")
                elif is_input_matched(event, "filter"):
                    config.search_mode = False
                    config.filter_active = bool(config.search_query)
                    config.needs_redraw = True
                    logger.debug(f"Validation du filtre avec manette: query={config.search_query}, filter_active={config.filter_active}")  
            elif config.search_mode and not getattr(config, 'joystick', False):
                # Gestion de la recherche sur PC (clavier et manette)
                if is_input_matched(event, "confirm"):
                    config.search_mode = False
                    config.filter_active = True
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug(f"Validation du filtre avec bouton entree sur PC: query={config.search_query}")
                elif is_input_matched(event, "cancel"):
                    config.search_mode = False
                    config.search_query = ""
                    # Restaurer les jeux filtrés par les filtres avancés si actifs
                    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                        config.filtered_games = config.game_filter_obj.apply_filters(config.games)
                        config.filter_active = True
                    else:
                        config.filtered_games = config.games
                        config.filter_active = False
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Sortie du mode recherche avec bouton cancel sur PC")
                elif event.type == pygame.KEYDOWN:
                    # Saisie de texte alphanumérique
                    if event.unicode.isalnum() or event.unicode == ' ':
                        config.search_query += event.unicode
                        # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                        base_games = config.games
                        if config.game_filter_obj and config.game_filter_obj.is_active():
                            base_games = config.game_filter_obj.apply_filters(config.games)
                        config.filtered_games = [game for game in base_games if config.search_query.lower() in game[0].lower()]
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug(f"Recherche mise à jour: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                    # Gestion de la suppression
                    elif is_input_matched(event, "delete"):
                        if config.search_query:
                            config.search_query = config.search_query[:-1]
                            # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                            base_games = config.games
                            if config.game_filter_obj and config.game_filter_obj.is_active():
                                base_games = config.game_filter_obj.apply_filters(config.games)
                            config.filtered_games = [game for game in base_games if config.search_query.lower() in game[0].lower()]
                            config.current_game = 0
                            config.scroll_offset = 0
                            config.needs_redraw = True
                            logger.debug(f"Suppression caractère: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                  
     
            else:
                if is_input_matched(event, "up"):
                    if config.current_game > 0:
                        config.current_game -= 1
                        update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                        event.button if event.type == pygame.JOYBUTTONDOWN else 
                                        (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                        event.value)
                        config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    if config.current_game < len(games) - 1:
                        config.current_game += 1
                        update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                        event.button if event.type == pygame.JOYBUTTONDOWN else 
                                        (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                        event.value)
                        config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.current_game = max(0, config.current_game - config.visible_games)
                    update_key_state("page_up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "left"):
                    config.current_game = max(0, config.current_game - config.visible_games)
                    update_key_state("left", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    update_key_state("page_down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "right"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True                    
                elif is_input_matched(event, "filter"):
                    # Afficher le menu de choix entre recherche et filtrage avancé
                    config.menu_state = "filter_menu_choice"
                    config.selected_filter_choice = 0
                    config.previous_menu_state = "game"
                    config.needs_redraw = True
                    logger.debug("Ouverture du menu de filtrage") 
                elif is_input_matched(event, "history"):
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug("Ouverture history depuis game")
                # Ajouter à la file d'attente avec la touche clear_history (réutilisée)
                elif is_input_matched(event, "clear_history"):
                    if games:
                        idx = config.current_game
                        game = games[idx]
                        url = game[1]
                        game_name = game[0]
                        platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                        
                        pending_download = check_extension_before_download(url, platform, game_name)
                        if pending_download:
                            is_supported = is_extension_supported(
                                sanitize_filename(game_name),
                                platform,
                                load_extensions_json()
                            )
                            zip_ok = bool(pending_download[3])
                            allow_unknown = get_allow_unknown_extensions()
                            
                            # Si extension non supportée ET pas en archive connu, afficher avertissement
                            if (not is_supported and not zip_ok) and not allow_unknown:
                                config.pending_download = pending_download
                                config.pending_download_is_queue = True  # Marquer comme action queue
                                config.previous_menu_state = config.menu_state
                                config.menu_state = "extension_warning"
                                config.extension_confirm_selection = 0
                                config.needs_redraw = True
                                logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                            else:
                                # Ajouter à la queue
                                task_id = str(pygame.time.get_ticks())
                                queue_item = {
                                    'url': url,
                                    'platform': platform,
                                    'game_name': game_name,
                                    'is_zip_non_supported': pending_download[3],
                                    'is_1fichier': is_1fichier_url(url),
                                    'task_id': task_id,
                                    'status': 'Queued'
                                }
                                config.download_queue.append(queue_item)
                                
                                # Ajouter une entrée à l'historique avec status "Queued"
                                config.history.append({
                                    'platform': platform,
                                    'game_name': game_name,
                                    'status': 'Queued',
                                    'url': url,
                                    'progress': 0,
                                    'message': _("download_queued"),
                                    'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    'downloaded_size': 0,
                                    'total_size': 0,
                                    'task_id': task_id
                                })
                                save_history(config.history)
                                
                                # Afficher un toast de notification
                                show_toast(f"{game_name}\n{_('download_queued')}")
                                
                                config.needs_redraw = True
                                logger.debug(f"{game_name} ajouté à la file d'attente. Queue size: {len(config.download_queue)}")
                                
                                # Si aucun téléchargement actif, lancer le premier de la queue
                                if not config.download_active and config.download_queue:
                                    _launch_next_queued_download()
                        else:
                            logger.error(f"config.pending_download est None pour {game_name}")
                            config.needs_redraw = True
                elif is_input_matched(event, "cancel"):
                    config.menu_state = "platform"
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Retour à platform")
                elif is_input_matched(event, "reload_games_data"):
                    config.previous_menu_state = config.menu_state
                    config.menu_state = "reload_games_data"
                    config.needs_redraw = True
                    logger.debug("Passage à reload_games_data depuis game")
                # Télécharger le jeu courant (ou scraper si appui long)
                elif is_input_matched(event, "confirm"):
                    # Détecter le début de l'appui
                    if event.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN):
                        config.confirm_press_start_time = current_time
                        config.confirm_long_press_triggered = False
                        logger.debug(f"Début appui confirm à {current_time}")
                        # NE PAS télécharger immédiatement, attendre le relâchement
                        # pour déterminer si c'est un appui long ou court

        # Avertissement extension
        elif config.menu_state == "extension_warning":
            if is_input_matched(event, "confirm"):
                if config.extension_confirm_selection == 0:  # 0 = Oui, 1 = Non
                    if config.pending_download and len(config.pending_download) == 4:
                        url, platform, game_name, is_zip_non_supported = config.pending_download
                        
                        # Vérifier si c'est une action queue
                        is_queue_action = getattr(config, 'pending_download_is_queue', False)
                        
                        if is_queue_action:
                            # Ajouter à la queue au lieu de télécharger immédiatement
                            task_id = str(pygame.time.get_ticks())
                            queue_item = {
                                'url': url,
                                'platform': platform,
                                'game_name': game_name,
                                'is_zip_non_supported': is_zip_non_supported,
                                'is_1fichier': is_1fichier_url(url),
                                'task_id': task_id,
                                'status': 'Queued'
                            }
                            config.download_queue.append(queue_item)
                            
                            # Ajouter une entrée à l'historique avec status "Queued"
                            config.history.append({
                                'platform': platform,
                                'game_name': game_name,
                                'status': 'Queued',
                                'url': url,
                                'progress': 0,
                                'message': _("download_queued"),
                                'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                'downloaded_size': 0,
                                'total_size': 0,
                                'task_id': task_id
                            })
                            save_history(config.history)
                            
                            # Afficher un toast de notification
                            show_toast(f"{game_name}\n{_('download_queued')}")
                            
                            # Le worker de la queue détectera automatiquement le nouvel élément
                            logger.debug(f"{game_name} ajouté à la file d'attente après confirmation. Queue size: {len(config.download_queue)}")
                        else:
                            # Téléchargement immédiat
                            if is_1fichier_url(url):
                                ensure_download_provider_keys(False)
                                
                                # Avertissement si pas de clé (utilisation mode gratuit)
                                if missing_all_provider_keys():
                                    logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
                                
                                task_id = str(pygame.time.get_ticks())
                                task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
                            else:
                                task_id = str(pygame.time.get_ticks())
                                task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))
                            config.download_tasks[task_id] = (task, url, game_name, platform)
                            # Afficher un toast de notification
                            show_toast(f"{_('download_started')}: {game_name}")
                            logger.debug(f"[CONTROLS_EXT_WARNING] Téléchargement confirmé après avertissement: {game_name} pour {platform} depuis {url}, task_id={task_id}")
                        
                        config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                        config.needs_redraw = True
                        config.pending_download = None
                        config.pending_download_is_queue = False
                        config.extension_confirm_selection = 0  # Réinitialiser la sélection
                        # Retourner au menu précédent
                        config.menu_state = config.previous_menu_state if config.previous_menu_state else "game"
                        logger.debug(f"[CONTROLS_EXT_WARNING] Retour au menu {config.menu_state} après confirmation")
                    else:
                        config.menu_state = "error"
                        config.error_message = _("error_invalid_download_data")
                        config.pending_download = None
                        config.needs_redraw = True
                        logger.error("config.pending_download invalide")
                else:
                    config.pending_download = None
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
                    logger.debug(f"Retour à {config.menu_state} depuis extension_warning")
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.extension_confirm_selection = 1 - config.extension_confirm_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.pending_download = None
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis extension_warning")

        #Historique            
        elif config.menu_state == "history":
            history = config.history
            if is_input_matched(event, "up"):
                # L'historique est inversé à l'affichage, donc UP descend dans l'index (incrément)
                if config.current_history_item < len(history) - 1:
                    config.current_history_item += 1
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "down"):
                # L'historique est inversé à l'affichage, donc DOWN monte dans l'index (décrement)
                if config.current_history_item > 0:
                    config.current_history_item -= 1
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "page_up"):
                # PAGE_UP va vers les plus récents (index décroissant)
                config.current_history_item = max(0, config.current_history_item - config.visible_history_items)
                config.repeat_action = None
                config.repeat_key = None
                config.repeat_start_time = 0
                config.repeat_last_action = current_time
                config.needs_redraw = True
                #logger.debug("Page précédente dans l'historique")
            elif is_input_matched(event, "page_down"):
                # PAGE_DOWN va vers les plus anciens (index croissant)
                config.current_history_item = min(len(history) - 1, config.current_history_item + config.visible_history_items)
                config.repeat_action = None
                config.repeat_key = None
                config.repeat_start_time = 0
                config.repeat_last_action = current_time
                config.needs_redraw = True
                #logger.debug("Page suivante dans l'historique")
            elif (is_input_matched(event, "clear_history")
                    or is_input_matched(event, "delete_history")
                    or is_input_matched(event, "progress")):
                config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                config.menu_state = "confirm_clear_history"
                config.confirm_clear_selection = 0  # 0 pour "Non", 1 pour "Oui"
                config.needs_redraw = True
                logger.debug("Passage à confirm_clear_history depuis history")
            elif is_input_matched(event, "confirm"):
                # Ouvrir le menu d'options pour le jeu sélectionné
                if config.history and config.current_history_item < len(config.history):
                    config.previous_menu_state = "history"
                    config.menu_state = "history_game_options"
                    config.history_game_option_selection = 0
                    config.needs_redraw = True
                    logger.debug("Ouverture history_game_options depuis history")
            elif is_input_matched(event, "cancel") or is_input_matched(event, "history"):
                if config.history and config.current_history_item < len(config.history):
                    entry = config.history[config.current_history_item]
                    if entry.get("status") in ["Downloading", "Téléchargement", "Extracting"] and is_input_matched(event, "cancel"):
                        config.menu_state = "confirm_cancel_download"
                        config.confirm_cancel_selection = 0
                        config.needs_redraw = True
                        logger.debug("Demande d'annulation de téléchargement")
                        return action
                # Retour à l'origine capturée si disponible sinon previous_menu_state
                target = getattr(config, 'history_origin', getattr(config, 'previous_menu_state', 'platform'))
                # Éviter boucle si target reste 'history' ou pointe vers un sous-menu history
                if target == 'history' or target.startswith('history_'):
                    target = 'platform'
                config.menu_state = validate_menu_state(target)
                if hasattr(config, 'history_origin'):
                    try:
                        delattr(config, 'history_origin')
                    except Exception:
                        pass
                config.current_history_item = 0
                config.history_scroll_offset = 0
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis history")
       
        # Confirmation annulation téléchargement
        elif config.menu_state == "confirm_cancel_download":
            if is_input_matched(event, "confirm"):
                if config.confirm_cancel_selection == 1:  # Oui
                    entry = config.history[config.current_history_item]
                    task_id = entry.get("task_id")
                    url = entry.get("url")
                    game_name = entry.get("game_name", "Unknown")
                    
                    # Annuler via cancel_events (pour les threads de téléchargement)
                    try:
                        request_cancel(task_id)
                        logger.debug(f"Signal d'annulation envoyé pour task_id={task_id}")
                    except Exception as e:
                        logger.debug(f"Erreur lors de l'envoi du signal d'annulation: {e}")
                    
                    # Annuler aussi la tâche asyncio si elle existe (pour les téléchargements directs)
                    for tid, (task, task_url, tname, tplatform) in list(config.download_tasks.items()):
                        if tid == task_id or task_url == url:
                            try:
                                task.cancel()
                                del config.download_tasks[tid]
                                logger.debug(f"Tâche asyncio annulée: {tname}")
                            except Exception as e:
                                logger.debug(f"Erreur lors de l'annulation de la tâche asyncio: {e}")
                            break
                    
                    # Mettre à jour l'entrée historique
                    entry["status"] = "Canceled"
                    entry["progress"] = 0
                    entry["message"] = _("download_canceled") if _ else "Download canceled"
                    save_history(config.history)
                    logger.debug(f"Téléchargement annulé: {game_name}")
                    
                    config.menu_state = "history"
                    config.needs_redraw = True
                else:  # Non
                    config.menu_state = "history"
                    config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.confirm_cancel_selection = 1 - config.confirm_cancel_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "history"
                config.needs_redraw = True
        
        # Confirmation vider l'historique   
        elif config.menu_state == "confirm_clear_history":
            
            if is_input_matched(event, "confirm"):
                # 0 = Non, 1 = Oui
                if config.confirm_clear_selection == 1:  # Oui
                    clear_history()
                    config.history = load_history()  # Recharger l'historique (conserve les téléchargements en cours)
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.menu_state = "history"
                    config.needs_redraw = True
                else:  # Non
                    config.menu_state = "history"
                    config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.confirm_clear_selection = 1 - config.confirm_clear_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "history"
                config.needs_redraw = True
                logger.debug("Annulation du vidage de l'historique, retour à history")

        # Dialogue fichier de support
        elif config.menu_state == "support_dialog":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                # Retour au menu pause
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                # Nettoyage des variables temporaires
                if hasattr(config, 'support_zip_path'):
                    delattr(config, 'support_zip_path')
                if hasattr(config, 'support_zip_error'):
                    delattr(config, 'support_zip_error')
                logger.debug("Retour au menu pause depuis support_dialog")

        # Menu options du jeu dans l'historique
        elif config.menu_state == "history_game_options":
            if not config.history or config.current_history_item >= len(config.history):
                config.menu_state = "history"
                config.needs_redraw = True
            else:
                entry = config.history[config.current_history_item]
                status = entry.get("status", "")
                game_name = entry.get("game_name", "")
                platform = entry.get("platform", "")
                
                # Vérifier l'existence du fichier (avec ou sans extension)
                dest_folder = _get_dest_folder_name(platform)
                base_path = os.path.join(config.ROMS_FOLDER, dest_folder)
                file_exists, actual_filename, actual_path = find_file_with_or_without_extension(base_path, game_name)
                
                # Stocker les informations pour les autres handlers
                config.history_actual_filename = actual_filename
                config.history_actual_path = actual_path
                
                # Déterminer les options disponibles selon le statut
                options = []
                
                # Option commune: scraper (toujours disponible)
                options.append("scraper")
                
                # Options selon statut
                if status == "Queued":
                    # En attente dans la queue
                    options.append("remove_from_queue")
                elif status in ["Downloading", "Téléchargement", "Extracting", "Paused"]:
                    # Téléchargement en cours ou en pause - ajouter pause/resume avant cancel
                    options.append("pause_resume_download")
                    options.append("cancel_download")
                elif status == "Download_OK" or status == "Completed":
                    # Vérifier si c'est une archive ET si le fichier existe
                    if actual_filename and file_exists:
                        ext = os.path.splitext(actual_filename)[1].lower()
                        if ext in ['.zip', '.rar']:
                            options.append("extract_archive")
                        elif ext == '.txt':
                            options.append("open_file")
                elif status in ["Erreur", "Error", "Canceled"]:
                    options.append("error_info")
                    options.append("retry")

                # Options communes si le fichier existe
                if file_exists:
                    options.append("download_folder")
                    options.append("delete_game")
                
                # Option commune: retour
                options.append("back")
                
                total_options = len(options)
                sel = getattr(config, 'history_game_option_selection', 0)
                
                if is_input_matched(event, "up"):
                    config.history_game_option_selection = (sel - 1) % total_options
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                    logger.debug(f"history_game_options: UP sel={config.history_game_option_selection}/{total_options}")
                elif is_input_matched(event, "down"):
                    config.history_game_option_selection = (sel + 1) % total_options
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                    logger.debug(f"history_game_options: DOWN sel={config.history_game_option_selection}/{total_options}")
                elif is_input_matched(event, "confirm"):
                    selected_option = options[sel]
                    logger.debug(f"history_game_options: CONFIRM option={selected_option}")
                    
                    if selected_option == "remove_from_queue":
                        # Retirer de la queue
                        task_id = entry.get("task_id")
                        url = entry.get("url")
                        
                        # Chercher et retirer de la queue
                        for i, queue_item in enumerate(config.download_queue):
                            if queue_item.get("task_id") == task_id or queue_item.get("url") == url:
                                config.download_queue.pop(i)
                                logger.debug(f"Jeu retiré de la queue: {game_name}")
                                break
                        
                        # Mettre à jour l'entrée historique avec status Canceled
                        entry["status"] = "Canceled"
                        entry["progress"] = 0
                        entry["message"] = _("download_canceled") if _ else "Download canceled"
                        save_history(config.history)
                        
                        # Retour à l'historique
                        config.menu_state = "history"
                        config.needs_redraw = True
                        
                    elif selected_option == "pause_resume_download":
                        # Mettre en pause ou reprendre le téléchargement
                        task_id = entry.get("task_id")
                        if task_id:
                            from network import toggle_pause_download, is_download_paused
                            is_paused = toggle_pause_download(task_id)
                            if is_paused:
                                entry["status"] = "Paused"
                            else:
                                entry["status"] = "Downloading"
                            save_history(config.history)
                            config.needs_redraw = True
                        # Retour à l'historique
                        config.menu_state = "history"
                        
                    elif selected_option == "cancel_download":
                        # Rediriger vers le dialogue de confirmation (même que bouton cancel)
                        config.previous_menu_state = "history"
                        config.menu_state = "confirm_cancel_download"
                        config.confirm_cancel_selection = 0
                        config.needs_redraw = True
                        logger.debug("Redirection vers confirm_cancel_download depuis history_game_options")
                        
                    elif selected_option == "download_folder":
                        # Afficher le chemin de destination
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_show_folder"
                        config.needs_redraw = True
                        logger.debug(f"Affichage du dossier de téléchargement pour {game_name}")
                        
                    elif selected_option == "open_file":
                        # Ouvrir le fichier texte
                        if actual_path and os.path.exists(actual_path):
                            try:
                                with open(actual_path, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()
                                config.text_file_content = content
                                config.text_file_name = actual_filename
                                config.text_file_scroll_offset = 0
                                config.previous_menu_state = "history_game_options"
                                config.menu_state = "text_file_viewer"
                                config.needs_redraw = True
                                logger.debug(f"Ouverture du fichier texte: {actual_filename}")
                            except Exception as e:
                                logger.error(f"Erreur lors de l'ouverture du fichier texte: {e}")
                                config.menu_state = "error"
                                config.error_message = f"Erreur lors de l'ouverture du fichier: {str(e)}"
                                config.needs_redraw = True
                        else:
                            logger.error(f"Fichier texte introuvable: {actual_path}")
                            config.menu_state = "error"
                            config.error_message = "Fichier introuvable"
                            config.needs_redraw = True
                        
                    elif selected_option == "extract_archive":
                        # L'option n'apparaît que si le fichier existe, pas besoin de re-vérifier
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_extract_archive"
                        config.needs_redraw = True
                        logger.debug(f"Extraction de l'archive {game_name}")
                        
                    elif selected_option == "scraper":
                        # Lancer le scraper
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "scraper"
                        config.scraper_game_name = game_name
                        config.scraper_platform_name = platform
                        config.scraper_loading = True
                        config.scraper_error_message = ""
                        config.scraper_image_surface = None
                        config.scraper_image_url = ""
                        config.scraper_description = ""
                        config.scraper_genre = ""
                        config.scraper_release_date = ""
                        config.scraper_game_page_url = ""
                        config.needs_redraw = True
                        logger.debug(f"Lancement du scraper pour {game_name}")
                        
                        # Lancer la recherche des métadonnées dans un thread séparé
                        
                        def scrape_async():
                            logger.info(f"Scraping métadonnées pour {game_name} sur {platform}")
                            metadata = get_game_metadata(game_name, platform)
                            
                            # Vérifier si on a une erreur
                            if "error" in metadata:
                                config.scraper_error_message = metadata["error"]
                                config.scraper_loading = False
                                config.needs_redraw = True
                                logger.error(f"Erreur de scraping: {metadata['error']}")
                                return
                            
                            # Mettre à jour les métadonnées textuelles
                            config.scraper_description = metadata.get("description", "")
                            config.scraper_genre = metadata.get("genre", "")
                            config.scraper_release_date = metadata.get("release_date", "")
                            config.scraper_game_page_url = metadata.get("game_page_url", "")
                            
                            # Télécharger l'image si disponible
                            image_url = metadata.get("image_url")
                            if image_url:
                                logger.info(f"Téléchargement de l'image: {image_url}")
                                image_surface = download_image_to_surface(image_url)
                                if image_surface:
                                    config.scraper_image_surface = image_surface
                                    config.scraper_image_url = image_url
                                else:
                                    logger.warning("Échec du téléchargement de l'image")
                            
                            config.scraper_loading = False
                            config.needs_redraw = True
                            logger.info("Scraping terminé")
                        
                        thread = threading.Thread(target=scrape_async, daemon=True)
                        thread.start()
                        
                    elif selected_option == "delete_game":
                        # Demander confirmation avant suppression
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_confirm_delete"
                        config.history_delete_confirm_selection = 0
                        config.needs_redraw = True
                        logger.debug(f"Demande de confirmation de suppression pour {game_name}")
                        
                    elif selected_option == "error_info":
                        # Afficher les détails de l'erreur
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_error_details"
                        config.needs_redraw = True
                        logger.debug(f"Affichage des détails de l'erreur pour {game_name}")
                        
                    elif selected_option == "retry":
                        # Relancer le téléchargement
                        config.menu_state = "history"
                        # Réinitialiser l'entrée et relancer
                        url = entry.get("url")
                        if url:
                            # Mettre à jour le statut
                            entry["status"] = "Downloading"
                            entry["progress"] = 0
                            entry["message"] = "Téléchargement en cours"
                            save_history(config.history)
                            
                            # Relancer le téléchargement
                            pending_download = check_extension_before_download(url, platform, game_name)
                            if pending_download:
                                task_id = str(pygame.time.get_ticks())
                                is_zip_non_supported = pending_download[3] if len(pending_download) > 3 else False
                                
                                if is_1fichier_url(url):
                                    task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
                                else:
                                    task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))
                                
                                config.download_tasks[task_id] = (task, url, game_name, platform)
                                # Afficher un toast de notification
                                show_toast(f"{_('download_started')}: {game_name}")
                                logger.debug(f"Relance du téléchargement: {game_name} pour {platform}")
                        config.needs_redraw = True
                        
                    elif selected_option == "back":
                        # Retour à l'historique
                        config.menu_state = "history"
                        # Ne pas mettre à jour previous_menu_state pour éviter les boucles
                        config.needs_redraw = True
                        logger.debug("Retour à history depuis history_game_options")
                        
                elif is_input_matched(event, "cancel"):
                    config.menu_state = "history"
                    # Ne pas mettre à jour previous_menu_state pour éviter les boucles
                    config.needs_redraw = True
                    logger.debug("Retour à history depuis history_game_options (cancel)")

        # Affichage du dossier de téléchargement
        elif config.menu_state == "history_show_folder":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True

        # Scraper
        elif config.menu_state == "scraper":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                logger.info(f"Scraper: fermeture demandée")
                # Retour au menu précédent
                config.menu_state = validate_menu_state(config.previous_menu_state)
                # Nettoyer les variables du scraper
                config.scraper_image_surface = None
                config.scraper_image_url = ""
                config.scraper_game_name = ""
                config.scraper_platform_name = ""
                config.scraper_loading = False
                config.scraper_error_message = ""
                config.scraper_description = ""
                config.scraper_genre = ""
                config.scraper_release_date = ""
                config.scraper_game_page_url = ""
                config.needs_redraw = True
        
        # Information scraper (ancien, gardé pour compatibilité)
        elif config.menu_state == "history_scraper_info":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True

        # Affichage détails erreur
        # Visualiseur de fichiers texte
        elif config.menu_state == "text_file_viewer":
            content = getattr(config, 'text_file_content', '')
            if content:
                lines = content.split('\n')
                line_height = config.small_font.get_height() + 2
                
                # Calculer le nombre de lignes visibles (approximation)
                controls_y = config.screen_height - int(config.screen_height * 0.037)
                margin = 40
                header_height = 60
                content_area_height = controls_y - 2 * margin - 10 - header_height - 20
                visible_lines = int(content_area_height / line_height)
                
                scroll_offset = getattr(config, 'text_file_scroll_offset', 0)
                max_scroll = max(0, len(lines) - visible_lines)
                
                if is_input_matched(event, "up"):
                    config.text_file_scroll_offset = max(0, scroll_offset - 1)
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    config.text_file_scroll_offset = min(max_scroll, scroll_offset + 1)
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.text_file_scroll_offset = max(0, scroll_offset - visible_lines)
                    update_key_state("page_up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.text_file_scroll_offset = min(max_scroll, scroll_offset + visible_lines)
                    update_key_state("page_down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "cancel") or is_input_matched(event, "confirm"):
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
            else:
                # Si pas de contenu, retourner au menu précédent
                if is_input_matched(event, "cancel") or is_input_matched(event, "confirm"):
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True

        # Visualiseur de fichiers texte
        elif config.menu_state == "text_file_viewer":
            content = getattr(config, 'text_file_content', '')
            if content:
                from utils import wrap_text
                
                # Calculer les dimensions
                controls_y = config.screen_height - int(config.screen_height * 0.037)
                margin = 40
                header_height = 60
                rect_width = config.screen_width - 2 * margin
                content_area_height = controls_y - 2 * margin - 10 - header_height - 20
                max_width = rect_width - 60
                
                # Diviser le contenu en lignes et appliquer le word wrap
                original_lines = content.split('\n')
                wrapped_lines = []
                
                for original_line in original_lines:
                    if original_line.strip():  # Si la ligne n'est pas vide
                        wrapped = wrap_text(original_line, config.small_font, max_width)
                        wrapped_lines.extend(wrapped)
                    else:  # Ligne vide
                        wrapped_lines.append('')
                
                line_height = config.small_font.get_height() + 2
                visible_lines = int(content_area_height / line_height)
                
                scroll_offset = getattr(config, 'text_file_scroll_offset', 0)
                max_scroll = max(0, len(wrapped_lines) - visible_lines)
                
                if is_input_matched(event, "up"):
                    config.text_file_scroll_offset = max(0, scroll_offset - 1)
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    config.text_file_scroll_offset = min(max_scroll, scroll_offset + 1)
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.text_file_scroll_offset = max(0, scroll_offset - visible_lines)
                    update_key_state("page_up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.text_file_scroll_offset = min(max_scroll, scroll_offset + visible_lines)
                    update_key_state("page_down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "cancel") or is_input_matched(event, "confirm"):
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
            else:
                # Si pas de contenu, retourner au menu précédent
                if is_input_matched(event, "cancel") or is_input_matched(event, "confirm"):
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True

        elif config.menu_state == "history_error_details":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True

        # Confirmation suppression jeu
        elif config.menu_state == "history_confirm_delete":
            if is_input_matched(event, "confirm"):
                if config.history_delete_confirm_selection == 1:  # Oui
                    # Supprimer le fichier
                    if config.history and config.current_history_item < len(config.history):
                        entry = config.history[config.current_history_item]
                        
                        # Utiliser le chemin réel trouvé (avec ou sans extension)
                        file_path = getattr(config, 'history_actual_path', None)
                        
                        if not file_path:
                            # Fallback si pas trouvé (ne devrait pas arriver)
                            game_name = entry.get("game_name", "")
                            platform = entry.get("platform", "")
                            sanitized_name = sanitize_filename(game_name)
                            dest_folder = _get_dest_folder_name(platform)
                            dest_dir = os.path.join(config.ROMS_FOLDER, dest_folder)
                            file_path = os.path.join(dest_dir, sanitized_name)
                        
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                                logger.info(f"Fichier supprimé: {file_path}")
                                # Mettre à jour l'historique
                                entry["message"] = _("history_delete_success")
                                save_history(config.history)
                                config.popup_message = _("history_delete_success")
                                config.popup_timer = 2000
                            else:
                                logger.warning(f"Fichier introuvable: {file_path}")
                                config.popup_message = _("history_delete_error").format("File not found")
                                config.popup_timer = 3000
                        except Exception as e:
                            logger.error(f"Erreur suppression {file_path}: {e}")
                            config.popup_message = _("history_delete_error").format(str(e))
                            config.popup_timer = 3000
                    
                    config.menu_state = "history"
                    config.needs_redraw = True
                else:  # Non
                    config.menu_state = "history_game_options"
                    config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.history_delete_confirm_selection = 1 - config.history_delete_confirm_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "history_game_options"
                config.needs_redraw = True

        # Extraction archive depuis historique
        elif config.menu_state == "history_extract_archive":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                if is_input_matched(event, "confirm"):
                    # Lancer l'extraction
                    if config.history and config.current_history_item < len(config.history):
                        entry = config.history[config.current_history_item]
                        platform = entry.get("platform", "")
                        
                        
                        # Utiliser le chemin réel trouvé (avec ou sans extension)
                        file_path = getattr(config, 'history_actual_path', None)
                        actual_filename = getattr(config, 'history_actual_filename', None)
                        
                        if not file_path or not actual_filename:
                            # Fallback si pas trouvé (ne devrait pas arriver)
                            game_name = entry.get("game_name", "")
                            sanitized_name = sanitize_filename(game_name)
                            dest_folder = _get_dest_folder_name(platform)
                            dest_dir = os.path.join(config.ROMS_FOLDER, dest_folder)
                            file_path = os.path.join(dest_dir, sanitized_name)
                            actual_filename = sanitized_name
                        else:
                            dest_folder = _get_dest_folder_name(platform)
                            dest_dir = os.path.join(config.ROMS_FOLDER, dest_folder)
                        
                        ext = os.path.splitext(actual_filename)[1].lower()
                        url = entry.get("url", "")
                        
                        if os.path.exists(file_path):
                            # Mettre à jour le statut avant extraction
                            entry["status"] = "Extracting"
                            entry["progress"] = 0
                            entry["message"] = _("history_extracting") if _ else "Extracting..."
                            save_history(config.history)
                            config.needs_redraw = True
                            
                            def do_extract():
                                try:
                                    if ext == '.zip':
                                        success, msg = extract_zip(file_path, dest_dir, url)
                                    elif ext == '.rar':
                                        success, msg = extract_rar(file_path, dest_dir, url)
                                    else:
                                        success, msg = False, "Not an archive"
                                    
                                    # Mettre à jour le statut après extraction
                                    if success:
                                        entry["status"] = "Completed"
                                        entry["progress"] = 100
                                        entry["message"] = _("history_extracted") if _ else "Extracted"
                                        logger.info(f"Extraction réussie: {actual_filename}")
                                    else:
                                        entry["status"] = "Error"
                                        entry["progress"] = 0
                                        entry["message"] = f"Extraction failed: {msg}"
                                        logger.error(f"Échec extraction: {msg}")
                                    save_history(config.history)
                                    config.needs_redraw = True
                                except Exception as e:
                                    logger.error(f"Erreur extraction: {e}")
                                    entry["status"] = "Error"
                                    entry["progress"] = 0
                                    entry["message"] = f"Error: {str(e)}"
                                    save_history(config.history)
                                    config.needs_redraw = True
                            
                            extract_thread = threading.Thread(target=do_extract, daemon=True)
                            extract_thread.start()
                            logger.info(f"Extraction lancée: {file_path}")
                
                # Retourner à l'historique pour voir la progression
                config.menu_state = "history"
                config.needs_redraw = True

        # Confirmation quitter
        elif config.menu_state == "confirm_exit":
            # Sous-menu Quit: 0=Quit RGSX, 1=Restart RGSX, 2=Back
            if is_input_matched(event, "up"):
                config.confirm_selection = max(0, config.confirm_selection - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.confirm_selection = min(2, config.confirm_selection + 1)
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.confirm_selection == 0:  # Quit RGSX
                    # Mark all in-progress downloads as canceled in history
                    try:
                        for entry in getattr(config, 'history', []) or []:
                            if entry.get("status") in ["Downloading", "Téléchargement", "Extracting"]:
                                entry["status"] = "Canceled"
                                entry["progress"] = 0
                                entry["message"] = _("download_canceled") if _ else "Download canceled"
                        save_history(config.history)
                    except Exception:
                        pass
                    return "quit"
                elif config.confirm_selection == 1:  # Restart RGSX
                    restart_application(2000)
                elif config.confirm_selection == 2:  # Back
                    # Retour à l'état capturé (confirm_exit_origin) sinon previous_menu_state sinon platform
                    target = getattr(config, 'confirm_exit_origin', getattr(config, 'previous_menu_state', 'platform'))
                    config.menu_state = validate_menu_state(target)
                    if hasattr(config, 'confirm_exit_origin'):
                        try:
                            delattr(config, 'confirm_exit_origin')
                        except Exception:
                            pass
                    config.needs_redraw = True
                    logger.debug(f"Retour à {config.menu_state} depuis confirm_exit (back)")
            elif is_input_matched(event, "cancel"):
                # Retour à l'état capturé
                target = getattr(config, 'confirm_exit_origin', getattr(config, 'previous_menu_state', 'platform'))
                config.menu_state = validate_menu_state(target)
                if hasattr(config, 'confirm_exit_origin'):
                    try:
                        delattr(config, 'confirm_exit_origin')
                    except Exception:
                        pass
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis confirm_exit (cancel)")

        # Menu pause
        elif config.menu_state == "pause_menu":
            #logger.debug(f"État pause_menu, selected_option={config.selected_option}, événement={event.type}, valeur={getattr(event, 'value', None)}")
            # Start toggles back to previous state when already in pause
            if is_input_matched(event, "start"):
                target = getattr(config, 'pause_origin_state', getattr(config, 'previous_menu_state', 'platform'))
                config.menu_state = validate_menu_state(target)
                config.needs_redraw = True
                logger.debug(f"Start: retour à {config.menu_state} depuis pause_menu")
            elif is_input_matched(event, "up"):
                # Menu racine hiérarchique: nombre dynamique (langue + catégories)
                total = getattr(config, 'pause_menu_total_options', 7)
                config.selected_option = (config.selected_option - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                # Menu racine hiérarchique: nombre dynamique (langue + catégories)
                total = getattr(config, 'pause_menu_total_options', 7)
                config.selected_option = (config.selected_option + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.selected_option == 0:  # Games submenu
                    config.menu_state = "pause_games_menu"
                    if not hasattr(config, 'pause_games_selection'):
                        config.pause_games_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 1:  # Language selector direct
                    config.menu_state = "language_select"
                    config.previous_menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 2:  # Controls submenu
                    config.menu_state = "pause_controls_menu"
                    if not hasattr(config, 'pause_controls_selection'):
                        config.pause_controls_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 3:  # Display submenu
                    config.menu_state = "pause_display_menu"
                    if not hasattr(config, 'pause_display_selection'):
                        config.pause_display_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 4:  # Settings submenu
                    config.menu_state = "pause_settings_menu"
                    if not hasattr(config, 'pause_settings_selection'):
                        config.pause_settings_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 5:  # Support
                    success, message, zip_path = generate_support_zip()
                    if success:
                        config.support_zip_path = zip_path
                        config.support_zip_error = None
                    else:
                        config.support_zip_path = None
                        config.support_zip_error = message
                    config.menu_state = "support_dialog"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 6:  # Quit submenu
                    # Capturer l'origine pause_menu pour retour si annulation
                    config.confirm_exit_origin = "pause_menu"
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "confirm_exit"
                    config.confirm_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                target = getattr(config, 'pause_origin_state', getattr(config, 'previous_menu_state', 'platform'))
                config.menu_state = validate_menu_state(target)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis pause_menu")

        # Sous-menu Controls
        elif config.menu_state == "pause_controls_menu":
            # Ajout de l'option inversion ABXY
            options = [
                {"key": "help", "title": _("controls_help_title"), "desc": _("instruction_controls_help")},
                {"key": "remap", "title": _("menu_remap_controls"), "desc": _("instruction_controls_remap")},
                {"key": "back", "title": _("menu_back"), "desc": _("instruction_generic_back")},
            ]
            sel = getattr(config, 'pause_controls_selection', 0)
            total = len(options)
            if is_input_matched(event, "up"):
                config.pause_controls_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_controls_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                selected = options[sel]["key"]
                if selected == "help":
                    config.previous_menu_state = "pause_controls_menu"
                    config.menu_state = "controls_help"
                elif selected == "remap":
                    if os.path.exists(config.CONTROLS_CONFIG_PATH):
                        try:
                            os.remove(config.CONTROLS_CONFIG_PATH)
                        except Exception as e:
                            logger.error(f"Erreur suppression controls_config: {e}")
                    config.previous_menu_state = "pause_controls_menu"
                    config.menu_state = "controls_mapping"
                # invert_abxy moved to controls_help submenu (interactive)
                else:  # Back
                    config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        
        # Menu Aide Contrôles (affichage interactif du style manette)
        elif config.menu_state == "controls_help":
            # Left/Right change controller style immediately
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                try:
                    from rgsx_settings import set_nintendo_layout, get_nintendo_layout
                    # Toggle style
                    new_val = set_nintendo_layout(not get_nintendo_layout())
                    config.nintendo_layout = new_val
                    # Clear icon cache so help screen updates immediately
                    try:
                        from display import clear_help_icon_cache
                        clear_help_icon_cache()
                    except Exception:
                        pass
                    config.popup_message = (_("menu_nintendo_layout_on") if new_val else _("menu_nintendo_layout_off"))
                    config.popup_timer = 1200
                    config.needs_redraw = True
                except Exception as e:
                    logger.error(f"Erreur toggle nintendo_layout from controls_help: {e}")
            elif is_input_matched(event, "confirm") or is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                # Return to previous menu
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
        # Sous-menu Display
        elif config.menu_state == "pause_display_menu":
            sel = getattr(config, 'pause_display_selection', 0)
            # layout, font submenu, family, [monitor if multi], light, unknown, back
            from rgsx_settings import get_available_monitors
            monitors = get_available_monitors()
            show_monitor = len(monitors) > 1
            total = 7 if show_monitor else 6  # dynamic total based on monitor count
            if is_input_matched(event, "up"):
                config.pause_display_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0 layout submenu - open submenu on confirm
                if sel == 0 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_display_layout_menu"
                    # Trouver l'index actuel pour la sélection
                    layouts = [(3,3),(3,4),(4,3),(4,4)]
                    try:
                        idx = layouts.index((config.GRID_COLS, config.GRID_ROWS))
                    except ValueError:
                        idx = 0
                    config.pause_display_layout_selection = idx
                    config.needs_redraw = True
                # 1 font size submenu - open submenu on confirm
                elif sel == 1 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_display_font_menu"
                    config.pause_display_font_selection = 0
                    config.needs_redraw = True
                # 2 font family cycle
                elif sel == 2 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        families = getattr(config, 'FONT_FAMILIES', ["pixel"]) or ["pixel"]
                        current = get_font_family()
                        try:
                            fam_index = families.index(current)
                        except ValueError:
                            fam_index = 0
                        direction = 1 if (is_input_matched(event, "right") or is_input_matched(event, "confirm")) else -1
                        fam_index = (fam_index + direction) % len(families)
                        new_family = families[fam_index]
                        set_font_family(new_family)
                        config.current_font_family_index = fam_index
                        init_font_func = getattr(config, 'init_font', None)
                        if callable(init_font_func):
                            init_font_func()
                        # popup
                        if _:
                            try:
                                # Vérifier proprement la présence de la clé i18n
                                fmt = _("popup_font_family_changed") if 'popup_font_family_changed' in getattr(_, 'translations', {}) else None
                            except Exception:
                                fmt = None
                            if fmt:
                                config.popup_message = fmt.format(new_family)
                            else:
                                config.popup_message = f"Font: {new_family}"
                        else:
                            config.popup_message = f"Font: {new_family}"
                        config.popup_timer = 2500
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement font family: {e}")
                # 3 monitor selection (only if multiple monitors)
                elif sel == 3 and show_monitor and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_display_monitor, set_display_monitor
                        current = get_display_monitor()
                        new_monitor = (current - 1) % len(monitors) if is_input_matched(event, "left") else (current + 1) % len(monitors)
                        set_display_monitor(new_monitor)
                        config.popup_message = _("display_monitor_restart_required") if _ else "Restart required to apply monitor change"
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement moniteur: {e}")
                # light mode toggle (index 4 if show_monitor, else 3)
                elif ((sel == 4 and show_monitor) or (sel == 3 and not show_monitor)) and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_light_mode, set_light_mode
                        current = get_light_mode()
                        new_val = set_light_mode(not current)
                        config.popup_message = _("display_light_mode_enabled") if new_val else _("display_light_mode_disabled")
                        config.popup_timer = 2000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle light mode: {e}")
                # allow unknown extensions (index 5 if show_monitor, else 4)
                elif ((sel == 5 and show_monitor) or (sel == 4 and not show_monitor)) and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_allow_unknown_extensions()
                        new_val = set_allow_unknown_extensions(not current)
                        config.popup_message = _("menu_allow_unknown_ext_enabled") if new_val else _("menu_allow_unknown_ext_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle allow_unknown_extensions: {e}")
                # back (index 6 if show_monitor, else 5)
                elif ((sel == 6 and show_monitor) or (sel == 5 and not show_monitor)) and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Display > Layout (disposition avec visualisation)
        elif config.menu_state == "pause_display_layout_menu":
            sel = getattr(config, 'pause_display_layout_selection', 0)
            total = 5  # 3x3, 3x4, 4x3, 4x4, back
            if is_input_matched(event, "up"):
                config.pause_display_layout_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_layout_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if sel < 4:  # Une des dispositions
                    layouts = [(3,3),(3,4),(4,3),(4,4)]
                    new_cols, new_rows = layouts[sel]
                    try:
                        set_display_grid(new_cols, new_rows)
                    except Exception as e:
                        logger.error(f"Erreur set_display_grid: {e}")
                    config.GRID_COLS = new_cols
                    config.GRID_ROWS = new_rows
                    # Afficher un popup indiquant que le changement sera effectif après redémarrage
                    try:
                        config.popup_message = _("popup_layout_changed_restart").format(new_cols, new_rows) if _ else f"Layout changed to {new_cols}x{new_rows}. Restart required to apply."
                        config.popup_timer = 3000
                    except Exception as e:
                        logger.error(f"Erreur popup layout: {e}")
                    config.menu_state = "pause_display_menu"
                    config.needs_redraw = True
                elif sel == 4:  # Back
                    config.menu_state = "pause_display_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_display_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Display > Font (tailles de police)
        elif config.menu_state == "pause_display_font_menu":
            sel = getattr(config, 'pause_display_font_selection', 0)
            total = 3  # font size, footer font size, back
            if is_input_matched(event, "up"):
                config.pause_display_font_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_font_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0 font size
                if sel == 0 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    opts = getattr(config, 'font_scale_options', [0.75,1.0,1.25,1.5,1.75])
                    idx = getattr(config, 'current_font_scale_index', 1)
                    idx = max(0, idx-1) if is_input_matched(event, "left") else min(len(opts)-1, idx+1)
                    if idx != getattr(config, 'current_font_scale_index', 1):
                        config.current_font_scale_index = idx
                        scale = opts[idx]
                        config.accessibility_settings["font_scale"] = scale
                        try:
                            save_accessibility_settings(config.accessibility_settings)
                        except Exception as e:
                            logger.error(f"Erreur sauvegarde accessibilité: {e}")
                        try:
                            config.init_font()
                        except Exception as e:
                            logger.error(f"Erreur init polices: {e}")
                        config.needs_redraw = True
                # 1 footer font size
                elif sel == 1 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    from accessibility import update_footer_font_scale
                    footer_opts = getattr(config, 'footer_font_scale_options', [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0])
                    idx = getattr(config, 'current_footer_font_scale_index', 3)
                    idx = max(0, idx-1) if is_input_matched(event, "left") else min(len(footer_opts)-1, idx+1)
                    if idx != getattr(config, 'current_footer_font_scale_index', 3):
                        config.current_footer_font_scale_index = idx
                        try:
                            update_footer_font_scale()
                        except Exception as e:
                            logger.error(f"Erreur update footer font scale: {e}")
                        config.needs_redraw = True
                # 2 back
                elif sel == 2 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_display_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_display_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Games
        elif config.menu_state == "pause_games_menu":
            sel = getattr(config, 'pause_games_selection', 0)
            total = 7  # update cache, history, source, unsupported, hide premium, filter, back
            if is_input_matched(event, "up"):
                config.pause_games_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_games_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right"):
                if sel == 0 and is_input_matched(event, "confirm"):  # update cache
                    config.previous_menu_state = "pause_games_menu"
                    config.menu_state = "reload_games_data"
                    config.redownload_confirm_selection = 0
                    config.needs_redraw = True
                elif sel == 1 and is_input_matched(event, "confirm"):  # history
                    config.history = load_history()
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.previous_menu_state = "pause_games_menu"
                    config.menu_state = "history"
                    config.needs_redraw = True
                elif sel == 2 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):  # source mode
                    try:
                        current_mode = get_sources_mode()
                        new_mode = set_sources_mode('custom' if current_mode == 'rgsx' else 'rgsx')
                        config.sources_mode = new_mode
                        if new_mode == 'custom':
                            config.popup_message = _("sources_mode_custom_select_info").format(config.RGSX_SETTINGS_PATH)
                            config.popup_timer = 10000
                        else:
                            config.popup_message = _("sources_mode_rgsx_select_info")
                            config.popup_timer = 4000
                        config.needs_redraw = True
                        logger.info(f"Changement du mode des sources vers {new_mode}")
                    except Exception as e:
                        logger.error(f"Erreur changement mode sources: {e}")
                elif sel == 3 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):  # unsupported toggle
                    try:
                        current = get_show_unsupported_platforms()
                        new_val = set_show_unsupported_platforms(not current)
                        load_sources()
                        config.popup_message = _("menu_show_unsupported_enabled") if new_val else _("menu_show_unsupported_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle unsupported: {e}")
                elif sel == 4 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):  # hide premium
                    try:
                        cur = get_hide_premium_systems()
                        new_val = set_hide_premium_systems(not cur)
                        config.popup_message = ("Premium hidden" if new_val else "Premium visible") if _ is None else (_("popup_hide_premium_on") if new_val else _("popup_hide_premium_off"))
                        config.popup_timer = 2500
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle hide_premium_systems: {e}")
                elif sel == 5 and is_input_matched(event, "confirm"):  # filter platforms
                    config.filter_return_to = "pause_games_menu"
                    config.menu_state = "filter_platforms"
                    config.selected_filter_index = 0
                    config.filter_platforms_scroll_offset = 0
                    config.needs_redraw = True
                elif sel == 6 and is_input_matched(event, "confirm"):  # back
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Settings
        elif config.menu_state == "pause_settings_menu":
            sel = getattr(config, 'pause_settings_selection', 0)
            # Calculer le nombre total d'options selon le système
            # Liste des options : music, symlink, auto_extract, roms_folder, [web_service], [custom_dns], api keys, back
            total = 6  # music, symlink, auto_extract, roms_folder, api keys, back (Windows)
            auto_extract_index = 2
            roms_folder_index = 3
            web_service_index = -1
            custom_dns_index = -1
            api_keys_index = 4
            back_index = 5
            
            if config.OPERATING_SYSTEM == "Linux":
                total = 8  # music, symlink, auto_extract, roms_folder, web_service, custom_dns, api keys, back
                web_service_index = 4
                custom_dns_index = 5
                api_keys_index = 6
                back_index = 7
            
            if is_input_matched(event, "up"):
                config.pause_settings_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_settings_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "clear_history"):
                # Option 0: Music toggle
                if sel == 0 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    config.music_enabled = not config.music_enabled
                    save_music_config()
                    if config.music_enabled:
                        music_files = getattr(config, "music_files", None)
                        music_folder = getattr(config, "music_folder", None)
                        if music_files and music_folder:
                            config.current_music = play_random_music(music_files, music_folder, getattr(config, "current_music", None))
                    else:
                        pygame.mixer.music.stop()
                    config.needs_redraw = True
                    logger.info(f"Musique {'activée' if config.music_enabled else 'désactivée'} via settings")
                # Option 1: Symlink toggle
                elif sel == 1 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    current_status = get_symlink_option()
                    success, message = set_symlink_option(not current_status)
                    config.popup_message = message
                    config.popup_timer = 3000 if success else 5000
                    config.needs_redraw = True
                    logger.info(f"Symlink option {'activée' if not current_status else 'désactivée'} via settings")
                # Option 2: Auto Extract toggle
                elif sel == auto_extract_index and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    from rgsx_settings import get_auto_extract, set_auto_extract
                    current_status = get_auto_extract()
                    set_auto_extract(not current_status)
                    config.needs_redraw = True
                    logger.info(f"Auto extract {'activée' if not current_status else 'désactivée'} via settings")
                # Option 3: ROMs folder - ouvrir le navigateur (confirm) ou reset (clear_history)
                elif sel == roms_folder_index:
                    if is_input_matched(event, "confirm"):
                        from rgsx_settings import get_roms_folder
                        # Ouvrir le navigateur de dossiers en mode roms_root
                        current_custom = get_roms_folder()
                        if current_custom and os.path.isdir(current_custom):
                            start_path = current_custom
                        else:
                            # Démarrer depuis le dossier parent de ROMS_FOLDER actuel
                            start_path = os.path.dirname(config.ROMS_FOLDER) if config.ROMS_FOLDER else "/"
                            if not os.path.isdir(start_path):
                                start_path = "/"
                        config.folder_browser_path = start_path
                        config.folder_browser_selection = 0
                        config.folder_browser_scroll_offset = 0
                        config.folder_browser_mode = "roms_root"
                        # Charger la liste des dossiers
                        try:
                            items = [".."]
                            for item in sorted(os.listdir(start_path)):
                                full_path = os.path.join(start_path, item)
                                if os.path.isdir(full_path):
                                    items.append(item)
                            config.folder_browser_items = items
                        except Exception as e:
                            logger.error(f"Erreur lecture dossier {start_path}: {e}")
                            config.folder_browser_items = [".."]
                        config.menu_state = "folder_browser"
                        config.needs_redraw = True
                        logger.info("Ouverture navigateur dossier ROMs principal")
                    elif is_input_matched(event, "clear_history"):
                        # Réinitialiser le dossier ROMs par défaut
                        from rgsx_settings import set_roms_folder, get_roms_folder
                        current = get_roms_folder()
                        if current:  # Si un dossier custom est défini, le réinitialiser
                            set_roms_folder("")
                            config.popup_message = _("roms_folder_reset") if _ else "ROMs folder reset to default\nRestart required!"
                            config.popup_timer = 5000
                            logger.info("Dossier ROMs réinitialisé par défaut")
                        config.needs_redraw = True
                # Option 4: Web Service toggle (seulement si Linux)
                elif sel == web_service_index and web_service_index >= 0 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    
                    current_status = check_web_service_status()
                    # Afficher un message de chargement
                    config.popup_message = _("settings_web_service_enabling") if not current_status else _("settings_web_service_disabling")
                    config.popup_timer = 1000
                    config.needs_redraw = True
                    # Exécuter en thread pour ne pas bloquer l'UI
                    def toggle_service():
                        success, message = toggle_web_service_at_boot(not current_status)
                        config.popup_message = message
                        config.popup_timer = 5000 if success else 7000
                        config.needs_redraw = True
                        if success:
                            logger.info(f"Service web {'activé' if not current_status else 'désactivé'} au démarrage")
                        else:
                            logger.error(f"Erreur toggle service web: {message}")
                    threading.Thread(target=toggle_service, daemon=True).start()
                # Option 3: Custom DNS toggle (seulement si Linux)
                elif sel == custom_dns_index and custom_dns_index >= 0 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    from utils import check_custom_dns_status, toggle_custom_dns_at_boot
                    current_status = check_custom_dns_status()
                    # Afficher un message de chargement
                    config.popup_message = _("settings_custom_dns_enabling") if not current_status else _("settings_custom_dns_disabling")
                    config.popup_timer = 1000
                    config.needs_redraw = True
                    # Exécuter en thread pour ne pas bloquer l'UI
                    def toggle_dns():
                        success, message = toggle_custom_dns_at_boot(not current_status)
                        config.popup_message = message
                        config.popup_timer = 5000 if success else 7000
                        config.needs_redraw = True
                        if success:
                            logger.info(f"Custom DNS {'activé' if not current_status else 'désactivé'} au démarrage")
                        else:
                            logger.error(f"Erreur toggle custom DNS: {message}")
                    threading.Thread(target=toggle_dns, daemon=True).start()
                # Option API Keys
                elif sel == api_keys_index and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_api_keys_status"
                    config.needs_redraw = True
                # Option Back (dernière option)
                elif sel == back_index and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        elif config.menu_state == "pause_api_keys_status":
            if is_input_matched(event, "cancel") or is_input_matched(event, "confirm") or is_input_matched(event, "start"):
                config.menu_state = "pause_settings_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Aide contrôles
        elif config.menu_state == "controls_help":
            if is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Retour au menu pause depuis controls_help")

        # Menu Affichage (layout, police, moniteur, mode écran, unsupported, extensions, filtres)
        elif config.menu_state == "display_menu":
            sel = getattr(config, 'display_menu_selection', 0)
            num_options = 7  # Layout, Font, Monitor, Mode, Unsupported, Extensions, Filters
            if is_input_matched(event, "up"):
                config.display_menu_selection = (sel - 1) % num_options
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.display_menu_selection = (sel + 1) % num_options
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0: layout change
                if sel == 0 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    layouts = [(3,3),(3,4),(4,3),(4,4)]
                    try:
                        idx = layouts.index((config.GRID_COLS, config.GRID_ROWS))
                    except ValueError:
                        idx = 1
                    idx = (idx - 1) % len(layouts) if is_input_matched(event, "left") else (idx + 1) % len(layouts)
                    new_cols, new_rows = layouts[idx]
                    try:
                        set_display_grid(new_cols, new_rows)
                    except Exception as e:
                        logger.error(f"Erreur set_display_grid: {e}")
                    config.GRID_COLS = new_cols
                    config.GRID_ROWS = new_rows
                    config.needs_redraw = True
                    # Redémarrage automatique pour appliquer proprement la modification de layout
                    try:
                        # Montrer brièvement l'info puis redémarrer
                        config.menu_state = "restart_popup"
                        config.popup_message = _("popup_restarting")
                        config.popup_timer = 2000
                        restart_application(2000)
                    except Exception as e:
                        logger.error(f"Erreur lors du redémarrage après changement de layout: {e}")
                # 1: font size adjust
                elif sel == 1 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    opts = getattr(config, 'font_scale_options', [0.75, 1.0, 1.25, 1.5, 1.75])
                    idx = getattr(config, 'current_font_scale_index', 1)
                    idx = max(0, idx - 1) if is_input_matched(event, "left") else min(len(opts)-1, idx + 1)
                    if idx != getattr(config, 'current_font_scale_index', 1):
                        config.current_font_scale_index = idx
                        scale = opts[idx]
                        config.accessibility_settings["font_scale"] = scale
                        try:
                            save_accessibility_settings(config.accessibility_settings)
                        except Exception as e:
                            logger.error(f"Erreur sauvegarde accessibilité: {e}")
                        try:
                            config.init_font()
                        except Exception as e:
                            logger.error(f"Erreur init polices: {e}")
                        config.needs_redraw = True
                # 2: monitor selection (new)
                elif sel == 2 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    try:
                        from rgsx_settings import get_display_monitor, set_display_monitor, get_available_monitors
                        monitors = get_available_monitors()
                        num_monitors = len(monitors)
                        if num_monitors > 1:
                            current = get_display_monitor()
                            new_monitor = (current - 1) % num_monitors if is_input_matched(event, "left") else (current + 1) % num_monitors
                            set_display_monitor(new_monitor)
                            config.needs_redraw = True
                            # Informer l'utilisateur qu'un redémarrage est nécessaire
                            config.popup_message = _("display_monitor_restart_required")
                            config.popup_timer = 3000
                        else:
                            config.popup_message = _("display_monitor_single_only")
                            config.popup_timer = 2000
                            config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement moniteur: {e}")
                # 3: fullscreen/windowed toggle (new)
                elif sel == 3 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_display_fullscreen, set_display_fullscreen
                        current = get_display_fullscreen()
                        new_val = set_display_fullscreen(not current)
                        config.needs_redraw = True
                        # Informer l'utilisateur qu'un redémarrage est nécessaire
                        config.popup_message = _("display_mode_restart_required")
                        config.popup_timer = 3000
                    except Exception as e:
                        logger.error(f"Erreur toggle fullscreen: {e}")
                # 4: toggle unsupported (was 2)
                elif sel == 4 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_show_unsupported_platforms()
                        new_val = set_show_unsupported_platforms(not current)
                        load_sources()
                        config.popup_message = _("menu_show_unsupported_enabled") if new_val else _("menu_show_unsupported_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle unsupported: {e}")
                # 5: toggle allow unknown extensions (was 3)
                elif sel == 5 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_allow_unknown_extensions()
                        new_val = set_allow_unknown_extensions(not current)
                        config.popup_message = _("menu_allow_unknown_ext_enabled") if new_val else _("menu_allow_unknown_ext_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle allow_unknown_extensions: {e}")
                # 6: open filter platforms menu (was 4)
                elif sel == 6 and (is_input_matched(event, "confirm") or is_input_matched(event, "right")):
                    # Remember return target so the filter menu can go back to display
                    config.filter_return_to = "display_menu"
                    config.menu_state = "filter_platforms"
                    config.selected_filter_index = 0
                    config.filter_platforms_scroll_offset = 0
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True

        # Remap controls
        elif config.menu_state == "controls_mapping":
            if is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Retour à pause_menu depuis controls_mapping")
        
        # Prompt de mise à jour automatique de la liste des jeux
        elif config.menu_state == "gamelist_update_prompt":
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.gamelist_update_selection = 1 - config.gamelist_update_selection
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.gamelist_update_selection == 1:  # Oui
                    logger.info("Utilisateur a accepté la mise à jour de la liste des jeux")
                    # Lancer le téléchargement
                    config.download_tasks.clear()
                    config.pending_download = None
                    if os.path.exists(config.SOURCES_FILE):
                        try:
                            if os.path.exists(config.SOURCES_FILE):
                                os.remove(config.SOURCES_FILE)
                            if os.path.exists(os.path.join(config.SAVE_FOLDER, "sources.json")):
                                os.remove(os.path.join(config.SAVE_FOLDER, "sources.json"))
                            if os.path.exists(config.GAMES_FOLDER):
                                shutil.rmtree(config.GAMES_FOLDER)
                            if os.path.exists(config.IMAGES_FOLDER):
                                shutil.rmtree(config.IMAGES_FOLDER)
                            # Mettre à jour la date
                            from rgsx_settings import set_last_gamelist_update
                            set_last_gamelist_update()
                            config.menu_state = "restart_popup"
                            config.popup_message = _("popup_gamelist_updating") if _ else "Updating game list... Restarting..."
                            config.popup_timer = 2000
                            config.needs_redraw = True
                            restart_application(2000)
                        except Exception as e:
                            logger.error(f"Erreur lors de la mise à jour: {e}")
                            config.menu_state = "loading"
                            config.needs_redraw = True
                    else:
                        # Pas de cache existant, juste mettre à jour la date et continuer
                        from rgsx_settings import set_last_gamelist_update
                        set_last_gamelist_update()
                        config.menu_state = "loading"
                        config.needs_redraw = True
                else:  # Non
                    logger.info("Utilisateur a refusé la mise à jour de la liste des jeux")
                    # Ne pas mettre à jour la date pour redemander plus tard
                    config.menu_state = "platform"
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                logger.info("Utilisateur a annulé le prompt de mise à jour")
                config.menu_state = "platform"
                config.needs_redraw = True
        
        # Configuration du dossier personnalisé pour une plateforme
        elif config.menu_state == "platform_folder_config":
            # Options: 0=Current path, 1=Browse, 2=Reset, 3=Cancel
            if is_input_matched(event, "up") or is_input_matched(event, "down"):
                total_options = 4
                if is_input_matched(event, "up"):
                    config.platform_folder_selection = (config.platform_folder_selection - 1) % total_options
                else:
                    config.platform_folder_selection = (config.platform_folder_selection + 1) % total_options
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                from rgsx_settings import get_platform_custom_path, set_platform_custom_path
                platform_name = config.platform_config_name
                
                if config.platform_folder_selection == 0:  # Show current path
                    current_path = get_platform_custom_path(platform_name)
                    if current_path:
                        config.popup_message = current_path
                    else:
                        # Afficher le chemin par défaut en utilisant le vrai nom de dossier
                        folder_name = _get_dest_folder_name(platform_name)
                        default_path = os.path.join(config.ROMS_FOLDER, folder_name)
                        config.popup_message = _("platform_folder_default_path").format(default_path) if _ else f"Default: {default_path}"
                    config.popup_timer = 5000
                    config.needs_redraw = True
                elif config.platform_folder_selection == 1:  # Browse
                    # Ouvrir le navigateur de dossiers intégré
                    current_path = get_platform_custom_path(platform_name)
                    if not current_path or not os.path.isdir(current_path):
                        # Démarrer depuis le dossier ROMS par défaut
                        current_path = config.ROMS_FOLDER
                    config.folder_browser_path = current_path
                    config.folder_browser_selection = 0
                    config.folder_browser_scroll_offset = 0
                    config.folder_browser_mode = "platform"
                    # Charger la liste des dossiers
                    try:
                        items = [".."]
                        for item in sorted(os.listdir(current_path)):
                            full_path = os.path.join(current_path, item)
                            if os.path.isdir(full_path):
                                items.append(item)
                        config.folder_browser_items = items
                    except Exception as e:
                        logger.error(f"Erreur lecture dossier {current_path}: {e}")
                        config.folder_browser_items = [".."]
                    config.menu_state = "folder_browser"
                    config.needs_redraw = True
                elif config.platform_folder_selection == 2:  # Reset
                    set_platform_custom_path(platform_name, "")
                    config.popup_message = _("platform_folder_reset").format(platform_name) if _ else f"Folder reset for {platform_name}"
                    config.popup_timer = 3000
                    logger.info(f"Dossier personnalisé réinitialisé pour {platform_name}")
                    config.menu_state = "platform"
                    config.needs_redraw = True
                elif config.platform_folder_selection == 3:  # Cancel
                    config.menu_state = "platform"
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "platform"
                config.needs_redraw = True
        
        # Navigateur de dossiers intégré
        elif config.menu_state == "folder_browser":
            if is_input_matched(event, "up"):
                if config.folder_browser_selection > 0:
                    config.folder_browser_selection -= 1
                    # Ajuster le scroll
                    if config.folder_browser_selection < config.folder_browser_scroll_offset:
                        config.folder_browser_scroll_offset = config.folder_browser_selection
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                if config.folder_browser_selection < len(config.folder_browser_items) - 1:
                    config.folder_browser_selection += 1
                    # Ajuster le scroll
                    if config.folder_browser_selection >= config.folder_browser_scroll_offset + config.folder_browser_visible_items:
                        config.folder_browser_scroll_offset = config.folder_browser_selection - config.folder_browser_visible_items + 1
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.folder_browser_items:
                    selected_item = config.folder_browser_items[config.folder_browser_selection]
                    if selected_item == "..":
                        # Remonter d'un niveau
                        parent = os.path.dirname(config.folder_browser_path)
                        if parent and parent != config.folder_browser_path:
                            config.folder_browser_path = parent
                            config.folder_browser_selection = 0
                            config.folder_browser_scroll_offset = 0
                            try:
                                items = [".."]
                                for item in sorted(os.listdir(parent)):
                                    full_path = os.path.join(parent, item)
                                    if os.path.isdir(full_path):
                                        items.append(item)
                                config.folder_browser_items = items
                            except Exception as e:
                                logger.error(f"Erreur lecture dossier {parent}: {e}")
                                config.folder_browser_items = [".."]
                    else:
                        # Entrer dans le dossier sélectionné
                        new_path = os.path.join(config.folder_browser_path, selected_item)
                        if os.path.isdir(new_path):
                            config.folder_browser_path = new_path
                            config.folder_browser_selection = 0
                            config.folder_browser_scroll_offset = 0
                            try:
                                items = [".."]
                                for item in sorted(os.listdir(new_path)):
                                    full_path = os.path.join(new_path, item)
                                    if os.path.isdir(full_path):
                                        items.append(item)
                                config.folder_browser_items = items
                            except Exception as e:
                                logger.error(f"Erreur lecture dossier {new_path}: {e}")
                                config.folder_browser_items = [".."]
                config.needs_redraw = True
            elif is_input_matched(event, "history"):
                # Valider et sélectionner le dossier actuel (touche X/Y)
                browser_mode = getattr(config, 'folder_browser_mode', 'platform')
                selected_path = config.folder_browser_path
                
                if browser_mode == "roms_root":
                    # Mode dossier ROMs principal
                    from rgsx_settings import set_roms_folder
                    set_roms_folder(selected_path)
                    config.popup_message = _("roms_folder_set").format(selected_path) if _ else f"ROMs folder set: {selected_path}"
                    config.popup_timer = 5000
                    logger.info(f"Dossier ROMs principal défini: {selected_path}")
                    # Informer qu'un redémarrage est nécessaire
                    config.popup_message = _("roms_folder_set_restart").format(selected_path) if _ else f"ROMs folder set: {selected_path}\nRestart required!"
                    config.menu_state = "pause_settings_menu"
                else:
                    # Mode dossier plateforme
                    from rgsx_settings import set_platform_custom_path
                    platform_name = config.platform_config_name
                    set_platform_custom_path(platform_name, selected_path)
                    config.popup_message = _("platform_folder_set").format(platform_name, selected_path) if _ else f"Folder set for {platform_name}: {selected_path}"
                    config.popup_timer = 3000
                    logger.info(f"Dossier personnalisé défini pour {platform_name}: {selected_path}")
                    config.menu_state = "platform"
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                # Annuler et revenir au menu approprié selon le mode
                browser_mode = getattr(config, 'folder_browser_mode', 'platform')
                if browser_mode == "roms_root":
                    config.menu_state = "pause_settings_menu"
                else:
                    config.menu_state = "platform_folder_config"
                config.needs_redraw = True
            elif is_input_matched(event, "clear_history"):
                # Créer un nouveau dossier
                config.new_folder_name = ""
                config.new_folder_selected_key = (0, 0)
                config.menu_state = "folder_browser_new_folder"
                config.needs_redraw = True
                logger.debug("Ouverture mode création de dossier")
        
        # Création d'un nouveau dossier dans le folder browser
        elif config.menu_state == "folder_browser_new_folder":
            keyboard_layout = [
                ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
                ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
                ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
                ['W', 'X', 'C', 'V', 'B', 'N', '-', '_', '.']
            ]
            row, col = getattr(config, 'new_folder_selected_key', (0, 0))
            max_row = len(keyboard_layout) - 1
            max_col = len(keyboard_layout[row]) - 1
            
            if is_input_matched(event, "up"):
                if row == 0:
                    row = max_row + (1 if col <= len(keyboard_layout[max_row]) - 1 else 0)
                if row > 0:
                    config.new_folder_selected_key = (row - 1, min(col, len(keyboard_layout[row - 1]) - 1))
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                if row == max_row:
                    row = -1
                if row < max_row:
                    config.new_folder_selected_key = (row + 1, min(col, len(keyboard_layout[row + 1]) - 1))
                config.needs_redraw = True
            elif is_input_matched(event, "left"):
                if col == 0:
                    col = max_col + 1
                if col > 0:
                    config.new_folder_selected_key = (row, col - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "right"):
                if col == max_col:
                    col = -1
                if col < max_col:
                    config.new_folder_selected_key = (row, col + 1)
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                # Ajouter le caractère sélectionné
                config.new_folder_name = getattr(config, 'new_folder_name', '') + keyboard_layout[row][col]
                config.needs_redraw = True
            elif is_input_matched(event, "delete"):
                # Supprimer le dernier caractère
                if getattr(config, 'new_folder_name', ''):
                    config.new_folder_name = config.new_folder_name[:-1]
                config.needs_redraw = True
            elif is_input_matched(event, "space"):
                # Ajouter un espace
                config.new_folder_name = getattr(config, 'new_folder_name', '') + " "
                config.needs_redraw = True
            elif is_input_matched(event, "history"):
                # Valider et créer le dossier
                folder_name = getattr(config, 'new_folder_name', '').strip()
                if folder_name:
                    new_folder_path = os.path.join(config.folder_browser_path, folder_name)
                    try:
                        os.makedirs(new_folder_path, exist_ok=True)
                        logger.info(f"Dossier créé: {new_folder_path}")
                        config.popup_message = _("folder_created").format(folder_name) if _ else f"Folder created: {folder_name}"
                        config.popup_timer = 2000
                        # Rafraîchir la liste des dossiers et sélectionner le nouveau
                        try:
                            items = [".."]
                            for item in sorted(os.listdir(config.folder_browser_path)):
                                full_path = os.path.join(config.folder_browser_path, item)
                                if os.path.isdir(full_path):
                                    items.append(item)
                            config.folder_browser_items = items
                            # Sélectionner le nouveau dossier
                            if folder_name in items:
                                config.folder_browser_selection = items.index(folder_name)
                                # Ajuster le scroll si nécessaire
                                if config.folder_browser_selection >= config.folder_browser_visible_items:
                                    config.folder_browser_scroll_offset = config.folder_browser_selection - config.folder_browser_visible_items + 1
                        except Exception as e:
                            logger.error(f"Erreur rafraîchissement liste: {e}")
                    except Exception as e:
                        logger.error(f"Erreur création dossier {new_folder_path}: {e}")
                        config.popup_message = _("folder_create_error").format(str(e)) if _ else f"Error: {e}"
                        config.popup_timer = 3000
                config.menu_state = "folder_browser"
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                # Annuler et revenir au folder browser
                config.menu_state = "folder_browser"
                config.needs_redraw = True
        
        # Redownload game cache
        elif config.menu_state == "reload_games_data":
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.redownload_confirm_selection = 1 - config.redownload_confirm_selection
                config.needs_redraw = True
                logger.debug(f"Changement sélection reload_games_data: {config.redownload_confirm_selection}")
            elif is_input_matched(event, "confirm"):
                logger.debug(f"Action confirm dans reload_games_data, sélection={config.redownload_confirm_selection}")
                if config.redownload_confirm_selection == 1:  # Oui
                    logger.debug("Début du redownload des jeux")
                    config.download_tasks.clear()
                    config.pending_download = None
                    if os.path.exists(config.SOURCES_FILE):
                        try:
                            if os.path.exists(config.SOURCES_FILE):
                                os.remove(config.SOURCES_FILE)
                                logger.debug("Fichier system_list.json supprimé avec succès")
                            if os.path.exists(os.path.join(config.SAVE_FOLDER, "sources.json")):
                                os.remove(os.path.join(config.SAVE_FOLDER, "sources.json"))
                            if os.path.exists(config.GAMES_FOLDER):
                                shutil.rmtree(config.GAMES_FOLDER)
                                logger.debug("Dossier games supprimé avec succès")
                            if os.path.exists(config.IMAGES_FOLDER):
                                shutil.rmtree(config.IMAGES_FOLDER)
                                logger.debug("Dossier images supprimé avec succès")
                            # Mettre à jour la date de dernière mise à jour
                            from rgsx_settings import set_last_gamelist_update
                            set_last_gamelist_update()
                            config.menu_state = "restart_popup"
                            config.popup_message = _("popup_redownload_success")
                            config.popup_timer = 2000  # bref message
                            config.needs_redraw = True
                            logger.debug("Passage à restart_popup")
                            # Redémarrage automatique
                            restart_application(2000)
                        except Exception as e:
                            logger.error(f"Erreur lors de la suppression du fichier sources.json ou dossiers: {e}")
                            config.menu_state = "error"
                            config.error_message = _("error_delete_sources")
                            config.needs_redraw = True
                            return action
                    else:
                        logger.debug("Fichier sources.json non trouvé, passage à restart_popup")
                        config.menu_state = "restart_popup"
                        config.popup_message = _("popup_no_cache")
                        config.popup_timer = 2000
                        config.needs_redraw = True
                        logger.debug("Passage à restart_popup")
                        restart_application(2000)
                else:  # Non
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
                    logger.debug(f"Annulation du redownload, retour à {config.menu_state}")
            elif is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis reload_games_data")
       
       
        # Popup de redémarrage
        elif config.menu_state == "restart_popup":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.popup_message = ""
                config.popup_timer = 0
                config.needs_redraw = True
                logger.debug(f"Retour manuel à {config.menu_state} depuis restart_popup")
                
        # Sélecteur de langue
        elif config.menu_state == "language_select":
            # Gestion directe des événements pour le sélecteur de langue
            available_languages = get_available_languages()
            
            if not available_languages:
                logger.error("Aucune langue disponible")
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                return action
            
            # Navigation avec clavier et manette
            if is_input_matched(event, "up"):
                config.selected_language_index = (config.selected_language_index - 1) % len(available_languages)
                config.needs_redraw = True
                logger.debug(f"Navigation vers le haut dans le sélecteur de langue: {config.selected_language_index}")
            elif is_input_matched(event, "down"):
                config.selected_language_index = (config.selected_language_index + 1) % len(available_languages)
                config.needs_redraw = True
                logger.debug(f"Navigation vers le bas dans le sélecteur de langue: {config.selected_language_index}")
            elif is_input_matched(event, "confirm"):
                lang_code = available_languages[config.selected_language_index]
                if set_language(lang_code):
                    logger.info(f"Langue changée pour {lang_code}")
                    config.current_language = lang_code
                    # Afficher un message de confirmation
                    config.menu_state = "restart_popup"
                    config.popup_message = _("language_changed").format(lang_code)
                    config.popup_timer = 2000  # 2 secondes
                else:
                    # Retour au menu pause en cas d'erreur
                    config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug(f"Sélection de la langue: {lang_code}")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Annulation de la sélection de langue, retour au menu pause")

        # Menu de choix filtrage
        elif config.menu_state == "filter_menu_choice":
            if is_input_matched(event, "up"):
                config.selected_filter_choice = (config.selected_filter_choice - 1) % 2
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.selected_filter_choice = (config.selected_filter_choice + 1) % 2
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.selected_filter_choice == 0:
                    # Recherche par nom (mode existant)
                    config.search_mode = True
                    config.search_query = ""
                    # Initialiser avec les jeux déjà filtrés par les filtres avancés si actifs
                    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                        config.filtered_games = config.game_filter_obj.apply_filters(config.games)
                    else:
                        config.filtered_games = config.games
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.selected_key = (0, 0)
                    config.menu_state = "game"
                    config.needs_redraw = True
                    logger.debug("Entrée en mode recherche par nom")
                else:
                    # Filtrage avancé
                    from game_filters import GameFilters
                    from rgsx_settings import load_game_filters
                    
                    # Initialiser le filtre
                    if not hasattr(config, 'game_filter_obj'):
                        config.game_filter_obj = GameFilters()
                        filter_dict = load_game_filters()
                        if filter_dict:
                            config.game_filter_obj.load_from_dict(filter_dict)
                    
                    config.menu_state = "filter_advanced"
                    config.selected_filter_option = 0
                    config.needs_redraw = True
                    logger.debug("Entrée en filtrage avancé")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "game"
                config.needs_redraw = True
                logger.debug("Retour à la liste des jeux")

        # Filtrage avancé
        elif config.menu_state == "filter_advanced":
            from game_filters import GameFilters
            from rgsx_settings import save_game_filters
            
            # Initialiser le filtre si nécessaire
            if not hasattr(config, 'game_filter_obj'):
                config.game_filter_obj = GameFilters()
                from rgsx_settings import load_game_filters
                filter_dict = load_game_filters()
                if filter_dict:
                    config.game_filter_obj.load_from_dict(filter_dict)
            
            # Construire la liste linéaire des éléments sélectionnables (pour simplifier l'indexation)
            # Régions individuelles
            num_regions = len(GameFilters.REGIONS)
            # Options toggle/button
            num_other_options = 3  # hide_non_release, one_rom_per_game, priority_config
            # Boutons en bas
            num_buttons = 3  # apply, reset, back
            
            total_items = num_regions + num_other_options + num_buttons
            
            if is_input_matched(event, "up"):
                # Navigation verticale dans la grille ou entre sections
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions (3 colonnes)
                    if config.selected_filter_option >= 3:
                        # Monter d'une ligne
                        config.selected_filter_option -= 3
                    else:
                        # Déjà en haut, aller aux boutons
                        config.selected_filter_option = total_items - 2  # Bouton du milieu (reset)
                else:
                    # Dans les options ou boutons, monter normalement
                    config.selected_filter_option = (config.selected_filter_option - 1) % total_items
                
                config.needs_redraw = True
                update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            
            elif is_input_matched(event, "down"):
                # Navigation verticale
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    if config.selected_filter_option + 3 < num_regions:
                        # Descendre d'une ligne
                        config.selected_filter_option += 3
                    else:
                        # Aller aux autres options
                        config.selected_filter_option = num_regions
                else:
                    # Dans les options ou boutons, descendre normalement
                    config.selected_filter_option = (config.selected_filter_option + 1) % total_items
                
                config.needs_redraw = True
                update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            
            elif is_input_matched(event, "left"):
                # Navigation horizontale
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    if config.selected_filter_option % 3 > 0:
                        config.selected_filter_option -= 1
                    config.needs_redraw = True
                elif config.selected_filter_option >= num_regions + num_other_options:
                    # Dans les boutons en bas
                    button_idx = config.selected_filter_option - (num_regions + num_other_options)
                    button_idx = (button_idx - 1) % num_buttons
                    config.selected_filter_option = num_regions + num_other_options + button_idx
                    config.needs_redraw = True
            
            elif is_input_matched(event, "right"):
                # Navigation horizontale
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    if config.selected_filter_option % 3 < 2 and config.selected_filter_option + 1 < num_regions:
                        config.selected_filter_option += 1
                    config.needs_redraw = True
                elif config.selected_filter_option >= num_regions + num_other_options:
                    # Dans les boutons en bas
                    button_idx = config.selected_filter_option - (num_regions + num_other_options)
                    button_idx = (button_idx + 1) % num_buttons
                    config.selected_filter_option = num_regions + num_other_options + button_idx
                    config.needs_redraw = True
            
            elif is_input_matched(event, "confirm"):
                # Déterminer quel élément a été sélectionné
                if config.selected_filter_option < num_regions:
                    # C'est une région
                    region = GameFilters.REGIONS[config.selected_filter_option]
                    current_state = config.game_filter_obj.region_filters.get(region, 'include')
                    if current_state == 'include':
                        config.game_filter_obj.region_filters[region] = 'exclude'
                    else:
                        config.game_filter_obj.region_filters[region] = 'include'
                    config.needs_redraw = True
                    logger.debug(f"Filtre région {region} modifié: {config.game_filter_obj.region_filters[region]}")
                
                elif config.selected_filter_option < num_regions + num_other_options:
                    # C'est une autre option
                    option_idx = config.selected_filter_option - num_regions
                    if option_idx == 0:
                        # hide_non_release
                        config.game_filter_obj.hide_non_release = not config.game_filter_obj.hide_non_release
                        config.needs_redraw = True
                        logger.debug("Toggle hide_non_release modifié")
                    elif option_idx == 1:
                        # one_rom_per_game
                        config.game_filter_obj.one_rom_per_game = not config.game_filter_obj.one_rom_per_game
                        config.needs_redraw = True
                        logger.debug("Toggle one_rom_per_game modifié")
                    elif option_idx == 2:
                        # priority_config
                        config.menu_state = "filter_priority_config"
                        config.selected_priority_index = 0
                        config.needs_redraw = True
                        logger.debug("Ouverture configuration priorité régions")
                
                else:
                    # C'est un bouton
                    button_idx = config.selected_filter_option - (num_regions + num_other_options)
                    if button_idx == 0:
                        # Apply
                        save_game_filters(config.game_filter_obj.to_dict())
                        
                        # Appliquer aux jeux actuels
                        if config.game_filter_obj.is_active():
                            config.filtered_games = config.game_filter_obj.apply_filters(config.games)
                            config.filter_active = True
                        else:
                            config.filtered_games = config.games
                            config.filter_active = False
                        
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.menu_state = "game"
                        config.needs_redraw = True
                        logger.debug("Filtres appliqués")
                    
                    elif button_idx == 1:
                        # Reset
                        config.game_filter_obj.reset()
                        save_game_filters(config.game_filter_obj.to_dict())
                        config.filtered_games = config.games
                        config.filter_active = False
                        config.needs_redraw = True
                        logger.debug("Filtres réinitialisés")
                    
                    elif button_idx == 2:
                        # Back
                        config.menu_state = "game"
                        config.needs_redraw = True
                        logger.debug("Retour sans appliquer les filtres")
            
            elif is_input_matched(event, "cancel"):
                config.menu_state = "game"
                config.needs_redraw = True
                logger.debug("Annulation du filtrage avancé")

        # Configuration priorité régions
        elif config.menu_state == "filter_priority_config":
            from game_filters import GameFilters
            from rgsx_settings import save_game_filters
            
            if not hasattr(config, 'game_filter_obj'):
                config.game_filter_obj = GameFilters()
            
            priority_list = config.game_filter_obj.region_priority
            total_items = len(priority_list) + 1  # +1 pour le bouton Back
            
            if not hasattr(config, 'selected_priority_index'):
                config.selected_priority_index = 0
            
            if is_input_matched(event, "up"):
                config.selected_priority_index = (config.selected_priority_index - 1) % total_items
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.selected_priority_index = (config.selected_priority_index + 1) % total_items
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.selected_priority_index >= len(priority_list):
                    # Bouton Back : retour au menu filtrage avancé
                    save_game_filters(config.game_filter_obj.to_dict())
                    config.menu_state = "filter_advanced"
                    config.needs_redraw = True
                    logger.debug("Retour au filtrage avancé")
            elif is_input_matched(event, "left") and config.selected_priority_index < len(priority_list):
                # Monter la région dans la priorité
                idx = config.selected_priority_index
                if idx > 0:
                    priority_list[idx], priority_list[idx-1] = priority_list[idx-1], priority_list[idx]
                    config.selected_priority_index = idx - 1
                    config.needs_redraw = True
                    logger.debug(f"Priorité modifiée: {priority_list}")
            elif is_input_matched(event, "right") and config.selected_priority_index < len(priority_list):
                # Descendre la région dans la priorité
                idx = config.selected_priority_index
                if idx < len(priority_list) - 1:
                    priority_list[idx], priority_list[idx+1] = priority_list[idx+1], priority_list[idx]
                    config.selected_priority_index = idx + 1
                    config.needs_redraw = True
                    logger.debug(f"Priorité modifiée: {priority_list}")
            elif is_input_matched(event, "cancel"):
                # Retour sans sauvegarder
                config.menu_state = "filter_advanced"
                config.needs_redraw = True
                logger.debug("Annulation configuration priorité")

    # Menu filtre plateformes
        elif config.menu_state == "filter_platforms":
            total_items = len(config.filter_platforms_selection)
            action_buttons = 4
            # Indices: 0-3 = boutons, 4+ = liste des systèmes
            extended_max = action_buttons + total_items - 1
            if is_input_matched(event, "up"):
                if config.selected_filter_index > 0:
                    config.selected_filter_index -= 1
                    config.needs_redraw = True
                else:
                    # Wrap vers le bas (dernière ligne de la liste)
                    config.selected_filter_index = extended_max
                    config.needs_redraw = True
                # Activer la répétition automatique
                update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            elif is_input_matched(event, "down"):
                if config.selected_filter_index < extended_max:
                    config.selected_filter_index += 1
                    config.needs_redraw = True
                else:
                    # Wrap retour en haut (premier bouton)
                    config.selected_filter_index = 0
                    config.needs_redraw = True
                # Activer la répétition automatique
                update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            elif is_input_matched(event, "left"):
                # Navigation gauche/droite uniquement pour les boutons (indices 0-3)
                if config.selected_filter_index < action_buttons:
                    if config.selected_filter_index > 0:
                        config.selected_filter_index -= 1
                        config.needs_redraw = True
                # sinon ignorer (dans la liste)
            elif is_input_matched(event, "right"):
                # Navigation gauche/droite uniquement pour les boutons (indices 0-3)
                if config.selected_filter_index < action_buttons:
                    if config.selected_filter_index < action_buttons - 1:
                        config.selected_filter_index += 1
                        config.needs_redraw = True
                # sinon ignorer (dans la liste)
            elif is_input_matched(event, "confirm"):
                # Indices 0-3 = boutons, 4+ = liste
                if config.selected_filter_index < action_buttons:
                    # Action sur un bouton
                    btn_idx = config.selected_filter_index
                    settings = load_rgsx_settings()
                    if btn_idx == 0:  # all visible
                        config.filter_platforms_selection = [(n, False) for n, _ in config.filter_platforms_selection]
                        config.filter_platforms_dirty = True
                    elif btn_idx == 1:  # none visible
                        config.filter_platforms_selection = [(n, True) for n, _ in config.filter_platforms_selection]
                        config.filter_platforms_dirty = True
                    elif btn_idx == 2:  # apply
                        hidden_list = [n for n, h in config.filter_platforms_selection if h]
                        settings["hidden_platforms"] = hidden_list
                        save_rgsx_settings(settings)
                        load_sources()
                        # Recalibrer la sélection et la page courante si elles dépassent la nouvelle liste visible
                        try:
                            systems_per_page = config.GRID_COLS * config.GRID_ROWS
                            if config.current_page * systems_per_page >= len(config.platforms):
                                config.current_page = 0
                            if config.selected_platform >= len(config.platforms):
                                config.selected_platform = 0
                        except Exception:
                            # Sécurité: en cas d'erreur on remet simplement à 0
                            config.current_page = 0
                            config.selected_platform = 0
                        config.filter_platforms_dirty = False
                        # Return either to display menu or pause menu depending on origin
                        target = getattr(config, 'filter_return_to', 'pause_menu')
                        config.menu_state = target
                        if target == 'display_menu':  # ancien cas (fallback)
                            config.display_menu_selection = 3
                        elif target == 'pause_display_menu':  # nouveau sous-menu hiérarchique
                            config.pause_display_selection = 4  # positionner sur Filter
                        else:
                            config.selected_option = 5  # keep pointer on Filter in pause menu
                        config.filter_return_to = None
                    elif btn_idx == 3:  # back
                        target = getattr(config, 'filter_return_to', 'pause_menu')
                        config.menu_state = target
                        if target == 'display_menu':
                            config.display_menu_selection = 3
                        elif target == 'pause_display_menu':
                            config.pause_display_selection = 4
                        else:
                            config.selected_option = 5
                        config.filter_return_to = None
                    config.needs_redraw = True
                else:
                    # Action sur un élément de la liste (indices >= action_buttons)
                    list_index = config.selected_filter_index - action_buttons
                    if list_index < total_items:
                        name, hidden = config.filter_platforms_selection[list_index]
                        config.filter_platforms_selection[list_index] = (name, not hidden)
                        config.filter_platforms_dirty = True
                        config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                target = getattr(config, 'filter_return_to', 'pause_menu')
                config.menu_state = target
                if target == 'display_menu':
                    config.display_menu_selection = 3
                elif target == 'pause_display_menu':
                    config.pause_display_selection = 4
                else:
                    config.selected_option = 5
                config.filter_return_to = None
                config.needs_redraw = True


    # Gestion des relâchements de touches
    if event.type == pygame.KEYUP:
        # Vérifier quelle touche a été relâchée
        # Définir le mapping clavier (même que dans is_input_matched)
        keyboard_fallback = {
            "up": pygame.K_UP,
            "down": pygame.K_DOWN,
            "left": pygame.K_LEFT,
            "right": pygame.K_RIGHT,
            "confirm": pygame.K_RETURN,
            "cancel": pygame.K_ESCAPE,
            "page_up": pygame.K_PAGEUP,
            "page_down": pygame.K_PAGEDOWN,
        }
        
        for action_name in ["up", "down", "left", "right", "page_up", "page_down", "confirm", "cancel"]:
            # Vérifier d'abord le keyboard_fallback
            if action_name in keyboard_fallback and keyboard_fallback[action_name] == event.key:
                update_key_state(action_name, False)
            # Sinon vérifier la config normale
            elif config.controls_config.get(action_name, {}).get("type") == "key" and \
               config.controls_config.get(action_name, {}).get("key") == event.key:
                update_key_state(action_name, False)
                
            # Gestion spéciale pour confirm dans le menu game (ne dépend pas du key_state)
            if action_name == "confirm" and config.menu_state == "game" and \
               ((action_name in keyboard_fallback and keyboard_fallback[action_name] == event.key) or \
                (config.controls_config.get(action_name, {}).get("type") == "key" and \
                 config.controls_config.get(action_name, {}).get("key") == event.key)):
                    press_duration = current_time - config.confirm_press_start_time
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not config.confirm_long_press_triggered:
                        # Déclencher le téléchargement normal
                        games = config.filtered_games if config.filter_active or config.search_mode else config.games
                        if games:
                            url = games[config.current_game][1]
                            game_name = games[config.current_game][0]
                            platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                            logger.debug(f"Appui court sur confirm ({press_duration}ms), téléchargement pour {game_name}, URL: {url}")
                            
                            # Vérifier d'abord l'extension avant d'ajouter à l'historique
                            if is_1fichier_url(url):
                                ensure_download_provider_keys(False)
                                
                                # Avertissement si pas de clé (utilisation mode gratuit)
                                if missing_all_provider_keys():
                                    logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
                                
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        load_extensions_json()
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        task_id = str(pygame.time.get_ticks())
                                        task = asyncio.create_task(download_from_1fichier(url, platform, game_name, config.pending_download[3], task_id))
                                        config.download_tasks[task_id] = (task, url, game_name, platform)
                                        show_toast(f"{_('download_started')}: {game_name}")
                                        config.needs_redraw = True
                                        logger.debug(f"Début du téléchargement 1fichier: {game_name} pour {platform}, task_id={task_id}")
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    config.error_message = "Extension non supportée ou erreur de téléchargement"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                            else:
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    extensions_data = load_extensions_json()
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        extensions_data
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        task_id = str(pygame.time.get_ticks())
                                        task = asyncio.create_task(download_rom(url, platform, game_name, config.pending_download[3], task_id))
                                        config.download_tasks[task_id] = (task, url, game_name, platform)
                                        show_toast(f"{_('download_started')}: {game_name}")
                                        config.needs_redraw = True
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    try:
                                        config.error_message = _("error_invalid_download_data")
                                    except Exception:
                                        config.error_message = "Invalid download data"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                    # Réinitialiser les flags
                    config.confirm_press_start_time = 0
                    config.confirm_long_press_triggered = False
            
            # Gestion spéciale pour confirm dans le menu platform (appui court = aller aux jeux)
            if action_name == "confirm" and config.menu_state == "platform" and \
               ((action_name in keyboard_fallback and keyboard_fallback[action_name] == event.key) or \
                (config.controls_config.get(action_name, {}).get("type") == "key" and \
                 config.controls_config.get(action_name, {}).get("key") == event.key)):
                    press_duration = current_time - getattr(config, 'platform_confirm_press_start_time', 0)
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not getattr(config, 'platform_confirm_long_press_triggered', False):
                        # Naviguer vers les jeux
                        if config.platforms:
                            config.current_platform = config.selected_platform
                            config.games = load_games(config.platforms[config.current_platform])
                            
                            # Apply saved filters automatically if any
                            if config.game_filter_obj and config.game_filter_obj.is_active():
                                config.filtered_games = config.game_filter_obj.apply_filters(config.games)
                                config.filter_active = True
                            else:
                                config.filtered_games = config.games
                                config.filter_active = False
                            
                            config.current_game = 0
                            config.scroll_offset = 0
                            
                            # Désactiver l'animation de transition en mode performance (light mode)
                            from rgsx_settings import get_light_mode
                            if not get_light_mode():
                                draw_validation_transition(screen, config.current_platform)
                            
                            config.menu_state = "game"
                            config.needs_redraw = True
                            logger.debug(f"Appui court clavier sur confirm ({press_duration}ms), navigation vers les jeux de {config.platforms[config.current_platform]}")
                    # Réinitialiser les flags platform
                    config.platform_confirm_press_start_time = 0
                    config.platform_confirm_long_press_triggered = False
    
    elif event.type == pygame.JOYBUTTONUP:
        # Vérifier quel bouton a été relâché
        for action_name in ["up", "down", "left", "right", "page_up", "page_down", "confirm", "cancel"]:
            if config.controls_config.get(action_name, {}).get("type") == "button" and \
               config.controls_config.get(action_name, {}).get("button") == event.button:
                # Vérifier que cette action était bien activée par un bouton gamepad
                if action_name in key_states and key_states[action_name].get("event_type") == pygame.JOYBUTTONDOWN:
                    update_key_state(action_name, False)
                
                # Gestion spéciale pour confirm dans le menu game (ne dépend pas du key_state)
                if action_name == "confirm" and config.menu_state == "game":
                    press_duration = current_time - config.confirm_press_start_time
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not config.confirm_long_press_triggered:
                        # Déclencher le téléchargement normal (même code que pour KEYUP)
                        games = config.filtered_games if config.filter_active or config.search_mode else config.games
                        if games:
                            url = games[config.current_game][1]
                            game_name = games[config.current_game][0]
                            platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                            logger.debug(f"Appui court sur confirm ({press_duration}ms), téléchargement pour {game_name}, URL: {url}")
                            
                            # Vérifier d'abord l'extension avant d'ajouter à l'historique
                            if is_1fichier_url(url):
                                ensure_download_provider_keys(False)
                                
                                # Avertissement si pas de clé (utilisation mode gratuit)
                                if missing_all_provider_keys():
                                    logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
                                
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        load_extensions_json()
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        task_id = str(pygame.time.get_ticks())
                                        task = asyncio.create_task(download_from_1fichier(url, platform, game_name, config.pending_download[3], task_id))
                                        config.download_tasks[task_id] = (task, url, game_name, platform)
                                        show_toast(f"{_('download_started')}: {game_name}")
                                        config.needs_redraw = True
                                        logger.debug(f"Début du téléchargement 1fichier: {game_name} pour {platform}, task_id={task_id}")
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    config.error_message = "Extension non supportée ou erreur de téléchargement"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                            else:
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    extensions_data = load_extensions_json()
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        extensions_data
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        task_id = str(pygame.time.get_ticks())
                                        task = asyncio.create_task(download_rom(url, platform, game_name, config.pending_download[3], task_id))
                                        config.download_tasks[task_id] = (task, url, game_name, platform)
                                        show_toast(f"{_('download_started')}: {game_name}")
                                        config.needs_redraw = True
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    try:
                                        config.error_message = _("error_invalid_download_data")
                                    except Exception:
                                        config.error_message = "Invalid download data"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                    # Réinitialiser les flags
                    config.confirm_press_start_time = 0
                    config.confirm_long_press_triggered = False
                
                # Gestion spéciale pour confirm dans le menu platform (appui court = aller aux jeux)
                if action_name == "confirm" and config.menu_state == "platform":
                    press_duration = current_time - getattr(config, 'platform_confirm_press_start_time', 0)
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not getattr(config, 'platform_confirm_long_press_triggered', False):
                        # Naviguer vers les jeux
                        if config.platforms:
                            config.current_platform = config.selected_platform
                            config.games = load_games(config.platforms[config.current_platform])
                            
                            # Apply saved filters automatically if any
                            if config.game_filter_obj and config.game_filter_obj.is_active():
                                config.filtered_games = config.game_filter_obj.apply_filters(config.games)
                                config.filter_active = True
                            else:
                                config.filtered_games = config.games
                                config.filter_active = False
                            
                            config.current_game = 0
                            config.scroll_offset = 0
                            
                            # Désactiver l'animation de transition en mode performance (light mode)
                            from rgsx_settings import get_light_mode
                            if not get_light_mode():
                                draw_validation_transition(screen, config.current_platform)
                            
                            config.menu_state = "game"
                            config.needs_redraw = True
                            logger.debug(f"Appui court sur confirm ({press_duration}ms), navigation vers les jeux de {config.platforms[config.current_platform]}")
                    # Réinitialiser les flags platform
                    config.platform_confirm_press_start_time = 0
                    config.platform_confirm_long_press_triggered = False
    
    elif event.type == pygame.JOYAXISMOTION:
        # Détection de relâchement d'axe
        # Pour les triggers Xbox (axes 4 et 5), relâché = retour à -1.0
        # Pour les autres axes, relâché = proche de 0
        is_released = False
        if event.axis in [4, 5]:  # Triggers Xbox
            is_released = event.value < 0.5  # Relâché si < 0.5 (pas appuyé)
        else:  # Autres axes
            is_released = abs(event.value) < 0.5
        
        if is_released:
            for action_name in ["up", "down", "left", "right", "page_up", "page_down"]:
                if config.controls_config.get(action_name, {}).get("type") == "axis" and \
                   config.controls_config.get(action_name, {}).get("axis") == event.axis:
                    # Vérifier que cette action était bien activée par cet axe
                    if action_name in key_states and key_states[action_name].get("event_type") == pygame.JOYAXISMOTION:
                        update_key_state(action_name, False)
    
    elif event.type == pygame.JOYHATMOTION and event.value == (0, 0):
        # Vérifier quel hat a été relâché
        for action_name in ["up", "down", "left", "right", "page_up", "page_down"]:
            if config.controls_config.get(action_name, {}).get("type") == "hat":
                # Vérifier que cette action était bien activée par un hat
                if action_name in key_states and key_states[action_name].get("event_type") == pygame.JOYHATMOTION:
                    update_key_state(action_name, False)

    return action

# Nouvelle implémentation de la répétition des touches
def update_key_state(action, pressed, event_type=None, event_value=None):
    """Met à jour l'état d'une touche pour la répétition automatique."""
    current_time = pygame.time.get_ticks()
    
    if pressed:
        # La touche vient d'être pressée
        if action not in key_states:
            key_states[action] = {
                "pressed": True,
                "first_press_time": current_time,
                "last_repeat_time": current_time,
                "event_type": event_type,
                "event_value": event_value
            }
    else:
        # La touche vient d'être relâchée
        if action in key_states:
            del key_states[action]

def process_key_repeats(sources, joystick, screen):
    """Traite la répétition des touches."""
    current_time = pygame.time.get_ticks()
    
    for action, state in list(key_states.items()):
        if not state["pressed"]:
            continue
            
        time_since_first_press = current_time - state["first_press_time"]
        time_since_last_repeat = current_time - state["last_repeat_time"]
        
        # Vérifier si nous devons déclencher une répétition
        if (time_since_first_press > REPEAT_DELAY and 
            time_since_last_repeat > REPEAT_INTERVAL):
            
            # Créer un événement synthétique selon le type
            event_type = state["event_type"]
            event_value = state["event_value"]
            
            if event_type == pygame.KEYDOWN:
                event = pygame.event.Event(pygame.KEYDOWN, {"key": event_value})
            elif event_type == pygame.JOYBUTTONDOWN:
                event = pygame.event.Event(pygame.JOYBUTTONDOWN, {"button": event_value})
            elif event_type == pygame.JOYAXISMOTION:
                axis, value = event_value
                event = pygame.event.Event(pygame.JOYAXISMOTION, {"axis": axis, "value": value})
            elif event_type == pygame.JOYHATMOTION:
                event = pygame.event.Event(pygame.JOYHATMOTION, {"value": event_value})
            else:
                continue  # Type d'événement non pris en charge
            
            # Traiter l'événement répété
            handle_controls(event, sources, joystick, screen)
            
            # Mettre à jour le temps de la dernière répétition
            state["last_repeat_time"] = current_time
            
            # Forcer le redessinage
            config.needs_redraw = True

def get_emergency_controls():
    """Retourne une configuration de contrôles de secours pour permettre la navigation de base."""
    return {
        "confirm": {"type": "key", "key": pygame.K_RETURN},
        "cancel": {"type": "key", "key": pygame.K_ESCAPE},
        "up": {"type": "key", "key": pygame.K_UP},
        "down": {"type": "key", "key": pygame.K_DOWN},
        "left": {"type": "key", "key": pygame.K_LEFT},
        "right": {"type": "key", "key": pygame.K_RIGHT},
        "start": {"type": "key", "key": pygame.K_p},
        "history": {"type": "key", "key": pygame.K_h},
        "clear_history": {"type": "key", "key": pygame.K_x},
        "page_up": {"type": "key", "key": pygame.K_PAGEUP},
        "page_down": {"type": "key", "key": pygame.K_PAGEDOWN},
        # manette basique
        "confirm_joy": {"type": "button", "button": 0},
        "cancel_joy": {"type": "button", "button": 1},
    }

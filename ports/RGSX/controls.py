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
    # Nouveaux sous-menus hiérarchiques (refonte pause menu)
    "pause_controls_menu",      # sous-menu Controls (aide, remap)
    "pause_display_menu",       # sous-menu Display (layout, font size, unsupported, unknown ext, filter)
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
    # Nouveaux menus filtrage avancé
    "filter_menu_choice",       # menu de choix entre recherche et filtrage avancé
    "filter_search",            # recherche par nom (existant, mais renommé)
    "filter_advanced",          # filtrage avancé par région, etc.
    "filter_priority_config",   # configuration priorité régions pour one-rom-per-game
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
                            print(f"Chargement préréglage (device) depuis le fichier: {fname}")
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
                    draw_validation_transition(screen, config.current_platform)
                    config.menu_state = "game"
                    config.needs_redraw = True
                    #logger.debug(f"Plateforme sélectionnée: {config.platforms[config.current_platform]}, {len(config.games)} jeux chargés")
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
                    if row > 0:
                        config.selected_key = (row - 1, min(col, len(keyboard_layout[row - 1]) - 1))
                        config.repeat_action = "up"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    if row < max_row:
                        config.selected_key = (row + 1, min(col, len(keyboard_layout[row + 1]) - 1))
                        config.repeat_action = "down"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "left"):
                    if col > 0:
                        config.selected_key = (row, col - 1)
                        config.repeat_action = "left"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "right"):
                    if col < max_col:
                        config.selected_key = (row, col + 1)
                        config.repeat_action = "right"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "confirm"):
                    config.search_query += keyboard_layout[row][col]
                    config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()]
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug(f"Recherche mise à jour: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "delete"):
                    if config.search_query:
                        config.search_query = config.search_query[:-1]
                        config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()]
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        #logger.debug(f"Suppression caractère: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "space"):
                    config.search_query += " "
                    config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()]
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    #logger.debug(f"Espace ajouté: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "cancel"):
                    config.search_mode = False
                    config.search_query = ""
                    config.selected_key = (0, 0)
                    config.filtered_games = config.games
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
                        config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()]
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug(f"Recherche mise à jour: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                    # Gestion de la suppression
                    elif is_input_matched(event, "delete"):
                        if config.search_query:
                            config.search_query = config.search_query[:-1]
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()]
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
                        config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                        config.needs_redraw = True
                        logger.debug(f"[CONTROLS_EXT_WARNING] Téléchargement confirmé après avertissement: {game_name} pour {platform} depuis {url}, task_id={task_id}")
                        config.pending_download = None
                        config.extension_confirm_selection = 0  # Réinitialiser la sélection
                        action = "download"
                        # Téléchargement simple - retourner au menu précédent
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
                    url = entry.get("url")
                    # Annuler la tâche correspondante
                    for task_id, (task, task_url, game_name, platform) in list(config.download_tasks.items()):
                        if task_url == url:
                            try:
                                request_cancel(task_id)
                            except Exception:
                                pass
                            task.cancel()
                            del config.download_tasks[task_id]
                            entry["status"] = "Canceled"
                            entry["progress"] = 0
                            entry["message"] = _("download_canceled") if _ else "Download canceled"
                            save_history(config.history)
                            logger.debug(f"Téléchargement annulé: {game_name}")
                            break
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
                if status == "Download_OK" or status == "Completed":
                    # Vérifier si c'est une archive ET si le fichier existe
                    if actual_filename and file_exists:
                        ext = os.path.splitext(actual_filename)[1].lower()
                        if ext in ['.zip', '.rar']:
                            options.append("extract_archive")
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
                    
                    if selected_option == "download_folder":
                        # Afficher le chemin de destination
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_show_folder"
                        config.needs_redraw = True
                        logger.debug(f"Affichage du dossier de téléchargement pour {game_name}")
                        
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
            if is_input_matched(event, "confirm"):
                if config.confirm_selection == 1:
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
                else:
                    # Retour à l'état capturé (confirm_exit_origin) sinon previous_menu_state sinon platform
                    target = getattr(config, 'confirm_exit_origin', getattr(config, 'previous_menu_state', 'platform'))
                    config.menu_state = validate_menu_state(target)
                    if hasattr(config, 'confirm_exit_origin'):
                        try:
                            delattr(config, 'confirm_exit_origin')
                        except Exception:
                            pass
                    config.needs_redraw = True
                    logger.debug(f"Retour à {config.menu_state} depuis confirm_exit (annulation)")
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.confirm_selection = 1 - config.confirm_selection
                config.needs_redraw = True
                #logger.debug(f"Changement sélection confirm_exit: {config.confirm_selection}")

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
                config.selected_option = max(0, config.selected_option - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                # Menu racine hiérarchique: nombre dynamique (langue + catégories)
                total = getattr(config, 'pause_menu_total_options', 7)
                config.selected_option = min(total - 1, config.selected_option + 1)
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.selected_option == 0:  # Language selector direct
                    config.menu_state = "language_select"
                    config.previous_menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 1:  # Controls submenu
                    config.menu_state = "pause_controls_menu"
                    if not hasattr(config, 'pause_controls_selection'):
                        config.pause_controls_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 2:  # Display submenu
                    config.menu_state = "pause_display_menu"
                    if not hasattr(config, 'pause_display_selection'):
                        config.pause_display_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 3:  # Games submenu
                    config.menu_state = "pause_games_menu"
                    if not hasattr(config, 'pause_games_selection'):
                        config.pause_games_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 4:  # Settings submenu
                    config.menu_state = "pause_settings_menu"
                    if not hasattr(config, 'pause_settings_selection'):
                        config.pause_settings_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif config.selected_option == 5:  # Restart
                    restart_application(2000)
                elif config.selected_option == 6:  # Support
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
                elif config.selected_option == 7:  # Quit
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
            sel = getattr(config, 'pause_controls_selection', 0)
            if is_input_matched(event, "up"):
                config.pause_controls_selection = (sel - 1) % 3
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_controls_selection = (sel + 1) % 3
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if sel == 0:  # Aide
                    config.previous_menu_state = "pause_controls_menu"
                    config.menu_state = "controls_help"
                elif sel == 1:  # Remap
                    if os.path.exists(config.CONTROLS_CONFIG_PATH):
                        try:
                            os.remove(config.CONTROLS_CONFIG_PATH)
                        except Exception as e:
                            logger.error(f"Erreur suppression controls_config: {e}")
                    config.previous_menu_state = "pause_controls_menu"
                    config.menu_state = "controls_mapping"
                else:  # Back
                    config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Display
        elif config.menu_state == "pause_display_menu":
            sel = getattr(config, 'pause_display_selection', 0)
            total = 6  # layout, font size, footer font size, font family, allow unknown extensions, back
            if is_input_matched(event, "up"):
                config.pause_display_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0 layout cycle
                if sel == 0 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    layouts = [(3,3),(3,4),(4,3),(4,4)]
                    try:
                        idx = layouts.index((config.GRID_COLS, config.GRID_ROWS))
                    except ValueError:
                        idx = 0
                    idx = (idx + 1) % len(layouts) if is_input_matched(event, "right") else (idx - 1) % len(layouts)
                    new_cols, new_rows = layouts[idx]
                    try:
                        set_display_grid(new_cols, new_rows)
                    except Exception as e:
                        logger.error(f"Erreur set_display_grid: {e}")
                    config.GRID_COLS = new_cols
                    config.GRID_ROWS = new_rows
                    # Afficher un popup indiquant que le changement sera effectif après redémarrage
                    try:
                        config.popup_message = _("popup_layout_changed_restart_required") if _ else "Layout changed. Restart required to apply."
                        config.popup_timer = 3000
                    except Exception as e:
                        logger.error(f"Erreur popup layout: {e}")
                    config.needs_redraw = True
                # 1 font size
                elif sel == 1 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
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
                # 2 footer font size
                elif sel == 2 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
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
                # 3 font family cycle
                elif sel == 3 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
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
                # 4 allow unknown extensions
                elif sel == 4 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_allow_unknown_extensions()
                        new_val = set_allow_unknown_extensions(not current)
                        config.popup_message = _("menu_allow_unknown_ext_enabled") if new_val else _("menu_allow_unknown_ext_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle allow_unknown_extensions: {e}")
                # 5 back
                elif sel == 5 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Games
        elif config.menu_state == "pause_games_menu":
            sel = getattr(config, 'pause_games_selection', 0)
            total = 7  # history, source, redownload, unsupported, hide premium, filter, back
            if is_input_matched(event, "up"):
                config.pause_games_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_games_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right"):
                if sel == 0 and is_input_matched(event, "confirm"):  # history
                    config.history = load_history()
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.previous_menu_state = "pause_games_menu"
                    config.menu_state = "history"
                    config.needs_redraw = True
                elif sel == 1 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
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
                elif sel == 2 and is_input_matched(event, "confirm"):  # redownload cache
                    config.previous_menu_state = "pause_games_menu"
                    config.menu_state = "reload_games_data"
                    config.redownload_confirm_selection = 0
                    config.needs_redraw = True
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
            total = 4  # music, symlink, api keys, back
            web_service_index = -1
            if config.OPERATING_SYSTEM == "Linux":
                total = 5  # music, symlink, web_service, api keys, back
                web_service_index = 2
            
            if is_input_matched(event, "up"):
                config.pause_settings_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_settings_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right"):
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
                # Option 2: Web Service toggle (seulement si Linux)
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
                # Option API Keys (index varie selon Linux ou pas)
                elif sel == (web_service_index + 1 if web_service_index >= 0 else 2) and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_api_keys_status"
                    config.needs_redraw = True
                # Option Back (dernière option)
                elif sel == (total - 1) and is_input_matched(event, "confirm"):
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

        # Menu Affichage (layout, police, unsupported)
        elif config.menu_state == "display_menu":
            sel = getattr(config, 'display_menu_selection', 0)
            if is_input_matched(event, "up"):
                config.display_menu_selection = (sel - 1) % 5
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.display_menu_selection = (sel + 1) % 5
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
                # 2: toggle unsupported
                elif sel == 2 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_show_unsupported_platforms()
                        new_val = set_show_unsupported_platforms(not current)
                        load_sources()
                        config.popup_message = _("menu_show_unsupported_enabled") if new_val else _("menu_show_unsupported_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle unsupported: {e}")
                # 3: toggle allow unknown extensions
                elif sel == 3 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_allow_unknown_extensions()
                        new_val = set_allow_unknown_extensions(not current)
                        config.popup_message = _("menu_allow_unknown_ext_enabled") if new_val else _("menu_allow_unknown_ext_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle allow_unknown_extensions: {e}")
                # 4: open filter platforms menu
                elif sel == 4 and (is_input_matched(event, "confirm") or is_input_matched(event, "right")):
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
            
            # Construire la liste des options (comme dans draw_filter_advanced)
            options = []
            options.append(('header', 'region_title'))
            for region in GameFilters.REGIONS:
                options.append(('region', region))
            options.append(('separator', ''))
            options.append(('header', 'other_options'))
            options.append(('toggle', 'hide_non_release'))
            options.append(('toggle', 'one_rom_per_game'))
            options.append(('button_inline', 'priority_config'))
            
            # Boutons séparés (3 boutons au total)
            buttons = [
                ('button', 'apply'),
                ('button', 'reset'),
                ('button', 'back')
            ]
            
            # Total d'éléments sélectionnables
            total_items = len(options) + len(buttons)
            
            if is_input_matched(event, "up"):
                # Chercher l'option sélectionnable précédente
                config.selected_filter_option = (config.selected_filter_option - 1) % total_items
                while config.selected_filter_option < len(options) and options[config.selected_filter_option][0] in ['header', 'separator']:
                    config.selected_filter_option = (config.selected_filter_option - 1) % total_items
                config.needs_redraw = True
                update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            elif is_input_matched(event, "down"):
                # Chercher l'option sélectionnable suivante
                config.selected_filter_option = (config.selected_filter_option + 1) % total_items
                while config.selected_filter_option < len(options) and options[config.selected_filter_option][0] in ['header', 'separator']:
                    config.selected_filter_option = (config.selected_filter_option + 1) % total_items
                config.needs_redraw = True
                update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                # Navigation gauche/droite uniquement pour les boutons en bas
                if config.selected_filter_option >= len(options):
                    button_index = config.selected_filter_option - len(options)
                    if is_input_matched(event, "left"):
                        button_index = (button_index - 1) % len(buttons)
                    else:
                        button_index = (button_index + 1) % len(buttons)
                    config.selected_filter_option = len(options) + button_index
                    config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                # Déterminer si c'est une option ou un bouton
                if config.selected_filter_option < len(options):
                    option_type, *option_data = options[config.selected_filter_option]
                else:
                    # C'est un bouton
                    button_index = config.selected_filter_option - len(options)
                    option_type, *option_data = buttons[button_index]
                
                if option_type == 'region':
                    # Basculer filtre région: include ↔ exclude (include par défaut)
                    region = option_data[0]
                    current_state = config.game_filter_obj.region_filters.get(region, 'include')
                    if current_state == 'include':
                        config.game_filter_obj.region_filters[region] = 'exclude'
                    else:
                        config.game_filter_obj.region_filters[region] = 'include'
                    config.needs_redraw = True
                    logger.debug(f"Filtre région {region} modifié: {config.game_filter_obj.region_filters[region]}")
                
                elif option_type == 'toggle':
                    toggle_name = option_data[0]
                    if toggle_name == 'hide_non_release':
                        config.game_filter_obj.hide_non_release = not config.game_filter_obj.hide_non_release
                    elif toggle_name == 'one_rom_per_game':
                        config.game_filter_obj.one_rom_per_game = not config.game_filter_obj.one_rom_per_game
                    config.needs_redraw = True
                    logger.debug(f"Toggle {toggle_name} modifié")
                
                elif option_type == 'button_inline':
                    button_name = option_data[0]
                    if button_name == 'priority_config':
                        # Ouvrir le menu de configuration de priorité
                        config.menu_state = "filter_priority_config"
                        config.selected_priority_index = 0
                        config.needs_redraw = True
                        logger.debug("Ouverture configuration priorité régions")
                
                elif option_type == 'button':
                    button_name = option_data[0]
                    if button_name == 'apply':
                        # Appliquer les filtres
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
                    
                    elif button_name == 'reset':
                        # Réinitialiser les filtres
                        config.game_filter_obj.reset()
                        save_game_filters(config.game_filter_obj.to_dict())
                        config.filtered_games = config.games
                        config.filter_active = False
                        config.needs_redraw = True
                        logger.debug("Filtres réinitialisés")
                    
                    elif button_name == 'back':
                        # Retour sans appliquer
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
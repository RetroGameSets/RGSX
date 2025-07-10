import shutil
import pygame # type: ignore
import config
from config import CONTROLS_CONFIG_PATH , GRID_COLS, GRID_ROWS
import asyncio
import math
import json
import os
from display import draw_validation_transition
from network import download_rom, check_extension_before_download, download_from_1fichier, is_1fichier_url, is_extension_supported,load_extensions_json,sanitize_filename
from utils import load_games
from history import load_history, clear_history
import logging

logger = logging.getLogger(__name__)

# Constantes pour la répétition automatique
REPEAT_DELAY = 300  # Délai initial avant répétition (ms)
REPEAT_INTERVAL = 100  # Intervalle entre répétitions (ms)
JOYHAT_DEBOUNCE = 200  # Délai anti-rebond pour JOYHATMOTION (ms)
JOYAXIS_DEBOUNCE = 50  # Délai anti-rebond pour JOYAXISMOTION (ms)
REPEAT_ACTION_DEBOUNCE = 50  # Délai anti-rebond pour répétitions up/down/left/right (ms)

# Liste des états valides
VALID_STATES = [
    "platform", "game", "download_progress", "download_result", "confirm_exit",
    "extension_warning", "pause_menu", "controls_help", "history", "controls_mapping",
    "redownload_game_cache", "restart_popup", "error", "loading", "confirm_clear_history"
]

def validate_menu_state(state):
    valid_states = ["platform", "game", "download_progress", "download_result", "confirm_exit", "extension_warning", "pause_menu", "controls_help", "controls_mapping", "redownload_game_cache", "restart_popup", "confirm_clear_history"]
    if state not in VALID_STATES:
        logger.debug(f"État invalide {state}, retour à platform")
        return "platform"
    if state == "history":  # Éviter de revenir à history
        logger.debug(f"État history non autorisé comme previous_menu_state, retour à platform")
        return "platform"
    return state


def load_controls_config(path=CONTROLS_CONFIG_PATH):
    """Charge la configuration des contrôles depuis un fichier JSON."""
    try:
        with open(path, "r") as f:
            config_data = json.load(f)
            # Vérifier les actions nécessaires
            required_actions = ["confirm", "cancel", "up", "down"]
            for action in required_actions:
                if action not in config_data:
                    logger.warning(f"Action {action} manquante dans {path}, utilisation de la valeur par défaut")
                    config_data[action] = {
                        "type": "key",
                        "value": {
                            "confirm": {"type": "key", "value": pygame.K_RETURN},
                            "cancel": {"type": "key", "value": pygame.K_ESCAPE},
                            "left": {"type": "key", "value": pygame.K_LEFT},
                            "right": {"type": "key", "value": pygame.K_RIGHT},
                            "up": {"type": "key", "value": pygame.K_UP},
                            "down": {"type": "key", "value": pygame.K_DOWN},
                            "start": {"type": "key", "value": pygame.K_p},
                            "progress": {"type": "key", "value": pygame.K_x},
                            "history": {"type": "key", "value": pygame.K_h},
                            "page_up": {"type": "key", "value": pygame.K_PAGEUP},
                            "page_down": {"type": "key", "value": pygame.K_PAGEDOWN},
                            "filter": {"type": "key", "value": pygame.K_f},
                            "delete": {"type": "key", "value": pygame.K_BACKSPACE},
                            "space": {"type": "key", "value": pygame.K_SPACE}
                        }[action]
                    }
            return config_data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Erreur lors de la lecture de {path} : {e}, utilisation de la configuration par défaut")
        return {
            "confirm": {"type": "key", "value": pygame.K_RETURN},
            "cancel": {"type": "key", "value": pygame.K_ESCAPE},
            "left": {"type": "key", "value": pygame.K_LEFT},
            "right": {"type": "key", "value": pygame.K_RIGHT},
            "up": {"type": "key", "value": pygame.K_UP},
            "down": {"type": "key", "value": pygame.K_DOWN},
            "start": {"type": "key", "value": pygame.K_p},
            "progress": {"type": "key", "value": pygame.K_x},
            "history": {"type": "key", "value": pygame.K_h},
            "page_up": {"type": "key", "value": pygame.K_PAGEUP},
            "page_down": {"type": "key", "value": pygame.K_PAGEDOWN},
            "filter": {"type": "key", "value": pygame.K_f},
            "delete": {"type": "key", "value": pygame.K_BACKSPACE},
            "space": {"type": "key", "value": pygame.K_SPACE}
        }

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

def handle_controls(event, sources, joystick, screen):
    """Gère un événement clavier/joystick/souris et la répétition automatique.
    Retourne 'quit', 'download', 'redownload', ou None.
    """
    action = None
    current_time = pygame.time.get_ticks()

    # Valider previous_menu_state avant tout traitement
    config.previous_menu_state = validate_menu_state(config.previous_menu_state)

    # Debounce général
    if current_time - config.last_state_change_time < config.debounce_delay:
        return action

    # --- CLAVIER, MANETTE, SOURIS ---
    if event.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION, pygame.JOYHATMOTION, pygame.MOUSEBUTTONDOWN):
        # Débouncer les événements JOYHATMOTION
        if event.type == pygame.JOYHATMOTION:
            logger.debug(f"JOYHATMOTION détecté: hat={event.hat}, value={event.value}")
            if event.value == (0, 0):  # Ignorer les relâchements
                return action
            if current_time - config.repeat_last_action < JOYHAT_DEBOUNCE:
                return action

        # Débouncer les événements JOYAXISMOTION
        if event.type == pygame.JOYAXISMOTION and current_time - config.repeat_last_action < JOYAXIS_DEBOUNCE:
            return action

        # Quitter l'appli
        if event.type == pygame.QUIT:
            logger.debug("Événement pygame.QUIT détecté")
            return "quit"
        
        # Menu pause
        if is_input_matched(event, "start") and config.menu_state not in ("pause_menu", "controls_help", "controls_mapping", "redownload_game_cache"):
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
            systems_per_page = GRID_COLS * GRID_ROWS
            max_index = min(systems_per_page, len(config.platforms) - config.current_page * systems_per_page) - 1
            current_grid_index = config.selected_platform - config.current_page * systems_per_page
            row = current_grid_index // GRID_COLS
            col = current_grid_index % GRID_COLS

            if is_input_matched(event, "down"):
                if current_grid_index + GRID_COLS <= max_index:
                    config.selected_platform += GRID_COLS
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "up"):
                if current_grid_index - GRID_COLS >= 0:
                    config.selected_platform -= GRID_COLS
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "left"):
                if col > 0:
                    config.selected_platform -= 1
                    config.repeat_action = "left"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif config.current_page > 0:
                    config.current_page -= 1
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS + (GRID_COLS - 1)
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = "left"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "right"):
                if col < GRID_COLS - 1 and current_grid_index < max_index:
                    config.selected_platform += 1
                    config.repeat_action = "right"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif (config.current_page + 1) * systems_per_page < len(config.platforms):
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = "right"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "page_down"):
                if (config.current_page + 1) * systems_per_page < len(config.platforms):
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                    #logger.debug("Page suivante, répétition réinitialisée")
            elif is_input_matched(event, "page_up"):
                if config.current_page > 0:
                    config.current_page -= 1
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS - col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                    #logger.debug("Page précédente, répétition réinitialisée")
            elif is_input_matched(event, "page_up"):
                if config.current_page > 0:
                    config.current_page -= 1
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                    #logger.debug("Page précédente, répétition réinitialisée")
            elif is_input_matched(event, "progress"):
                if config.download_tasks:
                    config.menu_state = "download_progress"
                    config.needs_redraw = True
                    logger.debug("Retour à download_progress depuis platform")
            elif is_input_matched(event, "history"):
                config.menu_state = "history"
                config.needs_redraw = True
                logger.debug("Ouverture history depuis platform")
            elif is_input_matched(event, "confirm"):
                if config.platforms:
                    config.current_platform = config.selected_platform
                    config.games = load_games(config.platforms[config.current_platform])
                    config.filtered_games = config.games
                    config.filter_active = False
                    config.current_game = 0
                    config.scroll_offset = 0
                    draw_validation_transition(screen, config.current_platform)
                    config.menu_state = "game"
                    config.needs_redraw = True
                    #logger.debug(f"Plateforme sélectionnée: {config.platforms[config.current_platform]}, {len(config.games)} jeux chargés")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0
                config.needs_redraw = True

        # Jeux
        elif config.menu_state == "game":
            games = config.filtered_games if config.filter_active or config.search_mode else config.games
            if config.search_mode and config.is_non_pc:
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
            elif config.search_mode and not config.is_non_pc:
                # Gestion de la recherche sur PC
                if event.type == pygame.KEYDOWN:
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
                   # Gestion de la validation
                    elif is_input_matched(event, "select"):
                        config.search_mode = False
                        config.filter_active = True  # Conserver le filtre actif
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug(f"Validation de la recherche: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                    # Gestion de l'annulation
                    elif is_input_matched(event, "cancel"):
                        config.search_mode = False
                        config.search_query = ""
                        config.filtered_games = config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug("Sortie du mode recherche")
     
            else:
                
                if is_input_matched(event, "up"):
                    if config.current_game > 0:
                        config.current_game -= 1
                        config.repeat_action = "up"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    if config.current_game < len(games) - 1:
                        config.current_game += 1
                        config.repeat_action = "down"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.current_game = max(0, config.current_game - config.visible_games)
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                    #logger.debug("Page précédente dans la liste des jeux")
                elif is_input_matched(event, "page_down"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                    #logger.debug("Page suivante dans la liste des jeux")
                elif is_input_matched(event, "filter"):
                    config.search_mode = True
                    config.search_query = ""
                    config.filtered_games = config.games
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.selected_key = (0, 0)
                    config.needs_redraw = True
                    logger.debug("Entrée en mode recherche")
                elif is_input_matched(event, "progress"):
                    if config.download_tasks:
                        config.previous_menu_state = config.menu_state
                        config.menu_state = "download_progress"
                        config.needs_redraw = True
                        logger.debug(f"Retour à download_progress depuis {config.previous_menu_state}")
                elif is_input_matched(event, "history"):
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug("Ouverture history depuis game") 
                elif is_input_matched(event, "confirm"):
                    if games:
                        config.pending_download = check_extension_before_download(
                            games[config.current_game][0],
                            config.platforms[config.current_platform],
                            games[config.current_game][1]
                        )
                        if config.pending_download:
                            url, platform, game_name, is_zip_non_supported = config.pending_download
                            is_supported = is_extension_supported(
                                sanitize_filename(game_name),
                                platform,
                                load_extensions_json()
                            )
                            if not is_supported:
                                config.previous_menu_state = config.menu_state  # Ajouter cette ligne
                                config.menu_state = "extension_warning"
                                config.extension_confirm_selection = 0
                                config.needs_redraw = True
                                logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                            else:
                                if is_1fichier_url(url):
                                    if not config.API_KEY_1FICHIER:
                                        config.previous_menu_state = config.menu_state  # Ajouter cette ligne
                                        config.menu_state = "error"
                                        config.error_message = (
                                            "Attention il faut renseigner sa clé API (premium only) dans le fichier /userdata/saves/ports/rgsx/1fichier.api à ouvrir dans un editeur de texte et coller la clé API"
                                        )
                                        config.needs_redraw = True
                                        logger.error("Clé API 1fichier absente, téléchargement impossible.")
                                        config.pending_download = None
                                        return action
                                    loop = asyncio.get_running_loop()
                                    task = loop.run_in_executor(None, download_from_1fichier, url, platform, game_name, is_zip_non_supported)
                                else:
                                    task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported))
                                config.download_tasks[task] = (task, url, game_name, platform)
                                config.previous_menu_state = config.menu_state  # Ajouter cette ligne
                                config.menu_state = "download_progress"
                                config.needs_redraw = True
                                logger.debug(f"Début du téléchargement: {game_name} pour {platform} depuis {url}")
                                config.pending_download = None
                                action = "download"
                        else:
                            config.menu_state = "error"
                            config.error_message = "Extension non supportée ou erreur de téléchargement"
                            config.pending_download = None
                            config.needs_redraw = True
                            logger.error(f"config.pending_download est None pour {games[config.current_game][0]}")
                elif is_input_matched(event, "cancel"):
                    config.menu_state = "platform"
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Retour à platform")
                elif is_input_matched(event, "redownload_game_cache"):
                    config.previous_menu_state = config.menu_state
                    config.menu_state = "redownload_game_cache"
                    config.needs_redraw = True
                    logger.debug("Passage à redownload_game_cache depuis game")

        #Historique            
        elif config.menu_state == "history":
            history = config.history
            if is_input_matched(event, "up"):
                if config.current_history_item > 0:
                    config.current_history_item -= 1
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "down"):
                if config.current_history_item < len(history) - 1:
                    config.current_history_item += 1
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "page_up"):
                config.current_history_item = max(0, config.current_history_item - config.visible_history_items)
                config.repeat_action = None
                config.repeat_key = None
                config.repeat_start_time = 0
                config.repeat_last_action = current_time
                config.needs_redraw = True
                #logger.debug("Page précédente dans l'historique")
            elif is_input_matched(event, "page_down"):
                config.current_history_item = min(len(history) - 1, config.current_history_item + config.visible_history_items)
                config.repeat_action = None
                config.repeat_key = None
                config.repeat_start_time = 0
                config.repeat_last_action = current_time
                config.needs_redraw = True
                #logger.debug("Page suivante dans l'historique")
            elif is_input_matched(event, "progress"):
                config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                config.menu_state = "confirm_clear_history"
                config.confirm_clear_selection = 0  # 0 pour "Non", 1 pour "Oui"
                config.needs_redraw = True
                logger.debug("Passage à confirm_clear_history depuis history")
            elif is_input_matched(event, "confirm"):
                if history:
                    entry = history[config.current_history_item]
                    platform = entry["platform"]
                    game_name = entry["game_name"]
                    for game in config.games:
                        if game[0] == game_name and config.platforms[config.current_platform] == platform:
                            config.pending_download = check_extension_before_download(game_name, platform, game[1])
                            if config.pending_download:
                                url, platform, game_name, is_zip_non_supported = config.pending_download
                                if is_zip_non_supported:
                                    config.previous_menu_state = config.menu_state  # Remplacer cette ligne
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non supportée pour retéléchargement, passage à extension_warning pour {game_name}")
                                else:
                                    task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported))
                                    config.download_tasks[task] = (task, url, game_name, platform)
                                    config.previous_menu_state = config.menu_state  # Remplacer cette ligne
                                    config.menu_state = "download_progress"
                                    config.needs_redraw = True
                                    logger.debug(f"Retéléchargement: {game_name} pour {platform} depuis {url}")
                                    config.pending_download = None
                                    action = "redownload"
                            else:
                                config.menu_state = "error"
                                config.error_message = "Extension non supportée ou erreur de retéléchargement"
                                config.pending_download = None
                                config.needs_redraw = True
                                logger.error(f"config.pending_download est None pour {game_name}")
                            break
            elif is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.current_history_item = 0
                config.history_scroll_offset = 0
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis history")
       
        # Confirmation vider l'historique"
        elif config.menu_state == "confirm_clear_history":
            logger.debug(f"État confirm_clear_history, confirm_clear_selection={config.confirm_clear_selection}, événement={event.type}, valeur={getattr(event, 'value', None)}")
            if is_input_matched(event, "confirm"):
                logger.debug(f"Action confirm détectée dans confirm_clear_history")
                if config.confirm_clear_selection == 1:  # Oui
                    clear_history()
                    config.history = []
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.info("Historique vidé après confirmation")
                else:  # Non
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug("Annulation du vidage de l'historique, retour à history")
            elif is_input_matched(event, "left"):
                #logger.debug(f"Action left détectée dans confirm_clear_history")
                config.confirm_clear_selection = 1  # Sélectionner "Non"
                config.needs_redraw = True
                #logger.debug(f"Changement sélection confirm_clear_history: {config.confirm_clear_selection}")
            elif is_input_matched(event, "right"):
                #logger.debug(f"Action right détectée dans confirm_clear_history")
                config.confirm_clear_selection = 0  # Sélectionner "Oui"
                config.needs_redraw = True
                #logger.debug(f"Changement sélection confirm_clear_history: {config.confirm_clear_selection}")
            elif is_input_matched(event, "cancel"):
                #logger.debug(f"Action cancel détectée dans confirm_clear_history")
                config.menu_state = "history"
                config.needs_redraw = True
                logger.debug("Annulation du vidage de l'historique, retour à history")
        
        # Progression téléchargement
        elif config.menu_state == "download_progress":
            if is_input_matched(event, "cancel"):
                for task in config.download_tasks:
                    task.cancel()
                config.download_tasks.clear()
                config.download_progress.clear()
                config.pending_download = None
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Téléchargement annulé, retour à {config.menu_state}")
            elif is_input_matched(event, "progress"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis download_progress")

        # Résultat téléchargement
        elif config.menu_state == "download_result":
            if is_input_matched(event, "confirm"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.popup_timer = 0
                config.pending_download = None
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis download_result")

        # Confirmation quitter
        elif config.menu_state == "confirm_exit":
            if is_input_matched(event, "confirm"):
                if config.confirm_selection == 1:
                    return "quit"
                else:
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
                    logger.debug(f"Retour à {config.menu_state} depuis confirm_exit")
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.confirm_selection = 1 - config.confirm_selection
                config.needs_redraw = True
                #logger.debug(f"Changement sélection confirm_exit: {config.confirm_selection}")

        # Avertissement extension
        elif config.menu_state == "extension_warning":
            if is_input_matched(event, "confirm"):
                if config.extension_confirm_selection == 1:
                    if config.pending_download and len(config.pending_download) == 4:
                        url, platform, game_name, is_zip_non_supported = config.pending_download
                        task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported))
                        config.download_tasks[task] = (task, url, game_name, platform)
                        config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                        config.menu_state = "download_progress"
                        config.needs_redraw = True
                        logger.debug(f"Téléchargement confirmé après avertissement: {game_name} pour {platform} depuis {url}")
                        config.pending_download = None
                        action = "download"
                    else:
                        config.menu_state = "error"
                        config.error_message = "Données de téléchargement invalides"
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
                #logger.debug(f"Changement sélection extension_warning: {config.extension_confirm_selection}")
            elif is_input_matched(event, "cancel"):
                config.pending_download = None
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis extension_warning")

        # Menu pause
        elif config.menu_state == "pause_menu":
            logger.debug(f"État pause_menu, selected_option={config.selected_option}, événement={event.type}, valeur={getattr(event, 'value', None)}")
            if is_input_matched(event, "up"):
                config.selected_option = max(0, config.selected_option - 1)
                config.repeat_action = "up"
                config.repeat_start_time = current_time + REPEAT_DELAY
                config.repeat_last_action = current_time
                config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                config.needs_redraw = True
                logger.debug(f"Navigation vers le haut: selected_option={config.selected_option}")
            elif is_input_matched(event, "down"):
                config.selected_option = min(4, config.selected_option + 1)
                config.repeat_action = "down"
                config.repeat_start_time = current_time + REPEAT_DELAY
                config.repeat_last_action = current_time
                config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                config.needs_redraw = True
                logger.debug(f"Navigation vers le bas: selected_option={config.selected_option}")
            elif is_input_matched(event, "confirm"):
                logger.debug(f"Confirmation dans pause_menu avec selected_option={config.selected_option}")
                if config.selected_option == 0:  # Controls
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "controls_help"
                    config.needs_redraw = True
                    logger.debug(f"Passage à controls_help depuis pause_menu")
                elif config.selected_option == 1:  # Remap controls
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    logger.debug(f"Previous menu state avant controls_mapping: {config.previous_menu_state}")
                    config.menu_state = "controls_mapping"
                    config.needs_redraw = True
                    logger.debug(f"Passage à controls_mapping depuis pause_menu")
                elif config.selected_option == 2:  # History
                    config.history = load_history()
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug(f"Passage à history depuis pause_menu")
                elif config.selected_option == 3:  # Redownload game cache
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "redownload_game_cache"
                    config.redownload_confirm_selection = 0
                    config.needs_redraw = True
                    logger.debug(f"Passage à redownload_game_cache depuis pause_menu")
                elif config.selected_option == 4:  # Quit
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "confirm_exit"
                    config.confirm_selection = 0
                    config.needs_redraw = True
                    logger.debug(f"Passage à confirm_exit depuis pause_menu")
            elif is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis pause_menu")

        # Aide contrôles
        elif config.menu_state == "controls_help":
            if is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis controls_help")

        # Remap controls
        elif config.menu_state == "controls_mapping":
            if is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Retour à pause_menu depuis controls_mapping")
        
        # Redownload game cache
        elif config.menu_state == "redownload_game_cache":
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.redownload_confirm_selection = 1 - config.redownload_confirm_selection
                config.needs_redraw = True
                logger.debug(f"Changement sélection redownload_game_cache: {config.redownload_confirm_selection}")
            elif is_input_matched(event, "confirm"):
                logger.debug(f"Action confirm dans redownload_game_cache, sélection={config.redownload_confirm_selection}")
                if config.redownload_confirm_selection == 1:  # Oui
                    logger.debug("Début du redownload des jeux")
                    config.download_tasks.clear()
                    config.download_progress.clear()
                    config.pending_download = None
                    if os.path.exists("/userdata/roms/ports/RGSX/sources.json"):
                        try:
                            os.remove("/userdata/roms/ports/RGSX/sources.json")
                            logger.debug("Fichier sources.json supprimé avec succès")
                            if os.path.exists("/userdata/roms/ports/RGSX/games"):
                                shutil.rmtree("/userdata/roms/ports/RGSX/games")
                                logger.debug("Dossier games supprimé avec succès")
                            if os.path.exists("/userdata/roms/ports/RGSX/images"):
                                shutil.rmtree("/userdata/roms/ports/RGSX/images")
                                logger.debug("Dossier images supprimé avec succès")
                            config.menu_state = "restart_popup"
                            config.popup_message = "Redownload des jeux effectué.\nVeuillez redémarrer l'application pour voir les changements."
                            config.popup_timer = 5000  # 5 secondes
                            config.needs_redraw = True
                            logger.debug("Passage à restart_popup")
                        except Exception as e:
                            logger.error(f"Erreur lors de la suppression du fichier sources.json ou dossiers: {e}")
                            config.menu_state = "error"
                            config.error_message = "Erreur lors de la suppression du fichier sources.json ou dossiers"
                            config.needs_redraw = True
                            return action
                    else:
                        logger.debug("Fichier sources.json non trouvé, passage à restart_popup")
                        config.menu_state = "restart_popup"
                        config.popup_message = "Aucun cache trouvé.\nVeuillez redémarrer l'application pour charger les jeux."
                        config.popup_timer = 5000  # 5 secondes
                        config.needs_redraw = True
                        logger.debug("Passage à restart_popup")
                else:  # Non
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
                    logger.debug(f"Annulation du redownload, retour à {config.menu_state}")
            elif is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis redownload_game_cache")
       
       
        # Popup de redémarrage
        elif config.menu_state == "restart_popup":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.popup_message = ""
                config.popup_timer = 0
                config.needs_redraw = True
                logger.debug(f"Retour manuel à {config.menu_state} depuis restart_popup")


    # Gestion de la répétition automatique (relâchement)
    if event.type in (pygame.KEYUP, pygame.JOYBUTTONUP, pygame.JOYAXISMOTION, pygame.JOYHATMOTION):
        if event.type == pygame.JOYAXISMOTION and abs(event.value) > 0.5:
            return action
        if event.type == pygame.JOYHATMOTION and event.value != (0, 0):
            return action
        config.repeat_action = None
        config.repeat_key = None
        config.repeat_start_time = 0
        #logger.debug("Répétition arrêtée")

    return action

#Gestion de la répétition automatique des actions
async def handle_repeat_actions():
    """Gère la répétition automatique des actions."""
    current_time = pygame.time.get_ticks()
    if config.repeat_action and config.repeat_key and current_time > config.repeat_start_time:
        if current_time - config.repeat_last_action > REPEAT_ACTION_DEBOUNCE:
            logger.debug(f"Répétition action: {config.repeat_action}")
            event_dict = {
                "type": pygame.KEYDOWN if isinstance(config.repeat_key, int) and config.repeat_key < 1000 else pygame.JOYBUTTONDOWN if isinstance(config.repeat_key, int) else pygame.JOYAXISMOTION if isinstance(config.repeat_key, tuple) and len(config.repeat_key) == 2 else pygame.JOYHATMOTION,
                "key": config.repeat_key if isinstance(config.repeat_key, int) and config.repeat_key < 1000 else None,
                "button": config.repeat_key if isinstance(config.repeat_key, int) and config.repeat_key >= 1000 else None,
                "axis": config.repeat_key[0] if isinstance(config.repeat_key, tuple) and len(config.repeat_key) == 2 else None,
                "value": config.repeat_key[1] if isinstance(config.repeat_key, tuple) and len(config.repeat_key) == 2 else config.repeat_key if isinstance(config.repeat_key, tuple) else None
            }
            handle_controls(event_dict, None, None, None)
            config.repeat_last_action = current_time
            config.repeat_start_time = current_time + REPEAT_INTERVAL
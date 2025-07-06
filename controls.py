import pygame
import config
import asyncio
import math
from display import draw_validation_transition
from network import download_rom, check_extension_before_download
from controls_mapper import get_readable_input_name
from utils import load_games  # Ajout de l'import
import logging

logger = logging.getLogger(__name__)

# Constantes pour la répétition automatique
REPEAT_DELAY = 300  # Délai initial avant répétition (ms)
REPEAT_INTERVAL = 100  # Intervalle entre répétitions (ms)
JOYHAT_DEBOUNCE = 200  # Délai anti-rebond pour JOYHATMOTION (ms)
JOYAXIS_DEBOUNCE = 50  # Délai anti-rebond pour JOYAXISMOTION (ms)
REPEAT_ACTION_DEBOUNCE = 50  # Délai anti-rebond pour répétitions up/down/left/right (ms)

def is_input_matched(event, action_name):
    """Vérifie si l'événement correspond à l'action configurée."""
    if not config.controls_config.get(action_name):
        return False
    mapping = config.controls_config[action_name]
    input_type = mapping["type"]
    input_value = mapping["value"]

    event_type = event["type"] if isinstance(event, dict) else event.type
    event_key = event.get("key") if isinstance(event, dict) else getattr(event, "key", None)
    event_button = event.get("button") if isinstance(event, dict) else getattr(event, "button", None)
    event_axis = event.get("axis") if isinstance(event, dict) else getattr(event, "axis", None)
    event_value = event.get("value") if isinstance(event, dict) else getattr(event, "value", None)

    if input_type == "key" and event_type in (pygame.KEYDOWN, pygame.KEYUP):
        logger.debug(f"Vérification key: event_key={event_key}, input_value={input_value}")
        return event_key == input_value
    elif input_type == "button" and event_type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP):
        logger.debug(f"Vérification button: event_button={event_button}, input_value={input_value}")
        return event_button == input_value
    elif input_type == "axis" and event_type == pygame.JOYAXISMOTION:
        axis, direction = input_value
        result = event_axis == axis and abs(event_value) > 0.5 and (1 if event_value > 0 else -1) == direction
        logger.debug(f"Vérification axis: event_axis={event_axis}, event_value={event_value}, input_value={input_value}, result={result}")
        return result
    elif input_type == "hat" and event_type == pygame.JOYHATMOTION:
        # Convertir input_value en tuple pour comparaison
        input_value_tuple = tuple(input_value) if isinstance(input_value, list) else input_value
        logger.debug(f"Vérification hat: event_value={event_value}, input_value={input_value_tuple}")
        return event_value == input_value_tuple
    elif input_type == "mouse" and event_type == pygame.MOUSEBUTTONDOWN:
        logger.debug(f"Vérification mouse: event_button={event_button}, input_value={input_value}")
        return event_button == input_value
    return False

def handle_controls(event, sources, joystick, screen):
    """Gère un événement clavier/joystick/souris et la répétition automatique.
    Retourne 'quit', 'download', ou None.
    """
    action = None
    current_time = pygame.time.get_ticks()

    # Debounce général
    if current_time - config.last_state_change_time < config.debounce_delay:
        return action

    # Log des événements reçus
    logger.debug(f"Événement reçu: type={event.type}, value={getattr(event, 'value', None)}")

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

        # Vérification des actions mappées
        for action_name in ["up", "down", "left", "right"]:
            if is_input_matched(event, action_name):
                logger.debug(f"Action mappée détectée: {action_name}, input={get_readable_input_name(event)}")

        # Erreur
        if config.menu_state == "error":
            if is_input_matched(event, "confirm"):
                config.menu_state = "loading"
                logger.debug("Sortie erreur avec Confirm")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0

        # Plateformes
        elif config.menu_state == "platform":
            max_index = min(9, len(config.platforms) - config.current_page * 9) - 1
            current_grid_index = config.selected_platform - config.current_page * 9
            row = current_grid_index // 3
            if is_input_matched(event, "down"):
                if current_grid_index + 3 <= max_index:
                    config.selected_platform += 3
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "up"):
                if current_grid_index - 3 >= 0:
                    config.selected_platform -= 3
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "left"):
                if current_grid_index % 3 != 0:
                    config.selected_platform -= 1
                    config.repeat_action = "left"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif config.current_page > 0:
                    config.current_page -= 1
                    config.selected_platform = config.current_page * 9 + row * 3 + 2
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = "left"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "right"):
                if current_grid_index % 3 != 2 and current_grid_index < max_index:
                    config.selected_platform += 1
                    config.repeat_action = "right"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif (config.current_page + 1) * 9 < len(config.platforms):
                    config.current_page += 1
                    config.selected_platform = config.current_page * 9 + row * 3
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    config.repeat_action = "right"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "page_down"):
                    if (config.current_page + 1) * 9 < len(config.platforms):
                        config.current_page += 1
                        config.selected_platform = config.current_page * 9 + row * 3
                        if config.selected_platform >= len(config.platforms):
                            config.selected_platform = len(config.platforms) - 1
                        config.repeat_action = None  # Réinitialiser la répétition
                        config.repeat_key = None
                        config.repeat_start_time = 0
                        config.repeat_last_action = current_time
                        config.needs_redraw = True
                        logger.debug("Page suivante, répétition réinitialisée")
            elif is_input_matched(event, "progress"):
                if config.download_tasks:
                    config.menu_state = "download_progress"
                    config.needs_redraw = True
                    logger.debug("Retour à download_progress depuis platform")
            elif is_input_matched(event, "confirm"):
                if config.platforms:
                    config.current_platform = config.selected_platform
                    config.games = load_games(config.platforms[config.current_platform])  # Appel à load_games depuis utils
                    config.filtered_games = config.games
                    config.filter_active = False
                    config.current_game = 0
                    config.scroll_offset = 0
                    draw_validation_transition(screen, config.current_platform)  # Animation de transition
                    config.menu_state = "game"
                    config.needs_redraw = True
                    logger.debug(f"Plateforme sélectionnée: {config.platforms[config.current_platform]}, {len(config.games)} jeux chargés")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0

        # Jeux
        elif config.menu_state == "game":
            if config.search_mode:
                if config.is_non_pc:
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
                        key = keyboard_layout[row][col]
                        if len(config.search_query) < 50:
                            config.search_query += key.lower()
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            config.needs_redraw = True
                    elif is_input_matched(event, "delete"):
                        config.search_query = config.search_query[:-1]
                        config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                    elif is_input_matched(event, "space"):
                        config.search_query += " "
                        config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                    elif is_input_matched(event, "cancel"):
                        config.search_mode = False
                        config.search_query = ""
                        config.filtered_games = config.games
                        config.filter_active = False
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug("Filtre annulé")
                    elif is_input_matched(event, "filter"):
                        config.search_mode = False
                        config.filter_active = bool(config.search_query)
                        config.needs_redraw = True
                else:
                    if is_input_matched(event, "confirm"):
                        config.search_mode = False
                        config.filter_active = bool(config.search_query)
                        config.needs_redraw = True
                    elif is_input_matched(event, "cancel"):
                        config.search_mode = False
                        config.search_query = ""
                        config.filtered_games = config.games
                        config.filter_active = False
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug("Filtre annulé")
                    elif event.type == pygame.KEYDOWN:
                        if event.key == pygame.K_BACKSPACE:
                            config.search_query = config.search_query[:-1]
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            config.needs_redraw = True
                        elif event.key == pygame.K_SPACE:
                            config.search_query += " "
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            config.needs_redraw = True
                        elif event.unicode.isprintable() and len(config.search_query) < 50:
                            config.search_query += event.unicode
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            config.needs_redraw = True
            else:
                if is_input_matched(event, "down"):
                    config.current_game = min(config.current_game + 1, len(config.filtered_games) - 1)
                    if config.current_game >= config.scroll_offset + config.visible_games:
                        config.scroll_offset += 1
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_input_matched(event, "up"):
                    config.current_game = max(config.current_game - 1, 0)
                    if config.current_game < config.scroll_offset:
                        config.scroll_offset -= 1
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.current_game = max(config.current_game - config.visible_games, 0)
                    config.scroll_offset = max(config.scroll_offset - config.visible_games, 0)
                    config.repeat_action = "page_up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.current_game = min(config.current_game + config.visible_games, len(config.filtered_games) - 1)
                    config.scroll_offset = min(config.scroll_offset + config.visible_games, len(config.filtered_games) - config.visible_games)
                    config.repeat_action = "page_down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_input_matched(event, "confirm"):
                    if config.filtered_games:
                        action = "download"
                elif is_input_matched(event, "filter"):
                    config.search_mode = True
                    config.search_query = ""
                    config.filtered_games = config.games
                    config.selected_key = (0, 0)
                    config.needs_redraw = True
                    logger.debug("Entrée en mode recherche")
                elif is_input_matched(event, "cancel"):
                    config.menu_state = "platform"
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.filter_active = False
                    config.filtered_games = config.games
                    config.needs_redraw = True
                    logger.debug("Retour à platform, filtre réinitialisé")
                elif is_input_matched(event, "progress"):
                    if config.download_tasks:
                        config.menu_state = "download_progress"
                        config.needs_redraw = True
                        logger.debug("Retour à download_progress depuis game")

        # Download progress
        elif config.menu_state == "download_progress":
            if is_input_matched(event, "cancel"):
                if config.download_tasks:
                    task = list(config.download_tasks.keys())[0]
                    config.download_tasks[task][0].cancel()
                    url = config.download_tasks[task][1]
                    game_name = config.download_tasks[task][2]
                    if url in config.download_progress:
                        del config.download_progress[url]
                    del config.download_tasks[task]
                    config.download_result_message = f"Téléchargement annulé : {game_name}"
                    config.download_result_error = True
                    config.download_result_start_time = pygame.time.get_ticks()
                    config.menu_state = "download_result"
            elif is_input_matched(event, "progress"):
                config.menu_state = "game"
                config.needs_redraw = True
                logger.debug("Retour à game depuis download_progress")

        # Confirmation de sortie
        elif config.menu_state == "confirm_exit":
            if is_input_matched(event, "left"):
                config.confirm_selection = 1
                config.needs_redraw = True
                logger.debug("Sélection Oui")
            elif is_input_matched(event, "right"):
                config.confirm_selection = 0
                config.needs_redraw = True
                logger.debug("Sélection Non")
            elif is_input_matched(event, "confirm"):
                if config.confirm_selection == 1:
                    logger.debug("Retour de 'quit' pour fermer l'application")
                    return "quit"
                else:
                    config.menu_state = "platform"
                    config.needs_redraw = True
                    logger.debug("Retour à platform depuis confirm_exit")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "platform"
                config.needs_redraw = True
                logger.debug("Annulation confirm_exit")
                
        # Avertissement d'extension
        elif config.menu_state == "extension_warning":
            if is_input_matched(event, "left"):
                config.extension_confirm_selection = 1
                config.needs_redraw = True
                logger.debug("Sélection Oui (extension_warning)")
            elif is_input_matched(event, "right"):
                config.extension_confirm_selection = 0
                config.needs_redraw = True
                logger.debug("Sélection Non (extension_warning)")
            elif is_input_matched(event, "confirm"):
                if config.extension_confirm_selection == 1:
                    if config.pending_download:
                        url, platform, game_name, is_zip_non_supported = config.pending_download
                        task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported=is_zip_non_supported))
                        config.download_tasks[task] = (task, url, game_name, platform)
                        config.menu_state = "download_progress"
                        config.pending_download = None
                        config.needs_redraw = True
                    else:
                        config.menu_state = "game"
                        config.needs_redraw = True
                else:
                    config.menu_state = "game"
                    config.pending_download = None
                    config.needs_redraw = True
                    logger.debug("Téléchargement annulé (extension_warning)")
            elif is_input_matched(event, "cancel"):
                config.menu_state = "game"
                config.pending_download = None
                config.needs_redraw = True
                logger.debug("Annulation extension_warning")

        # Résultat téléchargement
        elif config.menu_state == "download_result":
            if is_input_matched(event, "confirm"):
                config.menu_state = "game"
                config.needs_redraw = True
                logger.debug("Retour à game depuis download_result")

        # Enregistrer la touche pour la répétition
        if config.repeat_action in ["up", "down", "page_up", "page_down", "left", "right"]:
            if event.type == pygame.KEYDOWN:
                config.repeat_key = event.key
            elif event.type == pygame.JOYBUTTONDOWN:
                config.repeat_key = event.button
            elif event.type == pygame.JOYAXISMOTION:
                config.repeat_key = (event.axis, 1 if event.value > 0 else -1)
            elif event.type == pygame.JOYHATMOTION:
                config.repeat_key = event.value
                config.repeat_last_action = current_time

    elif event.type in (pygame.KEYUP, pygame.JOYBUTTONUP):
        if config.menu_state in ("game", "platform") and is_input_matched(event, config.repeat_action):
            config.repeat_action = None
            config.repeat_key = None
            config.repeat_start_time = 0
            config.needs_redraw = True

    # Gestion de la répétition automatique
    if config.menu_state in ("game", "platform") and config.repeat_action:
        if current_time >= config.repeat_start_time:
            if config.repeat_action in ["up", "down", "left", "right"] and current_time - config.repeat_last_action < REPEAT_ACTION_DEBOUNCE:
                return action

            last_repeat_time = config.repeat_start_time - REPEAT_INTERVAL
            config.repeat_last_action = current_time
            if config.menu_state == "game":
                if config.repeat_action == "down":
                    config.current_game = min(config.current_game + 1, len(config.filtered_games) - 1)
                    if config.current_game >= config.scroll_offset + config.visible_games:
                        config.scroll_offset += 1
                    config.needs_redraw = True
                elif config.repeat_action == "up":
                    config.current_game = max(config.current_game - 1, 0)
                    if config.current_game < config.scroll_offset:
                        config.scroll_offset -= 1
                    config.needs_redraw = True
                elif config.repeat_action == "page_down":
                    config.current_game = min(config.current_game + config.visible_games, len(config.filtered_games) - 1)
                    config.scroll_offset = min(config.scroll_offset + config.visible_games, len(config.filtered_games) - config.visible_games)
                    config.needs_redraw = True
                elif config.repeat_action == "page_up":
                    config.current_game = max(config.current_game - config.visible_games, 0)
                    config.scroll_offset = max(config.scroll_offset - config.visible_games, 0)
                    config.needs_redraw = True
            elif config.menu_state == "platform":
                max_index = min(9, len(config.platforms) - config.current_page * 9) - 1
                current_grid_index = config.selected_platform - config.current_page * 9
                row = current_grid_index // 3
                if config.repeat_action == "down":
                    if current_grid_index + 3 <= max_index:
                        config.selected_platform += 3
                        config.needs_redraw = True
                elif config.repeat_action == "up":
                    if current_grid_index - 3 >= 0:
                        config.selected_platform -= 3
                        config.needs_redraw = True
                elif config.repeat_action == "left":
                    if current_grid_index % 3 != 0:
                        config.selected_platform -= 1
                        config.needs_redraw = True
                    elif config.current_page > 0:
                        config.current_page -= 1
                        config.selected_platform = config.current_page * 9 + row * 3 + 2
                        if config.selected_platform >= len(config.platforms):
                            config.selected_platform = len(config.platforms) - 1
                        config.needs_redraw = True
                elif config.repeat_action == "right":
                    if current_grid_index % 3 != 2 and current_grid_index < max_index:
                        config.selected_platform += 1
                        config.needs_redraw = True
                    elif (config.current_page + 1) * 9 < len(config.platforms):
                        config.current_page += 1
                        config.selected_platform = config.current_page * 9 + row * 3
                        if config.selected_platform >= len(config.platforms):
                            config.selected_platform = len(config.platforms) - 1
                        config.needs_redraw = True
            config.repeat_start_time = last_repeat_time + REPEAT_INTERVAL
            if config.repeat_start_time < current_time:
                config.repeat_start_time = current_time + REPEAT_INTERVAL

    return action
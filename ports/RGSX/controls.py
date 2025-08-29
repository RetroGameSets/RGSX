import shutil
import pygame # type: ignore
import config
# Constantes pour la répétition automatique - importées de config.py
from config import REPEAT_DELAY, REPEAT_INTERVAL, REPEAT_ACTION_DEBOUNCE
from config import CONTROLS_CONFIG_PATH , GRID_COLS, GRID_ROWS
import asyncio
import json
import os
from display import draw_validation_transition
from network import download_rom, download_from_1fichier, is_1fichier_url
from utils import (
    load_games, check_extension_before_download, is_extension_supported,
    load_extensions_json, play_random_music, sanitize_filename,
    load_api_key_1fichier, save_music_config
)
from history import load_history, clear_history, add_to_history, save_history
import logging
from language import _  # Import de la fonction de traduction

logger = logging.getLogger(__name__)

# Extensions d'archives pour lesquelles on ignore l'avertissement d'extension non supportée
ARCHIVE_EXTENSIONS = {'.zip', '.7z', '.rar', '.tar', '.gz', '.xz', '.bz2'}


# Variables globales pour la répétition
key_states = {}  # Dictionnaire pour suivre l'état des touches

# Liste des états valides
VALID_STATES = [
    "platform", "game", "confirm_exit",
    "extension_warning", "pause_menu", "controls_help", "history", "controls_mapping",
    "redownload_game_cache", "restart_popup", "error", "loading", "confirm_clear_history",
    "language_select"
]

def validate_menu_state(state):
    if state not in VALID_STATES:
        logger.debug(f"État invalide {state}, retour à platform")
        return "platform"
    if state == "history":  # Éviter de revenir à history
        logger.debug(f"État history non autorisé comme previous_menu_state, retour à platform")
        return "platform"
    return state


def load_controls_config(path=CONTROLS_CONFIG_PATH):
    """Charge la configuration des contrôles depuis un fichier JSON."""
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
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
        else:
            data = {}
        changed = False
        for k, v in default_config.items():
            if k not in data:
                data[k] = v
                changed = True
        if changed:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logging.getLogger(__name__).debug(f"controls.json complété avec les actions manquantes: {path}")
        return data
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
        return event.axis == axis and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == direction
    elif input_type == "hat" and event.type == pygame.JOYHATMOTION:
        hat_value = mapping.get("value")
        if isinstance(hat_value, list):
            hat_value = tuple(hat_value)
        return event.value == hat_value
    elif input_type == "mouse" and event.type == pygame.MOUSEBUTTONDOWN:
        return event.button == mapping.get("button")
    return False

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
        if is_input_matched(event, "start") and config.menu_state not in ("pause_menu", "controls_mapping", "redownload_game_cache"):
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
            
            # Espace réservé pour des fonctions helper si nécessaire

            if is_input_matched(event, "down"):
                # Navigation vers le bas avec gestion des limites de page
                if current_grid_index + GRID_COLS <= max_index:
                    # Déplacement normal vers le bas
                    config.selected_platform += GRID_COLS
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif (config.current_page + 1) * systems_per_page < len(config.platforms):
                    # Passage à la page suivante si on est en bas de la grille
                    config.current_page += 1
                    new_row = 0  # Première ligne de la nouvelle page
                    config.selected_platform = config.current_page * systems_per_page + new_row * GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "up"):
                # Navigation vers le haut avec gestion des limites de page
                if current_grid_index - GRID_COLS >= 0:
                    # Déplacement normal vers le haut
                    config.selected_platform -= GRID_COLS
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif config.current_page > 0:
                    # Passage à la page précédente si on est en haut de la grille
                    config.current_page -= 1
                    new_row = GRID_ROWS - 1  # Dernière ligne de la page précédente
                    config.selected_platform = config.current_page * systems_per_page + new_row * GRID_COLS + col
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
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS + (GRID_COLS - 1)
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    update_key_state("left", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "right"):
                if col < GRID_COLS - 1 and current_grid_index < max_index:
                    # Déplacement normal vers la droite
                    config.selected_platform += 1
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif (config.current_page + 1) * systems_per_page < len(config.platforms):
                    # Passage à la page suivante si on est à la dernière colonne
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS
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
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS + col
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
                    config.selected_platform = config.current_page * systems_per_page + row * GRID_COLS + col
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    # Réinitialiser la répétition pour éviter des comportements inattendus
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
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
                    logger.debug(f"Validation du filtre avec manette: query={config.search_query}, filter_active={config.filter_active}")  
            elif config.search_mode and not config.is_non_pc:
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
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                elif is_input_matched(event, "left"):
                    config.current_game = max(0, config.current_game - config.visible_games)
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
                elif is_input_matched(event, "right"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True                    
                elif is_input_matched(event, "filter"):
                    config.search_mode = True
                    config.search_query = ""
                    config.filtered_games = config.games
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.selected_key = (0, 0)
                    config.needs_redraw = True
                    logger.debug("Entrée en mode recherche") 
                elif is_input_matched(event, "history"):
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug("Ouverture history depuis game")
                # Bascule de sélection multiple avec la touche clear_history (réutilisée)
                elif is_input_matched(event, "clear_history"):
                    if games:
                        idx = config.current_game
                        if idx in config.selected_games:
                            config.selected_games.remove(idx)
                        else:
                            config.selected_games.add(idx)
                        config.needs_redraw = True
                        logger.debug(f"Multi-select toggle index={idx}, now selected={len(config.selected_games)}")
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
                # Télécharger les jeux sélectionnés (multi) ou le jeu courant
                elif is_input_matched(event, "confirm"):
                    # Batch multi-sélection
                    if games and config.selected_games:
                        config.batch_download_indices = sorted({i for i in config.selected_games if 0 <= i < len(games)})
                        config.selected_games.clear()
                        config.batch_in_progress = True
                        config.batch_pending_game = None

                        def process_next_batch_item():
                            # si un jeu attend encore confirmation, ne pas avancer
                            if config.batch_pending_game:
                                return False
                            while config.batch_download_indices:
                                idx = config.batch_download_indices.pop(0)
                                g = games[idx]
                                url = g[1]
                                game_name = g[0]
                                platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                                logger.debug(f"Batch step: {game_name} idx={idx} restants={len(config.batch_download_indices)}")
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if not config.pending_download:
                                    continue  # passe au suivant
                                is_supported = is_extension_supported(
                                    sanitize_filename(game_name),
                                    platform,
                                    load_extensions_json()
                                )
                                ext = os.path.splitext(url)[1].lower()
                                if not is_supported and ext not in ARCHIVE_EXTENSIONS:
                                    # Stocker comme pending sans dupliquer l'entrée
                                    config.batch_pending_game = (url, platform, game_name, config.pending_download[3])
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    return False
                                # Téléchargement direct
                                config.history.append(add_to_history(platform, game_name, "downloading", url, 0, "Téléchargement en cours"))
                                config.current_history_item = len(config.history) -1
                                task_id = str(pygame.time.get_ticks())
                                if is_1fichier_url(url):
                                    config.API_KEY_1FICHIER = load_api_key_1fichier()
                                    if not config.API_KEY_1FICHIER:
                                        config.history[-1]["status"] = "Erreur"
                                        config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                        save_history(config.history)
                                        continue
                                    task = asyncio.create_task(download_from_1fichier(url, platform, game_name, config.pending_download[3], task_id))
                                else:
                                    task = asyncio.create_task(download_rom(url, platform, game_name, config.pending_download[3], task_id))
                                config.download_tasks[task_id] = (task, url, game_name, platform)
                                # passer à l'élément suivant (boucle while)
                            return True  # fin lot

                        process_next_batch_item()
                        # Aller à l'historique si pas d'avertissement en attente
                        if config.menu_state == "game" and not config.batch_pending_game:
                            config.menu_state = "history"
                        config.needs_redraw = True
                        action = "download"
                    elif games:
                        url = games[config.current_game][1]
                        game_name = games[config.current_game][0]
                        platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                        logger.debug(f"Vérification pour {game_name}, URL: {url}")
                        # Ajouter une entrée temporaire à l'historique
                        config.history.append(add_to_history(
                            platform=platform,
                            game_name=game_name,
                            status="downloading",
                            url=url,
                            progress=0,
                            message="Téléchargement en cours"
                        ))
                        config.current_history_item = len(config.history) - 1
                        # Vérifier d'abord si c'est un lien 1fichier
                        if is_1fichier_url(url):
                            config.API_KEY_1FICHIER = load_api_key_1fichier()
                            if not config.API_KEY_1FICHIER:
                                config.previous_menu_state = config.menu_state
                                config.menu_state = "error"
                                try:
                                    config.error_message = _("error_api_key_extended")
                                except Exception as e:
                                    logger.error(f"Erreur lors de la traduction de error_api_key_extended: {str(e)}")
                                    config.error_message = "Missing 1fichier API key"  # Message de secours
                                config.history[-1]["status"] = "Erreur"
                                config.history[-1]["progress"] = 0
                                config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.error("Clé API 1fichier absente, téléchargement impossible.")
                                config.pending_download = None
                                return action
                            config.pending_download = check_extension_before_download(url, platform, game_name)
                            if config.pending_download:
                                is_supported = is_extension_supported(
                                    sanitize_filename(game_name),
                                    platform,
                                    load_extensions_json()
                                )
                                ext = os.path.splitext(url)[1].lower()
                                if not is_supported and ext not in ARCHIVE_EXTENSIONS:
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    config.history.pop()  # Supprimer l'entrée temporaire
                                else:
                                    task_id = str(pygame.time.get_ticks())
                                    task = asyncio.create_task(download_from_1fichier(url, platform, game_name, config.pending_download[3], task_id))
                                    config.download_tasks[task_id] = (task, url, game_name, platform)
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "history"  # Passer à l'historique
                                    config.needs_redraw = True
                                    logger.debug(f"Début du téléchargement 1fichier: {game_name} pour {platform} depuis {url}, task_id={task_id}")
                                    config.pending_download = None
                                    action = "download"
                            else:
                                config.menu_state = "error"
                                config.error_message = "Extension non supportée ou erreur de téléchargement"
                                config.pending_download = None
                                config.needs_redraw = True
                                logger.error(f"config.pending_download est None pour {game_name}")
                                config.history.pop()  # Supprimer l'entrée temporaire
                        else:
                            config.pending_download = check_extension_before_download(url, platform, game_name)
                            if config.pending_download:
                                is_supported = is_extension_supported(
                                    sanitize_filename(game_name),
                                    platform,
                                    load_extensions_json()
                                )
                                ext = os.path.splitext(url)[1].lower()
                                if not is_supported and ext not in ARCHIVE_EXTENSIONS:
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    config.history.pop()  # Supprimer l'entrée temporaire
                                else:
                                    task_id = str(pygame.time.get_ticks())
                                    task = asyncio.create_task(download_rom(url, platform, game_name, config.pending_download[3], task_id))
                                    config.download_tasks[task_id] = (task, url, game_name, platform)
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "history"  # Passer à l'historique
                                    config.needs_redraw = True
                                    logger.debug(f"Début du téléchargement: {game_name} pour {platform} depuis {url}, task_id={task_id}")
                                    config.pending_download = None
                                    action = "download"
                            else:
                                config.menu_state = "error"
                                config.error_message = "Extension non supportée ou erreur de téléchargement"
                                config.pending_download = None
                                config.needs_redraw = True
                                logger.error(f"config.pending_download est None pour {game_name}")
                                config.history.pop()  # Supprimer l'entrée temporaire

        # Avertissement extension
        elif config.menu_state == "extension_warning":
            if is_input_matched(event, "confirm"):
                if config.extension_confirm_selection == 1:
                    if config.pending_download and len(config.pending_download) == 4:
                        url, platform, game_name, is_zip_non_supported = config.pending_download
                        # Ajouter une entrée temporaire à l'historique
                        config.history.append(add_to_history(
                            platform=platform,
                            game_name=game_name,
                            status="downloading",
                            url=url,
                            progress=0,
                            message="Téléchargement en cours"
                        ))
                        config.current_history_item = len(config.history) - 1
                        if is_1fichier_url(url):
                            if not config.API_KEY_1FICHIER:
                                config.previous_menu_state = config.menu_state
                                config.menu_state = "error"
                                config.error_message = _(
                                    "error_api_key"
                                ).format(os.join(config.SAVE_FOLDER,"1fichierAPI.txt"))
                                config.history[-1]["status"] = "Erreur"
                                config.history[-1]["progress"] = 0
                                config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                save_history(config.history)
                                config.needs_redraw = True
                                logger.error("Clé API 1fichier absente, téléchargement impossible.")
                                config.pending_download = None
                                return action
                            task_id = str(pygame.time.get_ticks())
                            task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
                        else:
                            task_id = str(pygame.time.get_ticks())
                            task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))
                        config.download_tasks[task_id] = (task, url, game_name, platform)
                        config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                        config.menu_state = "history"  # Passer à l'historique
                        config.needs_redraw = True
                        logger.debug(f"Téléchargement confirmé après avertissement: {game_name} pour {platform} depuis {url}, task_id={task_id}")
                        config.pending_download = None
                        action = "download"
                        # Reprendre batch si présent
                        # Reprise batch si un jeu était en attente
                        if config.batch_pending_game:
                            config.batch_pending_game = None
                        if config.batch_in_progress:
                            config.menu_state = "game"
                            # Relancer la progression du lot
                            # Appeler la fonction locale si disponible (ré-implémentation légère ici)
                            try:
                                games = config.filtered_games if config.filter_active or config.search_mode else config.games
                                while config.batch_download_indices and not config.batch_pending_game:
                                    idx = config.batch_download_indices.pop(0)
                                    if idx < 0 or idx >= len(games):
                                        continue
                                    g = games[idx]
                                    url = g[1]; game_name = g[0]
                                    platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                                    config.pending_download = check_extension_before_download(url, platform, game_name)
                                    if not config.pending_download:
                                        continue
                                    is_supported = is_extension_supported(sanitize_filename(game_name), platform, load_extensions_json())
                                    ext = os.path.splitext(url)[1].lower()
                                    if not is_supported and ext not in ARCHIVE_EXTENSIONS:
                                        config.batch_pending_game = (url, platform, game_name, config.pending_download[3])
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        break
                                    config.history.append(add_to_history(platform, game_name, "downloading", url, 0, "Téléchargement en cours"))
                                    config.current_history_item = len(config.history) -1
                                    task_id = str(pygame.time.get_ticks())
                                    if is_1fichier_url(url):
                                        config.API_KEY_1FICHIER = load_api_key_1fichier()
                                        if not config.API_KEY_1FICHIER:
                                            config.history[-1]["status"] = "Erreur"
                                            config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                            save_history(config.history)
                                            continue
                                        task = asyncio.create_task(download_from_1fichier(url, platform, game_name, config.pending_download[3], task_id))
                                    else:
                                        task = asyncio.create_task(download_rom(url, platform, game_name, config.pending_download[3], task_id))
                                    config.download_tasks[task_id] = (task, url, game_name, platform)
                                if not config.batch_download_indices and not config.batch_pending_game:
                                    # Batch terminé
                                    config.batch_in_progress = False
                                    config.menu_state = "history"
                            except Exception as e:
                                logger.error(f"Erreur reprise batch après warning: {e}")
                    else:
                        config.menu_state = "error"
                        config.error_message = _("error_invalid_download_data")
                        config.pending_download = None
                        config.needs_redraw = True
                        logger.error("config.pending_download invalide")
                        config.history.pop()  # Supprimer l'entrée temporaire
                else:
                    config.pending_download = None
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
                    logger.debug(f"Retour à {config.menu_state} depuis extension_warning")
                    if config.batch_pending_game:
                        # Annulation de ce jeu -> on le saute
                        config.batch_pending_game = None
                    if config.batch_in_progress:
                        config.menu_state = "game"
                        # Reprise similaire à ci-dessus
                        try:
                            games = config.filtered_games if config.filter_active or config.search_mode else config.games
                            while config.batch_download_indices and not config.batch_pending_game:
                                idx = config.batch_download_indices.pop(0)
                                if idx < 0 or idx >= len(games):
                                    continue
                                g = games[idx]
                                url = g[1]; game_name = g[0]
                                platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if not config.pending_download:
                                    continue
                                is_supported = is_extension_supported(sanitize_filename(game_name), platform, load_extensions_json())
                                ext = os.path.splitext(url)[1].lower()
                                if not is_supported and ext not in ARCHIVE_EXTENSIONS:
                                    config.batch_pending_game = (url, platform, game_name, config.pending_download[3])
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    break
                                config.history.append(add_to_history(platform, game_name, "downloading", url, 0, "Téléchargement en cours"))
                                config.current_history_item = len(config.history) -1
                                task_id = str(pygame.time.get_ticks())
                                if is_1fichier_url(url):
                                    config.API_KEY_1FICHIER = load_api_key_1fichier()
                                    if not config.API_KEY_1FICHIER:
                                        config.history[-1]["status"] = "Erreur"
                                        config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                        save_history(config.history)
                                        continue
                                    task = asyncio.create_task(download_from_1fichier(url, platform, game_name, config.pending_download[3], task_id))
                                else:
                                    task = asyncio.create_task(download_rom(url, platform, game_name, config.pending_download[3], task_id))
                                config.download_tasks[task_id] = (task, url, game_name, platform)
                            if not config.batch_download_indices and not config.batch_pending_game:
                                config.batch_in_progress = False
                                config.menu_state = "history"
                        except Exception as e:
                            logger.error(f"Erreur reprise batch annulation warning: {e}")
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.extension_confirm_selection = 1 - config.extension_confirm_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.pending_download = None
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis extension_warning")
                if config.batch_pending_game:
                    config.batch_pending_game = None
                if config.batch_in_progress:
                    config.menu_state = "game"

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
            elif (is_input_matched(event, "clear_history")
                    or is_input_matched(event, "delete_history")
                    or is_input_matched(event, "progress")):
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
                            config.pending_download = check_extension_before_download(game[1], platform, game_name)
                            if config.pending_download:
                                url, platform, game_name, is_zip_non_supported = config.pending_download
                                if is_zip_non_supported and os.path.splitext(url)[1].lower() not in ARCHIVE_EXTENSIONS:
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "extension_warning"
                                    config.extension_confirm_selection = 0
                                    config.needs_redraw = True
                                    logger.debug(f"Extension non supportée pour retéléchargement, passage à extension_warning pour {game_name}")
                                else:
                                    task_id = str(pygame.time.get_ticks())
                                    if is_1fichier_url(url):
                                        if not config.API_KEY_1FICHIER:
                                            config.previous_menu_state = config.menu_state
                                            config.menu_state = "error"
                                            logger.warning("clé api absente dans os.path.join(config.SAVE_FOLDER, '1fichierAPI.txt')\n")
                                            config.error_message = _("error_api_key").format(os.path.join(config.SAVE_FOLDER, "1fichierAPI.txt"))
                                            
                                            config.history[-1]["status"] = "Erreur"
                                            config.history[-1]["progress"] = 0
                                            config.history[-1]["message"] = "Erreur API : Clé API 1fichier absente"
                                            save_history(config.history)
                                            config.needs_redraw = True
                                            logger.error("Clé API 1fichier absente, retéléchargement impossible.")
                                            config.pending_download = None
                                            return action
                                        task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
                                    else:
                                        task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))
                                    config.download_tasks[task_id] = (task, url, game_name, platform)
                                    config.previous_menu_state = config.menu_state
                                    config.menu_state = "history"
                                    config.needs_redraw = True
                                    logger.debug(f"Retéléchargement: {game_name} pour {platform} depuis {url}, task_id={task_id}")
                                    config.pending_download = None
                                    action = "redownload"
                            else:
                                config.menu_state = "error"
                                config.error_message = "Extension non supportée ou erreur de retéléchargement"
                                config.pending_download = None
                                config.needs_redraw = True
                                logger.error(f"config.pending_download est None pour {game_name}")
                            break
            elif is_input_matched(event, "cancel") or is_input_matched(event, "history"):
                if config.history and config.current_history_item < len(config.history):
                    entry = config.history[config.current_history_item]
                    if entry.get("status") in ["downloading", "Téléchargement", "Extracting"] and is_input_matched(event, "cancel"):
                        config.menu_state = "confirm_cancel_download"
                        config.confirm_cancel_selection = 0
                        config.needs_redraw = True
                        logger.debug("Demande d'annulation de téléchargement")
                        return action
                config.menu_state = validate_menu_state(config.previous_menu_state)
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
                            task.cancel()
                            del config.download_tasks[task_id]
                            entry["status"] = "Canceled"
                            entry["progress"] = 0
                            entry["message"] = "Téléchargement annulé"
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
            logger.debug(f"État confirm_clear_history, confirm_clear_selection={config.confirm_clear_selection}, événement={event.type}, valeur={getattr(event, 'value', None)}")
            if is_input_matched(event, "confirm"):
                # 0 = Non, 1 = Oui
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
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.confirm_clear_selection = 1 - config.confirm_clear_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "history"
                config.needs_redraw = True
                logger.debug("Annulation du vidage de l'historique, retour à history")

    # État download_result supprimé

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

        # Menu pause
        elif config.menu_state == "pause_menu":
            #logger.debug(f"État pause_menu, selected_option={config.selected_option}, événement={event.type}, valeur={getattr(event, 'value', None)}")
            if is_input_matched(event, "up"):
                config.selected_option = max(0, config.selected_option - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.selected_option = min(8, config.selected_option + 1)  # 9 options maintenant (0-8)
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.selected_option == 0:  # Controls
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "controls_help"
                    config.needs_redraw = True
                    #logger.debug(f"Passage à controls_help depuis pause_menu")
                elif config.selected_option == 1:  # Remap controls
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    #logger.debug(f"Previous menu state avant controls_mapping: {config.previous_menu_state}")
                    #Supprimer le fichier de configuration des contrôles s'il existe
                    if os.path.exists(config.CONTROLS_CONFIG_PATH):
                        try:
                            os.remove(config.CONTROLS_CONFIG_PATH)
                            logger.debug(f"Fichier de configuration des contrôles supprimé: {config.CONTROLS_CONFIG_PATH}")
                        except Exception as e:
                            logger.error(f"Erreur lors de la suppression du fichier de configuration des contrôles: {e}")
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
                elif config.selected_option == 3:  # Language
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "language_select"
                    config.selected_language_index = 0
                    config.needs_redraw = True
                    logger.debug(f"Passage à language_select depuis pause_menu")
                elif config.selected_option == 4:  # Accessibility
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "accessibility_menu"
                    config.needs_redraw = True
                    logger.debug("Passage au menu accessibilité")
                elif config.selected_option == 5:  # Redownload game cache
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "redownload_game_cache"
                    config.redownload_confirm_selection = 0
                    config.needs_redraw = True
                    logger.debug(f"Passage à redownload_game_cache depuis pause_menu")
                elif config.selected_option == 6:  # Music toggle
                    config.music_enabled = not config.music_enabled
                    save_music_config()
                    if config.music_enabled:
                        # Relancer la musique si activée
                        # Utilise les variables globales si elles existent
                        music_files = getattr(config, "music_files", None)
                        music_folder = getattr(config, "music_folder", None)
                        if music_files and music_folder:
                            config.current_music = play_random_music(music_files, music_folder, getattr(config, "current_music", None))
                    else:
                        pygame.mixer.music.stop()
                    config.needs_redraw = True
                    logger.info(f"Musique {'activée' if config.music_enabled else 'désactivée'} via menu pause")
                elif config.selected_option == 7:  # Symlink option
                    from rgsx_settings import set_symlink_option, get_symlink_option
                    current_status = get_symlink_option()
                    success, message = set_symlink_option(not current_status)
                    config.popup_message = message
                    config.popup_timer = 3000 if success else 5000
                    config.needs_redraw = True
                    logger.info(f"Symlink option {'activée' if not current_status else 'désactivée'} via menu pause")
                elif config.selected_option == 8:  # Quit
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
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Retour au menu pause depuis controls_help")

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
                    config.pending_download = None
                    if os.path.exists(config.SOURCES_FILE):
                        try:
                            os.remove(config.SOURCES_FILE)
                            logger.debug("Fichier sources.json supprimé avec succès")
                            if os.path.exists(config.GAMES_FOLDER):
                                shutil.rmtree(config.GAMES_FOLDER)
                                logger.debug("Dossier games supprimé avec succès")
                            if os.path.exists(config.IMAGES_FOLDER):
                                shutil.rmtree(config.IMAGES_FOLDER)
                                logger.debug("Dossier images supprimé avec succès")
                            config.menu_state = "restart_popup"
                            config.popup_message = _("popup_redownload_success")
                            config.popup_timer = 5000  # 5 secondes
                            config.needs_redraw = True
                            logger.debug("Passage à restart_popup")
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
                
        # Sélecteur de langue
        elif config.menu_state == "language_select":
            # Gestion directe des événements pour le sélecteur de langue
            from language import get_available_languages, set_language, _
            
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


    # Gestion des relâchements de touches
    if event.type == pygame.KEYUP:
        # Vérifier quelle touche a été relâchée
        for action_name in ["up", "down", "left", "right", "confirm", "cancel"]:
            if config.controls_config.get(action_name, {}).get("type") == "key" and \
               config.controls_config.get(action_name, {}).get("key") == event.key:
                update_key_state(action_name, False)
    
    elif event.type == pygame.JOYBUTTONUP:
        # Vérifier quel bouton a été relâché
        for action_name in ["up", "down", "left", "right", "confirm", "cancel"]:
            if config.controls_config.get(action_name, {}).get("type") == "button" and \
               config.controls_config.get(action_name, {}).get("button") == event.button:
                update_key_state(action_name, False)
    
    elif event.type == pygame.JOYAXISMOTION and abs(event.value) < 0.5:
        # Vérifier quel axe a été relâché
        for action_name in ["up", "down", "left", "right"]:
            if config.controls_config.get(action_name, {}).get("type") == "axis" and \
               config.controls_config.get(action_name, {}).get("axis") == event.axis:
                update_key_state(action_name, False)
    
    elif event.type == pygame.JOYHATMOTION and event.value == (0, 0):
        # Vérifier quel hat a été relâché
        for action_name in ["up", "down", "left", "right"]:
            if config.controls_config.get(action_name, {}).get("type") == "hat":
                update_key_state(action_name, False)

    return action

# Nouvelle implémentation de la répétition des touches
def update_key_state(action, pressed, event_type=None, event_value=None):
    """Met à jour l'état d'une touche pour la répétition automatique."""
    current_time = pygame.time.get_ticks()
    
    if pressed:
        # La touche vient d'être pressée
        if action not in key_states:
            # Ajouter un délai initial pour éviter les doubles actions sur appui court
            initial_debounce = REPEAT_ACTION_DEBOUNCE
            key_states[action] = {
                "pressed": True,
                "first_press_time": current_time + initial_debounce,  # Ajouter un délai initial
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
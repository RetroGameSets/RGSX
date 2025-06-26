import pygame
import config
import asyncio
import math
import cache
from display import draw_validation_transition
from cache import load_games
from network import download_rom, check_extension_before_download
import logging

logger = logging.getLogger(__name__)

# Constantes pour la répétition automatique
REPEAT_DELAY = 300  # Délai initial avant répétition (ms)
REPEAT_INTERVAL = 100  # Intervalle entre répétitions (ms)
JOYHAT_DEBOUNCE = 200  # Délai anti-rebond pour JOYHATMOTION (ms)

# Variables globales pour la répétition et le débounce
repeat_key = None
repeat_time = 0
last_joyhat_time = 0

def handle_controls(events, current_time, joystick, screen):
    """Gère tous les événements clavier/joystick et la répétition automatique.
    Retourne "quit", "download", ou None.
    """
    global repeat_key, repeat_time, last_joyhat_time

    action = None
    for event in events:
        config.needs_redraw = True

        # Quitter l'appli
        if event.type == pygame.QUIT:
            return "quit"

        # --- CLAVIER ---
        if event.type == pygame.KEYDOWN:
            repeat_key = event.key
            repeat_time = current_time + REPEAT_DELAY

            # Erreur
            if config.menu_state == "error":
                if event.key == pygame.K_RETURN:
                    config.menu_state = "loading"
                    logger.debug("Sortie erreur avec Entrée")

            # Plateformes
            elif config.menu_state == "platform":
                max_index = min(9, len(config.platforms) - config.current_page * 9) - 1
                current_grid_index = config.selected_platform - config.current_page * 9
                row = current_grid_index // 3
                if event.key == pygame.K_DOWN:
                    if current_grid_index + 3 <= max_index:
                        config.selected_platform += 3
                        logger.debug(f"Bas, selected_platform={config.selected_platform}")
                elif event.key == pygame.K_UP:
                    if current_grid_index - 3 >= 0:
                        config.selected_platform -= 3
                        logger.debug(f"Haut, selected_platform={config.selected_platform}")
                elif event.key == pygame.K_LEFT:
                    if current_grid_index % 3 != 0:
                        config.selected_platform -= 1
                        logger.debug(f"Gauche, selected_platform={config.selected_platform}")
                    elif config.current_page > 0:
                        config.current_page -= 1
                        config.selected_platform = config.current_page * 9 + row * 3 + 2
                        if config.selected_platform >= len(config.platforms):
                            config.selected_platform = len(config.platforms) - 1
                        logger.debug(f"Page précédente, page={config.current_page}, selected_platform={config.selected_platform}")
                elif event.key == pygame.K_RIGHT:
                    if current_grid_index % 3 != 2 and current_grid_index < max_index:
                        config.selected_platform += 1
                        logger.debug(f"Droite, selected_platform={config.selected_platform}")
                    elif (config.current_page + 1) * 9 < len(config.platforms):
                        config.current_page += 1
                        config.selected_platform = config.current_page * 9 + row * 3
                        if config.selected_platform >= len(config.platforms):
                            config.selected_platform = len(config.platforms) - 1
                        logger.debug(f"Page suivante, page={config.current_page}, selected_platform={config.selected_platform}")
                elif event.key == pygame.K_x:
                    if config.download_tasks:
                        config.menu_state = "download_progress"
                        config.needs_redraw = True
                        logger.debug("Retour à download_progress depuis platform (touche X)")                                
                elif event.key == pygame.K_RETURN:
                    if config.platforms:
                        config.current_platform = config.selected_platform
                        config.games = load_games(config.platforms[config.current_platform])
                        config.filtered_games = config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.menu_state = "game"
                        logger.debug(f"Plateforme sélectionnée: {config.platforms[config.current_platform]}")
                elif event.key == pygame.K_ESCAPE:
                    config.menu_state = "confirm_exit"
                    config.confirm_selection = 0
                    logger.debug(f"Passage à confirm_exit, confirm_selection={config.confirm_selection}")

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
                        if event.key == pygame.K_UP and row > 0:
                            config.selected_key = (row - 1, min(col, len(keyboard_layout[row - 1]) - 1))
                            logger.debug(f"Clavier: Haut, selected_key={config.selected_key}")
                        elif event.key == pygame.K_DOWN and row < max_row:
                            config.selected_key = (row + 1, min(col, len(keyboard_layout[row + 1]) - 1))
                            logger.debug(f"Clavier: Bas, selected_key={config.selected_key}")
                        elif event.key == pygame.K_LEFT and col > 0:
                            config.selected_key = (row, col - 1)
                            logger.debug(f"Clavier: Gauche, selected_key={config.selected_key}")
                        elif event.key == pygame.K_RIGHT and col < max_col:
                            config.selected_key = (row, col + 1)
                            logger.debug(f"Clavier: Droite, selected_key={config.selected_key}")
                        elif event.key == pygame.K_RETURN:
                            key = keyboard_layout[row][col]
                            if len(config.search_query) < 50:
                                config.search_query += key.lower()
                                config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                                config.current_game = 0
                                config.scroll_offset = 0
                                logger.debug(f"Recherche mise à jour: {config.search_query}")
                    else:
                        if event.key == pygame.K_RETURN:
                            config.search_mode = False
                            logger.debug(f"Filtre appliqué: {config.search_query}")
                        elif event.key == pygame.K_ESCAPE:
                            config.search_mode = False
                            config.search_query = ""
                            config.filtered_games = config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            logger.debug("Filtre annulé")
                        elif event.key == pygame.K_BACKSPACE:
                            config.search_query = config.search_query[:-1]
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            logger.debug(f"Recherche mise à jour: {config.search_query}")
                        elif event.key == pygame.K_SPACE:
                            config.search_query += " "
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            logger.debug(f"Recherche mise à jour: {config.search_query}")
                        elif event.unicode.isprintable() and len(config.search_query) < 50:
                            config.search_query += event.unicode
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            logger.debug(f"Recherche mise à jour: {config.search_query}")
                else:
                    if event.key == pygame.K_DOWN:
                        config.current_game = min(config.current_game + 1, len(config.filtered_games) - 1)
                        if config.current_game >= config.scroll_offset + config.visible_games:
                            config.scroll_offset += 1
                        config.repeat_action = "down"
                        logger.debug(f"Bas, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
                    elif event.key == pygame.K_UP:
                        config.current_game = max(config.current_game - 1, 0)
                        if config.current_game < config.scroll_offset:
                            config.scroll_offset -= 1
                        config.repeat_action = "up"
                        logger.debug(f"Haut, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
                    elif event.key == pygame.K_q:
                        config.current_game = max(config.current_game - config.visible_games, 0)
                        config.scroll_offset = max(config.scroll_offset - config.visible_games, 0)
                        config.repeat_action = "page_up"
                        logger.debug(f"Page haut, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
                    elif event.key == pygame.K_e:
                        config.current_game = min(config.current_game + config.visible_games, len(config.filtered_games) - 1)
                        config.scroll_offset = min(config.scroll_offset + config.visible_games, len(config.filtered_games) - config.visible_games)
                        config.repeat_action = "page_down"
                        logger.debug(f"Page bas, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
                    elif event.key == pygame.K_RETURN:
                        if config.filtered_games:
                            action = "download"
                            logger.debug(f"Téléchargement initié pour jeu: {config.filtered_games[config.current_game][0]}")
                    elif event.key == pygame.K_SPACE:
                        config.search_mode = True
                        config.search_query = ""
                        config.filtered_games = config.games
                        config.selected_key = (0, 0)
                        logger.debug("Entrée en mode recherche")
                    elif event.key == pygame.K_ESCAPE:
                        config.menu_state = "platform"
                        config.current_game = 0
                        config.scroll_offset = 0
                        logger.debug("Retour à platform")
                    elif event.key == pygame.K_x:
                        if config.download_tasks:
                            config.menu_state = "download_progress"
                            config.needs_redraw = True
                            logger.debug("Retour à download_progress depuis game (touche X)")

            # Download progress
            elif config.menu_state == "download_progress":
                if event.key == pygame.K_ESCAPE:
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
                        logger.debug(f"Téléchargement annulé pour {game_name}")
                elif event.key == pygame.K_x:
                    config.menu_state = "game"
                    config.needs_redraw = True
                    logger.debug("Retour à game depuis download_progress")

            # Confirmation de sortie
            elif config.menu_state == "confirm_exit":
                if event.key == pygame.K_LEFT:
                    config.confirm_selection = 1
                    logger.debug("Sélection Oui")
                elif event.key == pygame.K_RIGHT:
                    config.confirm_selection = 0
                    logger.debug("Sélection Non")
                elif event.key == pygame.K_RETURN:
                    if config.confirm_selection == 1:
                        return "quit"
                    else:
                        config.menu_state = "platform"
                        logger.debug("Retour à platform depuis confirm_exit")
                elif event.key == pygame.K_ESCAPE:
                    config.menu_state = "platform"
                    logger.debug("Annulation confirm_exit")

            # Avertissement d'extension
            elif config.menu_state == "extension_warning":
                if event.key == pygame.K_LEFT:
                    config.extension_confirm_selection = 1
                    logger.debug("Sélection Oui (extension_warning)")
                elif event.key == pygame.K_RIGHT:
                    config.extension_confirm_selection = 0
                    logger.debug("Sélection Non (extension_warning)")
                elif event.key == pygame.K_RETURN:
                    if config.extension_confirm_selection == 1:
                        # Lancer le téléchargement
                        if config.pending_download:
                            url, platform, game_name, is_zip_non_supported = config.pending_download
                            task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported=is_zip_non_supported))
                            config.download_tasks[task] = (task, url, game_name, platform)
                            config.menu_state = "download_progress"
                            config.pending_download = None
                            logger.debug(f"Téléchargement confirmé pour {game_name}")
                        else:
                            config.menu_state = "game"
                    else:
                        config.menu_state = "game"
                        config.pending_download = None
                        logger.debug("Téléchargement annulé (extension_warning)")
                elif event.key == pygame.K_ESCAPE:
                    config.menu_state = "game"
                    config.pending_download = None
                    logger.debug("Annulation extension_warning")
            # Résultat téléchargement
            elif config.menu_state == "download_result":
                if event.key == pygame.K_RETURN:
                    config.menu_state = "game"
                    logger.debug("Retour à game depuis download_result")

        elif event.type == pygame.KEYUP:
            if event.key == repeat_key:
                repeat_key = None
            if config.menu_state == "game" and event.key in (pygame.K_DOWN, pygame.K_UP, pygame.K_q, pygame.K_e):
                config.repeat_action = None
                logger.debug(f"Touche relâchée, répétition arrêtée: {event.key}")

        # --- JOYSTICK ---
        elif event.type == pygame.JOYBUTTONDOWN:
            logger.debug(f"Bouton pressé : {event.button}")
            if config.menu_state == "error":
                if event.button == 0:  # A
                    config.menu_state = "loading"
                    logger.debug("Sortie erreur avec A")
                if event.button == 1:   #B
                    config.menu_state = "confirm_exit"
                    config.confirm_selection = 0
                    logger.debug(f"Passage à confirm_exit, confirm_selection={config.confirm_selection}")
                
            elif config.menu_state == "platform":
                if event.button == 2:  # X
                    if config.download_tasks:
                        config.menu_state = "download_progress"
                        config.needs_redraw = True
                        logger.debug("Retour à download_progress depuis platform (bouton X)")
                elif event.button == 0:  # A
                    if config.platforms:
                        config.current_platform = config.selected_platform
                        config.games = load_games(config.platforms[config.current_platform])
                        config.filtered_games = config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.menu_state = "game"
                        logger.debug(f"Plateforme sélectionnée: {config.platforms[config.current_platform]}")
                elif event.button == 1:  # B
                    config.menu_state = "confirm_exit"
                    config.confirm_selection = 0
                    logger.debug(f"Passage à confirm_exit, confirm_selection={config.confirm_selection}")
                
            elif config.menu_state == "confirm_exit":
                if event.button == 0:  # A
                    logger.debug(f"Validation confirm_exit avec confirm_selection={config.confirm_selection}")
                    if config.confirm_selection == 1:
                        return "quit"
                    else:
                        config.menu_state = "platform"
                        config.needs_redraw = True
                        logger.debug("Retour à platform depuis confirm_exit")
                elif event.button == 1:  # B
                    config.menu_state = "platform"
                    config.needs_redraw = True
                    logger.debug("Annulation confirm_exit")
            elif config.menu_state == "download_progress":
                if event.button == 1:  # B
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
                        logger.debug(f"Téléchargement annulé pour {game_name}")
                elif event.button == 2:  # X
                    config.menu_state = "game"
                    config.needs_redraw = True
                    logger.debug("Retour à game depuis download_progress")
            elif config.menu_state == "download_result":
                if event.button == 0:  # A
                    config.menu_state = "game"
                    config.needs_redraw = True
            elif config.menu_state == "extension_warning":
                if event.button == 0:  # A
                    if config.extension_confirm_selection == 1:
                        if config.pending_download:
                            url, platform, game_name, is_zip_non_supported = config.pending_download
                            task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported=is_zip_non_supported))
                            config.download_tasks[task] = (task, url, game_name, platform)
                            config.menu_state = "download_progress"
                            config.pending_download = None
                            logger.debug(f"Téléchargement confirmé pour {game_name}")
                        else:
                            config.menu_state = "game"
                    else:
                        config.menu_state = "game"
                        config.pending_download = None
                elif event.button == 1:  # B
                    config.menu_state = "game"
                    config.pending_download = None
                    logger.debug("Annulation extension_warning")
            elif config.menu_state == "game":
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
                    if event.button == 0:  # A (valider lettre/chiffre)
                        key = keyboard_layout[row][col]
                        if len(config.search_query) < 50:
                            config.search_query += key.lower()
                            config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                            config.current_game = 0
                            config.scroll_offset = 0
                            logger.debug(f"Recherche mise à jour: {config.search_query}")
                    elif event.button == 4:  # LT (effacer)
                        config.search_query = config.search_query[:-1]
                        config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        logger.debug(f"Recherche mise à jour: {config.search_query}")
                    elif event.button == 5:  # RT (espace)
                        config.search_query += " "
                        config.filtered_games = [game for game in config.games if config.search_query.lower() in game[0].lower()] if config.search_query else config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        logger.debug(f"Recherche mise à jour: {config.search_query}")
                    elif event.button == 8:  # SELECT (annuler)
                        config.search_mode = False
                        config.search_query = ""
                        config.filtered_games = config.games
                        config.current_game = 0
                        config.scroll_offset = 0
                        logger.debug("Filtre annulé")
                    elif event.button == 9:  # START (valider)
                        config.search_mode = False
                        logger.debug(f"Filtre appliqué: {config.search_query}")
                else:
                    if event.button == 0:  # A
                        if config.filtered_games:
                            action = "download"
                            logger.debug(f"Téléchargement initié pour jeu: {config.filtered_games[config.current_game][0]}")
                    elif event.button == 1:  # B
                        config.menu_state = "platform"
                        config.current_game = 0
                        config.scroll_offset = 0
                        logger.debug("Retour à platform")
                    elif event.button == 2:  # X
                        if config.download_tasks:
                            config.menu_state = "download_progress"
                            config.needs_redraw = True
                            logger.debug("Retour à download_progress depuis game")
                    elif event.button == 8:  # SELECT
                        config.search_mode = True
                        config.search_query = ""
                        config.filtered_games = config.games
                        config.selected_key = (0, 0)
                        logger.debug("Entrée en mode recherche")
                    elif event.button == 4:  # LT
                        config.current_game = max(config.current_game - config.visible_games, 0)
                        config.scroll_offset = max(config.scroll_offset - config.visible_games, 0)
                        config.repeat_action = "page_up"
                        logger.debug(f"LT, page haut, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
                    elif event.button == 5:  # RT
                        config.current_game = min(config.current_game + config.visible_games, len(config.filtered_games) - 1)
                        config.scroll_offset = min(config.scroll_offset + config.visible_games, len(config.filtered_games) - config.visible_games)
                        config.repeat_action = "page_down"
                        logger.debug(f"RT, page bas, current_game={config.current_game}, scroll_offset={config.scroll_offset}")

        elif event.type == pygame.JOYHATMOTION:
            if current_time - last_joyhat_time < JOYHAT_DEBOUNCE:
                continue
            last_joyhat_time = current_time

            if config.menu_state == "platform":
                x, y = event.value
                max_index = min(9, len(config.platforms) - config.current_page * 9) - 1
                current_grid_index = config.selected_platform - config.current_page * 9
                row = current_grid_index // 3
                if y == 1 and current_grid_index - 3 >= 0:
                    config.selected_platform -= 3
                    logger.debug(f"Haut joystick, selected_platform={config.selected_platform}")
                elif y == -1 and current_grid_index + 3 <= max_index:
                    config.selected_platform += 3
                    logger.debug(f"Bas joystick, selected_platform={config.selected_platform}")
                elif x == -1 and current_grid_index % 3 != 0:
                    config.selected_platform -= 1
                    logger.debug(f"Gauche joystick, selected_platform={config.selected_platform}")
                elif x == -1 and config.current_page > 0:
                    config.current_page -= 1
                    config.selected_platform = config.current_page * 9 + row * 3 + 2
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    logger.debug(f"Page précédente joystick, page={config.current_page}, selected_platform={config.selected_platform}")
                elif x == 1 and current_grid_index % 3 != 2 and current_grid_index < max_index:
                    config.selected_platform += 1
                    logger.debug(f"Droite joystick, selected_platform={config.selected_platform}")
                elif x == 1 and (config.current_page + 1) * 9 < len(config.platforms):
                    config.current_page += 1
                    config.selected_platform = config.current_page * 9 + row * 3
                    if config.selected_platform >= len(config.platforms):
                        config.selected_platform = len(config.platforms) - 1
                    logger.debug(f"Page suivante joystick, page={config.current_page}, selected_platform={config.selected_platform}")
            elif config.menu_state == "confirm_exit":
                x, y = event.value
                if x == -1:
                    config.confirm_selection = 1
                    logger.debug(f"Joystick: Sélection Oui, confirm_selection={config.confirm_selection}")
                elif x == 1:
                    config.confirm_selection = 0
                    logger.debug(f"Joystick: Sélection Non, confirm_selection={config.confirm_selection}")
            elif config.menu_state == "extension_warning":
                x, y = event.value
                if x == -1:
                    config.extension_confirm_selection = 1
                    logger.debug(f"Joystick: Sélection Oui (extension_warning)")
                elif x == 1:
                    config.extension_confirm_selection = 0
                    logger.debug(f"Joystick: Sélection Non (extension_warning)")
            elif config.menu_state == "game":
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
                    x, y = event.value
                    if y == 1 and row > 0:
                        config.selected_key = (row - 1, min(col, len(keyboard_layout[row - 1]) - 1))
                        logger.debug(f"Clavier joystick: Haut, selected_key={config.selected_key}")
                    elif y == -1 and row < max_row:
                        config.selected_key = (row + 1, min(col, len(keyboard_layout[row + 1]) - 1))
                        logger.debug(f"Clavier joystick: Bas, selected_key={config.selected_key}")
                    elif x == -1 and col > 0:
                        config.selected_key = (row, col - 1)
                        logger.debug(f"Clavier joystick: Gauche, selected_key={config.selected_key}")
                    elif x == 1 and col < max_col:
                        config.selected_key = (row, col + 1)
                        logger.debug(f"Clavier joystick: Droite, selected_key={config.selected_key}")
                else:
                    x, y = event.value
                    if y == 1:
                        config.current_game = max(config.current_game - 1, 0)
                        if config.current_game < config.scroll_offset:
                            config.scroll_offset -= 1
                        config.repeat_action = "up"
                        logger.debug(f"Haut joystick, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
                    elif y == -1:
                        config.current_game = min(config.current_game + 1, len(config.filtered_games) - 1)
                        if config.current_game >= config.scroll_offset + config.visible_games:
                            config.scroll_offset += 1
                        config.repeat_action = "down"
                        logger.debug(f"Bas joystick, current_game={config.current_game}, scroll_offset={config.scroll_offset}")

    # Gestion de la répétition automatique
    if config.menu_state == "game" and repeat_key and current_time > repeat_time:
        if config.repeat_action == "down" and repeat_key == pygame.K_DOWN:
            config.current_game = min(config.current_game + 1, len(config.filtered_games) - 1)
            if config.current_game >= config.scroll_offset + config.visible_games:
                config.scroll_offset += 1
            logger.debug(f"Répétition bas, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
        elif config.repeat_action == "up" and repeat_key == pygame.K_UP:
            config.current_game = max(config.current_game - 1, 0)
            if config.current_game < config.scroll_offset:
                config.scroll_offset -= 1
            logger.debug(f"Répétition haut, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
        elif config.repeat_action == "page_down" and repeat_key == pygame.K_e:
            config.current_game = min(config.current_game + config.visible_games, len(config.filtered_games) - 1)
            config.scroll_offset = min(config.scroll_offset + config.visible_games, len(config.filtered_games) - config.visible_games)
            logger.debug(f"Répétition page bas, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
        elif config.repeat_action == "page_up" and repeat_key == pygame.K_q:
            config.current_game = max(config.current_game - config.visible_games, 0)
            config.scroll_offset = max(config.scroll_offset - config.visible_games, 0)
            logger.debug(f"Répétition page haut, current_game={config.current_game}, scroll_offset={config.scroll_offset}")
        repeat_time = current_time + REPEAT_INTERVAL

    return action
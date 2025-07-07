import pygame
import os
import logging

logger = logging.getLogger(__name__)

# Version actuelle de l'application
app_version = "1.4.0"

# Variables d'état
platforms = []
current_platform = 0
platform_names = {}  # {platform_id: platform_name}
games = []
current_game = 0
menu_state = "popup"
confirm_choice = False
scroll_offset = 0
visible_games = 15
popup_start_time = 0
last_progress_update = 0
needs_redraw = True
transition_state = "idle"
transition_progress = 0.0
transition_duration = 18
games_count = {}
download_tasks = {}
download_progress = {}
download_result_message = ""
download_result_error = False
download_result_start_time = 0
loading_progress = 0.0
current_loading_system = ""
error_message = ""
repeat_action = None
repeat_start_time = 0
repeat_last_action = 0
repeat_key = None 
filtered_games = []
search_mode = False
search_query = ""
filter_active = False
extension_confirm_selection = 0
pending_download = None
controls_config = {}
selected_pause_option = 0
previous_menu_state = None
history = []  # Liste des entrées de l'historique
current_history_item = 0  # Index de l'élément sélectionné dans l'historique
history_scroll_offset = 0  # Offset pour le défilement de l'historique
visible_history_items = 15  # Nombre d'éléments d'historique visibles (ajusté dynamiquement)
confirm_clear_selection = 0  # confirmation clear historique
last_state_change_time = 0  # Temps du dernier changement d'état pour debounce
debounce_delay = 200  # Délai de debounce en millisecondes
platform_dicts = []  # Liste des dictionnaires de plateformes
selected_key = (0, 0)  # Position du curseur dans le clavier virtuel
is_non_pc = True  # Indicateur pour plateforme non-PC (par exemple, console)

# Résolution de l'écran
screen_width = 800
screen_height = 600
SCREEN_WIDTH = 800
"""Largeur de l'écran en pixels."""
SCREEN_HEIGHT = 600
"""Hauteur de l'écran en pixels."""

# Polices
FONT = None
"""Police par défaut pour l'affichage, initialisée via init_font()."""
progress_font = None
"""Police pour l'affichage de la progression."""
title_font = None
"""Police pour les titres."""
search_font = None
"""Police pour la recherche."""
small_font = None
"""Police pour les petits textes."""

CONTROLS_CONFIG_PATH = "/userdata/saves/ports/rgsx/controls.json"
"""Chemin du fichier de configuration des contrôles."""
HISTORY_PATH = "/userdata/saves/ports/rgsx/history.json"
"""Chemin du fichier de l'historique des téléchargements."""

def init_font():
    """Initialise les polices après pygame.init()."""
    global FONT, progress_font, title_font, search_font, small_font
    try:
        FONT = pygame.font.Font(None, 36)
        progress_font = pygame.font.Font(None, 28)
        title_font = pygame.font.Font(None, 48)
        search_font = pygame.font.Font(None, 36)
        small_font = pygame.font.Font(None, 24)
        logger.debug("Polices initialisées avec succès")
    except pygame.error as e:
        logger.error(f"Erreur lors de l'initialisation des polices : {e}")
        FONT = None
        progress_font = None
        title_font = None
        search_font = None
        small_font = None

def validate_resolution():
    """Valide la résolution de l'écran par rapport aux capacités du matériel."""
    display_info = pygame.display.Info()
    if SCREEN_WIDTH > display_info.current_w or SCREEN_HEIGHT > display_info.current_h:
        logger.warning(f"Résolution {SCREEN_WIDTH}x{SCREEN_HEIGHT} dépasse les limites de l'écran")
        return display_info.current_w, display_info.current_h
    return SCREEN_WIDTH, SCREEN_HEIGHT
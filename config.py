import pygame # type: ignore
import os
import sys
import logging

# Version actuelle de l'application
app_version = "1.9.7.8"

def get_application_root():
    """Détermine le dossier de l'application de manière portable."""
    try:
        # Obtenir le chemin absolu du fichier config.py
        current_file = os.path.abspath(__file__)
        # Remonter au dossier parent de config.py (par exemple, dossier de l'application)
        app_root = os.path.dirname(os.path.dirname(current_file))
        return app_root
    except NameError:
        # Si __file__ n'est pas défini (par exemple, exécution dans un REPL)
        return os.path.abspath(os.getcwd())

def get_system_root():
    """Détermine le dossier racine du système de fichiers (par exemple, /userdata ou C:\\)."""
    try:
        if sys.platform.startswith("win"):
            # Sur Windows, extraire la lettre de disque
            current_path = os.path.abspath(__file__)
            drive, _ = os.path.splitdrive(current_path)
            system_root = drive + os.sep
            return system_root
        else:
            # Sur Linux/Batocera, remonter jusqu'à atteindre /userdata ou /
            current_path = os.path.abspath(__file__)
            current_dir = current_path
            while current_dir != os.path.dirname(current_dir):  # Tant qu'on peut remonter
                parent_dir = os.path.dirname(current_dir)
                if os.path.basename(parent_dir) == "userdata":  # Vérifier si le parent est userdata
                    system_root = parent_dir
                    return system_root
                current_dir = parent_dir
            # Si userdata n'est pas trouvé, retourner /
            return "/"
    except NameError:
        # Si __file__ n'est pas défini, utiliser le répertoire de travail actuel
        return "/" if not sys.platform.startswith("win") else os.path.splitdrive(os.getcwd())[0] + os.sep

# Chemins de base
SYSTEM_FOLDER = get_system_root()
APP_FOLDER = os.path.join(get_application_root(), "RGSX")
ROMS_FOLDER = os.path.join(SYSTEM_FOLDER, "roms")
SAVE_FOLDER = os.path.join(SYSTEM_FOLDER, "saves", "ports", "rgsx")

# Configuration du logging
logger = logging.getLogger(__name__)
log_dir = os.path.join(APP_FOLDER, "logs")
log_file = os.path.join(log_dir, "RGSX.log")

# Chemins de base
UPDATE_FOLDER = os.path.join(APP_FOLDER, "update")
GAMELISTXML = os.path.join(APP_FOLDER, "gamelist.xml")
IMAGES_FOLDER = os.path.join(APP_FOLDER, "images", "systemes")
GAMES_FOLDER = os.path.join(APP_FOLDER, "games")
CONTROLS_CONFIG_PATH = os.path.join(SAVE_FOLDER, "controls.json")
HISTORY_PATH = os.path.join(SAVE_FOLDER, "history.json")
LANGUAGE_CONFIG_PATH = os.path.join(SAVE_FOLDER, "language.json")
JSON_EXTENSIONS = os.path.join(APP_FOLDER, "rom_extensions.json")




# URL
OTA_SERVER_URL = "https://retrogamesets.fr/softs/"
OTA_VERSION_ENDPOINT = os.path.join(OTA_SERVER_URL, "version.json")
OTA_UPDATE_ZIP = os.path.join(OTA_SERVER_URL, "RGSX.zip")
OTA_data_ZIP = os.path.join(OTA_SERVER_URL, "rgsx-data.zip")


# Constantes pour la répétition automatique dans pause_menu
REPEAT_DELAY = 350  # Délai initial avant répétition (ms) - augmenté pour éviter les doubles actions
REPEAT_INTERVAL = 120  # Intervalle entre répétitions (ms) - ajusté pour une navigation plus contrôlée
REPEAT_ACTION_DEBOUNCE = 150  # Délai anti-rebond pour répétitions (ms) - augmenté pour éviter les doubles actions


# Variables d'état
platforms = []
current_platform = 0
accessibility_mode = False  # Mode accessibilité pour les polices agrandies
accessibility_settings = {"font_scale": 1.0}
font_scale_options = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0]
current_font_scale_index = 3  # Index pour 1.0
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
API_KEY_1FICHIER = ""  # Initialisation de la variable globale pour la clé API

# Variables pour la sélection de langue
selected_language_index = 0

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
selected_option = 0
previous_menu_state = None
history = []  # Liste des entrées d'historique avec platform, game_name, status, url, progress, message, timestamp
download_progress = {}
download_tasks = {}  # Dictionnaire pour les tâches de téléchargement
download_result_message = ""
download_result_error = False
download_result_start_time = 0
needs_redraw = False
current_history_item = 0
history_scroll_offset = 0  # Offset pour le défilement de l'historique
visible_history_items = 15  # Nombre d'éléments d'historique visibles (ajusté dynamiquement)
confirm_clear_selection = 0  # confirmation clear historique
confirm_cancel_selection = 0  # confirmation annulation téléchargement
last_state_change_time = 0  # Temps du dernier changement d'état pour debounce
debounce_delay = 200  # Délai de debounce en millisecondes
platform_dicts = []  # Liste des dictionnaires de plateformes
selected_key = (0, 0)  # Position du curseur dans le clavier virtuel
is_non_pc = True  # Indicateur pour plateforme non-PC (par exemple, console)
redownload_confirm_selection = 0  # Sélection pour la confirmation de redownload
popup_message = ""  # Message à afficher dans les popups
popup_timer = 0  # Temps restant pour le popup en millisecondes (0 = inactif)
last_frame_time = pygame.time.get_ticks()
current_music_name = None
music_popup_start_time = 0


GRID_COLS = 3  # Number of columns in the platform grid
GRID_ROWS = 4  # Number of rows in the platform grid

# Résolution de l'écran fallback
# Utilisée si la résolution définie dépasse les capacités de l'écran
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

def init_font():
    """Initialise les polices après pygame.init()."""

    global font, progress_font, title_font, search_font, small_font
    font_scale = accessibility_settings.get("font_scale", 1.0)
    try:
        font_path = os.path.join(APP_FOLDER, "assets", "Pixel-UniCode.ttf")
        font = pygame.font.Font(font_path, int(36 * font_scale))
        title_font = pygame.font.Font(font_path, int(48 * font_scale))
        search_font = pygame.font.Font(font_path, int(48 * font_scale))
        progress_font = pygame.font.Font(font_path, int(36 * font_scale))
        small_font = pygame.font.Font(font_path, int(28 * font_scale))
        logger.debug(f"Polices Pixel-UniCode initialisées (font_scale: {font_scale})")
    except Exception as e:
        try:
            font = pygame.font.SysFont("arial", int(48 * font_scale))
            title_font = pygame.font.SysFont("arial", int(60 * font_scale))
            search_font = pygame.font.SysFont("arial", int(60 * font_scale))
            progress_font = pygame.font.SysFont("arial", int(36 * font_scale))
            small_font = pygame.font.SysFont("arial", int(28 * font_scale))
            logger.debug(f"Polices Arial initialisées (font_scale: {font_scale})")
        except Exception as e2:
            logger.error(f"Erreur lors de l'initialisation des polices : {e2}")
            font = None
            progress_font = None
            title_font = None
            search_font = None
            small_font = None

def validate_resolution():
    """Valide la résolution de l'écran par rapport aux capacités de l'écran."""
    display_info = pygame.display.Info()
    if SCREEN_WIDTH > display_info.current_w or SCREEN_HEIGHT > display_info.current_h:
        logger.warning(f"Résolution {SCREEN_WIDTH}x{SCREEN_HEIGHT} dépasse les limites de l'écran")
        return display_info.current_w, display_info.current_h
    return SCREEN_WIDTH, SCREEN_HEIGHT



    


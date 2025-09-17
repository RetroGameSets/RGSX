import os
import logging
import platform

# Headless mode for CLI: set env RGSX_HEADLESS=1 to avoid pygame and noisy prints
HEADLESS = os.environ.get("RGSX_HEADLESS") == "1"
try:
    if not HEADLESS:
        import pygame  # type: ignore
    else:
        pygame = None  # type: ignore
except Exception:
    pygame = None  # type: ignore

# Version actuelle de l'application
app_version = "2.2.2.5"


def get_application_root():
    """Détermine le dossier de l'application (PORTS)"""
    try:
        # Obtenir le chemin absolu du fichier config.py
        current_file = os.path.abspath(__file__)
        # Remonter au dossier parent de config.py (par exemple, dossier de l'application)
        app_root = os.path.dirname(os.path.dirname(current_file))
        return app_root
    except NameError:
        # Si __file__ n'est pas défini (par exemple, exécution dans un REPL)
        return os.path.abspath(os.getcwd())

def detect_operating_system():
    """Renvoie le nom du système d'exploitation."""
    OPERATING_SYSTEM = platform.system()
    return OPERATING_SYSTEM
    

# Chemins de base
APP_FOLDER = os.path.join(get_application_root(), "RGSX")
USERDATA_FOLDER = os.path.dirname(os.path.dirname(os.path.dirname(APP_FOLDER)))
ROMS_FOLDER = os.path.join(USERDATA_FOLDER, "roms")
SAVE_FOLDER = os.path.join(USERDATA_FOLDER, "saves", "ports", "rgsx")
GAMELISTXML = os.path.join(ROMS_FOLDER, "ports","gamelist.xml")
GAMELISTXML_WINDOWS = os.path.join(ROMS_FOLDER, "windows","gamelist.xml")


# Configuration du logging
logger = logging.getLogger(__name__)
log_dir = os.path.join(APP_FOLDER, "logs")
log_file = os.path.join(log_dir, "RGSX.log")

#Dossier de l'APP : /roms/ports/rgsx
UPDATE_FOLDER = os.path.join(APP_FOLDER, "update")
LANGUAGES_FOLDER = os.path.join(APP_FOLDER, "languages")
MUSIC_FOLDER = os.path.join(APP_FOLDER, "assets", "music")

#Dossier de sauvegarde : /saves/ports/rgsx
IMAGES_FOLDER = os.path.join(SAVE_FOLDER, "images")
GAMES_FOLDER = os.path.join(SAVE_FOLDER, "games")
SOURCES_FILE = os.path.join(SAVE_FOLDER, "systems_list.json")
JSON_EXTENSIONS = os.path.join(SAVE_FOLDER, "rom_extensions.json")
PRECONF_CONTROLS_PATH = os.path.join(APP_FOLDER, "assets", "controls")
CONTROLS_CONFIG_PATH = os.path.join(SAVE_FOLDER, "controls.json")
HISTORY_PATH = os.path.join(SAVE_FOLDER, "history.json")
# Séparation chemin / valeur pour éviter les confusions lors du chargement
API_KEY_1FICHIER_PATH = os.path.join(SAVE_FOLDER, "1FichierAPI.txt")
API_KEY_ALLDEBRID_PATH = os.path.join(SAVE_FOLDER, "AllDebridAPI.txt")
API_KEY_REALDEBRID_PATH = os.path.join(SAVE_FOLDER, "RealDebridAPI.txt")
# Valeurs chargées (remplies dynamiquement par utils.load_api_key_*).
API_KEY_1FICHIER = ""
API_KEY_ALLDEBRID = ""
API_KEY_REALDEBRID = ""
RGSX_SETTINGS_PATH = os.path.join(SAVE_FOLDER, "rgsx_settings.json")

# URL
OTA_SERVER_URL = "https://retrogamesets.fr/softs/"
OTA_VERSION_ENDPOINT = os.path.join(OTA_SERVER_URL, "version.json")
OTA_UPDATE_ZIP = os.path.join(OTA_SERVER_URL, "RGSX.zip")
OTA_data_ZIP = os.path.join(OTA_SERVER_URL, "games.zip")

#CHEMINS DES EXECUTABLES
UNRAR_EXE = os.path.join(APP_FOLDER,"assets", "unrar.exe")
XDVDFS_EXE = os.path.join(APP_FOLDER,"assets", "xdvdfs.exe")
XDVDFS_LINUX = os.path.join(APP_FOLDER,"assets", "xdvdfs")

if not HEADLESS:
    # Print des chemins pour debug
    print(f"OPERATING_SYSTEM: {detect_operating_system()}")
    print(f"APP_FOLDER: {APP_FOLDER}")
    print(f"USERDATA_FOLDER: {USERDATA_FOLDER}")
    print(f"ROMS_FOLDER: {ROMS_FOLDER}")
    print(f"SAVE_FOLDER: {SAVE_FOLDER}")
    print(f"RGSX LOGS_FOLDER: {log_dir}")
    print(f"RGSX SETTINGS PATH: {RGSX_SETTINGS_PATH}")
    print(f"JSON_EXTENSIONS: {JSON_EXTENSIONS}")
    print(f"IMAGES_FOLDER: {IMAGES_FOLDER}")
    print(f"GAMES_FOLDER: {GAMES_FOLDER}")
    print(f"SOURCES_FILE: {SOURCES_FILE}")


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
music_enabled = True  # Par défaut la musique est activée
sources_mode = "rgsx"  # Mode des sources de jeux (rgsx/custom)
custom_sources_url = ""  # URL personnalisée si mode custom

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
popup_message = ""  # Message à afficher dans les popups
popup_timer = 0  # Temps restant pour le popup en millisecondes (0 = inactif)
last_frame_time = pygame.time.get_ticks() if pygame is not None else 0
current_music_name = None
music_popup_start_time = 0
selected_games = set()  # Indices des jeux sélectionnés pour un téléchargement multiple (menu game)
batch_download_indices = []  # File d'attente des indices de jeux à traiter en lot
batch_in_progress = False  # Indique qu'un lot est en cours
batch_pending_game = None  # Données du jeu en attente de confirmation d'extension

PREMIUM_HOST_MARKERS = [
    "1Fichier",
]
hide_premium_systems = False

# Indicateurs d'entrée (détectés au démarrage)
joystick = False
keyboard = False
xbox_controller = False
playstation_controller = False
nintendo_controller = False
logitech_controller = False
eightbitdo_controller = False
steam_controller = False
trimui_controller = False
generic_controller = False
xbox_elite_controller = False  # Flag spécifique manette Xbox Elite
anbernic_rg35xx_controller = False  # Flag spécifique Anbernic RG3xxx

# --- Filtre plateformes (UI) ---
selected_filter_index = 0  # index dans la liste visible triée
filter_platforms_scroll_offset = 0  # défilement si liste longue
filter_platforms_dirty = False  # indique si modifications non sauvegardées
filter_platforms_selection = []  # copie de travail des plateformes visibles (bool masque?) structure: list of (name, hidden_bool)


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

# Liste des familles de polices disponibles (identifiants logiques)
FONT_FAMILIES = [
    "pixel",   # police rétro Pixel-UniCode.ttf
    "dejavu"   # police plus standard lisible petites tailles
]
current_font_family_index = 0  # 0=pixel par défaut

# Après définition de FONT_FAMILIES et current_font_family_index, tenter de charger la famille depuis les settings
try:
    from rgsx_settings import get_font_family  # import tardif pour éviter dépendances circulaires lors de l'exécution initiale
    saved_family = get_font_family()
    if saved_family in FONT_FAMILIES:
        current_font_family_index = FONT_FAMILIES.index(saved_family)
except Exception as e:
    logging.getLogger(__name__).debug(f"Impossible de charger la famille de police sauvegardée: {e}")

def init_font():
    """Initialise les polices après pygame.init() en fonction de la famille choisie."""
    global font, progress_font, title_font, search_font, small_font
    font_scale = accessibility_settings.get("font_scale", 1.0)

    # Déterminer la famille sélectionnée
    family_id = FONT_FAMILIES[current_font_family_index] if 0 <= current_font_family_index < len(FONT_FAMILIES) else "pixel"


    def load_family(fam: str):
        """Retourne un tuple (font, title_font, search_font, progress_font, small_font)."""
        base_size = 36
        title_size = 48
        search_size = 48
        small_size = 28
        if fam == "pixel":
            path = os.path.join(APP_FOLDER, "assets", "Pixel-UniCode.ttf")
            f = pygame.font.Font(path, int(base_size * font_scale))
            t = pygame.font.Font(path, int(title_size * font_scale))
            s = pygame.font.Font(path, int(search_size * font_scale))
            p = pygame.font.Font(path, int(base_size * font_scale))
            sm = pygame.font.Font(path, int(small_size * font_scale))
            return f, t, s, p, sm
        elif fam == "dejavu":
            try:
                f = pygame.font.SysFont("dejavusans", int(base_size * font_scale))
                t = pygame.font.SysFont("dejavusans", int(title_size * font_scale))
                s = pygame.font.SysFont("dejavusans", int(search_size * font_scale))
                p = pygame.font.SysFont("dejavusans", int(base_size * font_scale))
                sm = pygame.font.SysFont("dejavusans", int(small_size * font_scale))
            except Exception:
                f = pygame.font.SysFont("dejavu sans", int(base_size * font_scale))
                t = pygame.font.SysFont("dejavu sans", int(title_size * font_scale))
                s = pygame.font.SysFont("dejavu sans", int(search_size * font_scale))
                p = pygame.font.SysFont("dejavu sans", int(base_size * font_scale))
                sm = pygame.font.SysFont("dejavu sans", int(small_size * font_scale))
            return f, t, s, p, sm
        

    try:
        font, title_font, search_font, progress_font, small_font = load_family(family_id)
        logger.debug(f"Polices initialisées (famille={family_id}, scale={font_scale})")
    except Exception as e:
        logger.error(f"Erreur chargement famille {family_id}: {e}, fallback dejavu")
        try:
            font, title_font, search_font, progress_font, small_font = load_family("dejavu")
        except Exception as e2:
            logger.error(f"Erreur fallback dejavu: {e2}")
            font = title_font = search_font = progress_font = small_font = None

# Indique si une vérification/installation des mises à jour a déjà été effectuée au démarrage
update_checked = False

def validate_resolution():
    """Valide la résolution de l'écran par rapport aux capacités de l'écran."""
    if pygame is None:
        return SCREEN_WIDTH, SCREEN_HEIGHT
    display_info = pygame.display.Info()
    if SCREEN_WIDTH > display_info.current_w or SCREEN_HEIGHT > display_info.current_h:
        logger.warning(f"Résolution {SCREEN_WIDTH}x{SCREEN_HEIGHT} dépasse les limites de l'écran")
        return display_info.current_w, display_info.current_h
    return SCREEN_WIDTH, SCREEN_HEIGHT
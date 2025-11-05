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
app_version = "2.3.1.7"


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

    
### CONSTANTES DES CHEMINS DE BASE

# Chemins de base
APP_FOLDER = os.path.join(get_application_root(), "RGSX")
USERDATA_FOLDER = os.path.dirname(os.path.dirname(os.path.dirname(APP_FOLDER))) # remonte de /userdata/roms/ports/rgsx à /userdata ou \Retrobat
SAVE_FOLDER = os.path.join(USERDATA_FOLDER, "saves", "ports", "rgsx")

# ROMS_FOLDER - Charger depuis rgsx_settings.json si défini, sinon valeur par défaut
_default_roms_folder = os.path.join(USERDATA_FOLDER, "roms")
try:
    # Import tardif pour éviter les dépendances circulaires
    _settings_path = os.path.join(SAVE_FOLDER, "rgsx_settings.json")
    if os.path.exists(_settings_path):
        import json
        with open(_settings_path, 'r', encoding='utf-8') as _f:
            _settings = json.load(_f)
            _custom_roms = _settings.get("roms_folder", "").strip()
            if _custom_roms and os.path.isdir(_custom_roms):
                ROMS_FOLDER = _custom_roms
            else:
                ROMS_FOLDER = _default_roms_folder
    else:
        ROMS_FOLDER = _default_roms_folder
except Exception as _e:
    ROMS_FOLDER = _default_roms_folder
    logging.getLogger(__name__).debug(f"Impossible de charger roms_folder depuis settings: {_e}")


# Configuration du logging
logger = logging.getLogger(__name__)

# File d'attente de téléchargements (jobs en attente)
download_queue = []  # Liste de dicts: {url, platform, game_name, ...}
# Indique si un téléchargement est en cours
download_active = False
log_dir = os.path.join(APP_FOLDER, "logs")
log_file = os.path.join(log_dir, "RGSX.log")
log_file_web = os.path.join(log_dir, 'rgsx_web.log')

# Dans le Dossier de l'APP : /roms/ports/rgsx
UPDATE_FOLDER = os.path.join(APP_FOLDER, "update")
LANGUAGES_FOLDER = os.path.join(APP_FOLDER, "languages")
MUSIC_FOLDER = os.path.join(APP_FOLDER, "assets", "music")
GAMELISTXML = os.path.join(ROMS_FOLDER, "ports","gamelist.xml")
GAMELISTXML_WINDOWS = os.path.join(ROMS_FOLDER, "windows","gamelist.xml")

# Dans le Dossier de sauvegarde : /saves/ports/rgsx
IMAGES_FOLDER = os.path.join(SAVE_FOLDER, "images")
GAMES_FOLDER = os.path.join(SAVE_FOLDER, "games")
SOURCES_FILE = os.path.join(SAVE_FOLDER, "systems_list.json")
JSON_EXTENSIONS = os.path.join(SAVE_FOLDER, "rom_extensions.json")
PRECONF_CONTROLS_PATH = os.path.join(APP_FOLDER, "assets", "controls")
CONTROLS_CONFIG_PATH = os.path.join(SAVE_FOLDER, "controls.json")
HISTORY_PATH = os.path.join(SAVE_FOLDER, "history.json")
DOWNLOADED_GAMES_PATH = os.path.join(SAVE_FOLDER, "downloaded_games.json")
RGSX_SETTINGS_PATH = os.path.join(SAVE_FOLDER, "rgsx_settings.json")
API_KEY_1FICHIER_PATH = os.path.join(SAVE_FOLDER, "1FichierAPI.txt")
API_KEY_ALLDEBRID_PATH = os.path.join(SAVE_FOLDER, "AllDebridAPI.txt")
API_KEY_REALDEBRID_PATH = os.path.join(SAVE_FOLDER, "RealDebridAPI.txt")



# URL - GitHub Releases
GITHUB_REPO = "RetroGameSets/RGSX"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

# URLs pour les mises à jour OTA (Over-The-Air)
# Utilise le fichier RGSX_latest.zip qui pointe toujours vers la dernière version
OTA_UPDATE_ZIP = f"{GITHUB_RELEASES_URL}/latest/download/RGSX_update_latest.zip"
OTA_VERSION_ENDPOINT = "https://raw.githubusercontent.com/RetroGameSets/RGSX/refs/heads/main/version.json"  # Endpoint pour vérifier la version disponible

# URLs legacy (conservées pour compatibilité)
OTA_SERVER_URL = "https://retrogamesets.fr/softs/"
OTA_data_ZIP = os.path.join(OTA_SERVER_URL, "games.zip")

#CHEMINS DES EXECUTABLES
UNRAR_EXE = os.path.join(APP_FOLDER,"assets","progs","unrar.exe")
XISO_EXE = os.path.join(APP_FOLDER,"assets", "progs", "extract-xiso_win.exe")
XISO_LINUX = os.path.join(APP_FOLDER,"assets", "progs", "extract-xiso_linux")
PS3DEC_EXE = os.path.join(APP_FOLDER,"assets", "progs", "ps3dec_win.exe")
PS3DEC_LINUX = os.path.join(APP_FOLDER,"assets", "progs", "ps3dec_linux")
SEVEN_Z_LINUX = os.path.join(APP_FOLDER,"assets", "progs", "7zz")
SEVEN_Z_EXE = os.path.join(APP_FOLDER,"assets", "progs", "7z.exe")

# Détection du système d'exploitation (une seule fois au démarrage)
OPERATING_SYSTEM = platform.system()

# Informations système (Batocera)
SYSTEM_INFO = {
    "model": "",
    "system": "",
    "architecture": "",
    "cpu_model": "",
    "cpu_cores": "",
    "cpu_max_frequency": "",
    "cpu_features": "",
    "temperature": "",
    "available_memory": "",
    "total_memory": "",
    "display_resolution": "",
    "display_refresh_rate": "",
    "data_partition_format": "",
    "data_partition_space": "",
    "network_ip": ""
}

def get_batocera_system_info():
    """Récupère les informations système via la commande batocera-info."""
    global SYSTEM_INFO
    try:
        import subprocess
        result = subprocess.run(['batocera-info'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == "Model":
                        SYSTEM_INFO["model"] = value
                    elif key == "System":
                        SYSTEM_INFO["system"] = value
                    elif key == "Architecture":
                        SYSTEM_INFO["architecture"] = value
                    elif key == "CPU Model":
                        SYSTEM_INFO["cpu_model"] = value
                    elif key == "CPU Cores":
                        SYSTEM_INFO["cpu_cores"] = value
                    elif key == "CPU Max Frequency":
                        SYSTEM_INFO["cpu_max_frequency"] = value
                    elif key == "CPU Features":
                        SYSTEM_INFO["cpu_features"] = value
                    elif key == "Temperature":
                        SYSTEM_INFO["temperature"] = value
                    elif key == "Available Memory":
                        SYSTEM_INFO["available_memory"] = value.split('/')[0].strip() if '/' in value else value
                        SYSTEM_INFO["total_memory"] = value.split('/')[1].strip() if '/' in value else ""
                    elif key == "Display Resolution":
                        SYSTEM_INFO["display_resolution"] = value
                    elif key == "Display Refresh Rate":
                        SYSTEM_INFO["display_refresh_rate"] = value
                    elif key == "Data Partition Format":
                        SYSTEM_INFO["data_partition_format"] = value
                    elif key == "Data Partition Available Space":
                        SYSTEM_INFO["data_partition_space"] = value
                    elif key == "Network IP Address":
                        SYSTEM_INFO["network_ip"] = value
            
            logger.debug(f"Informations système Batocera récupérées: {SYSTEM_INFO}")      
            print(f"SYSTEM_INFO: {SYSTEM_INFO}")
            return True
    except FileNotFoundError:
        logger.debug("Commande batocera-info non disponible (système non-Batocera)")
    except subprocess.TimeoutExpired:
        logger.warning("Timeout lors de l'exécution de batocera-info")
    except Exception as e:
        logger.debug(f"Erreur lors de la récupération des infos système: {e}")
    
    # Fallback: informations basiques avec platform
    SYSTEM_INFO["system"] = f"{platform.system()} {platform.release()}"
    SYSTEM_INFO["architecture"] = platform.machine()
    SYSTEM_INFO["cpu_model"] = platform.processor() or "Unknown"
    
    return False

if not HEADLESS:
    # Print des chemins pour debug
    print(f"OPERATING_SYSTEM: {OPERATING_SYSTEM}")
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

# Récupérer les informations système au démarrage
get_batocera_system_info()

### Variables d'état par défaut

# Résolution de l'écran fallback
SCREEN_WIDTH = 800  # Largeur de l'écran en pixels.
SCREEN_HEIGHT = 600  # Hauteur de l'écran en pixels.

# Polices
FONT = None  # Police par défaut pour l'affichage, initialisée via init_font().
progress_font = None  # Police pour l'affichage de la progression
title_font = None  # Police pour les titres
search_font = None  # Police pour la recherche
small_font = None  # Police pour les petits textes
FONT_FAMILIES = [
    "pixel",   # police rétro Pixel-UniCode.ttf
    "dejavu"   # police plus standard lisible petites tailles
]
current_font_family_index = 0  # 0=pixel par défaut

# Constantes pour la répétition automatique et le debounce
REPEAT_DELAY = 350  # Délai initial avant répétition (ms) - augmenté pour éviter les doubles actions
REPEAT_INTERVAL = 120  # Intervalle entre répétitions (ms) - ajusté pour une navigation plus contrôlée
REPEAT_ACTION_DEBOUNCE = 150  # Délai anti-rebond pour répétitions (ms) - augmenté pour éviter les doubles actions
repeat_action = None  # Action en cours de répétition automatique
repeat_start_time = 0  # Timestamp de début de la répétition
repeat_last_action = 0  # Timestamp de la dernière action répétée
repeat_key = None  # Touche ou bouton en cours de répétition
last_state_change_time = 0  # Temps du dernier changement d'état pour debounce
debounce_delay = 200  # Délai de debounce en millisecondes

# gestion des entrées et détection des joystick/clavier/controller
joystick = False
keyboard = False  # Indicateur si un clavier est détecté
controller_device_name = ""  # Nom exact du joystick détecté (pour auto-préréglages)

# Affichage des plateformes
GRID_COLS = 3  # Number of columns in the platform grid
GRID_ROWS = 4  # Number of rows in the platform grid
platforms = []  # Liste des plateformes disponibles
current_platform = 0  # Index de la plateforme actuelle sélectionnée
platform_names = {}  # {platform_id: platform_name}
games_count = {}  # Dictionnaire comptant le nombre de jeux par plateforme
platform_dicts = []  # Liste des dictionnaires de plateformes

# Filtre plateformes
selected_filter_index = 0  # index dans la liste visible triée
filter_platforms_scroll_offset = 0  # défilement si liste longue
filter_platforms_dirty = False  # indique si modifications non sauvegardées
filter_platforms_selection = []  # copie de travail des plateformes visibles (bool masque?) structure: list of (name, hidden_bool)

# Affichage des jeux et sélection
games = []  # Liste des jeux pour la plateforme actuelle
current_game = 0  # Index du jeu actuellement sélectionné
menu_state = "loading"  # État actuel de l'interface menu
scroll_offset = 0  # Offset de défilement pour la liste des jeux
visible_games = 15  # Nombre de jeux visibles en même temps par défaut

# Options d'affichage
accessibility_mode = False  # Mode accessibilité pour les polices agrandies
accessibility_settings = {"font_scale": 1.0}  # Paramètres d'accessibilité (échelle de police)
font_scale_options = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0]  # Options disponibles pour l'échelle de police
current_font_scale_index = 3  # Index pour 1.0
popup_start_time = 0  # Timestamp de début d'affichage du popup
last_progress_update = 0  # Timestamp de la dernière mise à jour de progression
transition_state = "idle"  # État de la transition d'écran
transition_progress = 0.0  # Progression de la transition (0.0 à 1.0)
transition_duration = 18  # Durée de la transition en frames
music_enabled = True  # Par défaut la musique est activée
sources_mode = "rgsx"  # Mode des sources de jeux (rgsx/custom)
custom_sources_url = {OTA_data_ZIP}  # URL personnalisée si mode custom
selected_language_index = 0  # Index de la langue sélectionnée dans la liste

# Recherche et filtres
filtered_games = []  # Liste des jeux filtrés par recherche ou filtre
search_mode = False  # Indicateur si le mode recherche est actif
search_query = ""  # Chaîne de recherche saisie par l'utilisateur
filter_active = False  # Indicateur si un filtre est appliqué

# Gestion des états du menu
needs_redraw = False  # Indicateur si l'écran doit être redessiné
selected_option = 0  # Index de l'option sélectionnée dans le menu
previous_menu_state = None  # État précédent du menu pour navigation
loading_progress = 0.0  # Progression du chargement initial (0.0 à 1.0)
current_loading_system = ""  # Nom du système en cours de chargement

# Gestion des téléchargements et de l'historique
history = []  # Liste des entrées d'historique avec platform, game_name, status, url, progress, message, timestamp
pending_download = None  # Objet de téléchargement en attente
download_progress = {}  # Dictionnaire de progression des téléchargements actifs
download_tasks = {}  # Dictionnaire pour les tâches de téléchargement
download_result_message = ""  # Message de résultat du dernier téléchargement
download_result_error = False  # Indicateur d'erreur pour le résultat de téléchargement
download_result_start_time = 0  # Timestamp de début du résultat affiché
current_history_item = 0  # Index de l'élément d'historique affiché
history_scroll_offset = 0  # Offset pour le défilement de l'historique
visible_history_items = 15  # Nombre d'éléments d'historique visibles (ajusté dynamiquement)
confirm_clear_selection = 0  # confirmation clear historique
confirm_cancel_selection = 0  # confirmation annulation téléchargement

# Tracking des jeux téléchargés
downloaded_games = {}  # Dict {platform_name: {game_name: {"timestamp": "...", "size": "..."}}}

# Scraper de métadonnées
scraper_image_surface = None  # Surface Pygame contenant l'image scrapée
scraper_image_url = ""  # URL de l'image actuellement affichée
scraper_game_name = ""  # Nom du jeu en cours de scraping
scraper_platform_name = ""  # Nom de la plateforme en cours de scraping
scraper_loading = False  # Indicateur de chargement en cours
scraper_error_message = ""  # Message d'erreur du scraper
scraper_description = ""  # Description du jeu
scraper_genre = ""  # Genre(s) du jeu
scraper_release_date = ""  # Date de sortie du jeu
scraper_game_page_url = ""  # URL de la page du jeu sur TheGamesDB

# CLES API / PREMIUM HOSTS
API_KEY_1FICHIER = ""
API_KEY_ALLDEBRID = ""
API_KEY_REALDEBRID = ""
PREMIUM_HOST_MARKERS = [
    "1Fichier",
]
hide_premium_systems = False  # Indicateur pour masquer les systèmes premium

# Variables diverses
update_checked = False
extension_confirm_selection = 0  # Index de sélection pour confirmation d'extension
controls_config = {}  # Configuration des contrôles personnalisés
selected_key = (0, 0)  # Position du curseur dans le clavier virtuel
popup_message = ""  # Message à afficher dans les popups
popup_timer = 0  # Temps restant pour le popup en millisecondes (0 = inactif)
last_frame_time = pygame.time.get_ticks() if pygame is not None else 0  # Timestamp de la dernière frame rendue
current_music_name = None  # Nom de la piste musicale actuelle
music_popup_start_time = 0  # Timestamp de début du popup musique
error_message = ""  # Message d'erreur à afficher

# Détection d'appui long sur confirm (menu game)
confirm_press_start_time = 0  # Timestamp du début de l'appui sur confirm
confirm_long_press_threshold = 2000  # Durée en ms pour déclencher l'appui long (2 secondes)
confirm_long_press_triggered = False  # Flag pour éviter de déclencher plusieurs fois

# Tenter la récupération de la famille de police sauvegardée
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
            path = os.path.join(APP_FOLDER, "assets", "fonts", "Pixel-UniCode.ttf")
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


def validate_resolution():
    """Valide la résolution de l'écran par rapport aux capacités de l'écran."""
    if pygame is None:
        return SCREEN_WIDTH, SCREEN_HEIGHT
    display_info = pygame.display.Info()
    if SCREEN_WIDTH > display_info.current_w or SCREEN_HEIGHT > display_info.current_h:
        logger.warning(f"Résolution {SCREEN_WIDTH}x{SCREEN_HEIGHT} dépasse les limites de l'écran")
        return display_info.current_w, display_info.current_h
    return SCREEN_WIDTH, SCREEN_HEIGHT
    
import pygame
import os
import logging

logger = logging.getLogger(__name__)

# Chemins de cache
cache_dir = os.getenv("RGSX_CACHE_DIR", "/userdata/roms/ports/RGSX/cache")
images_cache_dir = os.path.join(cache_dir, "images/systemes")
games_cache_dir = os.path.join(cache_dir, "games")
os.makedirs(images_cache_dir, exist_ok=True)
os.makedirs(games_cache_dir, exist_ok=True)
logger.debug(f"Dossiers de cache créés: {images_cache_dir}, {games_cache_dir}")

# Variables d'état
platforms = []
current_platform = 0
platform_names = {}  # {platform_id: platform_name}
games = []
current_game = 0
menu_state = "popup"
confirm_choice = False
images = {}  # Cache mémoire pour les images
scroll_offset = 0
visible_games = 15
popup_start_time = 0  # Initialisé à 0, sera mis à jour dans main.py
last_progress_update = 0
needs_redraw = True
transition_state = "idle"
transition_progress = 0.0
transition_duration = 18
current_y = {}
target_y = {}
last_platform = -1
games_count = {}
loading_games_count = {}
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
filtered_games = []  # Liste des jeux filtrés
search_mode = False  # Indique si le mode recherche est actif
search_query = ""  # Texte saisi par l'utilisateur
extension_confirm_selection = 0  # Sélection dans la popup d'avertissement d'extension (0=Non, 1=Oui)
pending_download = None  # Stocke les paramètres du téléchargement en attente (url, platform, game_name)

# Résolution de l'écran (sera mise à jour après init_display)
screen_width = 800
screen_height = 600

# Polices (déclarées mais non initialisées ici, seront définies dans main.py)
font = None
progress_font = None
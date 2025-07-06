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

# Résolution de l'écran
screen_width = 800
screen_height = 600

# Polices
font = None
progress_font = None
title_font = None
search_font = None
small_font = None
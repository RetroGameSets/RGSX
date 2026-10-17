import pygame # type: ignore
import shutil
import asyncio
import json
import re
import os
import datetime
import threading
import logging
import config
import catalog_sync
from config import REPEAT_DELAY, REPEAT_INTERVAL, REPEAT_ACTION_DEBOUNCE, CONTROLS_CONFIG_PATH, Game
from display import draw_validation_transition, pause_root_index, show_toast
from network import download_rom, download_from_1fichier, is_1fichier_url, request_cancel, cleanup_torrent_temp, stop_active_seeder
from utils import (
    load_games, clear_games_cache, check_extension_before_download, is_extension_supported,
    load_extensions_json, play_random_music, sanitize_filename,
    save_music_config, load_api_keys, _get_dest_folder_name,
    extract_zip, extract_rar, extract_7z, find_file_with_or_without_extension, find_matching_files, toggle_web_service_at_boot, check_web_service_status,
    restart_application, generate_support_zip, load_sources,
    ensure_download_provider_keys, missing_all_provider_keys, build_provider_paths_string,
    start_connection_status_check, get_clean_display_name, get_existing_history_matches, remember_history_local_match,
    clear_torrent_manifest_cache,
    request_torrent_manifest_refresh,
    move_files_to_directory, parse_torrent_download_url,
    _refresh_loading_feedback,
    parse_game_size_to_bytes,
    sort_games_list,
)
from history import load_history, clear_history, add_to_history, save_history, scan_roms_for_downloaded_games
from language import _, get_available_languages, set_language  
from rgsx_settings import (
    DISPLAY_GRID_LAYOUTS, get_allow_unknown_extensions, set_display_grid, get_font_family, set_font_family,
    get_show_unsupported_platforms, set_show_unsupported_platforms,
    set_allow_unknown_extensions, set_symlink_option, get_symlink_option,
    get_global_sort_option, set_global_sort_option,
    load_rgsx_settings, save_rgsx_settings
)
from accessibility import save_accessibility_settings
from pathlib import Path

logger = logging.getLogger(__name__)

# Extensions d'archives pour lesquelles on ignore l'avertissement d'extension non supportée
ARCHIVE_EXTENSIONS = {'.zip', '.7z', '.rar', '.tar', '.gz', '.xz', '.bz2'}

GLOBAL_SORT_OPTIONS = [
    ("name_asc", lambda: _("web_sort_name_asc") or "A-Z (Name)"),
    ("name_desc", lambda: _("web_sort_name_desc") or "Z-A (Name)"),
    ("size_asc", lambda: _("web_sort_size_asc") or "Size -+ (Small first)"),
    ("size_desc", lambda: _("web_sort_size_desc") or "Size +- (Large first)"),
    ("date_asc", lambda: _("web_sort_date_asc") or "Date -+ (Oldest first)"),
    ("date_desc", lambda: _("web_sort_date_desc") or "Date +- (Newest first)"),
]


def _notify_torrent_in_maintenance(game_name: str | None = None) -> None:
    # Fonction devenue inutile, ne fait plus rien
    pass


def _has_download_url(url, game_name: str | None = None) -> bool:
    if isinstance(url, str) and url.strip():
        return True

    config.needs_redraw = True
    return False


def _wrap_index(current_index: int, delta: int, item_count: int) -> int:
    if item_count <= 0:
        return 0
    return (current_index + delta) % item_count


def _sort_global_items(items: list[dict]) -> list[dict]:
    option = getattr(config, 'global_sort_option', 'name_asc') or 'name_asc'
    reverse = option in ('name_desc', 'size_desc', 'date_desc')

    if option.startswith('size_'):
        return sorted(
            items,
            key=lambda item: (
                int(item.get('size_bytes') or 0),
                str(item.get('display_name') or '').lower(),
                str(item.get('platform_label') or '').lower(),
            ),
            reverse=reverse,
        )

    if option.startswith('date_'):
        dated_items = [item for item in items if item.get('updated_at')]
        undated_items = [item for item in items if not item.get('updated_at')]
        dated_items.sort(
            key=lambda item: (
                str(item.get('updated_at') or ''),
                str(item.get('display_name') or '').lower(),
                str(item.get('platform_label') or '').lower(),
            ),
            reverse=reverse,
        )
        undated_items.sort(
            key=lambda item: (
                str(item.get('display_name') or '').lower(),
                str(item.get('platform_label') or '').lower(),
            )
        )
        return dated_items + undated_items

    return sorted(
        items,
        key=lambda item: (
            str(item.get('display_name') or '').lower(),
            str(item.get('platform_label') or '').lower(),
            int(item.get('size_bytes') or 0),
        ),
        reverse=reverse,
    )


def _get_global_sort_index(option: str | None = None) -> int:
    target = option or getattr(config, 'global_sort_option', 'name_asc')
    for index, (key, _) in enumerate(GLOBAL_SORT_OPTIONS):
        if key == target:
            return index
    return 0


def _sort_local_games(items: list[Game]) -> list[Game]:
    option = getattr(config, 'global_sort_option', 'name_asc')
    return sort_games_list(items, option)


def _apply_sorted_active_filters() -> list[Game]:
    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
        return _sort_local_games(config.game_filter_obj.apply_filters(config.games))
    return config.games


def refresh_catalog_from_database() -> tuple[int, int]:
    previous_platform = None
    if 0 <= getattr(config, "current_platform", -1) < len(config.platforms):
        previous_platform = config.platforms[config.current_platform]

    current_games = config.filtered_games if config.filter_active or config.search_mode else config.games
    previous_game_name = None
    if 0 <= getattr(config, "current_game", -1) < len(current_games):
        previous_game_name = current_games[config.current_game].name

    clear_games_cache()
    catalog_sync.sync_catalog(config.DB_PATH)
    sources = load_sources(allow_torrent_manifest_fetch=False)
    if not sources:
        raise RuntimeError("Le catalogue DB n'a renvoyé aucune plateforme")

    if not config.platforms:
        config.current_platform = 0
        config.current_game = 0
        config.games = []
        config.filtered_games = []
        config.scroll_offset = 0
        return len(sources), 0

    config.current_platform = (
        config.platforms.index(previous_platform)
        if previous_platform in config.platforms
        else 0
    )
    platform_name = config.platforms[config.current_platform]
    config.games = load_games(platform_name)

    if (config.search_mode or config.filter_active) and config.search_query:
        config.filtered_games = filter_games_by_search_query()
    elif hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
        config.filtered_games = _apply_sorted_active_filters()
    else:
        config.filtered_games = config.games

    visible_games = config.filtered_games if config.filter_active or config.search_mode else config.games
    config.current_game = next(
        (index for index, game in enumerate(visible_games) if game.name == previous_game_name),
        0,
    )
    config.scroll_offset = 0
    return len(sources), len(config.platforms)


def _get_advanced_filter_region_columns() -> int:
    """Retourne le nombre de colonnes réellement affichables dans le filtre avancé."""
    available_grid_width = max(180, getattr(config, 'screen_width', 0) - 40)
    item_spacing_x = 20

    if not getattr(config, 'font', None):
        return 2 if getattr(config, 'screen_width', 0) <= 720 else 3

    include_label = _("filter_region_include") if _ else "Include"
    exclude_label = _("filter_region_exclude") if _ else "Exclude"
    max_region_width = 0

    try:
        from game_filters import GameFilters

        for region in GameFilters.REGIONS:
            region_key = f"filter_region_{region.lower()}"
            region_label = _(region_key) if _ else region
            include_text = f"{region_label}: [V] {include_label}"
            exclude_text = f"{region_label}: [X] {exclude_label}"
            max_region_width = max(
                max_region_width,
                config.font.render(include_text, True, (255, 255, 255)).get_width() + 30,
                config.font.render(exclude_text, True, (255, 255, 255)).get_width() + 30,
            )
    except Exception:
        max_region_width = 220

    return min(3, max(1, (available_grid_width + item_spacing_x) // max(1, max_region_width + item_spacing_x)))


_platform_torrent_support_cache: dict[str, bool] = {}


def _is_arm_device() -> bool:
    architecture = str(getattr(config, 'SYSTEM_INFO', {}).get('architecture') or '').lower().strip()
    if not architecture:
        try:
            import platform as _platform
            architecture = (_platform.machine() or '').lower().strip()
        except Exception:
            architecture = ''
    return any(token in architecture for token in ('arm', 'aarch64', 'arm64', 'armv7', 'armv8'))


def _platform_has_torrents(platform_id: str) -> bool:
    cached = _platform_torrent_support_cache.get(platform_id)
    if cached is not None:
        return cached

    try:
        games = load_games(platform_id)
        has_torrents = any(
            parse_torrent_download_url(game.url) is not None
            for game in games
            if getattr(game, 'url', None)
        )
    except Exception as exc:
        logger.debug(f"Impossible de déterminer la présence de torrents pour {platform_id}: {exc}")
        has_torrents = False

    _platform_torrent_support_cache[platform_id] = has_torrents
    return has_torrents


def _warn_torrents_unavailable_on_arm(platform_label: str | None = None) -> None:
    message = "Les téléchargements torrent ne sont pas encore disponibles sur les appareils ARM pour le moment."
    if platform_label:
        message = f"{platform_label}\n{message}"
    try:
        show_toast(message, duration=5000)
    except Exception:
        pass
    try:
        config.popup_message = message
        config.popup_timer = 5000
    except Exception:
        pass
    config.needs_redraw = True


def _is_1fichier_platform(platform_id: str, platform_label: str) -> bool:
    markers = [str(marker or "").lower().replace(" ", "") for marker in getattr(config, "PREMIUM_HOST_MARKERS", [])]
    haystacks = [str(platform_id or ""), str(platform_label or "")]
    for text in haystacks:
        normalized = text.lower().replace(" ", "")
        if "1fichier" in normalized:
            return True
        if any(marker and marker in normalized for marker in markers):
            return True
    return False


def _warn_missing_api_key_for_1fichier_platform(platform_label: str | None = None) -> None:
    try:
        ensure_download_provider_keys(False)
    except Exception:
        pass

    try:
        no_api_keys = missing_all_provider_keys()
    except Exception:
        no_api_keys = not any([
            getattr(config, "API_KEY_1FICHIER", ""),
            getattr(config, "API_KEY_ALLDEBRID", ""),
            getattr(config, "API_KEY_DEBRIDLINK", ""),
            getattr(config, "API_KEY_REALDEBRID", ""),
        ])

    if not no_api_keys:
        return

    warning_line = _("platform_1fichier_no_api_warning") if _ else "No API key configured: this 1fichier source runs in free mode and may fail."
    if warning_line == "platform_1fichier_no_api_warning":
        warning_line = "No API key configured: this 1fichier source runs in free mode and may fail."
    advice_line = _("free_mode_premium_advice") if _ else "For unlimited, on-demand, full-speed downloads, you need a premium account or debrid service and must enter its API key in RGSX."
    if advice_line == "free_mode_premium_advice":
        advice_line = "For unlimited, on-demand, full-speed downloads, you need a premium account or debrid service and must enter its API key in RGSX."

    lines = [warning_line, advice_line]
    message = "\n".join(line for line in lines if line)
    if platform_label:
        message = f"{platform_label}\n{message}"

    try:
        show_toast(message, duration=6500)
    except Exception:
        pass
    try:
        config.popup_message = message
        config.popup_timer = 6500
    except Exception:
        pass
    config.needs_redraw = True
    logger.warning("Plateforme 1fichier ouverte sans clé API: affichage avertissement mode gratuit")


def _open_selected_platform(screen) -> bool:
    platform_groups = getattr(config, "platform_groups", [])
    if not platform_groups:
        platform_groups = [{"platforms": [name]} for name in config.platforms]
        config.platform_groups = platform_groups
    group_index = config.selected_platform
    if group_index < 0 or group_index >= len(platform_groups):
        return False

    group_platforms = platform_groups[group_index].get("platforms", [])
    if not group_platforms:
        return False
    if len(group_platforms) > 1:
        config.platform_source_group_index = group_index
        config.platform_source_selected = 0
        config.platform_source_scroll_offset = 0
        config.menu_state = "platform_source"
        config.needs_redraw = True
        return False
    config.platform_source_group_index = group_index
    return _open_platform_source(screen, 0)


def _open_platform_source(screen, source_index: int) -> bool:
    platform_groups = getattr(config, "platform_groups", [])
    group_index = getattr(config, "platform_source_group_index", config.selected_platform)
    if group_index < 0 or group_index >= len(platform_groups):
        return False
    group_platforms = platform_groups[group_index].get("platforms", [])
    if source_index < 0 or source_index >= len(group_platforms):
        return False

    platform_id = str(group_platforms[source_index])
    try:
        platform_index = config.platforms.index(platform_id)
    except ValueError:
        logger.error("Selected platform source is no longer available: %s", platform_id)
        config.menu_state = "platform"
        config.needs_redraw = True
        return False

    platform_label = _get_platform_label(platform_id)

    if _is_arm_device() and _platform_has_torrents(platform_id):
        logger.warning(f"Plateforme torrent bloquée sur ARM: {platform_id}")
        _warn_torrents_unavailable_on_arm(platform_label)
        return False

    if _is_1fichier_platform(platform_id, platform_label):
        _warn_missing_api_key_for_1fichier_platform(platform_label)

    config.current_platform = platform_index
    config.games = load_games(platform_id)

    # Apply saved filters automatically if any
    if config.game_filter_obj and config.game_filter_obj.is_active():
        config.filtered_games = _apply_sorted_active_filters()
        config.filter_active = True
    else:
        config.filtered_games = config.games
        config.filter_active = False

    config.current_game = 0
    config.scroll_offset = 0

    # Désactiver l'animation de transition en mode performance (light mode)
    from rgsx_settings import get_light_mode
    if not get_light_mode():
        draw_validation_transition(screen, config.current_platform)

    config.menu_state = "game"
    config.needs_redraw = True
    logger.debug(f"Navigation vers les jeux de {platform_id}")
    return True


def _is_windows_os() -> bool:
    return str(getattr(config, 'OPERATING_SYSTEM', '') or '').lower() == "windows" or os.name == 'nt'


def _is_windows_drive_root(path: str) -> bool:
    if not _is_windows_os() or not path:
        return False
    normalized = os.path.normpath(path)
    drive, tail = os.path.splitdrive(normalized)
    return bool(drive) and tail in ('\\', '/')


def _get_available_windows_drives() -> list[str]:
    drives = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if os.path.isdir(drive):
            drives.append(drive)
    return drives


def _load_folder_browser_items(path: str) -> list[str]:
    if _is_windows_os() and not path:
        return _get_available_windows_drives()

    target_path = path
    if not target_path:
        target_path = "/"

    items = [".."]
    try:
        for item in sorted(os.listdir(target_path)):
            full_path = os.path.join(target_path, item)
            if os.path.isdir(full_path):
                items.append(item)
    except Exception as e:
        logger.error(f"Erreur lecture dossier {target_path}: {e}")
        return [".."] if target_path else []
    return items


def _set_folder_browser_location(path: str | None, reset_selection: bool = True) -> None:
    if _is_windows_os():
        normalized_path = os.path.normpath(path) if path else ""
        if normalized_path in ('\\', '/'):
            normalized_path = ""
        if normalized_path and not os.path.isdir(normalized_path):
            normalized_path = ""
    else:
        normalized_path = path or "/"
        if not os.path.isdir(normalized_path):
            normalized_path = "/"

    config.folder_browser_path = normalized_path
    config.folder_browser_items = _load_folder_browser_items(normalized_path)

    if reset_selection:
        config.folder_browser_selection = 0
        config.folder_browser_scroll_offset = 0
    else:
        max_index = max(0, len(config.folder_browser_items) - 1)
        config.folder_browser_selection = max(0, min(config.folder_browser_selection, max_index))
        max_scroll = max(0, len(config.folder_browser_items) - max(1, int(getattr(config, 'folder_browser_visible_items', 10) or 10)))
        config.folder_browser_scroll_offset = max(0, min(config.folder_browser_scroll_offset, max_scroll))


def _build_filter_menu_entries(context: str) -> list[dict[str, str]]:
    global_search_label = 'Recherche globale' if (_ is None or _("global_search_title") == "global_search_title") else _("global_search_title").format("").replace(" : ", "").rstrip(': ')
    platform_search_label = 'Recherche sur cette plateforme' if (_ is None or _("platform_search_title") == "platform_search_title") else _("platform_search_title")
    advanced_filter_label = 'Filtrer' if (_ is None or _("filter_advanced") == "filter_advanced") else _("filter_advanced")
    sort_label = 'Trier' if (_ is None or _("web_sort") == "web_sort") else _("web_sort")
    back_label = 'Retour' if (_ is None or _("menu_back") == "menu_back") else _("menu_back")

    entries = []
    if context == 'game':
        entries.extend([
            {
                'key': 'platform_search',
                'label': platform_search_label,
            },
            {
                'key': 'global_sort',
                'label': sort_label,
            },
            {
                'key': 'global_search',
                'label': global_search_label,
            },
            {
                'key': 'global_filter',
                'label': advanced_filter_label,
            },
        ])
    else:
        entries.extend([
            {
                'key': 'global_search',
                'label': global_search_label,
            },
            {
                'key': 'global_filter',
                'label': advanced_filter_label,
            },
            {
                'key': 'global_sort',
                'label': sort_label,
            },
        ])

    entries.append({
        'key': 'back',
        'label': back_label,
    })
    return entries


def open_unified_filter_menu(source_state: str) -> None:
    context = 'game' if source_state == 'game' else 'global'
    config.filter_menu_context = context
    config.filter_menu_entries = _build_filter_menu_entries(context)
    config.filter_menu_return_state = validate_menu_state(source_state)
    config.selected_filter_choice = 0
    config.previous_menu_state = source_state
    config.menu_state = 'filter_menu_choice'
    config.needs_redraw = True
    logger.debug(f"Ouverture du menu filtre unifie depuis {source_state}")


# Variables globales pour la répétition
key_states = {}  # Dictionnaire pour suivre l'état des touches

# Liste des états valides
VALID_STATES = [
    "platform", "game", "confirm_exit",
    "extension_warning", "pause_menu", "controls_help", "history", "controls_mapping",
    "reload_games_data", "restart_popup", "error", "loading", "confirm_clear_history",
    "reset_settings_confirm",
    "language_select", "filter_platforms", "display_menu", "confirm_cancel_download",
    "gamelist_update_prompt", "platform_folder_config", "platform_source",
    # Nouveaux sous-menus hiérarchiques (refonte pause menu)
    "pause_controls_menu",      # sous-menu Controls (aide, remap)
    "pause_display_menu",       # sous-menu Display (layout, font size, unsupported, unknown ext, filter)
    "pause_display_layout_menu",# sous-menu Display > Layout (disposition avec visualisation)
    "pause_display_font_menu",  # sous-menu Display > Font (taille police + footer)
    "pause_games_menu",         # sous-menu Games (source mode, update/redownload cache)
    "pause_settings_menu",      # sous-menu Settings
    "pause_scrap_menu",         # sous-menu Scrap (ScreenScraper account, Media Manager)
    "pause_api_keys_status",    # sous-menu API Keys (affichage statut des clés)
    "pause_connection_status",  # sous-menu Connection status (statut accès sites)
    "media_manager",            # Settings > Media Manager (image download)
    "screenscraper_input",      # Scrap > ScreenScraper username/password
    # Nouveaux menus historique
    "history_game_options",     # menu options pour un jeu de l'historique
    "history_show_folder",      # afficher le dossier de téléchargement
    "game_info",                # ScreenScraper game details
    "history_error_details",    # détails de l'erreur
    "history_confirm_delete",   # confirmation suppression jeu
    "history_extract_archive",  # extraction d'archive
    "text_file_viewer",         # visualiseur de fichiers texte
    # Nouveaux menus filtrage avancé
    "filter_menu_choice",       # menu de choix entre recherche et filtrage avancé
    "filter_search",            # recherche par nom (existant, mais renommé)
    "filter_advanced",          # filtrage avancé par région, etc.
    "filter_priority_config",   # configuration priorité régions pour one-rom-per-game
    "global_sort_menu",         # menu de tri global
    "platform_search",          # recherche globale inter-plateformes
    "platform_folder_config",   # configuration du dossier personnalisé pour une plateforme
    "folder_browser",           # navigateur de dossiers intégré
    "folder_browser_new_folder", # création d'un nouveau dossier
]

def validate_menu_state(state):
    if not state:
        return "platform"
    if state not in VALID_STATES:
        logger.debug(f"État invalide {state}, retour à platform")
        return "platform"
    return state


def should_open_pause_menu(menu_state: str | None) -> bool:
    state = str(menu_state or "")
    return not state.startswith("pause_") and state not in {
        "controls_help",
        "controls_mapping",
        "history",
        "confirm_clear_history",
        "reload_games_data",
        "reset_settings_confirm",
        "screenscraper_input",
        "media_manager",
        "game_info",
    }


def load_controls_config(path=CONTROLS_CONFIG_PATH):
    """Charge la configuration des contrôles.
    Priorité:
    1) Fichier utilisateur dans SAVE_FOLDER (controls.json)
    2) Préréglage correspondant dans PRECONF_CONTROLS_PATH (sans copie)
    3) Configuration clavier par défaut
    """
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

    def _is_keyboard_only_config(data):
        if not isinstance(data, dict) or not data:
            return False
        for action_name, mapping in data.items():
            if action_name == "device":
                continue
            if not isinstance(mapping, dict):
                return False
            if mapping.get("type") != "key":
                return False
        return True
    
    try:
        # 1) Fichier utilisateur
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
            keyboard_mode = (not getattr(config, 'joystick', False)) or getattr(config, 'keyboard', False)
            if keyboard_mode and not _is_keyboard_only_config(data):
                logging.getLogger(__name__).info("Configuration utilisateur manette ignorée en mode clavier")
            else:
            # Compléter les actions manquantes, et sauve seulement si le fichier utilisateur existe
                changed = False
                for k, v in default_config.items():
                    if k not in data:
                        data[k] = v
                        changed = True
                if changed:
                    try:
                        os.makedirs(os.path.dirname(path), exist_ok=True)
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(data, f, indent=2)
                        logging.getLogger(__name__).debug(f"controls.json complété avec les actions manquantes: {path}")
                    except Exception as e:
                        logging.getLogger(__name__).warning(f"Impossible d'écrire les actions manquantes dans {path}: {e}")
                return data

        # 2) Préréglages sans copie si aucun fichier utilisateur
        try:
            # --- Auto-match par nom de périphérique détecté ---
            def _sanitize(s: str) -> str:
                s = (s or "").strip().lower()
                s = re.sub(r"[^a-z0-9]+", "_", s)
                s = re.sub(r"_+", "_", s).strip("_")
                return s

            def _extract_device_from_comment(val: str) -> str:
                try:
                    if not isinstance(val, str):
                        return ""
                    # Expect formats like "# Device: NAME" or just NAME
                    if "Device:" in val:
                        part = val.split("Device:", 1)[1]
                        return part.strip().lstrip('#').strip()
                    return val.strip().lstrip('#').strip()
                except Exception:
                    return ""

            device_name = getattr(config, 'controller_device_name', '') or ''
            if getattr(config, 'joystick', False) and device_name:
                target_norm = _sanitize(device_name)
                try:
                    for fname in os.listdir(config.PRECONF_CONTROLS_PATH):
                        if not fname.lower().endswith('.json'):
                            continue
                        src = os.path.join(config.PRECONF_CONTROLS_PATH, fname)
                        try:
                            with open(src, 'r', encoding='utf-8') as f:
                                preset = json.load(f)
                        except Exception:
                            continue
                        # Match by explicit device field
                        dev_field = preset.get('device') if isinstance(preset, dict) else None
                        if isinstance(dev_field, str) and _sanitize(dev_field) == target_norm:
                            logging.getLogger(__name__).info(f"Chargement préréglage (device) depuis le fichier: {fname}")
                            print(f"Chargement prereglage (device) depuis le fichier: {fname}")
                            return preset
                except Exception as e:
                    logging.getLogger(__name__).warning(f"Échec scan préréglages par device: {e}")

            # Fallback préréglage explicite clavier si pas de joystick
            if not getattr(config, 'joystick', False) or getattr(config, 'keyboard', False):
                src = os.path.join(config.PRECONF_CONTROLS_PATH, 'keyboard.json')
                if os.path.exists(src):
                    with open(src, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if isinstance(data, dict) and data:
                            logging.getLogger(__name__).info("Chargement des contrôles préréglés: keyboard.json")
                            return data
        except Exception as e:
            logging.getLogger(__name__).warning(f"Échec du chargement des contrôles préréglés: {e}")

        # 3) Fallback: si joystick présent mais aucun préréglage trouvé, retourner {} pour déclencher le remap
        if getattr(config, 'joystick', False):
            logging.getLogger(__name__).info("Aucun préréglage trouvé pour le joystick connecté, ouverture du remap")
            return {}
        # Sinon, fallback clavier par défaut
        logging.getLogger(__name__).info("Aucun fichier utilisateur ou préréglage trouvé, utilisation des contrôles clavier par défaut")
        return default_config.copy()
    
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
        threshold = 0.5
        # Pour les triggers Xbox (axes 4 et 5), la position de repos est -1.0
        # Il faut inverser la détection : direction -1 = trigger appuyé (vers +1.0)
        if axis in [4, 5]:
            # Triggers Xbox: repos à -1.0, appuyé vers +1.0
            # On inverse la direction configurée
            if direction == -1:
                # Direction -1 configurée = détecter quand trigger appuyé (valeur positive)
                return event.axis == axis and event.value > threshold
            else:
                # Direction +1 configurée = détecter aussi quand trigger appuyé
                return event.axis == axis and event.value > threshold
        else:
            # Autres axes: logique normale
            return event.axis == axis and abs(event.value) > threshold and (1 if event.value > 0 else -1) == direction
    elif input_type == "hat" and event.type == pygame.JOYHATMOTION:
        hat_value = mapping.get("value")
        if isinstance(hat_value, list):
            hat_value = tuple(hat_value)
        return event.value == hat_value
    elif input_type == "mouse" and event.type == pygame.MOUSEBUTTONDOWN:
        return event.button == mapping.get("button")
    
    # Fallback clavier pour dépannage (fonctionne toujours même avec manette configurée)
    if event.type == pygame.KEYDOWN:
        keyboard_fallback = {
            "up": pygame.K_UP,
            "down": pygame.K_DOWN,
            "left": pygame.K_LEFT,
            "right": pygame.K_RIGHT,
            "confirm": pygame.K_RETURN,
            "cancel": pygame.K_ESCAPE,
            "start": pygame.K_RALT,
            "filter": pygame.K_f,
            "history": pygame.K_h,
            "clear_history": pygame.K_DELETE,
            "delete": pygame.K_d,
            "space": pygame.K_SPACE,
            "page_up": pygame.K_PAGEUP,
            "page_down": pygame.K_PAGEDOWN,
        }
        if action_name in keyboard_fallback:
            return event.key == keyboard_fallback[action_name]
    
    return False


def is_global_search_input_matched(event, action_name):
    """Fallback robuste pour la recherche globale, independant du preset courant."""
    if is_input_matched(event, action_name):
        return True

    if event.type == pygame.KEYDOWN:
        keyboard_fallback = {
            "up": pygame.K_UP,
            "down": pygame.K_DOWN,
            "left": pygame.K_LEFT,
            "right": pygame.K_RIGHT,
            "confirm": pygame.K_RETURN,
            "cancel": pygame.K_ESCAPE,
            "filter": pygame.K_f,
            "delete": pygame.K_BACKSPACE,
            "space": pygame.K_SPACE,
            "page_up": pygame.K_PAGEUP,
            "page_down": pygame.K_PAGEDOWN,
        }
        if action_name in keyboard_fallback and event.key == keyboard_fallback[action_name]:
            return True

    if event.type == pygame.JOYBUTTONDOWN:
        common_button_fallback = {
            "confirm": {0},
            "cancel": {1},
            "filter": {6},
            "start": {7},
            "delete": {2},
            "space": {5},
            "page_up": {4},
            "page_down": {5},
        }
        if action_name in common_button_fallback and event.button in common_button_fallback[action_name]:
            return True

    if event.type == pygame.JOYHATMOTION:
        hat_fallback = {
            "up": (0, 1),
            "down": (0, -1),
            "left": (-1, 0),
            "right": (1, 0),
        }
        if action_name in hat_fallback and event.value == hat_fallback[action_name]:
            return True

    if event.type == pygame.JOYAXISMOTION:
        axis_fallback = {
            "left": (0, -1),
            "right": (0, 1),
            "up": (1, -1),
            "down": (1, 1),
        }
        if action_name in axis_fallback:
            axis_id, direction = axis_fallback[action_name]
            if event.axis == axis_id and abs(event.value) > 0.5 and (1 if event.value > 0 else -1) == direction:
                return True

    return False

def _launch_next_queued_download(force: bool = False):
    """Lance le(s) prochain(s) téléchargement(s) de la queue selon les slots disponibles.
    Si force=True, ignore la limite (Force Download depuis l'UI).
    Peut être appelée plusieurs fois pour remplir tous les slots libres.
    """
    max_dl = getattr(config, 'max_simultaneous_downloads', 5)
    active = getattr(config, 'active_download_count', 0)
    if not force and active >= max_dl:
        return
    if not config.download_queue:
        return

    queue_item = config.download_queue.pop(0)
    config.active_download_count = active + 1
    config.download_active = True

    url = queue_item['url']
    platform = queue_item['platform']
    game_name = queue_item['game_name']
    is_zip_non_supported = queue_item['is_zip_non_supported']
    is_1fichier = queue_item['is_1fichier']
    task_id = queue_item['task_id']

    # Mettre à jour le statut dans l'historique: queued -> Downloading
    for entry in config.history:
        if entry.get('task_id') == task_id and entry.get('status') == 'Queued':
            entry['status'] = 'Downloading'
            entry['message'] = _("download_in_progress")
            save_history(config.history)
            break

    logger.info(f"📋 Lancement téléchargement (slot {config.active_download_count}/{max_dl}): {game_name} (task_id={task_id})")

    # Lancer le téléchargement de manière asynchrone avec callback
    try:
        if is_1fichier:
            task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
        else:
            task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))
        _register_download_task(task_id, task, url, game_name, platform)
        
    except Exception as e:
        logger.error(f"Erreur lancement queue download: {e}")
        config.active_download_count = max(0, getattr(config, 'active_download_count', 1) - 1)
        config.download_active = config.active_download_count > 0
        # Mettre à jour l'historique en erreur
        for entry in config.history:
            if entry.get('task_id') == task_id:
                entry['status'] = 'Erreur'
                entry['message'] = str(e)
                save_history(config.history)
                break
        # Relancer le suivant
        _launch_next_queued_download()


def _register_download_task(task_id: str, task, url: str, game_name: str, platform: str, increment_slot: bool = False):
    """Enregistre une tâche de téléchargement et branche la relance de queue à la fin."""
    if increment_slot:
        config.active_download_count = getattr(config, 'active_download_count', 0) + 1
        config.download_active = True

    config.download_tasks[task_id] = (task, url, game_name, platform)

    def on_task_done(t):
        try:
            t.result()
        except asyncio.CancelledError:
            logger.info(f"Tâche annulée pour {game_name} (task_id={task_id})")
        except Exception as e:
            logger.error(f"Erreur tâche download {game_name}: {e}")
        finally:
            # Le décrément des slots est géré dans network.notify_download_finished().
            config.download_active = getattr(config, 'active_download_count', 0) > 0
            _launch_next_queued_download()

    task.add_done_callback(on_task_done)


def _queue_download(url: str, platform: str, game_name: str, is_zip_non_supported: bool, display_name: str | None = None) -> str:
    """Ajoute un téléchargement à la file d'attente et l'historique."""
    task_id = str(pygame.time.get_ticks())
    queue_item = {
        'url': url,
        'platform': platform,
        'game_name': game_name,
        'is_zip_non_supported': is_zip_non_supported,
        'is_1fichier': is_1fichier_url(url),
        'task_id': task_id,
        'status': 'Queued'
    }
    config.download_queue.append(queue_item)

    shown_name = display_name or get_clean_display_name(game_name, platform)
    config.history.append({
        'platform': platform,
        'game_name': game_name,
        'display_name': shown_name,
        'status': 'Queued',
        'url': url,
        'progress': 0,
        'message': _("download_queued"),
        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'downloaded_size': 0,
        'total_size': 0,
        'task_id': task_id
    })
    save_history(config.history)
    show_toast(f"{shown_name}\n{_('download_queued')}")
    config.needs_redraw = True
    logger.info(f"{game_name} ajouté à la file d'attente. Queue size: {len(config.download_queue)}")
    return task_id


def start_or_queue_download(url: str, platform: str, game_name: str, is_zip_non_supported: bool, display_name: str | None = None, force_start: bool = False) -> tuple[str, str]:
    """Démarre un téléchargement si un slot est libre, sinon le place en queue."""
    max_dl = getattr(config, 'max_simultaneous_downloads', 5)
    active = getattr(config, 'active_download_count', 0)

    if not force_start and active >= max_dl:
        task_id = _queue_download(url, platform, game_name, is_zip_non_supported, display_name)
        _launch_next_queued_download()
        return ("queued", task_id)

    if is_1fichier_url(url):
        ensure_download_provider_keys(False)
        if missing_all_provider_keys():
            logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
        task_id = str(pygame.time.get_ticks())
        task = asyncio.create_task(download_from_1fichier(url, platform, game_name, is_zip_non_supported, task_id))
    else:
        task_id = str(pygame.time.get_ticks())
        task = asyncio.create_task(download_rom(url, platform, game_name, is_zip_non_supported, task_id))

    _register_download_task(task_id, task, url, game_name, platform, increment_slot=True)
    shown_name = display_name or get_clean_display_name(game_name, platform)
    show_toast(f"{_('download_started')}: {shown_name}")
    config.needs_redraw = True
    logger.info(f"Téléchargement démarré: {game_name} pour {platform}, task_id={task_id}")
    return ("started", task_id)

def filter_games_by_search_query() -> list[Game]:
    base_games = config.games
    if config.game_filter_obj and config.game_filter_obj.is_active():
        base_games = config.game_filter_obj.apply_filters(config.games)

    filtered_games = []
    query = _normalize_search_text(config.search_query)
    for game in base_games:
        game_name = game.display_name
        if _search_text_matches(query, game_name):
            filtered_games.append(game)

    return _sort_local_games(filtered_games)


SEARCH_TEXT_EXTRA_CHARS = {'.', '_', '-', ','}


def _normalize_search_text(text: str | None) -> str:
    value = str(text or "").lower()
    value = re.sub(r"[._\-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _compact_search_text(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_search_text(text))


def _search_text_matches(normalized_query: str, candidate_text: str | None) -> bool:
    if not normalized_query:
        return True

    normalized_candidate = _normalize_search_text(candidate_text)
    if normalized_query in normalized_candidate:
        return True

    compact_query = _compact_search_text(normalized_query)
    compact_candidate = _compact_search_text(candidate_text)
    return bool(compact_query) and compact_query in compact_candidate


def _global_search_item_matches(normalized_query: str, compact_query: str, item: dict) -> bool:
    if not normalized_query:
        return True

    candidate_text = item.get("search_name") or _normalize_search_text(item.get("display_name", ""))
    if normalized_query in candidate_text:
        return True

    compact_candidate = item.get("compact_search_name") or _compact_search_text(item.get("display_name", ""))
    return bool(compact_query) and compact_query in compact_candidate


def _get_search_input_char(event) -> str | None:
    if event.type != pygame.KEYDOWN:
        return None

    char = getattr(event, 'unicode', '') or ''
    if len(char) != 1:
        return None

    if char.isalnum() or char == ' ' or char in SEARCH_TEXT_EXTRA_CHARS:
        return char
    return None


GLOBAL_SEARCH_KEYBOARD_LAYOUT = [
    ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
    ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
    ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
    ['W', 'X', 'C', 'V', 'B', 'N', '.', '_', '-', ',']
]


def _save_screenscraper_account():
    """Save both ScreenScraper credentials and check the account in the background."""
    import screenscraper
    username = str(getattr(config, "ss_input_username", "")).strip()
    password = str(getattr(config, "ss_input_password", ""))
    try:
        screenscraper.save_account(username, password)
    except Exception as exc:
        logger.error(f"Could not save ScreenScraper account: {exc}")
        config.popup_message = _("screenscraper_save_error")
        config.popup_timer = 4000
        return
    if not (username and password):
        return

    def check_login():
        try:
            remaining, max_per_day = screenscraper.get_user_info() or ("?", "?")
            config.popup_message = _("screenscraper_login_ok").format(remaining, max_per_day)
        except screenscraper.ScreenScraperError as exc:
            logger.warning(f"ScreenScraper login check failed: {exc.kind} ({exc})")
            messages = {
                "account_required": "screenscraper_account_required",
                "auth": "screenscraper_login_failed",
                "config": "screenscraper_dev_credentials_missing",
                "quota": "media_quota_exhausted",
                "rate_limited": "screenscraper_rate_limited",
            }
            config.popup_message = _(messages[exc.kind]) if exc.kind in messages else _("media_error").format(exc.kind)
        config.popup_timer = 4000
        config.needs_redraw = True

    threading.Thread(target=check_login, daemon=True).start()


def _get_platform_id(platform) -> str:
    return platform.get("name") if isinstance(platform, dict) else str(platform)


def _get_platform_label(platform_id: str) -> str:
    return config.platform_names.get(platform_id, platform_id)


def _build_global_search_loading_title() -> str:
    fallback = "Loading..."
    if _ is None:
        return fallback
    try:
        text = _("global_search_title").format("").replace(" : ", "").rstrip(': ')
    except Exception:
        text = ""
    return text or fallback


def build_global_search_index() -> list[dict]:
    indexed_games = []
    total_platforms = max(1, len(config.platforms))
    for platform_index, platform in enumerate(config.platforms):
        platform_id = _get_platform_id(platform)
        platform_label = _get_platform_label(platform_id)
        _refresh_loading_feedback(
            current_system=_build_global_search_loading_title(),
            progress=((platform_index / total_platforms) * 100.0),
            detail_lines=[
                _("loading_platform_counter").format(platform_index + 1, total_platforms) if _ else f"Platform {platform_index + 1}/{total_platforms}",
                _("loading_platform_name").format(platform_label) if _ else f"Platform: {platform_label}",
                _("loading_read_games_resolve_sources") if _ else "Reading games and resolving sources...",
            ],
            force=True,
        )
        for game in load_games(platform_id):
            display_name = game.display_name or Path(game.name).stem
            indexed_games.append({
                "platform_id": platform_id,
                "platform_label": platform_label,
                "platform_index": platform_index,
                "game_name": game.name,
                "display_name": display_name,
                "search_name": _normalize_search_text(display_name),
                "compact_search_name": _compact_search_text(display_name),
                "url": game.url,
                "size": game.size,
                "size_bytes": parse_game_size_to_bytes(game.size),
                "updated_at": game.updated_at,
                "game_obj": game,
            })

    _refresh_loading_feedback(
        current_system=_build_global_search_loading_title(),
        progress=100.0,
        detail_lines=[
            _("loading_platform_counter").format(total_platforms, total_platforms) if _ else f"Platform {total_platforms}/{total_platforms}",
        ],
        force=True,
    )

    return _sort_global_items(indexed_games)


def _ensure_global_search_index(operation_title: str | None = None) -> None:
    index_signature = tuple(config.platforms)
    if getattr(config, 'global_search_index', None) and getattr(config, 'global_search_index_signature', None) == index_signature:
        return

    previous_menu_state = getattr(config, 'menu_state', 'platform')
    previous_loading_system = getattr(config, 'current_loading_system', '')
    previous_loading_progress = getattr(config, 'loading_progress', 0.0)
    previous_loading_detail_lines = list(getattr(config, 'loading_detail_lines', []) or [])

    config.menu_state = "loading"
    config.current_loading_system = operation_title or _build_global_search_loading_title()
    config.loading_progress = 0.0
    config.loading_detail_lines = [config.current_loading_system]
    config.needs_redraw = True
    _refresh_loading_feedback(force=True)

    try:
        config.global_search_index = build_global_search_index()
        config.global_search_index_signature = index_signature
    finally:
        config.menu_state = previous_menu_state
        config.current_loading_system = previous_loading_system
        config.loading_progress = previous_loading_progress
        config.loading_detail_lines = previous_loading_detail_lines
        config.needs_redraw = True


def _get_global_search_source_items() -> tuple[list[dict], tuple]:
    items = getattr(config, 'global_search_index', None)
    if items is None:
        items = []
    filter_obj = getattr(config, 'game_filter_obj', None)
    filter_signature = None
    filter_active = bool(filter_obj and filter_obj.is_active())
    if filter_active:
        filter_signature = (
            tuple(sorted(
                (str(region), str(state))
                for region, state in (getattr(filter_obj, 'region_filters', {}) or {}).items()
            )),
            bool(getattr(filter_obj, 'hide_non_release', False)),
            bool(getattr(filter_obj, 'one_rom_per_game', False)),
            tuple(str(region) for region in (getattr(filter_obj, 'region_priority', ()) or ())),
        )

    signature = (
        id(items),
        getattr(config, 'global_sort_option', 'name_asc'),
        filter_signature,
    )
    if getattr(config, 'global_search_source_signature', None) != signature:
        source_items = list(items)
        if filter_active:
            item_by_game = {
                id(item.get('game_obj')): item
                for item in source_items
                if item.get('game_obj') is not None
            }
            filtered_games = filter_obj.apply_filters(
                [item.get('game_obj') for item in source_items if item.get('game_obj') is not None]
            )
            source_items = [
                item_by_game[id(game)]
                for game in filtered_games
                if id(game) in item_by_game
            ]

        config.global_search_source_items = _sort_global_items(source_items)
        config.global_search_source_signature = signature
        config.global_search_applied_query = ""
        config.global_search_applied_signature = None

    return config.global_search_source_items, signature


def refresh_global_search_results(reset_selection: bool = True) -> None:
    query = _normalize_search_text(config.global_search_query)
    source_items, source_signature = _get_global_search_source_items()
    previous_query = getattr(config, 'global_search_applied_query', "")
    previous_signature = getattr(config, 'global_search_applied_signature', None)
    if query and previous_query and source_signature == previous_signature and query.startswith(previous_query):
        items = config.global_search_results
    else:
        items = source_items

    if query:
        compact_query = _compact_search_text(query)
        items = [
            item for item in items
            if _global_search_item_matches(query, compact_query, item)
        ]
    elif not getattr(config, 'global_search_allow_empty', False):
        items = []

    config.global_search_results = items
    config.global_search_applied_query = query
    config.global_search_applied_signature = source_signature

    if reset_selection:
        config.global_search_selected = 0
        config.global_search_scroll_offset = 0
    else:
        max_index = max(0, len(config.global_search_results) - 1)
        config.global_search_selected = max(0, min(config.global_search_selected, max_index))
        config.global_search_scroll_offset = max(0, min(config.global_search_scroll_offset, config.global_search_selected))


def enter_global_search() -> None:
    _ensure_global_search_index(_build_global_search_loading_title())
    config.global_search_query = ""
    config.global_search_results = []
    config.global_search_applied_query = ""
    config.global_search_applied_signature = None
    config.global_search_selected = 0
    config.global_search_scroll_offset = 0
    config.global_search_editing = True
    config.global_search_allow_empty = False
    config.global_search_title_override = _("global_search_title").format("").replace(" : ", "").rstrip(': ') if _ else 'Recherche globale'
    config.selected_key = (0, 0)
    config.menu_state = "platform_search"
    config.needs_redraw = True
    logger.debug("Entree en recherche globale inter-plateformes")


def enter_global_filtered_results() -> None:
    _ensure_global_search_index(_("filter_advanced") if _ else "Loading...")
    config.global_search_query = ""
    config.global_search_selected = 0
    config.global_search_scroll_offset = 0
    config.global_search_editing = False
    config.global_search_allow_empty = True
    config.global_search_title_override = _("filter_advanced") if _ else 'Filtrer'
    refresh_global_search_results(reset_selection=True)
    config.menu_state = "platform_search"
    config.needs_redraw = True
    logger.debug(f"Affichage des resultats globaux filtres: {len(config.global_search_results)}")


def enter_global_sorted_results() -> None:
    _ensure_global_search_index(_("web_sort") if _ else "Loading...")
    config.global_search_query = ""
    config.global_search_selected = 0
    config.global_search_scroll_offset = 0
    config.global_search_editing = False
    config.global_search_allow_empty = True
    config.global_search_title_override = _("web_sort") if _ else 'Trier'
    refresh_global_search_results(reset_selection=True)
    config.menu_state = "platform_search"
    config.needs_redraw = True
    logger.debug(f"Affichage des resultats globaux tries ({config.global_sort_option}): {len(config.global_search_results)}")


def exit_global_search() -> None:
    config.global_search_query = ""
    config.global_search_results = []
    config.global_search_applied_query = ""
    config.global_search_applied_signature = None
    config.global_search_selected = 0
    config.global_search_scroll_offset = 0
    config.global_search_editing = False
    config.global_search_allow_empty = False
    config.global_search_title_override = ""
    config.selected_key = (0, 0)
    config.menu_state = validate_menu_state(getattr(config, 'global_search_return_state', None) or getattr(config, 'previous_menu_state', None))
    config.needs_redraw = True


def open_global_search_result(screen) -> None:
    if not config.global_search_results:
        return

    result = config.global_search_results[config.global_search_selected]
    platform_index = result.get("platform_index", 0)
    if platform_index < 0 or platform_index >= len(config.platforms):
        return

    platform_id = result["platform_id"]
    config.current_platform = platform_index
    config.selected_platform = getattr(config, "platform_group_index", {}).get(
        platform_id,
        platform_index,
    )
    config.current_page = config.selected_platform // max(1, config.GRID_COLS * config.GRID_ROWS)

    config.games = load_games(platform_id)
    config.filtered_games = config.games
    config.search_mode = False
    config.search_query = ""
    config.filter_active = False

    target_name = result["game_name"]
    target_display_name = result["display_name"]
    target_index = 0
    for index, game in enumerate(config.games):
        if game.name == target_name:
            target_index = index
            break
        if game.display_name == target_display_name:
            target_index = index

    config.current_game = target_index
    config.scroll_offset = 0
    config.global_search_editing = False

    from rgsx_settings import get_light_mode
    if not get_light_mode():
        draw_validation_transition(screen, config.current_platform)

    config.menu_state = "game"
    config.needs_redraw = True
    logger.debug(f"Ouverture du resultat global {target_display_name} sur {platform_id}")


def trigger_global_search_download(queue_only: bool = False) -> None:
    if not config.global_search_results:
        return

    result = config.global_search_results[config.global_search_selected]
    url = result.get("url")
    platform = result.get("platform_id")
    game_name = result.get("game_name")
    display_name = result.get("display_name") or get_clean_display_name(game_name, platform)

    if not platform or not game_name:
        logger.error(f"Resultat de recherche globale invalide: {result}")
        return
    if not _has_download_url(url, game_name):
        return

    pending_download = check_extension_before_download(url, platform, game_name)
    if not pending_download:
        logger.error(f"config.pending_download est None pour {game_name}")
        config.needs_redraw = True
        return

    is_supported = is_extension_supported(
        sanitize_filename(game_name),
        platform,
        load_extensions_json()
    )
    zip_ok = bool(pending_download[3])
    allow_unknown = get_allow_unknown_extensions()

    if (not is_supported and not zip_ok) and not allow_unknown:
        config.pending_download = pending_download
        config.pending_download_is_queue = queue_only
        config.previous_menu_state = config.menu_state
        config.menu_state = "extension_warning"
        config.extension_confirm_selection = 0
        config.needs_redraw = True
        logger.debug(f"Extension non supportee, passage a extension_warning pour {game_name}")
        return

    if queue_only:
        _queue_download(url, platform, game_name, pending_download[3], display_name)
        _launch_next_queued_download()
        return

    start_or_queue_download(url, platform, game_name, pending_download[3], display_name)

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
        if is_input_matched(event, "start") and should_open_pause_menu(config.menu_state):
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
                
        elif config.menu_state == "platform_source":
            groups = getattr(config, "platform_groups", [])
            group_index = getattr(config, "platform_source_group_index", -1)
            group_platforms = (
                groups[group_index].get("platforms", [])
                if 0 <= group_index < len(groups)
                else []
            )
            if is_input_matched(event, "up") and group_platforms:
                config.platform_source_selected = max(0, config.platform_source_selected - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "down") and group_platforms:
                config.platform_source_selected = min(
                    len(group_platforms) - 1,
                    config.platform_source_selected + 1,
                )
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                _open_platform_source(screen, config.platform_source_selected)
            elif is_input_matched(event, "cancel"):
                config.menu_state = "platform"
                config.needs_redraw = True

        #Plateformes
        elif config.menu_state == "platform":
            platform_count = len(getattr(config, "platform_groups", []) or config.platforms)
            systems_per_page = config.GRID_COLS * config.GRID_ROWS
            max_index = min(systems_per_page, platform_count - config.current_page * systems_per_page) - 1
            current_grid_index = config.selected_platform - config.current_page * systems_per_page
            row = current_grid_index // config.GRID_COLS
            col = current_grid_index % config.GRID_COLS
            
            # Espace réservé pour des fonctions helper si nécessaire

            if is_input_matched(event, "down"):
                # Navigation vers le bas avec gestion des limites de page
                if current_grid_index + config.GRID_COLS <= max_index:
                    # Déplacement normal vers le bas
                    config.selected_platform += config.GRID_COLS
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif (config.current_page + 1) * systems_per_page < platform_count:
                    # Passage à la page suivante si on est en bas de la grille
                    config.current_page += 1
                    new_row = 0  # Première ligne de la nouvelle page
                    config.selected_platform = config.current_page * systems_per_page + new_row * config.GRID_COLS + col
                    if config.selected_platform >= platform_count:
                        config.selected_platform = platform_count - 1
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "up"):
                # Navigation vers le haut avec gestion des limites de page
                if current_grid_index - config.GRID_COLS >= 0:
                    # Déplacement normal vers le haut
                    config.selected_platform -= config.GRID_COLS
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif config.current_page > 0:
                    # Passage à la page précédente si on est en haut de la grille
                    config.current_page -= 1
                    new_row = config.GRID_ROWS - 1  # Dernière ligne de la page précédente
                    config.selected_platform = config.current_page * systems_per_page + new_row * config.GRID_COLS + col
                    if config.selected_platform >= platform_count:
                        config.selected_platform = platform_count - 1
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
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS + (config.GRID_COLS - 1)
                    if config.selected_platform >= platform_count:
                        config.selected_platform = platform_count - 1
                    update_key_state("left", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "right"):
                if col < config.GRID_COLS - 1 and current_grid_index < max_index:
                    # Déplacement normal vers la droite
                    config.selected_platform += 1
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                elif (config.current_page + 1) * systems_per_page < platform_count:
                    # Passage à la page suivante si on est à la dernière colonne
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS
                    if config.selected_platform >= platform_count:
                        config.selected_platform = platform_count - 1
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
            elif is_input_matched(event, "page_down"):
                # Navigation rapide vers la page suivante
                if (config.current_page + 1) * systems_per_page < platform_count:
                    config.current_page += 1
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS + col
                    if config.selected_platform >= platform_count:
                        config.selected_platform = platform_count - 1
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
                    config.selected_platform = config.current_page * systems_per_page + row * config.GRID_COLS + col
                    if config.selected_platform >= platform_count:
                        config.selected_platform = platform_count - 1
                    # Réinitialiser la répétition pour éviter des comportements inattendus
                    config.repeat_action = None
                    config.repeat_key = None
                    config.repeat_start_time = 0
                    config.repeat_last_action = current_time
                    config.needs_redraw = True
            elif is_input_matched(event, "history"):
                # Capturer l'origine si on vient directement des plateformes
                config.history_origin = "platform"
                config.menu_state = "history"
                config.needs_redraw = True
                logger.debug("Ouverture history depuis platform")
            elif is_input_matched(event, "filter"):
                open_unified_filter_menu("platform")
            elif is_input_matched(event, "confirm"):
                # Démarrer le chronomètre pour l'appui long - ne pas exécuter immédiatement
                # L'action sera exécutée au relâchement si appui court, ou config dossier si appui long
                if not hasattr(config, 'platform_confirm_press_start_time'):
                    config.platform_confirm_press_start_time = 0
                if not hasattr(config, 'platform_confirm_long_press_triggered'):
                    config.platform_confirm_long_press_triggered = False
                
                config.platform_confirm_press_start_time = current_time
                config.platform_confirm_long_press_triggered = False
                config.needs_redraw = True
                # Note: la navigation vers les jeux sera gérée au BUTTONUP/KEYUP si appui court
            elif is_input_matched(event, "cancel"):
                # Capturer l'origine (plateformes) pour un retour correct si l'utilisateur choisit "Non"
                config.confirm_exit_origin = "platform"
                config.menu_state = "confirm_exit"
                config.confirm_selection = 0
                config.needs_redraw = True

        elif config.menu_state == "platform_search":
            direct_input_char = _get_search_input_char(event)
            if direct_input_char is not None and getattr(config, 'global_search_editing', False):
                config.global_search_query += direct_input_char
                refresh_global_search_results()
                config.needs_redraw = True
            elif getattr(config, 'joystick', False) and getattr(config, 'global_search_editing', False):
                row, col = config.selected_key
                max_row = len(GLOBAL_SEARCH_KEYBOARD_LAYOUT) - 1
                max_col = len(GLOBAL_SEARCH_KEYBOARD_LAYOUT[row]) - 1
                if is_global_search_input_matched(event, "up"):
                    target_row = max_row if row == 0 else row - 1
                    config.selected_key = (target_row, min(col, len(GLOBAL_SEARCH_KEYBOARD_LAYOUT[target_row]) - 1))
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "down"):
                    target_row = 0 if row == max_row else row + 1
                    config.selected_key = (target_row, min(col, len(GLOBAL_SEARCH_KEYBOARD_LAYOUT[target_row]) - 1))
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "left"):
                    if col == 0:
                        col = max_col + 1
                    if col > 0:
                        config.selected_key = (row, col - 1)
                        config.repeat_action = "left"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_global_search_input_matched(event, "right"):
                    if col == max_col:
                        col = -1
                    if col < max_col:
                        config.selected_key = (row, col + 1)
                        config.repeat_action = "right"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_global_search_input_matched(event, "confirm"):
                    config.global_search_query += GLOBAL_SEARCH_KEYBOARD_LAYOUT[row][col]
                    refresh_global_search_results()
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "delete"):
                    if config.global_search_query:
                        config.global_search_query = config.global_search_query[:-1]
                        refresh_global_search_results()
                        config.needs_redraw = True
                elif is_global_search_input_matched(event, "space"):
                    config.global_search_query += " "
                    refresh_global_search_results()
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "filter"):
                    config.global_search_editing = False
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "cancel"):
                    exit_global_search()
            elif not getattr(config, 'joystick', False) and getattr(config, 'global_search_editing', False):
                if is_global_search_input_matched(event, "confirm"):
                    config.global_search_editing = False
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "delete"):
                    if config.global_search_query:
                        config.global_search_query = config.global_search_query[:-1]
                        refresh_global_search_results()
                        config.needs_redraw = True
                elif is_global_search_input_matched(event, "cancel"):
                    exit_global_search()
            else:
                results = config.global_search_results
                if is_global_search_input_matched(event, "up"):
                    if config.global_search_selected > 0:
                        config.global_search_selected -= 1
                        update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else event.value)
                        config.needs_redraw = True
                elif is_global_search_input_matched(event, "down"):
                    if config.global_search_selected < len(results) - 1:
                        config.global_search_selected += 1
                        update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else event.value)
                        config.needs_redraw = True
                elif is_global_search_input_matched(event, "page_up") or is_global_search_input_matched(event, "left"):
                    config.global_search_selected = max(0, config.global_search_selected - 10)
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "page_down") or is_global_search_input_matched(event, "right"):
                    config.global_search_selected = min(max(0, len(results) - 1), config.global_search_selected + 10)
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "confirm"):
                    trigger_global_search_download(queue_only=False)
                elif is_global_search_input_matched(event, "clear_history"):
                    trigger_global_search_download(queue_only=True)
                elif is_global_search_input_matched(event, "filter"):
                    config.global_search_editing = True
                    config.needs_redraw = True
                elif is_global_search_input_matched(event, "cancel"):
                    exit_global_search()
                elif not getattr(config, 'joystick', False) and event.type == pygame.KEYDOWN:
                    if is_global_search_input_matched(event, "delete"):
                        if config.global_search_query:
                            config.global_search_query = config.global_search_query[:-1]
                            refresh_global_search_results()
                            config.needs_redraw = True

                if config.global_search_results:
                    config.global_search_selected = max(0, min(config.global_search_selected, len(config.global_search_results) - 1))
                else:
                    config.global_search_selected = 0

        # Jeux
        elif config.menu_state == "game":
            games: list[Game] = config.filtered_games if config.filter_active or config.search_mode else config.games
            if config.search_mode and getattr(config, 'joystick', False):
                direct_input_char = _get_search_input_char(event)
                if direct_input_char is not None:
                    config.search_query += direct_input_char
                    config.filtered_games = filter_games_by_search_query()
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.search_mode = True
                    config.needs_redraw = True
                keyboard_layout = GLOBAL_SEARCH_KEYBOARD_LAYOUT
                row, col = config.selected_key
                max_row = len(keyboard_layout) - 1
                max_col = len(keyboard_layout[row]) - 1
                if direct_input_char is not None:
                    pass
                elif is_input_matched(event, "up"):
                    target_row = max_row if row == 0 else row - 1
                    config.selected_key = (target_row, min(col, len(keyboard_layout[target_row]) - 1))
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    target_row = 0 if row == max_row else row + 1
                    config.selected_key = (target_row, min(col, len(keyboard_layout[target_row]) - 1))
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
                elif is_input_matched(event, "left"):
                    if col == 0: # if you are in the first col and press LEFT jump to last col
                        col = max_col + 1
                    if col > 0:
                        config.selected_key = (row, col - 1)
                        config.repeat_action = "left"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "right"):
                    if col == max_col: # if you are in the last col and press RIGHT jump to first col
                        col = -1
                    if col < max_col:
                        config.selected_key = (row, col + 1)
                        config.repeat_action = "right"
                        config.repeat_start_time = current_time + REPEAT_DELAY
                        config.repeat_last_action = current_time
                        config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                        config.needs_redraw = True
                elif is_input_matched(event, "confirm"):
                    config.search_query += keyboard_layout[row][col]
                    # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                    config.filtered_games = filter_games_by_search_query()
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug(f"Recherche mise à jour: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "delete"):
                    if config.search_query:
                        config.search_query = config.search_query[:-1]
                        # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                        config.filtered_games = filter_games_by_search_query()
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        #logger.debug(f"Suppression caractère: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "space"):
                    config.search_query += " "
                    # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                    config.filtered_games = filter_games_by_search_query()
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    #logger.debug(f"Espace ajouté: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                elif is_input_matched(event, "cancel"):
                    config.search_mode = False
                    config.search_query = ""
                    config.selected_key = (0, 0)
                    # Restaurer les jeux filtrés par les filtres avancés si actifs
                    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                        config.filtered_games = _apply_sorted_active_filters()
                        config.filter_active = True
                    else:
                        config.filtered_games = config.games
                        config.filter_active = False
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Sortie du mode recherche")
                elif is_input_matched(event, "filter"):
                    config.search_mode = False
                    config.filter_active = bool(config.search_query)
                    config.needs_redraw = True
                    logger.debug(f"Validation du filtre avec manette: query={config.search_query}, filter_active={config.filter_active}")  
            elif config.search_mode and not getattr(config, 'joystick', False):
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
                    # Restaurer les jeux filtrés par les filtres avancés si actifs
                    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                        config.filtered_games = _apply_sorted_active_filters()
                        config.filter_active = True
                    else:
                        config.filtered_games = config.games
                        config.filter_active = False
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Sortie du mode recherche avec bouton cancel sur PC")
                elif event.type == pygame.KEYDOWN:
                    # Saisie de texte alphanumérique
                    direct_input_char = _get_search_input_char(event)
                    if direct_input_char is not None:
                        config.search_query += direct_input_char
                        # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                        config.filtered_games = filter_games_by_search_query()
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.needs_redraw = True
                        logger.debug(f"Recherche mise à jour: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                    # Gestion de la suppression
                    elif is_input_matched(event, "delete"):
                        if config.search_query:
                            config.search_query = config.search_query[:-1]
                            # Appliquer d'abord les filtres avancés si actifs, puis le filtre par nom
                            config.filtered_games = filter_games_by_search_query()
                            config.current_game = 0
                            config.scroll_offset = 0
                            config.needs_redraw = True
                            logger.debug(f"Suppression caractère: query={config.search_query}, jeux filtrés={len(config.filtered_games)}")
                  
     
            else:
                if is_input_matched(event, "up"):
                    if games:
                        config.current_game = _wrap_index(config.current_game, -1, len(games))
                        update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                        event.button if event.type == pygame.JOYBUTTONDOWN else 
                                        (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                        event.value)
                        config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    if games:
                        config.current_game = _wrap_index(config.current_game, 1, len(games))
                        update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                        event.button if event.type == pygame.JOYBUTTONDOWN else 
                                        (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                        event.value)
                        config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.current_game = max(0, config.current_game - config.visible_games)
                    update_key_state("page_up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "left"):
                    config.current_game = max(0, config.current_game - config.visible_games)
                    update_key_state("left", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    update_key_state("page_down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "right"):
                    config.current_game = min(len(games) - 1, config.current_game + config.visible_games)
                    update_key_state("right", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True                    
                elif is_input_matched(event, "filter"):
                    open_unified_filter_menu("game")
                elif is_input_matched(event, "history"):
                    config.history_origin = "game"
                    config.menu_state = "history"
                    config.needs_redraw = True
                    logger.debug("Ouverture history depuis game")
                # Ajouter à la file d'attente avec la touche clear_history (réutilisée)
                elif is_input_matched(event, "clear_history"):
                    if games:
                        idx = config.current_game
                        game = games[idx]
                        url = game.url
                        game_name = game.name
                        platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                        if not _has_download_url(url, game_name):
                            return action
                        
                        pending_download = check_extension_before_download(url, platform, game_name)
                        if pending_download:
                            is_supported = is_extension_supported(
                                sanitize_filename(game_name),
                                platform,
                                load_extensions_json()
                            )
                            zip_ok = bool(pending_download[3])
                            allow_unknown = get_allow_unknown_extensions()
                            
                            # Si extension non supportée ET pas en archive connu, afficher avertissement
                            if (not is_supported and not zip_ok) and not allow_unknown:
                                config.pending_download = pending_download
                                config.pending_download_is_queue = True  # Marquer comme action queue
                                config.previous_menu_state = config.menu_state
                                config.menu_state = "extension_warning"
                                config.extension_confirm_selection = 0
                                config.needs_redraw = True
                                logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                            else:
                                # Ajouter à la queue
                                task_id = str(pygame.time.get_ticks())
                                queue_item = {
                                    'url': url,
                                    'platform': platform,
                                    'game_name': game_name,
                                    'is_zip_non_supported': pending_download[3],
                                    'is_1fichier': is_1fichier_url(url),
                                    'task_id': task_id,
                                    'status': 'Queued'
                                }
                                config.download_queue.append(queue_item)
                                
                                # Ajouter une entrée à l'historique avec status "Queued"
                                config.history.append({
                                    'platform': platform,
                                    'game_name': game_name,
                                    'display_name': get_clean_display_name(game_name, platform),
                                    'status': 'Queued',
                                    'url': url,
                                    'progress': 0,
                                    'message': _("download_queued"),
                                    'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    'downloaded_size': 0,
                                    'total_size': 0,
                                    'task_id': task_id
                                })
                                save_history(config.history)
                                
                                # Afficher un toast de notification
                                show_toast(f"{game_name}\n{_('download_queued')}")
                                
                                config.needs_redraw = True
                                logger.debug(f"{game_name} ajouté à la file d'attente. Queue size: {len(config.download_queue)}")
                                
                                # Si aucun téléchargement actif, lancer le premier de la queue
                                _launch_next_queued_download()
                        else:
                            logger.error(f"config.pending_download est None pour {game_name}")
                            config.needs_redraw = True
                elif is_input_matched(event, "cancel"):
                    config.menu_state = "platform"
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Retour à platform")
                elif is_input_matched(event, "reload_games_data"):
                    config.previous_menu_state = config.menu_state
                    config.menu_state = "reload_games_data"
                    config.needs_redraw = True
                    logger.debug("Passage à reload_games_data depuis game")
                # Télécharger le jeu courant (ou scraper si appui long)
                elif is_input_matched(event, "confirm"):
                    # Détecter le début de l'appui
                    if event.type in (pygame.KEYDOWN, pygame.JOYBUTTONDOWN):
                        config.confirm_press_start_time = current_time
                        config.confirm_long_press_triggered = False
                        logger.debug(f"Début appui confirm à {current_time}")
                        # NE PAS télécharger immédiatement, attendre le relâchement
                        # pour déterminer si c'est un appui long ou court

        # Avertissement extension
        elif config.menu_state == "extension_warning":
            if is_input_matched(event, "confirm"):
                if config.extension_confirm_selection == 0:  # 0 = Oui, 1 = Non
                    if config.pending_download and len(config.pending_download) == 4:
                        url, platform, game_name, is_zip_non_supported = config.pending_download
                        
                        # Vérifier si c'est une action queue
                        is_queue_action = getattr(config, 'pending_download_is_queue', False)
                        
                        if is_queue_action:
                            _queue_download(url, platform, game_name, is_zip_non_supported)
                            _launch_next_queued_download()
                        else:
                            state, task_id = start_or_queue_download(url, platform, game_name, is_zip_non_supported)
                            logger.debug(f"[CONTROLS_EXT_WARNING] Téléchargement confirmé après avertissement: {game_name} pour {platform} depuis {url}, task_id={task_id}, state={state}")
                        
                        config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                        config.needs_redraw = True
                        config.pending_download = None
                        config.pending_download_is_queue = False
                        config.extension_confirm_selection = 0  # Réinitialiser la sélection
                        # Retourner au menu précédent
                        config.menu_state = config.previous_menu_state if config.previous_menu_state else "game"
                        logger.debug(f"[CONTROLS_EXT_WARNING] Retour au menu {config.menu_state} après confirmation")
                    else:
                        config.menu_state = "error"
                        config.error_message = _("error_invalid_download_data")
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
            elif is_input_matched(event, "cancel"):
                config.pending_download = None
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis extension_warning")

        #Historique            
        elif config.menu_state == "history":
            history = config.history
            if is_input_matched(event, "up"):
                # L'historique est inversé à l'affichage, donc UP descend dans l'index (incrément)
                if history:
                    config.current_history_item = _wrap_index(config.current_history_item, 1, len(history))
                    config.repeat_action = "up"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "down"):
                # L'historique est inversé à l'affichage, donc DOWN monte dans l'index (décrement)
                if history:
                    config.current_history_item = _wrap_index(config.current_history_item, -1, len(history))
                    config.repeat_action = "down"
                    config.repeat_start_time = current_time + REPEAT_DELAY
                    config.repeat_last_action = current_time
                    config.repeat_key = event.key if event.type == pygame.KEYDOWN else event.button if event.type == pygame.JOYBUTTONDOWN else (event.axis, 1 if event.value > 0 else -1) if event.type == pygame.JOYAXISMOTION else event.value
                    config.needs_redraw = True
            elif is_input_matched(event, "page_up"):
                # PAGE_UP va vers les plus récents (index décroissant)
                config.current_history_item = max(0, config.current_history_item - config.visible_history_items)
                config.repeat_action = None
                config.repeat_key = None
                config.repeat_start_time = 0
                config.repeat_last_action = current_time
                config.needs_redraw = True
                #logger.debug("Page précédente dans l'historique")
            elif is_input_matched(event, "page_down"):
                # PAGE_DOWN va vers les plus anciens (index croissant)
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
                # Ouvrir le menu d'options pour le jeu sélectionné
                if config.history and config.current_history_item < len(config.history):
                    config.previous_menu_state = "history"
                    config.menu_state = "history_game_options"
                    config.history_game_option_selection = 0
                    config.needs_redraw = True
                    logger.debug("Ouverture history_game_options depuis history")
            elif is_input_matched(event, "cancel") or is_input_matched(event, "history"):
                if config.history and config.current_history_item < len(config.history):
                    entry = config.history[config.current_history_item]
                    if entry.get("status") in ["Downloading", "Téléchargement", "Extracting", "Seeding"] and is_input_matched(event, "cancel"):
                        config.menu_state = "confirm_cancel_download"
                        config.confirm_cancel_selection = 0
                        config.needs_redraw = True
                        logger.debug("Demande d'annulation de téléchargement")
                        return action
                # Retour à l'origine capturée si disponible sinon previous_menu_state
                target = getattr(config, 'history_origin', getattr(config, 'previous_menu_state', 'platform'))
                # Éviter boucle si target reste 'history' ou pointe vers un sous-menu history
                if target == 'history' or target.startswith('history_'):
                    target = 'platform'
                config.menu_state = validate_menu_state(target)
                if hasattr(config, 'history_origin'):
                    try:
                        delattr(config, 'history_origin')
                    except Exception:
                        pass
                config.current_history_item = 0
                config.history_scroll_offset = 0
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis history")
       
        # Confirmation annulation téléchargement
        elif config.menu_state == "confirm_cancel_download":
            if is_input_matched(event, "confirm"):
                if config.confirm_cancel_selection == 1:  # Oui
                    entry = config.history[config.current_history_item]
                    task_id = entry.get("task_id")
                    url = entry.get("url")
                    game_name = entry.get("game_name", "Unknown")
                    was_seeding = entry.get("status") == "Seeding"

                    # Annuler via cancel_events (pour les threads de téléchargement)
                    try:
                        request_cancel(task_id)
                        logger.debug(f"Signal d'annulation envoyé pour task_id={task_id}")
                    except Exception as e:
                        logger.debug(f"Erreur lors de l'envoi du signal d'annulation: {e}")

                    # Arrêter explicitement un éventuel seeding actif lié à cette entrée.
                    try:
                        if stop_active_seeder(task_id=task_id, original_history_url=url):
                            logger.debug(f"Seeder actif arrêté pour task_id={task_id}")
                    except Exception as e:
                        logger.debug(f"Erreur arrêt seeder actif: {e}")
                    
                    # Supprimer le dossier temp torrent (cas où cancel_events est vide :
                    # téléchargement déjà terminé côté thread mais UI encore "Téléchargement").
                    try:
                        if cleanup_torrent_temp(task_id):
                            logger.debug(f"Dossier temp torrent supprimé pour task_id={task_id}")
                    except Exception as e:
                        logger.debug(f"Erreur nettoyage temp torrent: {e}")
                    
                    # Annuler aussi la tâche asyncio si elle existe (pour les téléchargements directs)
                    for tid, (task, task_url, tname, tplatform) in list(config.download_tasks.items()):
                        if tid == task_id or task_url == url:
                            try:
                                task.cancel()
                                del config.download_tasks[tid]
                                logger.debug(f"Tâche asyncio annulée: {tname}")
                            except Exception as e:
                                logger.debug(f"Erreur lors de l'annulation de la tâche asyncio: {e}")
                            break
                    
                    # Mettre à jour l'entrée historique : un arrêt de partage n'est pas une
                    # annulation, le fichier est bien téléchargé (statut "terminé", pas "annulé").
                    if was_seeding:
                        entry["status"] = "Download_OK"
                        entry["progress"] = 100
                        entry.pop("seeds", None)
                        entry.pop("ul_speed", None)
                        logger.debug(f"Partage arrêté: {game_name}")
                    else:
                        entry["status"] = "Canceled"
                        entry["progress"] = 0
                        entry["message"] = _("download_canceled") if _ else "Download canceled"
                        logger.debug(f"Téléchargement annulé: {game_name}")
                    save_history(config.history)
                    
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
            
            if is_input_matched(event, "confirm"):
                # 0 = Non, 1 = Oui
                if config.confirm_clear_selection == 1:  # Oui
                    clear_history()
                    config.history = load_history()  # Recharger l'historique (conserve les téléchargements en cours)
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.menu_state = "history"
                    config.needs_redraw = True
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

        # Dialogue fichier de support
        elif config.menu_state == "support_dialog":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                # Retour au menu pause
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                # Nettoyage des variables temporaires
                if hasattr(config, 'support_zip_path'):
                    delattr(config, 'support_zip_path')
                if hasattr(config, 'support_zip_error'):
                    delattr(config, 'support_zip_error')
                logger.debug("Retour au menu pause depuis support_dialog")

        # Menu options du jeu dans l'historique
        elif config.menu_state == "history_game_options":
            if not config.history or config.current_history_item >= len(config.history):
                config.menu_state = "history"
                config.needs_redraw = True
            else:
                entry = config.history[config.current_history_item]
                status = entry.get("status", "")
                game_name = entry.get("game_name", "")
                platform = entry.get("platform", "")
                
                # Vérifier l'existence du fichier (avec ou sans extension)
                dest_folder = _get_dest_folder_name(platform)
                base_path = os.path.join(config.ROMS_FOLDER, dest_folder)
                file_exists, actual_filename, actual_path = find_file_with_or_without_extension(base_path, game_name)
                actual_matches = find_matching_files(base_path, game_name)
                local_path = entry.get("local_path")
                local_filename = entry.get("local_filename")
                if not file_exists and local_path and os.path.isfile(local_path):
                    actual_filename = os.path.basename(local_path)
                    actual_path = local_path
                    file_exists = True
                    actual_matches = [(actual_filename, actual_path)]
                    logger.debug("[HISTORY_OPTIONS] direct local_path match used: %s", actual_path)
                elif not file_exists and local_filename:
                    local_filename_path = os.path.join(base_path, str(local_filename))
                    if os.path.isfile(local_filename_path):
                        actual_filename = os.path.basename(local_filename_path)
                        actual_path = local_filename_path
                        file_exists = True
                        actual_matches = [(actual_filename, actual_path)]
                        logger.debug("[HISTORY_OPTIONS] direct local_filename match used: %s", actual_path)
                if not actual_matches:
                    actual_matches = get_existing_history_matches(entry)
                    if actual_matches:
                        actual_filename, actual_path = actual_matches[0]
                        file_exists = True
                if file_exists and actual_path:
                    remember_history_local_match(entry, actual_filename, actual_path)
                config.history_actual_matches = actual_matches
                
                # Stocker les informations pour les autres handlers
                config.history_actual_filename = actual_filename
                config.history_actual_path = actual_path
                
                # Déterminer les options disponibles selon le statut
                options = []
                
                # Option commune: ScreenScraper details
                if not config.SCREENSCRAPER_TEMPORARILY_DISABLED:
                    options.append("game_info")
                
                # Options selon statut
                if status == "Queued":
                    # En attente dans la queue
                    options.append("force_download")
                    options.append("remove_from_queue")
                elif status in ["Downloading", "Téléchargement", "Extracting", "Paused"]:
                    # Téléchargement en cours ou en pause - ajouter pause/resume avant cancel
                    options.append("pause_resume_download")
                    options.append("cancel_download")
                elif status == "Seeding":
                    # Seed en cours: proposer arrêt manuel + garder les actions post-download.
                    options.append("cancel_download")
                    if actual_filename and file_exists:
                        ext = os.path.splitext(actual_filename)[1].lower()
                        if ext in ['.zip', '.rar', '.7z']:
                            options.append("extract_archive")
                        elif ext == '.txt':
                            options.append("open_file")
                elif status == "Download_OK" or status == "Completed":
                    # Vérifier si c'est une archive ET si le fichier existe
                    if actual_filename and file_exists:
                        ext = os.path.splitext(actual_filename)[1].lower()
                        if ext in ['.zip', '.rar', '.7z']:
                            options.append("extract_archive")
                        elif ext == '.txt':
                            options.append("open_file")
                elif status in ["Erreur", "Error", "Canceled"]:
                    options.append("error_info")
                    options.append("retry")

                # Options communes si le fichier existe
                if file_exists:
                    options.append("download_folder")
                    options.append("delete_game")
                
                # Option commune: retour
                options.append("back")

                diagnostics_signature = (
                    entry.get("url", ""),
                    status,
                    file_exists,
                    actual_filename or "",
                    actual_path or "",
                    tuple(options),
                )
                if getattr(config, 'history_options_diagnostics_signature', None) != diagnostics_signature:
                    config.history_options_diagnostics_signature = diagnostics_signature
                    logger.debug(
                        "[HISTORY_OPTIONS] platform=%s game=%s status=%s dest_folder=%s base_path=%s file_exists=%s actual_filename=%s actual_path=%s local_path=%s moved_paths=%s options=%s",
                        platform,
                        game_name,
                        status,
                        dest_folder,
                        base_path,
                        file_exists,
                        actual_filename,
                        actual_path,
                        entry.get("local_path"),
                        entry.get("moved_paths"),
                        options,
                    )
                
                total_options = len(options)
                sel = getattr(config, 'history_game_option_selection', 0)
                
                if is_input_matched(event, "up"):
                    config.history_game_option_selection = (sel - 1) % total_options
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                    # logger.debug(f"history_game_options: UP sel={config.history_game_option_selection}/{total_options}")
                elif is_input_matched(event, "down"):
                    config.history_game_option_selection = (sel + 1) % total_options
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                    # logger.debug(f"history_game_options: DOWN sel={config.history_game_option_selection}/{total_options}")
                elif is_input_matched(event, "confirm"):
                    selected_option = options[sel]
                    # logger.debug(f"history_game_options: CONFIRM option={selected_option}")
                    
                    if selected_option == "force_download":
                        # Forcer le démarrage immédiat d'un téléchargement en file d'attente,
                        # en ignorant la limite de slots simultanés.
                        task_id = entry.get("task_id")
                        url = entry.get("url")
                        # Retirer cet item de la queue (où qu'il soit)
                        for i, qi in enumerate(config.download_queue):
                            if qi.get("task_id") == task_id or qi.get("url") == url:
                                config.download_queue.insert(0, config.download_queue.pop(i))
                                break
                        _launch_next_queued_download(force=True)
                        config.menu_state = "history"
                        config.needs_redraw = True
                        logger.info(f"Force Download: {game_name} (task_id={task_id})")

                    elif selected_option == "remove_from_queue":
                        # Retirer de la queue
                        task_id = entry.get("task_id")
                        url = entry.get("url")
                        
                        # Chercher et retirer de la queue
                        for i, queue_item in enumerate(config.download_queue):
                            if queue_item.get("task_id") == task_id or queue_item.get("url") == url:
                                config.download_queue.pop(i)
                                logger.debug(f"Jeu retiré de la queue: {game_name}")
                                break
                        
                        # Mettre à jour l'entrée historique avec status Canceled
                        entry["status"] = "Canceled"
                        entry["progress"] = 0
                        entry["message"] = _("download_canceled") if _ else "Download canceled"
                        save_history(config.history)
                        
                        # Retour à l'historique
                        config.menu_state = "history"
                        config.needs_redraw = True
                        
                    elif selected_option == "pause_resume_download":
                        # Mettre en pause ou reprendre le téléchargement
                        task_id = entry.get("task_id")
                        if task_id:
                            from network import toggle_pause_download, is_download_paused
                            is_paused = toggle_pause_download(task_id)
                            if is_paused:
                                entry["status"] = "Paused"
                            else:
                                entry["status"] = "Downloading"
                            save_history(config.history)
                            config.needs_redraw = True
                        # Retour à l'historique
                        config.menu_state = "history"
                        
                    elif selected_option == "cancel_download":
                        # Rediriger vers le dialogue de confirmation (même que bouton cancel)
                        config.previous_menu_state = "history"
                        config.menu_state = "confirm_cancel_download"
                        config.confirm_cancel_selection = 0
                        config.needs_redraw = True
                        logger.debug("Redirection vers confirm_cancel_download depuis history_game_options")
                        
                    elif selected_option == "download_folder":
                        # Afficher le chemin de destination
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_show_folder"
                        config.needs_redraw = True
                        logger.debug(f"Affichage du dossier de téléchargement pour {game_name}")
                        
                    elif selected_option == "open_file":
                        # Ouvrir le fichier texte
                        if actual_path and os.path.exists(actual_path):
                            try:
                                with open(actual_path, 'r', encoding='utf-8', errors='replace') as f:
                                    content = f.read()
                                config.text_file_content = content
                                config.text_file_name = actual_filename
                                config.text_file_scroll_offset = 0
                                config.previous_menu_state = "history_game_options"
                                config.menu_state = "text_file_viewer"
                                config.needs_redraw = True
                                logger.debug(f"Ouverture du fichier texte: {actual_filename}")
                            except Exception as e:
                                logger.error(f"Erreur lors de l'ouverture du fichier texte: {e}")
                                config.menu_state = "error"
                                config.error_message = f"Erreur lors de l'ouverture du fichier: {str(e)}"
                                config.needs_redraw = True
                        else:
                            logger.error(f"Fichier texte introuvable: {actual_path}")
                            config.menu_state = "error"
                            config.error_message = "Fichier introuvable"
                            config.needs_redraw = True
                        
                    elif selected_option == "extract_archive":
                        # L'option n'apparaît que si le fichier existe, pas besoin de re-vérifier
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_extract_archive"
                        config.needs_redraw = True
                        logger.debug(f"Extraction de l'archive {game_name}")
                        
                    elif selected_option == "game_info":
                        from game_info import open_game_info
                        open_game_info(
                            config.history_actual_filename or game_name,
                            game_name,
                            platform,
                            "history_game_options",
                        )
                        
                    elif selected_option == "delete_game":
                        # Demander confirmation avant suppression
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_confirm_delete"
                        config.history_delete_confirm_selection = 0
                        config.needs_redraw = True
                        logger.debug(f"Demande de confirmation de suppression pour {game_name}")
                        
                    elif selected_option == "error_info":
                        # Afficher les détails de l'erreur
                        config.previous_menu_state = "history_game_options"
                        config.menu_state = "history_error_details"
                        config.needs_redraw = True
                        logger.debug(f"Affichage des détails de l'erreur pour {game_name}")
                        
                    elif selected_option == "retry":
                        # Relancer le téléchargement
                        config.menu_state = "history"
                        # Réinitialiser l'entrée et relancer
                        url = entry.get("url")
                        if _has_download_url(url, game_name):
                            # Mettre à jour le statut
                            entry["status"] = "Downloading"
                            entry["progress"] = 0
                            entry["message"] = "Téléchargement en cours"
                            save_history(config.history)
                            
                            # Relancer le téléchargement
                            pending_download = check_extension_before_download(url, platform, game_name)
                            if pending_download:
                                is_zip_non_supported = pending_download[3] if len(pending_download) > 3 else False
                                state, task_id = start_or_queue_download(url, platform, game_name, is_zip_non_supported)
                                if state == "queued":
                                    entry["status"] = "Queued"
                                    entry["progress"] = 0
                                    entry["message"] = _("download_queued")
                                    save_history(config.history)
                                logger.debug(f"Relance du téléchargement: {game_name} pour {platform}, state={state}, task_id={task_id}")
                        config.needs_redraw = True
                        
                    elif selected_option == "back":
                        # Retour à l'historique
                        config.menu_state = "history"
                        # Ne pas mettre à jour previous_menu_state pour éviter les boucles
                        config.needs_redraw = True
                        logger.debug("Retour à history depuis history_game_options")
                        
                elif is_input_matched(event, "cancel"):
                    config.menu_state = "history"
                    # Ne pas mettre à jour previous_menu_state pour éviter les boucles
                    config.needs_redraw = True
                    logger.debug("Retour à history depuis history_game_options (cancel)")

        # Affichage du dossier de téléchargement
        elif config.menu_state == "history_show_folder":
            if is_input_matched(event, "clear_history"):
                if not config.history or config.current_history_item >= len(config.history):
                    config.menu_state = "history"
                    config.needs_redraw = True
                else:
                    entry = config.history[config.current_history_item]
                    actual_matches = getattr(config, 'history_actual_matches', None) or []
                    if not actual_matches:
                        actual_matches = get_existing_history_matches(entry)

                    start_path = None
                    if actual_matches:
                        start_path = os.path.dirname(actual_matches[0][1])
                    else:
                        actual_path = getattr(config, 'history_actual_path', None)
                        if actual_path and os.path.exists(actual_path):
                            start_path = os.path.dirname(actual_path)

                    if not start_path or not os.path.isdir(start_path):
                        start_path = config.ROMS_FOLDER

                    config.folder_browser_path = start_path
                    config.folder_browser_selection = 0
                    config.folder_browser_scroll_offset = 0
                    config.folder_browser_mode = "history_move"
                    config.platform_config_name = entry.get("display_name") or get_clean_display_name(entry.get("game_name", ""), entry.get("platform", ""))

                    _set_folder_browser_location(start_path, reset_selection=True)

                    config.menu_state = "folder_browser"
                    config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True

        # ScreenScraper game details
        elif config.menu_state == "game_info":
            if is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = validate_menu_state(config.game_info_return_state)
                config.game_info_loading = False
                config.needs_redraw = True

        # Affichage détails erreur
        # Visualiseur de fichiers texte
        elif config.menu_state == "text_file_viewer":
            content = getattr(config, 'text_file_content', '')
            if content:
                from utils import wrap_text
                
                # Calculer les dimensions
                controls_y = config.screen_height - int(config.screen_height * 0.037)
                margin = 40
                header_height = 60
                rect_width = config.screen_width - 2 * margin
                content_area_height = controls_y - 2 * margin - 10 - header_height - 20
                max_width = rect_width - 60
                
                # Diviser le contenu en lignes et appliquer le word wrap
                original_lines = content.split('\n')
                wrapped_lines = []
                
                for original_line in original_lines:
                    if original_line.strip():  # Si la ligne n'est pas vide
                        wrapped = wrap_text(original_line, config.small_font, max_width)
                        wrapped_lines.extend(wrapped)
                    else:  # Ligne vide
                        wrapped_lines.append('')
                
                line_height = config.small_font.get_height() + 2
                visible_lines = int(content_area_height / line_height)
                
                scroll_offset = getattr(config, 'text_file_scroll_offset', 0)
                max_scroll = max(0, len(wrapped_lines) - visible_lines)
                viewer_mode = getattr(config, 'text_file_mode', '')
                
                if is_input_matched(event, "up"):
                    config.text_file_scroll_offset = max(0, scroll_offset - 1)
                    update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "down"):
                    config.text_file_scroll_offset = min(max_scroll, scroll_offset + 1)
                    update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_up"):
                    config.text_file_scroll_offset = max(0, scroll_offset - visible_lines)
                    update_key_state("page_up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif is_input_matched(event, "page_down"):
                    config.text_file_scroll_offset = min(max_scroll, scroll_offset + visible_lines)
                    update_key_state("page_down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                    event.button if event.type == pygame.JOYBUTTONDOWN else 
                                    (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                    event.value)
                    config.needs_redraw = True
                elif viewer_mode == "ota_update" and is_input_matched(event, "confirm"):
                    config.startup_update_confirmed = True
                    config.menu_state = "loading"
                    config.needs_redraw = True
                elif viewer_mode != "ota_update" and (is_input_matched(event, "cancel") or is_input_matched(event, "confirm")):
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
            else:
                # Si pas de contenu, retourner au menu précédent
                if is_input_matched(event, "cancel") or is_input_matched(event, "confirm"):
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True

        elif config.menu_state == "history_error_details":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True

        # Confirmation suppression jeu
        elif config.menu_state == "history_confirm_delete":
            if is_input_matched(event, "confirm"):
                if config.history_delete_confirm_selection == 1:  # Oui
                    # Supprimer le fichier
                    if config.history and config.current_history_item < len(config.history):
                        entry = config.history[config.current_history_item]
                        
                        # Utiliser le chemin réel trouvé (avec ou sans extension)
                        file_path = getattr(config, 'history_actual_path', None)
                        
                        if not file_path:
                            # Fallback si pas trouvé (ne devrait pas arriver)
                            game_name = entry.get("game_name", "")
                            platform = entry.get("platform", "")
                            sanitized_name = sanitize_filename(game_name)
                            dest_folder = _get_dest_folder_name(platform)
                            dest_dir = os.path.join(config.ROMS_FOLDER, dest_folder)
                            file_path = os.path.join(dest_dir, sanitized_name)
                        
                        try:
                            if os.path.exists(file_path):
                                os.remove(file_path)
                                logger.info(f"Fichier supprimé: {file_path}")
                                # Mettre à jour l'historique
                                entry["message"] = _("history_delete_success")
                                save_history(config.history)
                                config.popup_message = _("history_delete_success")
                                config.popup_timer = 2000
                            else:
                                logger.warning(f"Fichier introuvable: {file_path}")
                                config.popup_message = _("history_delete_error").format("File not found")
                                config.popup_timer = 3000
                        except Exception as e:
                            logger.error(f"Erreur suppression {file_path}: {e}")
                            config.popup_message = _("history_delete_error").format(str(e))
                            config.popup_timer = 3000
                    
                    config.menu_state = "history"
                    config.needs_redraw = True
                else:  # Non
                    config.menu_state = "history_game_options"
                    config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.history_delete_confirm_selection = 1 - config.history_delete_confirm_selection
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "history_game_options"
                config.needs_redraw = True

        # Extraction archive depuis historique
        elif config.menu_state == "history_extract_archive":
            if is_input_matched(event, "confirm") or is_input_matched(event, "cancel"):
                if is_input_matched(event, "confirm"):
                    # Lancer l'extraction
                    if config.history and config.current_history_item < len(config.history):
                        entry = config.history[config.current_history_item]
                        platform = entry.get("platform", "")
                        
                        
                        # Utiliser le chemin réel trouvé (avec ou sans extension)
                        file_path = getattr(config, 'history_actual_path', None)
                        actual_filename = getattr(config, 'history_actual_filename', None)
                        
                        if not file_path or not actual_filename:
                            # Fallback si pas trouvé (ne devrait pas arriver)
                            game_name = entry.get("game_name", "")
                            sanitized_name = sanitize_filename(game_name)
                            dest_folder = _get_dest_folder_name(platform)
                            dest_dir = os.path.join(config.ROMS_FOLDER, dest_folder)
                            file_path = os.path.join(dest_dir, sanitized_name)
                            actual_filename = sanitized_name
                        else:
                            dest_folder = _get_dest_folder_name(platform)
                            dest_dir = os.path.join(config.ROMS_FOLDER, dest_folder)
                        
                        ext = os.path.splitext(actual_filename)[1].lower()
                        url = entry.get("url", "")
                        
                        if os.path.exists(file_path):
                            # Mettre à jour le statut avant extraction
                            entry["status"] = "Extracting"
                            entry["progress"] = 0
                            entry["message"] = _("history_extracting") if _ else "Extracting..."
                            save_history(config.history)
                            config.needs_redraw = True
                            
                            def do_extract():
                                try:
                                    if ext == '.zip':
                                        success, msg = extract_zip(file_path, dest_dir, url)
                                    elif ext == '.rar':
                                        success, msg = extract_rar(file_path, dest_dir, url)
                                    elif ext == '.7z':
                                        success, msg = extract_7z(file_path, dest_dir, url)
                                    else:
                                        success, msg = False, "Not an archive"
                                    
                                    # Mettre à jour le statut après extraction
                                    if success:
                                        entry["status"] = "Completed"
                                        entry["progress"] = 100
                                        entry["message"] = _("history_extracted") if _ else "Extracted"
                                        logger.info(f"Extraction réussie: {actual_filename}")
                                    else:
                                        entry["status"] = "Error"
                                        entry["progress"] = 0
                                        entry["message"] = f"Extraction failed: {msg}"
                                        logger.error(f"Échec extraction: {msg}")
                                    save_history(config.history)
                                    config.needs_redraw = True
                                except Exception as e:
                                    logger.error(f"Erreur extraction: {e}")
                                    entry["status"] = "Error"
                                    entry["progress"] = 0
                                    entry["message"] = f"Error: {str(e)}"
                                    save_history(config.history)
                                    config.needs_redraw = True
                            
                            extract_thread = threading.Thread(target=do_extract, daemon=True)
                            extract_thread.start()
                            logger.info(f"Extraction lancée: {file_path}")
                
                # Retourner à l'historique pour voir la progression
                config.menu_state = "history"
                config.needs_redraw = True

        # Confirmation quitter
        elif config.menu_state == "confirm_exit":
            # Sous-menu Quit: 0=Quit RGSX, 1=Restart RGSX, 2=Back
            if is_input_matched(event, "up"):
                config.confirm_selection = max(0, config.confirm_selection - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.confirm_selection = min(2, config.confirm_selection + 1)
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.confirm_selection == 0:  # Quit RGSX
                    # Les téléchargements actifs restent en état "Téléchargement" dans l'historique
                    # pour permettre la reprise au prochain démarrage (fichiers .aria2 conservés).
                    return "quit"
                elif config.confirm_selection == 1:  # Restart RGSX
                    restart_application(2000)
                elif config.confirm_selection == 2:  # Back
                    # Retour à l'état capturé (confirm_exit_origin) sinon previous_menu_state sinon platform
                    target = getattr(config, 'confirm_exit_origin', getattr(config, 'previous_menu_state', 'platform'))
                    config.menu_state = validate_menu_state(target)
                    if hasattr(config, 'confirm_exit_origin'):
                        try:
                            delattr(config, 'confirm_exit_origin')
                        except Exception:
                            pass
                    config.needs_redraw = True
                    logger.debug(f"Retour à {config.menu_state} depuis confirm_exit (back)")
            elif is_input_matched(event, "cancel"):
                # Retour à l'état capturé
                target = getattr(config, 'confirm_exit_origin', getattr(config, 'previous_menu_state', 'platform'))
                config.menu_state = validate_menu_state(target)
                if hasattr(config, 'confirm_exit_origin'):
                    try:
                        delattr(config, 'confirm_exit_origin')
                    except Exception:
                        pass
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis confirm_exit (cancel)")

        # Menu pause
        elif config.menu_state == "pause_menu":
            #logger.debug(f"État pause_menu, selected_option={config.selected_option}, événement={event.type}, valeur={getattr(event, 'value', None)}")
            # Start toggles back to previous state when already in pause
            if is_input_matched(event, "start"):
                target = getattr(config, 'pause_origin_state', getattr(config, 'previous_menu_state', 'platform'))
                config.menu_state = validate_menu_state(target)
                config.needs_redraw = True
                logger.debug(f"Start: retour à {config.menu_state} depuis pause_menu")
            elif is_input_matched(event, "up"):
                # Menu racine hiérarchique: nombre dynamique (langue + catégories)
                total = getattr(config, 'pause_menu_total_options', 9)
                config.selected_option = (config.selected_option - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                # Menu racine hiérarchique: nombre dynamique (langue + catégories)
                total = getattr(config, 'pause_menu_total_options', 9)
                config.selected_option = (config.selected_option + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                choice = pause_root_index(config.selected_option)
                if choice == 0:  # Games submenu
                    config.menu_state = "pause_games_menu"
                    if not hasattr(config, 'pause_games_selection'):
                        config.pause_games_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 1:  # Language selector direct
                    config.menu_state = "language_select"
                    config.previous_menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 2:  # Controls submenu
                    config.menu_state = "pause_controls_menu"
                    if not hasattr(config, 'pause_controls_selection'):
                        config.pause_controls_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 3:  # Display submenu
                    config.menu_state = "pause_display_menu"
                    if not hasattr(config, 'pause_display_selection'):
                        config.pause_display_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 4:  # Scrap submenu
                    config.menu_state = "pause_scrap_menu"
                    if not hasattr(config, 'pause_scrap_selection'):
                        config.pause_scrap_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 5:  # Settings submenu
                    config.menu_state = "pause_settings_menu"
                    if not hasattr(config, 'pause_settings_selection'):
                        config.pause_settings_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 6:  # Support
                    success, message, zip_path = generate_support_zip()
                    if success:
                        config.support_zip_path = zip_path
                        config.support_zip_error = None
                    else:
                        config.support_zip_path = None
                        config.support_zip_error = message
                    config.menu_state = "support_dialog"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 7:  # Reset default settings (delete file + restart)
                    config.previous_menu_state = "pause_menu"
                    config.menu_state = "reset_settings_confirm"
                    config.reset_settings_confirm_selection = 0  # 0=No, 1=Yes
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
                elif choice == 8:  # Quit submenu
                    # Capturer l'origine pause_menu pour retour si annulation
                    config.confirm_exit_origin = "pause_menu"
                    config.previous_menu_state = validate_menu_state(config.previous_menu_state)
                    config.menu_state = "confirm_exit"
                    config.confirm_selection = 0
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                target = getattr(config, 'pause_origin_state', getattr(config, 'previous_menu_state', 'platform'))
                config.menu_state = validate_menu_state(target)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis pause_menu")

        # Sous-menu Controls
        elif config.menu_state == "pause_controls_menu":
            # Ajout de l'option inversion ABXY
            options = [
                {"key": "help", "title": _("controls_help_title"), "desc": _("instruction_controls_help")},
                {"key": "remap", "title": _("menu_remap_controls"), "desc": _("instruction_controls_remap")},
                {"key": "back", "title": _("menu_back"), "desc": _("instruction_generic_back")},
            ]
            sel = getattr(config, 'pause_controls_selection', 0)
            total = len(options)
            if is_input_matched(event, "up"):
                config.pause_controls_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_controls_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                selected = options[sel]["key"]
                if selected == "help":
                    config.previous_menu_state = "pause_controls_menu"
                    config.menu_state = "controls_help"
                elif selected == "remap":
                    if os.path.exists(config.CONTROLS_CONFIG_PATH):
                        try:
                            os.remove(config.CONTROLS_CONFIG_PATH)
                        except Exception as e:
                            logger.error(f"Erreur suppression controls_config: {e}")
                    config.previous_menu_state = "pause_controls_menu"
                    config.menu_state = "controls_mapping"
                # invert_abxy moved to controls_help submenu (interactive)
                else:  # Back
                    config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        
        # Menu Aide Contrôles (affichage interactif du style manette)
        elif config.menu_state == "controls_help":
            # Left/Right change controller style immediately
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                try:
                    from rgsx_settings import set_nintendo_layout, get_nintendo_layout
                    # Toggle style
                    new_val = set_nintendo_layout(not get_nintendo_layout())
                    config.nintendo_layout = new_val
                    # Clear icon cache so help screen updates immediately
                    try:
                        from display import clear_help_icon_cache
                        clear_help_icon_cache()
                    except Exception:
                        pass
                    config.popup_message = (_("menu_nintendo_layout_on") if new_val else _("menu_nintendo_layout_off"))
                    config.popup_timer = 1200
                    config.needs_redraw = True
                except Exception as e:
                    logger.error(f"Erreur toggle nintendo_layout from controls_help: {e}")
            elif is_input_matched(event, "confirm") or is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                # Return to previous menu
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
        # Sous-menu Display
        elif config.menu_state == "pause_display_menu":
            sel = getattr(config, 'pause_display_selection', 0)
            # layout, font submenu, family, [monitor if multi], [display mode on Windows], light, unknown, back
            from rgsx_settings import get_available_monitors
            monitors = get_available_monitors()
            show_monitor = len(monitors) > 1
            show_display_mode = getattr(config, 'OPERATING_SYSTEM', '') == "Windows"

            monitor_index = 3 if show_monitor else None
            display_mode_index = 4 if show_monitor else 3
            if not show_display_mode:
                display_mode_index = None

            next_index = 3
            if show_monitor:
                next_index += 1
            if show_display_mode:
                next_index += 1

            background_index = next_index
            light_index = background_index + 1
            unknown_index = light_index + 1
            back_index = unknown_index + 1
            total = back_index + 1
            if is_input_matched(event, "up"):
                config.pause_display_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0 layout submenu - open submenu on confirm
                if sel == 0 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_display_layout_menu"
                    # Trouver l'index actuel pour la sélection
                    layouts = DISPLAY_GRID_LAYOUTS
                    try:
                        idx = layouts.index((config.GRID_COLS, config.GRID_ROWS))
                    except ValueError:
                        idx = 0
                    config.pause_display_layout_selection = idx
                    config.needs_redraw = True
                # 1 font size submenu - open submenu on confirm
                elif sel == 1 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_display_font_menu"
                    config.pause_display_font_selection = 0
                    config.needs_redraw = True
                # 2 font family cycle
                elif sel == 2 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        families = getattr(config, 'FONT_FAMILIES', ["pixel"]) or ["pixel"]
                        current = get_font_family()
                        try:
                            fam_index = families.index(current)
                        except ValueError:
                            fam_index = 0
                        direction = 1 if (is_input_matched(event, "right") or is_input_matched(event, "confirm")) else -1
                        fam_index = (fam_index + direction) % len(families)
                        new_family = families[fam_index]
                        set_font_family(new_family)
                        config.current_font_family_index = fam_index
                        init_font_func = getattr(config, 'init_font', None)
                        if callable(init_font_func):
                            init_font_func()
                        # popup
                        if _:
                            try:
                                # Vérifier proprement la présence de la clé i18n
                                fmt = _("popup_font_family_changed") if 'popup_font_family_changed' in getattr(_, 'translations', {}) else None
                            except Exception:
                                fmt = None
                            if fmt:
                                config.popup_message = fmt.format(new_family)
                            else:
                                config.popup_message = f"Font: {new_family}"
                        else:
                            config.popup_message = f"Font: {new_family}"
                        config.popup_timer = 2500
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement font family: {e}")
                # Monitor selection (only if multiple monitors)
                elif monitor_index is not None and sel == monitor_index and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_display_monitor, set_display_monitor
                        current = get_display_monitor()
                        new_monitor = (current - 1) % len(monitors) if is_input_matched(event, "left") else (current + 1) % len(monitors)
                        set_display_monitor(new_monitor)
                        config.popup_message = _("display_monitor_restart_required") if _ else "Restart required to apply monitor change"
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement moniteur: {e}")
                # Display mode toggle (Windows only)
                elif display_mode_index is not None and sel == display_mode_index and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_display_fullscreen, set_display_fullscreen
                        current = get_display_fullscreen()
                        set_display_fullscreen(not current)
                        config.popup_message = _("display_mode_restart_required") if _ else "Restart required to apply screen mode"
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle fullscreen/windowed: {e}")
                # Background gradient theme cycle
                elif sel == background_index and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_display_background_theme, set_display_background_theme

                        theme_keys = ["default", "sunset", "forest", "midnight"]
                        theme_label_keys = {
                            "default": "background_theme_default",
                            "sunset": "background_theme_sunset",
                            "forest": "background_theme_forest",
                            "midnight": "background_theme_midnight",
                        }

                        current = get_display_background_theme()
                        try:
                            idx = theme_keys.index(current)
                        except ValueError:
                            idx = 0

                        direction = -1 if is_input_matched(event, "left") else 1
                        new_theme = set_display_background_theme(theme_keys[(idx + direction) % len(theme_keys)])

                        label_key = theme_label_keys.get(new_theme, "")
                        translated_label = _(label_key) if (_ and label_key) else new_theme
                        if translated_label == label_key:
                            translated_label = new_theme
                        config.popup_message = f"{_('display_background') if _ else 'Background'}: {translated_label}"
                        config.popup_timer = 1800
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement theme de fond: {e}")
                # Light mode toggle
                elif sel == light_index and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_light_mode, set_light_mode
                        current = get_light_mode()
                        new_val = set_light_mode(not current)
                        config.popup_message = _("display_light_mode_enabled") if new_val else _("display_light_mode_disabled")
                        config.popup_timer = 2000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle light mode: {e}")
                # Allow unknown extensions
                elif sel == unknown_index and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_allow_unknown_extensions()
                        new_val = set_allow_unknown_extensions(not current)
                        config.popup_message = _("menu_allow_unknown_ext_enabled") if new_val else _("menu_allow_unknown_ext_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle allow_unknown_extensions: {e}")
                # Back
                elif sel == back_index and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Display > Layout (disposition avec visualisation)
        elif config.menu_state == "pause_display_layout_menu":
            sel = getattr(config, 'pause_display_layout_selection', 0)
            layouts = DISPLAY_GRID_LAYOUTS
            total = len(layouts) + 1
            if is_input_matched(event, "up"):
                config.pause_display_layout_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_layout_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if sel < len(layouts):  # Une des dispositions
                    new_cols, new_rows = layouts[sel]
                    try:
                        set_display_grid(new_cols, new_rows)
                    except Exception as e:
                        logger.error(f"Erreur set_display_grid: {e}")
                    config.GRID_COLS = new_cols
                    config.GRID_ROWS = new_rows
                    # Afficher un popup indiquant que le changement sera effectif après redémarrage
                    try:
                        config.popup_message = _("popup_layout_changed").format(new_cols, new_rows) if _ else f"Layout {new_cols}x{new_rows} applied immediately; no restart needed."
                        config.popup_timer = 3000
                    except Exception as e:
                        logger.error(f"Erreur popup layout: {e}")
                    config.menu_state = "pause_display_menu"
                    config.needs_redraw = True
                elif sel == len(layouts):  # Back
                    config.menu_state = "pause_display_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_display_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Display > Font (tailles de police)
        elif config.menu_state == "pause_display_font_menu":
            sel = getattr(config, 'pause_display_font_selection', 0)
            total = 3  # font size, footer font size, back
            if is_input_matched(event, "up"):
                config.pause_display_font_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_display_font_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0 font size
                if sel == 0 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    opts = getattr(config, 'font_scale_options', [0.75,1.0,1.25,1.5,1.75])
                    idx = getattr(config, 'current_font_scale_index', 1)
                    idx = max(0, idx-1) if is_input_matched(event, "left") else min(len(opts)-1, idx+1)
                    if idx != getattr(config, 'current_font_scale_index', 1):
                        config.current_font_scale_index = idx
                        scale = opts[idx]
                        config.accessibility_settings["font_scale"] = scale
                        try:
                            save_accessibility_settings(config.accessibility_settings)
                        except Exception as e:
                            logger.error(f"Erreur sauvegarde accessibilité: {e}")
                        try:
                            config.init_font()
                        except Exception as e:
                            logger.error(f"Erreur init polices: {e}")
                        config.needs_redraw = True
                # 1 footer font size
                elif sel == 1 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    from accessibility import update_footer_font_scale
                    footer_opts = getattr(config, 'footer_font_scale_options', [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0])
                    idx = getattr(config, 'current_footer_font_scale_index', 3)
                    idx = max(0, idx-1) if is_input_matched(event, "left") else min(len(footer_opts)-1, idx+1)
                    if idx != getattr(config, 'current_footer_font_scale_index', 3):
                        config.current_footer_font_scale_index = idx
                        try:
                            update_footer_font_scale()
                        except Exception as e:
                            logger.error(f"Erreur update footer font scale: {e}")
                        config.needs_redraw = True
                # 2 back
                elif sel == 2 and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_display_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_display_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Games
        elif config.menu_state == "pause_games_menu":
            sel = getattr(config, 'pause_games_selection', 0)
            total = 6  # update cache, scan roms, history, unsupported, filter, back
            if is_input_matched(event, "up"):
                config.pause_games_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_games_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right"):
                if sel == 0 and is_input_matched(event, "confirm"):  # update cache
                    config.previous_menu_state = "pause_games_menu"
                    config.menu_state = "reload_games_data"
                    config.redownload_confirm_selection = 0
                    config.needs_redraw = True
                elif sel == 1 and is_input_matched(event, "confirm"):  # scan local roms
                    try:
                        added_games, scanned_platforms = scan_roms_for_downloaded_games()
                        config.popup_message = _("popup_scan_owned_roms_done").format(added_games, scanned_platforms) if _ else f"ROM scan complete: {added_games} games added across {scanned_platforms} platforms"
                        config.popup_timer = 4000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur scan ROMs locaux: {e}")
                        config.popup_message = _("popup_scan_owned_roms_error").format(str(e)) if _ else f"ROM scan error: {e}"
                        config.popup_timer = 5000
                        config.needs_redraw = True
                elif sel == 2 and is_input_matched(event, "confirm"):  # history
                    config.history = load_history()
                    config.current_history_item = 0
                    config.history_scroll_offset = 0
                    config.previous_menu_state = "pause_games_menu"
                    config.menu_state = "history"
                    config.needs_redraw = True
                elif sel == 3 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):  # unsupported toggle
                    try:
                        current = get_show_unsupported_platforms()
                        new_val = set_show_unsupported_platforms(not current)
                        load_sources()
                        config.popup_message = _("menu_show_unsupported_enabled") if new_val else _("menu_show_unsupported_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle unsupported: {e}")
                elif sel == 4 and is_input_matched(event, "confirm"):  # filter platforms
                    config.filter_return_to = "pause_games_menu"
                    config.menu_state = "filter_platforms"
                    config.selected_filter_index = 0
                    config.filter_platforms_scroll_offset = 0
                    config.filter_platforms_source_map = {}
                    config.filter_platforms_expanded_sources = []
                    config.needs_redraw = True
                elif sel == 5 and is_input_matched(event, "confirm"):  # back
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Scrap
        elif config.menu_state == "pause_scrap_menu":
            options_count = 3
            sel = getattr(config, "pause_scrap_selection", 0)
            if is_input_matched(event, "up"):
                config.pause_scrap_selection = (sel - 1) % options_count
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_scrap_selection = (sel + 1) % options_count
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if sel == 0:
                    from screenscraper import load_account
                    config.ss_input_username, config.ss_input_password = load_account()
                    config.ss_input_field = "username"
                    config.ss_input_selected_key = (0, 0)
                    config.ss_input_shift = False
                    config.ss_input_return_state = "pause_scrap_menu"
                    config.menu_state = "screenscraper_input"
                elif sel == 1:
                    from media_manager import manager
                    manager.open()
                    config.media_manager_selection = 0
                    config.media_manager_scroll_offset = 0
                    config.menu_state = "media_manager"
                else:
                    config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        # Sous-menu Settings
        elif config.menu_state == "pause_settings_menu":
            sel = getattr(config, 'pause_settings_selection', 0)
            # Les options API et statut suivent les réglages système.
            total = 8  # Windows: 5 settings, API keys, connection status, back
            auto_extract_index = 2
            roms_folder_index = 3
            max_dl_index = 4
            web_service_index = -1
            custom_dns_index = -1
            api_keys_index = 5
            connection_status_index = 6
            back_index = 7

            if config.OPERATING_SYSTEM == "Linux":
                total = 10
                web_service_index = 5
                custom_dns_index = 6
                api_keys_index = 7
                connection_status_index = 8
                back_index = 9
            
            if is_input_matched(event, "up"):
                config.pause_settings_selection = (sel - 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.pause_settings_selection = (sel + 1) % total
                config.needs_redraw = True
            elif is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "clear_history"):
                # Option 0: Music toggle
                if sel == 0 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    config.music_enabled = not config.music_enabled
                    save_music_config()
                    if config.music_enabled:
                        music_files = getattr(config, "music_files", None)
                        music_folder = getattr(config, "music_folder", None)
                        if music_files and music_folder:
                            config.current_music = play_random_music(music_files, music_folder, getattr(config, "current_music", None))
                    else:
                        pygame.mixer.music.stop()
                    config.needs_redraw = True
                    logger.info(f"Musique {'activée' if config.music_enabled else 'désactivée'} via settings")
                # Option 1: Symlink toggle
                elif sel == 1 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    current_status = get_symlink_option()
                    success, message = set_symlink_option(not current_status)
                    config.popup_message = message
                    config.popup_timer = 3000 if success else 5000
                    config.needs_redraw = True
                    logger.info(f"Symlink option {'activée' if not current_status else 'désactivée'} via settings")
                # Option 2: Auto Extract toggle
                elif sel == auto_extract_index and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    from rgsx_settings import get_auto_extract, set_auto_extract
                    current_status = get_auto_extract()
                    set_auto_extract(not current_status)
                    config.needs_redraw = True
                    logger.info(f"Auto extract {'activée' if not current_status else 'désactivée'} via settings")
                # Option 3: ROMs folder - ouvrir le navigateur (confirm) ou reset (clear_history)
                elif sel == roms_folder_index:
                    if is_input_matched(event, "confirm"):
                        from rgsx_settings import get_roms_folder
                        # Ouvrir le navigateur de dossiers en mode roms_root
                        current_custom = get_roms_folder()
                        if current_custom and os.path.isdir(current_custom):
                            start_path = current_custom
                        else:
                            # Démarrer depuis le dossier parent de ROMS_FOLDER actuel
                            start_path = os.path.dirname(config.ROMS_FOLDER) if config.ROMS_FOLDER else "/"
                            if not os.path.isdir(start_path):
                                start_path = "/"
                        config.folder_browser_path = start_path
                        config.folder_browser_selection = 0
                        config.folder_browser_scroll_offset = 0
                        config.folder_browser_mode = "roms_root"
                        _set_folder_browser_location(start_path, reset_selection=True)
                        config.menu_state = "folder_browser"
                        config.needs_redraw = True
                        logger.info("Ouverture navigateur dossier ROMs principal")
                    elif is_input_matched(event, "clear_history"):
                        # Réinitialiser le dossier ROMs par défaut
                        from rgsx_settings import set_roms_folder, get_roms_folder
                        current = get_roms_folder()
                        if current:  # Si un dossier custom est défini, le réinitialiser
                            set_roms_folder("")
                            config.popup_message = _("roms_folder_reset") if _ else "ROMs folder reset to default\nRestart required!"
                            config.popup_timer = 5000
                            logger.info("Dossier ROMs réinitialisé par défaut")
                        config.needs_redraw = True
                # Option 4: Max simultaneous downloads (left/right pour -/+)
                elif sel == max_dl_index and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    from rgsx_settings import get_max_simultaneous_downloads, set_max_simultaneous_downloads
                    current_max = get_max_simultaneous_downloads()
                    if is_input_matched(event, "left"):
                        new_max = max(1, current_max - 1)
                    else:
                        new_max = min(10, current_max + 1)
                    if new_max != current_max:
                        set_max_simultaneous_downloads(new_max)
                        config.popup_message = _("settings_max_dl_changed").format(new_max) if _ else f"Max simultaneous downloads: {new_max}"
                        config.popup_timer = 1500
                        config.needs_redraw = True
                        logger.info(f"max_simultaneous_downloads réglé à {new_max}")
                # Option 5: Web Service toggle (seulement si Linux)
                elif sel == web_service_index and web_service_index >= 0 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    
                    current_status = check_web_service_status()
                    # Afficher un message de chargement
                    config.popup_message = _("settings_web_service_enabling") if not current_status else _("settings_web_service_disabling")
                    config.popup_timer = 1000
                    config.needs_redraw = True
                    # Exécuter en thread pour ne pas bloquer l'UI
                    def toggle_service():
                        success, message = toggle_web_service_at_boot(not current_status)
                        config.popup_message = message
                        config.popup_timer = 5000 if success else 7000
                        config.needs_redraw = True
                        if success:
                            logger.info(f"Service web {'activé' if not current_status else 'désactivé'} au démarrage")
                        else:
                            logger.error(f"Erreur toggle service web: {message}")
                    threading.Thread(target=toggle_service, daemon=True).start()
                # Option 3: Custom DNS toggle (seulement si Linux)
                elif sel == custom_dns_index and custom_dns_index >= 0 and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                    from utils import check_custom_dns_status, toggle_custom_dns_at_boot
                    current_status = check_custom_dns_status()
                    # Afficher un message de chargement
                    config.popup_message = _("settings_custom_dns_enabling") if not current_status else _("settings_custom_dns_disabling")
                    config.popup_timer = 1000
                    config.needs_redraw = True
                    # Exécuter en thread pour ne pas bloquer l'UI
                    def toggle_dns():
                        success, message = toggle_custom_dns_at_boot(not current_status)
                        config.popup_message = message
                        config.popup_timer = 5000 if success else 7000
                        config.needs_redraw = True
                        if success:
                            logger.info(f"Custom DNS {'activé' if not current_status else 'désactivé'} au démarrage")
                        else:
                            logger.error(f"Erreur toggle custom DNS: {message}")
                    threading.Thread(target=toggle_dns, daemon=True).start()
                # Option API Keys
                elif sel == api_keys_index and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_api_keys_status"
                    config.needs_redraw = True
                # Option Connection Status
                elif sel == connection_status_index and is_input_matched(event, "confirm"):
                    start_connection_status_check(force=True)
                    config.menu_state = "pause_connection_status"
                    config.needs_redraw = True
                # Options ScreenScraper account: edit with the virtual keyboard
                # Option Back (dernière option)
                elif sel == back_index and is_input_matched(event, "confirm"):
                    config.menu_state = "pause_menu"
                    config.last_state_change_time = pygame.time.get_ticks()
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        elif config.menu_state == "pause_api_keys_status":
            if is_input_matched(event, "cancel") or is_input_matched(event, "confirm") or is_input_matched(event, "start"):
                config.menu_state = "pause_settings_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        elif config.menu_state == "pause_connection_status":
            if is_input_matched(event, "cancel") or is_input_matched(event, "confirm") or is_input_matched(event, "start"):
                config.menu_state = "pause_settings_menu"
                config.last_state_change_time = pygame.time.get_ticks()
                config.needs_redraw = True

        elif config.menu_state == "screenscraper_input":
            from display import SCREENSCRAPER_KEYBOARD_LAYOUT
            row, col = getattr(config, 'ss_input_selected_key', (0, 0))
            rows, cols = len(SCREENSCRAPER_KEYBOARD_LAYOUT), len(SCREENSCRAPER_KEYBOARD_LAYOUT[0])
            field_name = "ss_input_" + config.ss_input_field
            value = str(getattr(config, field_name, ""))
            keyboard_handled = False
            if event.type == pygame.KEYDOWN and not getattr(config, "joystick", False):
                if event.key == pygame.K_TAB:
                    config.ss_input_field = "password" if config.ss_input_field == "username" else "username"
                    keyboard_handled = True
                elif event.key == pygame.K_BACKSPACE:
                    setattr(config, field_name, value[:-1])
                    keyboard_handled = True
                else:
                    typed_char = getattr(event, "unicode", "") or ""
                    if not (event.mod & (pygame.KMOD_CTRL | pygame.KMOD_ALT)) and typed_char.isprintable():
                        setattr(config, field_name, value + typed_char)
                        keyboard_handled = True

            if not keyboard_handled:
                if getattr(config, "joystick", False) and is_input_matched(event, "up"):
                    config.ss_input_selected_key = ((row - 1) % rows, col)
                elif getattr(config, "joystick", False) and is_input_matched(event, "down"):
                    config.ss_input_selected_key = ((row + 1) % rows, col)
                elif getattr(config, "joystick", False) and is_input_matched(event, "left"):
                    config.ss_input_selected_key = (row, (col - 1) % cols)
                elif getattr(config, "joystick", False) and is_input_matched(event, "right"):
                    config.ss_input_selected_key = (row, (col + 1) % cols)
                elif is_input_matched(event, "confirm") and getattr(config, "joystick", False):
                    char = SCREENSCRAPER_KEYBOARD_LAYOUT[row][col]
                    setattr(config, field_name, value + (char.upper() if config.ss_input_shift else char))
                elif is_input_matched(event, "delete"):
                    setattr(config, field_name, value[:-1])
                elif is_input_matched(event, "space"):
                    setattr(config, field_name, value + " ")
                elif is_input_matched(event, "filter"):
                    config.ss_input_shift = not config.ss_input_shift
                elif is_input_matched(event, "page_up") or is_input_matched(event, "page_down"):
                    config.ss_input_field = "password" if config.ss_input_field == "username" else "username"
                elif is_input_matched(event, "history") or (
                    not getattr(config, "joystick", False) and is_input_matched(event, "confirm")
                ):
                    _save_screenscraper_account()
                    config.menu_state = validate_menu_state(getattr(config, "ss_input_return_state", "pause_scrap_menu"))
                    config.last_state_change_time = pygame.time.get_ticks()
                elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                    config.menu_state = validate_menu_state(getattr(config, "ss_input_return_state", "pause_scrap_menu"))
                    config.last_state_change_time = pygame.time.get_ticks()
            config.needs_redraw = True

        elif config.menu_state == "media_manager":
            from media_manager import manager
            rows = manager.rows()
            sel = min(getattr(config, 'media_manager_selection', 0), len(rows) - 1)
            row_type, group = rows[sel]
            if is_input_matched(event, "history"):
                if manager.running:
                    manager.cancel()
                elif manager.pending:
                    manager.start(resume=True)
                    config.media_manager_selection = 0
                elif manager.estimate()[0]:
                    manager.start()
            elif is_input_matched(event, "up"):
                config.media_manager_selection = (sel - 1) % len(rows)
            elif is_input_matched(event, "down"):
                config.media_manager_selection = (sel + 1) % len(rows)
            elif row_type == "profile" and not manager.running and (is_input_matched(event, "confirm") or is_input_matched(event, "left") or is_input_matched(event, "right")):
                manager.profile = "max" if manager.profile == "default" else "default"
            elif is_input_matched(event, "confirm"):
                if row_type == "action":
                    if manager.running:
                        manager.cancel()
                    elif manager.estimate()[0]:
                        manager.start()
                elif row_type == "resume":
                    manager.start(resume=True)
                    config.media_manager_selection = 0
                elif row_type == "select_all" and not manager.running:
                    manager.toggle_all()
                elif row_type == "platform" and group["platform_id"] and not manager.running:
                    manager.selected ^= {group["folder"]}
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                # Download keeps running in the background.
                config.menu_state = "pause_scrap_menu"
                config.last_state_change_time = pygame.time.get_ticks()
            config.needs_redraw = True

        # Aide contrôles
        elif config.menu_state == "controls_help":
            if is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Retour au menu pause depuis controls_help")

        # Menu Affichage (layout, police, moniteur, mode écran, unsupported, extensions, filtres)
        elif config.menu_state == "display_menu":
            sel = getattr(config, 'display_menu_selection', 0)
            num_options = 7  # Layout, Font, Monitor, Mode, Unsupported, Extensions, Filters
            if is_input_matched(event, "up"):
                config.display_menu_selection = (sel - 1) % num_options
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.display_menu_selection = (sel + 1) % num_options
                config.needs_redraw = True
            elif is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm"):
                # 0: layout change
                if sel == 0 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    layouts = DISPLAY_GRID_LAYOUTS
                    try:
                        idx = layouts.index((config.GRID_COLS, config.GRID_ROWS))
                    except ValueError:
                        idx = 1
                    idx = (idx - 1) % len(layouts) if is_input_matched(event, "left") else (idx + 1) % len(layouts)
                    new_cols, new_rows = layouts[idx]
                    try:
                        set_display_grid(new_cols, new_rows)
                    except Exception as e:
                        logger.error(f"Erreur set_display_grid: {e}")
                    config.GRID_COLS = new_cols
                    config.GRID_ROWS = new_rows
                    config.needs_redraw = True
                    try:
                        config.popup_message = _("popup_layout_changed").format(new_cols, new_rows) if _ else f"Layout {new_cols}x{new_rows} applied immediately; no restart needed."
                        config.popup_timer = 3000
                    except Exception as e:
                        logger.error(f"Erreur lors de l'affichage du changement de layout: {e}")
                # 1: font size adjust
                elif sel == 1 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    opts = getattr(config, 'font_scale_options', [0.75, 1.0, 1.25, 1.5, 1.75])
                    idx = getattr(config, 'current_font_scale_index', 1)
                    idx = max(0, idx - 1) if is_input_matched(event, "left") else min(len(opts)-1, idx + 1)
                    if idx != getattr(config, 'current_font_scale_index', 1):
                        config.current_font_scale_index = idx
                        scale = opts[idx]
                        config.accessibility_settings["font_scale"] = scale
                        try:
                            save_accessibility_settings(config.accessibility_settings)
                        except Exception as e:
                            logger.error(f"Erreur sauvegarde accessibilité: {e}")
                        try:
                            config.init_font()
                        except Exception as e:
                            logger.error(f"Erreur init polices: {e}")
                        config.needs_redraw = True
                # 2: monitor selection (new)
                elif sel == 2 and (is_input_matched(event, "left") or is_input_matched(event, "right")):
                    try:
                        from rgsx_settings import get_display_monitor, set_display_monitor, get_available_monitors
                        monitors = get_available_monitors()
                        num_monitors = len(monitors)
                        if num_monitors > 1:
                            current = get_display_monitor()
                            new_monitor = (current - 1) % num_monitors if is_input_matched(event, "left") else (current + 1) % num_monitors
                            set_display_monitor(new_monitor)
                            config.needs_redraw = True
                            # Informer l'utilisateur qu'un redémarrage est nécessaire
                            config.popup_message = _("display_monitor_restart_required")
                            config.popup_timer = 3000
                        else:
                            config.popup_message = _("display_monitor_single_only")
                            config.popup_timer = 2000
                            config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur changement moniteur: {e}")
                # 3: fullscreen/windowed toggle (new)
                elif sel == 3 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        from rgsx_settings import get_display_fullscreen, set_display_fullscreen
                        current = get_display_fullscreen()
                        new_val = set_display_fullscreen(not current)
                        config.needs_redraw = True
                        # Informer l'utilisateur qu'un redémarrage est nécessaire
                        config.popup_message = _("display_mode_restart_required")
                        config.popup_timer = 3000
                    except Exception as e:
                        logger.error(f"Erreur toggle fullscreen: {e}")
                # 4: toggle unsupported (was 2)
                elif sel == 4 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_show_unsupported_platforms()
                        new_val = set_show_unsupported_platforms(not current)
                        load_sources()
                        config.popup_message = _("menu_show_unsupported_enabled") if new_val else _("menu_show_unsupported_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle unsupported: {e}")
                # 5: toggle allow unknown extensions (was 3)
                elif sel == 5 and (is_input_matched(event, "left") or is_input_matched(event, "right") or is_input_matched(event, "confirm")):
                    try:
                        current = get_allow_unknown_extensions()
                        new_val = set_allow_unknown_extensions(not current)
                        config.popup_message = _("menu_allow_unknown_ext_enabled") if new_val else _("menu_allow_unknown_ext_disabled")
                        config.popup_timer = 3000
                        config.needs_redraw = True
                    except Exception as e:
                        logger.error(f"Erreur toggle allow_unknown_extensions: {e}")
                # 6: open filter platforms menu (was 4)
                elif sel == 6 and (is_input_matched(event, "confirm") or is_input_matched(event, "right")):
                    # Remember return target so the filter menu can go back to display
                    config.filter_return_to = "display_menu"
                    config.menu_state = "filter_platforms"
                    config.selected_filter_index = 0
                    config.filter_platforms_scroll_offset = 0
                    config.filter_platforms_source_map = {}
                    config.filter_platforms_expanded_sources = []
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True

        # Remap controls
        elif config.menu_state == "controls_mapping":
            if is_input_matched(event, "cancel"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
                logger.debug("Retour à pause_menu depuis controls_mapping")
        
        # Prompt de mise à jour automatique de la liste des jeux
        elif config.menu_state == "gamelist_update_prompt":
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.gamelist_update_selection = 1 - config.gamelist_update_selection
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.gamelist_update_selection == 1:  # Oui
                    logger.info("Utilisateur a accepté la mise à jour de la liste des jeux")
                    # Lancer le téléchargement
                    config.download_tasks.clear()
                    config.pending_download = None
                    # Catalog updates are synchronized from the HTTPS API.
                    config.menu_state = "platform"
                    config.needs_redraw = True
                else:  # Non
                    logger.info("Utilisateur a refusé la mise à jour de la liste des jeux")
                    from rgsx_settings import set_last_gamelist_prompt_remote_update
                    set_last_gamelist_prompt_remote_update(getattr(config, 'gamelist_remote_update_timestamp', None))
                    config.menu_state = "platform"
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                logger.info("Utilisateur a annulé le prompt de mise à jour")
                from rgsx_settings import set_last_gamelist_prompt_remote_update
                set_last_gamelist_prompt_remote_update(getattr(config, 'gamelist_remote_update_timestamp', None))
                config.menu_state = "platform"
                config.needs_redraw = True
        
        # Configuration du dossier personnalisé pour une plateforme
        elif config.menu_state == "platform_folder_config":
            # Options: 0=Current path, 1=Browse, 2=Reset, 3=Cancel
            if is_input_matched(event, "up") or is_input_matched(event, "down"):
                total_options = 4
                if is_input_matched(event, "up"):
                    config.platform_folder_selection = (config.platform_folder_selection - 1) % total_options
                else:
                    config.platform_folder_selection = (config.platform_folder_selection + 1) % total_options
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                from rgsx_settings import get_platform_custom_path, set_platform_custom_path
                platform_name = config.platform_config_name
                
                if config.platform_folder_selection == 0:  # Show current path
                    current_path = get_platform_custom_path(platform_name)
                    if current_path:
                        config.popup_message = current_path
                    else:
                        # Afficher le chemin par défaut en utilisant le vrai nom de dossier
                        folder_name = _get_dest_folder_name(platform_name)
                        default_path = os.path.join(config.ROMS_FOLDER, folder_name)
                        config.popup_message = _("platform_folder_default_path").format(default_path) if _ else f"Default: {default_path}"
                    config.popup_timer = 5000
                    config.needs_redraw = True
                elif config.platform_folder_selection == 1:  # Browse
                    # Ouvrir le navigateur de dossiers intégré
                    current_path = get_platform_custom_path(platform_name)
                    if not current_path or not os.path.isdir(current_path):
                        # Démarrer depuis le dossier ROMS par défaut
                        current_path = config.ROMS_FOLDER
                    config.folder_browser_path = current_path
                    config.folder_browser_selection = 0
                    config.folder_browser_scroll_offset = 0
                    config.folder_browser_mode = "platform"
                    _set_folder_browser_location(current_path, reset_selection=True)
                    config.menu_state = "folder_browser"
                    config.needs_redraw = True
                elif config.platform_folder_selection == 2:  # Reset
                    set_platform_custom_path(platform_name, "")
                    config.popup_message = _("platform_folder_reset").format(platform_name) if _ else f"Folder reset for {platform_name}"
                    config.popup_timer = 3000
                    logger.info(f"Dossier personnalisé réinitialisé pour {platform_name}")
                    config.menu_state = "platform"
                    config.needs_redraw = True
                elif config.platform_folder_selection == 3:  # Cancel
                    config.menu_state = "platform"
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = "platform"
                config.needs_redraw = True
        
        # Navigateur de dossiers intégré
        elif config.menu_state == "folder_browser":
            if is_input_matched(event, "up"):
                if config.folder_browser_selection > 0:
                    config.folder_browser_selection -= 1
                    # Ajuster le scroll
                    if config.folder_browser_selection < config.folder_browser_scroll_offset:
                        config.folder_browser_scroll_offset = config.folder_browser_selection
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                if config.folder_browser_selection < len(config.folder_browser_items) - 1:
                    config.folder_browser_selection += 1
                    # Ajuster le scroll
                    if config.folder_browser_selection >= config.folder_browser_scroll_offset + config.folder_browser_visible_items:
                        config.folder_browser_scroll_offset = config.folder_browser_selection - config.folder_browser_visible_items + 1
                config.needs_redraw = True
            elif is_input_matched(event, "page_up"):
                jump_size = 10
                if config.folder_browser_selection > 0:
                    config.folder_browser_selection = max(0, config.folder_browser_selection - jump_size)
                    config.folder_browser_scroll_offset = min(
                        config.folder_browser_scroll_offset,
                        config.folder_browser_selection
                    )
                config.needs_redraw = True
            elif is_input_matched(event, "page_down"):
                jump_size = 10
                if config.folder_browser_selection < len(config.folder_browser_items) - 1:
                    config.folder_browser_selection = min(
                        len(config.folder_browser_items) - 1,
                        config.folder_browser_selection + jump_size
                    )
                    if config.folder_browser_selection >= config.folder_browser_scroll_offset + config.folder_browser_visible_items:
                        config.folder_browser_scroll_offset = config.folder_browser_selection - config.folder_browser_visible_items + 1
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.folder_browser_items:
                    selected_item = config.folder_browser_items[config.folder_browser_selection]
                    if selected_item == "..":
                        current_path = config.folder_browser_path
                        if _is_windows_os() and _is_windows_drive_root(current_path):
                            parent = ""
                        else:
                            parent = os.path.dirname(current_path) if current_path else ("" if _is_windows_os() else "/")
                        if parent != current_path:
                            _set_folder_browser_location(parent, reset_selection=True)
                    else:
                        if _is_windows_os() and not config.folder_browser_path:
                            new_path = selected_item
                        else:
                            new_path = os.path.join(config.folder_browser_path, selected_item)
                        if os.path.isdir(new_path):
                            _set_folder_browser_location(new_path, reset_selection=True)
                config.needs_redraw = True
            elif is_input_matched(event, "history"):
                # Valider et sélectionner le dossier actuel (touche X/Y)
                browser_mode = getattr(config, 'folder_browser_mode', 'platform')
                selected_path = config.folder_browser_path

                if not selected_path or not os.path.isdir(selected_path):
                    config.popup_message = "Please enter a drive/folder first"
                    config.popup_timer = 2200
                    config.needs_redraw = True
                    return action
                
                if browser_mode == "roms_root":
                    # Mode dossier ROMs principal
                    from rgsx_settings import set_roms_folder
                    set_roms_folder(selected_path)
                    config.popup_message = _("roms_folder_set").format(selected_path) if _ else f"ROMs folder set: {selected_path}"
                    config.popup_timer = 5000
                    logger.info(f"Dossier ROMs principal défini: {selected_path}")
                    # Informer qu'un redémarrage est nécessaire
                    config.popup_message = _("roms_folder_set_restart").format(selected_path) if _ else f"ROMs folder set: {selected_path}\nRestart required!"
                    config.menu_state = "pause_settings_menu"
                elif browser_mode == "history_move":
                    entry = config.history[config.current_history_item] if config.history and config.current_history_item < len(config.history) else None
                    actual_matches = getattr(config, 'history_actual_matches', None) or []
                    if not actual_matches and entry:
                        actual_matches = get_existing_history_matches(entry)

                    source_paths = [match_path for _, match_path in actual_matches]
                    if not source_paths:
                        actual_path = getattr(config, 'history_actual_path', None)
                        if actual_path:
                            source_paths = [actual_path]

                    success, moved_matches, error_message = move_files_to_directory(source_paths, selected_path)
                    if success:
                        config.history_actual_matches = moved_matches
                        if moved_matches:
                            config.history_actual_filename, config.history_actual_path = moved_matches[0]
                        if entry is not None:
                            entry["moved_paths"] = [path for _, path in moved_matches]
                            save_history(config.history)
                        config.popup_message = _("history_move_success").format(len(moved_matches), selected_path) if _ else f"Moved {len(moved_matches)} file(s) to {selected_path}"
                        config.popup_timer = 3000
                        logger.info(f"Déplacement historique terminé vers {selected_path}: {len(moved_matches)} fichier(s)")
                    else:
                        config.popup_message = _("history_move_error").format(error_message) if _ else f"Move error: {error_message}"
                        config.popup_timer = 4000
                        logger.error(f"Erreur déplacement historique vers {selected_path}: {error_message}")
                    config.menu_state = "history_show_folder"
                else:
                    # Mode dossier plateforme
                    from rgsx_settings import set_platform_custom_path
                    platform_name = config.platform_config_name
                    set_platform_custom_path(platform_name, selected_path)
                    config.popup_message = _("platform_folder_set").format(platform_name, selected_path) if _ else f"Folder set for {platform_name}: {selected_path}"
                    config.popup_timer = 3000
                    logger.info(f"Dossier personnalisé défini pour {platform_name}: {selected_path}")
                    config.menu_state = "platform"
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                # Annuler et revenir au menu approprié selon le mode
                browser_mode = getattr(config, 'folder_browser_mode', 'platform')
                if browser_mode == "roms_root":
                    config.menu_state = "pause_settings_menu"
                elif browser_mode == "history_move":
                    config.menu_state = "history_show_folder"
                else:
                    config.menu_state = "platform_folder_config"
                config.needs_redraw = True
            elif is_input_matched(event, "clear_history"):
                # Créer un nouveau dossier
                config.new_folder_name = ""
                config.new_folder_selected_key = (0, 0)
                config.menu_state = "folder_browser_new_folder"
                config.needs_redraw = True
                logger.debug("Ouverture mode création de dossier")
        
        # Création d'un nouveau dossier dans le folder browser
        elif config.menu_state == "folder_browser_new_folder":
            keyboard_layout = [
                ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
                ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
                ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
                ['W', 'X', 'C', 'V', 'B', 'N', '-', '_', '.']
            ]
            row, col = getattr(config, 'new_folder_selected_key', (0, 0))
            max_row = len(keyboard_layout) - 1
            max_col = len(keyboard_layout[row]) - 1
            
            if is_input_matched(event, "up"):
                if row == 0:
                    row = max_row + (1 if col <= len(keyboard_layout[max_row]) - 1 else 0)
                if row > 0:
                    config.new_folder_selected_key = (row - 1, min(col, len(keyboard_layout[row - 1]) - 1))
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                if row == max_row:
                    row = -1
                if row < max_row:
                    config.new_folder_selected_key = (row + 1, min(col, len(keyboard_layout[row + 1]) - 1))
                config.needs_redraw = True
            elif is_input_matched(event, "left"):
                if col == 0:
                    col = max_col + 1
                if col > 0:
                    config.new_folder_selected_key = (row, col - 1)
                config.needs_redraw = True
            elif is_input_matched(event, "right"):
                if col == max_col:
                    col = -1
                if col < max_col:
                    config.new_folder_selected_key = (row, col + 1)
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                # Ajouter le caractère sélectionné
                config.new_folder_name = getattr(config, 'new_folder_name', '') + keyboard_layout[row][col]
                config.needs_redraw = True
            elif is_input_matched(event, "delete"):
                # Supprimer le dernier caractère
                if getattr(config, 'new_folder_name', ''):
                    config.new_folder_name = config.new_folder_name[:-1]
                config.needs_redraw = True
            elif is_input_matched(event, "space"):
                # Ajouter un espace
                config.new_folder_name = getattr(config, 'new_folder_name', '') + " "
                config.needs_redraw = True
            elif is_input_matched(event, "history"):
                # Valider et créer le dossier
                folder_name = getattr(config, 'new_folder_name', '').strip()
                if folder_name:
                    new_folder_path = os.path.join(config.folder_browser_path, folder_name)
                    try:
                        os.makedirs(new_folder_path, exist_ok=True)
                        logger.info(f"Dossier créé: {new_folder_path}")
                        config.popup_message = _("folder_created").format(folder_name) if _ else f"Folder created: {folder_name}"
                        config.popup_timer = 2000
                        config.folder_browser_items = _load_folder_browser_items(config.folder_browser_path)
                        if folder_name in config.folder_browser_items:
                            config.folder_browser_selection = config.folder_browser_items.index(folder_name)
                            if config.folder_browser_selection >= config.folder_browser_visible_items:
                                config.folder_browser_scroll_offset = config.folder_browser_selection - config.folder_browser_visible_items + 1
                    except Exception as e:
                        logger.error(f"Erreur création dossier {new_folder_path}: {e}")
                        config.popup_message = _("folder_create_error").format(str(e)) if _ else f"Error: {e}"
                        config.popup_timer = 3000
                config.menu_state = "folder_browser"
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                # Annuler et revenir au folder browser
                config.menu_state = "folder_browser"
                config.needs_redraw = True
        
        # Refresh the catalog directly from the database.
        elif config.menu_state == "reload_games_data":
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.redownload_confirm_selection = 1 - config.redownload_confirm_selection
                config.needs_redraw = True
                logger.debug(f"Changement sélection reload_games_data: {config.redownload_confirm_selection}")
            elif is_input_matched(event, "confirm"):
                logger.debug(f"Action confirm dans reload_games_data, sélection={config.redownload_confirm_selection}")
                if config.redownload_confirm_selection == 1:  # Oui
                    return_state = validate_menu_state(config.previous_menu_state)
                    try:
                        platform_count, visible_count = refresh_catalog_from_database()
                        if return_state == "game" and not config.platforms:
                            return_state = "platform"
                        config.menu_state = return_state
                        config.popup_message = _("popup_redownload_success").format(platform_count, visible_count)
                        config.popup_timer = 3500
                        config.needs_redraw = True
                        logger.info(
                            "Catalogue DB actualisé: %s plateformes (%s visibles)",
                            platform_count,
                            visible_count,
                        )
                    except Exception as exc:
                        logger.exception("Échec du rafraîchissement DB depuis le menu Games")
                        config.previous_menu_state = "reload_games_data"
                        config.menu_state = "error"
                        config.error_message = _("error_catalog_refresh_failed")
                        config.needs_redraw = True
                else:  # Non
                    config.menu_state = validate_menu_state(config.previous_menu_state)
                    config.needs_redraw = True
                    logger.debug(f"Annulation du redownload, retour à {config.menu_state}")
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = validate_menu_state(config.previous_menu_state)
                config.needs_redraw = True
                logger.debug(f"Retour à {config.menu_state} depuis reload_games_data")

        # Confirmation reset settings (warning + yes/no)
        elif config.menu_state == "reset_settings_confirm":
            if is_input_matched(event, "left") or is_input_matched(event, "right"):
                config.reset_settings_confirm_selection = 1 - int(getattr(config, 'reset_settings_confirm_selection', 0))
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if int(getattr(config, 'reset_settings_confirm_selection', 0)) == 1:  # Yes
                    try:
                        settings_path = getattr(config, 'RGSX_SETTINGS_PATH', '')
                        if settings_path and os.path.exists(settings_path):
                            os.remove(settings_path)
                            logger.info(f"Paramètres supprimés: {settings_path}")
                        else:
                            logger.info(f"Aucun fichier paramètres à supprimer: {settings_path}")

                        restart_msg = _("popup_settings_reset_restarting") if _ else "Default settings reset. Restarting..."
                        if not restart_msg or restart_msg == "popup_settings_reset_restarting":
                            restart_msg = "Default settings reset. Restarting..."

                        config.menu_state = "restart_popup"
                        config.popup_message = restart_msg
                        config.popup_timer = 2000
                        config.last_state_change_time = pygame.time.get_ticks()
                        config.needs_redraw = True
                        restart_application(2000)
                    except Exception as e:
                        logger.error(f"Erreur reset paramètres par défaut: {e}")
                        err_tpl = _("popup_settings_reset_error") if _ else "Unable to reset settings: {0}"
                        if not err_tpl or err_tpl == "popup_settings_reset_error":
                            config.popup_message = f"Unable to reset settings: {e}"
                        else:
                            try:
                                config.popup_message = err_tpl.format(str(e))
                            except Exception:
                                config.popup_message = f"Unable to reset settings: {e}"
                        config.popup_timer = 5000
                        config.menu_state = "pause_menu"
                        config.needs_redraw = True
                else:  # No
                    config.menu_state = "pause_menu"
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel") or is_input_matched(event, "start"):
                config.menu_state = "pause_menu"
                config.needs_redraw = True
       
       
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

        # Menu de choix filtrage
        elif config.menu_state == "filter_menu_choice":
            entries = getattr(config, 'filter_menu_entries', []) or _build_filter_menu_entries(getattr(config, 'filter_menu_context', 'global'))
            return_state = validate_menu_state(getattr(config, 'filter_menu_return_state', None))
            total_entries = max(1, len(entries))
            if is_input_matched(event, "up"):
                config.selected_filter_choice = (config.selected_filter_choice - 1) % total_entries
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.selected_filter_choice = (config.selected_filter_choice + 1) % total_entries
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                selected_entry = entries[config.selected_filter_choice] if entries else {'key': 'back'}
                selected_key = selected_entry.get('key')
                if selected_key == 'global_search':
                    config.global_search_return_state = return_state
                    enter_global_search()
                elif selected_key == 'platform_search':
                    config.search_mode = True
                    config.search_query = ""
                    if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                        config.filtered_games = _apply_sorted_active_filters()
                    else:
                        config.filtered_games = config.games
                    config.current_game = 0
                    config.scroll_offset = 0
                    config.selected_key = (0, 0)
                    config.menu_state = "game"
                    config.needs_redraw = True
                    logger.debug("Entrée en mode recherche sur cette plateforme")
                elif selected_key == 'global_filter':
                    from game_filters import GameFilters
                    from rgsx_settings import load_game_filters

                    if not hasattr(config, 'game_filter_obj'):
                        config.game_filter_obj = GameFilters()
                        filter_dict = load_game_filters()
                        if filter_dict:
                            config.game_filter_obj.load_from_dict(filter_dict)

                    config.filter_target_scope = 'local' if getattr(config, 'filter_menu_context', 'global') == 'game' else 'saved'
                    config.global_search_return_state = return_state
                    config.previous_menu_state = 'filter_menu_choice'
                    config.menu_state = "filter_advanced"
                    config.selected_filter_option = 0
                    config.filter_advanced_scroll_offset = 0
                    config.needs_redraw = True
                    logger.debug("Entrée en filtrage avancé global")
                elif selected_key == 'global_sort':
                    config.global_search_return_state = return_state
                    config.global_sort_selected = _get_global_sort_index()
                    config.menu_state = 'global_sort_menu'
                    config.previous_menu_state = 'filter_menu_choice'
                    config.needs_redraw = True
                    logger.debug("Ouverture du menu de tri global")
                else:
                    config.menu_state = return_state
                    config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                config.menu_state = return_state
                config.needs_redraw = True
                logger.debug(f"Retour depuis menu filtre vers {config.menu_state}")

        elif config.menu_state == 'global_sort_menu':
            total_items = len(GLOBAL_SORT_OPTIONS) + 1
            if is_input_matched(event, 'up'):
                config.global_sort_selected = (config.global_sort_selected - 1) % total_items
                config.needs_redraw = True
            elif is_input_matched(event, 'down'):
                config.global_sort_selected = (config.global_sort_selected + 1) % total_items
                config.needs_redraw = True
            elif is_input_matched(event, 'confirm'):
                if config.global_sort_selected < len(GLOBAL_SORT_OPTIONS):
                    config.global_sort_option = set_global_sort_option(GLOBAL_SORT_OPTIONS[config.global_sort_selected][0])
                    if getattr(config, 'filter_menu_context', 'global') == 'game':
                        config.games = _sort_local_games(config.games)
                        if config.search_query:
                            config.filtered_games = filter_games_by_search_query()
                            config.filter_active = True
                        elif hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
                            config.filtered_games = _sort_local_games(config.game_filter_obj.apply_filters(config.games))
                            config.filter_active = True
                        else:
                            config.filtered_games = config.games
                            config.filter_active = False
                        config.current_game = 0
                        config.scroll_offset = 0
                        config.menu_state = validate_menu_state(getattr(config, 'filter_menu_return_state', None))
                        config.needs_redraw = True
                        logger.debug(f"Tri local applique sur la liste courante ({config.global_sort_option})")
                    else:
                        enter_global_sorted_results()
                else:
                    config.menu_state = 'filter_menu_choice'
                    config.needs_redraw = True
            elif is_input_matched(event, 'cancel'):
                config.menu_state = 'filter_menu_choice'
                config.needs_redraw = True

        # Filtrage avancé
        elif config.menu_state == "filter_advanced":
            from game_filters import GameFilters
            from rgsx_settings import save_game_filters
            
            # Initialiser le filtre si nécessaire
            if not hasattr(config, 'game_filter_obj'):
                config.game_filter_obj = GameFilters()
                from rgsx_settings import load_game_filters
                filter_dict = load_game_filters()
                if filter_dict:
                    config.game_filter_obj.load_from_dict(filter_dict)
            
            # Construire la liste linéaire des éléments sélectionnables (pour simplifier l'indexation)
            # Régions individuelles
            num_regions = len(GameFilters.REGIONS)
            region_cols = _get_advanced_filter_region_columns()
            # Options toggle/button
            num_other_options = 3  # hide_non_release, one_rom_per_game, priority_config
            # Boutons en bas
            num_buttons = 3  # apply, reset, back
            
            total_items = num_regions + num_other_options + num_buttons
            
            if is_input_matched(event, "up"):
                # Navigation verticale dans la grille ou entre sections
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    if config.selected_filter_option >= region_cols:
                        # Monter d'une ligne
                        config.selected_filter_option -= region_cols
                    else:
                        # Déjà en haut, aller aux boutons
                        config.selected_filter_option = total_items - 2  # Bouton du milieu (reset)
                else:
                    # Dans les options ou boutons, monter normalement
                    config.selected_filter_option = (config.selected_filter_option - 1) % total_items
                
                config.needs_redraw = True
                update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            
            elif is_input_matched(event, "down"):
                # Navigation verticale
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    if config.selected_filter_option + region_cols < num_regions:
                        # Descendre d'une ligne
                        config.selected_filter_option += region_cols
                    else:
                        # Aller aux autres options
                        config.selected_filter_option = num_regions
                else:
                    # Dans les options ou boutons, descendre normalement
                    config.selected_filter_option = (config.selected_filter_option + 1) % total_items
                
                config.needs_redraw = True
                update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else 
                                event.button if event.type == pygame.JOYBUTTONDOWN else 
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else 
                                event.value)
            
            elif is_input_matched(event, "left"):
                # Navigation horizontale
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    if config.selected_filter_option % region_cols > 0:
                        config.selected_filter_option -= 1
                    config.needs_redraw = True
                elif config.selected_filter_option >= num_regions + num_other_options:
                    # Dans les boutons en bas
                    button_idx = config.selected_filter_option - (num_regions + num_other_options)
                    button_idx = (button_idx - 1) % num_buttons
                    config.selected_filter_option = num_regions + num_other_options + button_idx
                    config.needs_redraw = True
            
            elif is_input_matched(event, "right"):
                # Navigation horizontale
                if config.selected_filter_option < num_regions:
                    # Dans la grille des régions
                    current_col = config.selected_filter_option % region_cols
                    if current_col < region_cols - 1 and config.selected_filter_option + 1 < num_regions:
                        config.selected_filter_option += 1
                    config.needs_redraw = True
                elif config.selected_filter_option >= num_regions + num_other_options:
                    # Dans les boutons en bas
                    button_idx = config.selected_filter_option - (num_regions + num_other_options)
                    button_idx = (button_idx + 1) % num_buttons
                    config.selected_filter_option = num_regions + num_other_options + button_idx
                    config.needs_redraw = True
            
            elif is_input_matched(event, "confirm"):
                # Déterminer quel élément a été sélectionné
                if config.selected_filter_option < num_regions:
                    # C'est une région
                    region = GameFilters.REGIONS[config.selected_filter_option]
                    current_state = config.game_filter_obj.region_filters.get(region, 'include')
                    if current_state == 'include':
                        config.game_filter_obj.region_filters[region] = 'exclude'
                    else:
                        config.game_filter_obj.region_filters[region] = 'include'
                    config.needs_redraw = True
                    logger.debug(f"Filtre région {region} modifié: {config.game_filter_obj.region_filters[region]}")
                
                elif config.selected_filter_option < num_regions + num_other_options:
                    # C'est une autre option
                    option_idx = config.selected_filter_option - num_regions
                    if option_idx == 0:
                        # hide_non_release
                        config.game_filter_obj.hide_non_release = not config.game_filter_obj.hide_non_release
                        config.needs_redraw = True
                        logger.debug("Toggle hide_non_release modifié")
                    elif option_idx == 1:
                        # one_rom_per_game
                        config.game_filter_obj.one_rom_per_game = not config.game_filter_obj.one_rom_per_game
                        config.needs_redraw = True
                        logger.debug("Toggle one_rom_per_game modifié")
                    elif option_idx == 2:
                        # priority_config
                        config.menu_state = "filter_priority_config"
                        config.selected_priority_index = 0
                        config.needs_redraw = True
                        logger.debug("Ouverture configuration priorité régions")
                
                else:
                    # C'est un bouton
                    button_idx = config.selected_filter_option - (num_regions + num_other_options)
                    if button_idx == 0:
                        # Apply
                        save_game_filters(config.game_filter_obj.to_dict())

                        if getattr(config, 'filter_target_scope', 'local') == 'global':
                            enter_global_filtered_results()
                        elif getattr(config, 'filter_target_scope', 'local') == 'saved':
                            config.menu_state = validate_menu_state(getattr(config, 'filter_menu_return_state', None))
                            config.needs_redraw = True
                        else:
                            if config.game_filter_obj.is_active():
                                config.filtered_games = _apply_sorted_active_filters()
                                config.filter_active = True
                            else:
                                config.filtered_games = config.games
                                config.filter_active = False

                            config.current_game = 0
                            config.scroll_offset = 0
                            config.menu_state = "game"
                            config.needs_redraw = True
                        logger.debug("Filtres appliqués")
                    
                    elif button_idx == 1:
                        # Reset
                        config.game_filter_obj.reset()
                        save_game_filters(config.game_filter_obj.to_dict())
                        if getattr(config, 'filter_target_scope', 'local') == 'global':
                            config.needs_redraw = True
                        elif getattr(config, 'filter_target_scope', 'local') == 'saved':
                            config.needs_redraw = True
                        else:
                            config.filtered_games = config.games
                            config.filter_active = False
                            config.needs_redraw = True
                        logger.debug("Filtres réinitialisés")
                    
                    elif button_idx == 2:
                        # Back
                        scope = getattr(config, 'filter_target_scope', 'local')
                        if scope == 'global':
                            config.menu_state = "filter_menu_choice"
                        elif scope == 'saved':
                            config.menu_state = validate_menu_state(getattr(config, 'filter_menu_return_state', None))
                        else:
                            config.menu_state = "game"
                        config.needs_redraw = True
                        logger.debug("Retour sans appliquer les filtres")
            
            elif is_input_matched(event, "cancel"):
                scope = getattr(config, 'filter_target_scope', 'local')
                if scope == 'global':
                    config.menu_state = "filter_menu_choice"
                elif scope == 'saved':
                    config.menu_state = validate_menu_state(getattr(config, 'filter_menu_return_state', None))
                else:
                    config.menu_state = "game"
                config.needs_redraw = True
                logger.debug("Annulation du filtrage avancé")

        # Configuration priorité régions
        elif config.menu_state == "filter_priority_config":
            from game_filters import GameFilters
            from rgsx_settings import save_game_filters
            
            if not hasattr(config, 'game_filter_obj'):
                config.game_filter_obj = GameFilters()
            
            priority_list = config.game_filter_obj.region_priority
            total_items = len(priority_list) + 1  # +1 pour le bouton Back
            
            if not hasattr(config, 'selected_priority_index'):
                config.selected_priority_index = 0
            
            if is_input_matched(event, "up"):
                config.selected_priority_index = (config.selected_priority_index - 1) % total_items
                config.needs_redraw = True
            elif is_input_matched(event, "down"):
                config.selected_priority_index = (config.selected_priority_index + 1) % total_items
                config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if config.selected_priority_index >= len(priority_list):
                    # Bouton Back : retour au menu filtrage avancé
                    save_game_filters(config.game_filter_obj.to_dict())
                    config.menu_state = "filter_advanced"
                    config.needs_redraw = True
                    logger.debug("Retour au filtrage avancé")
            elif is_input_matched(event, "left") and config.selected_priority_index < len(priority_list):
                # Monter la région dans la priorité
                idx = config.selected_priority_index
                if idx > 0:
                    priority_list[idx], priority_list[idx-1] = priority_list[idx-1], priority_list[idx]
                    config.selected_priority_index = idx - 1
                    config.needs_redraw = True
                    logger.debug(f"Priorité modifiée: {priority_list}")
            elif is_input_matched(event, "right") and config.selected_priority_index < len(priority_list):
                # Descendre la région dans la priorité
                idx = config.selected_priority_index
                if idx < len(priority_list) - 1:
                    priority_list[idx], priority_list[idx+1] = priority_list[idx+1], priority_list[idx]
                    config.selected_priority_index = idx + 1
                    config.needs_redraw = True
                    logger.debug(f"Priorité modifiée: {priority_list}")
            elif is_input_matched(event, "cancel"):
                # Retour sans sauvegarder
                config.menu_state = "filter_advanced"
                config.needs_redraw = True
                logger.debug("Annulation configuration priorité")

    # Menu filtre plateformes
        elif config.menu_state == "filter_platforms":
            def _extract_source(platform_name: str) -> str:
                match = re.search(r'\(([^()]+)\)\s*$', str(platform_name).strip())
                if match:
                    return match.group(1).strip()
                fallback = _("games_source_rgsx") if _ else "RGSX"
                return fallback if fallback != "games_source_rgsx" else "RGSX"

            def _build_source_map() -> dict:
                source_map_local = {}
                for entry in config.platform_dicts:
                    platform_name = entry.get("platform_name", "") if isinstance(entry, dict) else ""
                    platform_name = str(platform_name).strip()
                    if not platform_name:
                        continue
                    source_name = _extract_source(platform_name)
                    source_map_local.setdefault(source_name, []).append(platform_name)

                normalized = {}
                for source_name in sorted(source_map_local.keys(), key=lambda s: str(s).lower()):
                    unique_names = sorted(set(source_map_local.get(source_name, [])), key=lambda s: str(s).lower())
                    normalized[source_name] = unique_names
                return normalized

            def _all_platform_names(source_map_local: dict) -> list:
                names = []
                for source_name in sorted(source_map_local.keys(), key=lambda s: str(s).lower()):
                    names.extend(source_map_local.get(source_name, []))
                return names

            def _ensure_working_selection(source_map_local: dict) -> None:
                all_platform_names = _all_platform_names(source_map_local)
                current = getattr(config, 'filter_platforms_selection', [])
                current_map = {}
                if isinstance(current, list):
                    for item in current:
                        if isinstance(item, (list, tuple)) and len(item) == 2:
                            name = str(item[0]).strip()
                            if name:
                                current_map[name] = bool(item[1])

                expected_set = set(all_platform_names)
                if set(current_map.keys()) != expected_set:
                    settings_local = load_rgsx_settings()
                    hidden_platforms = set(settings_local.get("hidden_platforms", [])) if isinstance(settings_local, dict) else set()
                    config.filter_platforms_selection = [(name, name in hidden_platforms) for name in all_platform_names]
                    config.selected_filter_index = 0
                    config.filter_platforms_scroll_offset = 0
                    config.filter_platforms_dirty = False
                else:
                    config.filter_platforms_selection = [(name, current_map.get(name, False)) for name in all_platform_names]

            def _hidden_map() -> dict:
                return {name: bool(is_hidden) for name, is_hidden in config.filter_platforms_selection}

            def _set_hidden_map(hidden_map_local: dict, source_map_local: dict) -> None:
                ordered_names = _all_platform_names(source_map_local)
                config.filter_platforms_selection = [(name, bool(hidden_map_local.get(name, False))) for name in ordered_names]

            def _build_rows(source_map_local: dict, hidden_map_local: dict, expanded_sources_local: set) -> list:
                rows_local = []
                for source_name in sorted(source_map_local.keys(), key=lambda s: str(s).lower()):
                    platforms = source_map_local.get(source_name, [])
                    total = len(platforms)
                    hidden_count = sum(1 for platform_name in platforms if hidden_map_local.get(platform_name, False))
                    rows_local.append({
                        "type": "source",
                        "source": source_name,
                        "platforms": platforms,
                        "total": total,
                        "hidden_count": hidden_count,
                        "expanded": source_name in expanded_sources_local,
                    })
                    if source_name in expanded_sources_local:
                        for platform_name in platforms:
                            rows_local.append({
                                "type": "platform",
                                "source": source_name,
                                "platform": platform_name,
                                "hidden": bool(hidden_map_local.get(platform_name, False)),
                            })
                return rows_local

            def _return_from_filter() -> None:
                target = getattr(config, 'filter_return_to', 'pause_menu')
                config.menu_state = target
                if target == 'display_menu':
                    config.display_menu_selection = 3
                elif target == 'pause_display_menu':
                    config.pause_display_selection = 4
                else:
                    # Index visible de Settings (4 quand l'entrée Scrap est masquée)
                    config.selected_option = 4 if config.SCREENSCRAPER_TEMPORARILY_DISABLED else 5
                config.filter_return_to = None

            def _show_unsaved_exit_toast() -> None:
                if not getattr(config, 'filter_platforms_dirty', False):
                    return
                try:
                    msg_tpl = _("filter_unsaved_toast") if _ else ""
                    if msg_tpl and msg_tpl != "filter_unsaved_toast":
                        show_toast(msg_tpl, 3000)
                    else:
                        show_toast("Unsaved changes\nApply with History/Start before leaving", 3000)
                except Exception as toast_error:
                    logger.debug(f"Impossible d'afficher le toast unsaved filter: {toast_error}")

            def _apply_filter() -> None:
                settings_local = load_rgsx_settings()
                hidden_map_local = _hidden_map()
                hidden_list = sorted({name for name, is_hidden in hidden_map_local.items() if is_hidden}, key=lambda s: str(s).lower())
                settings_local["hidden_platforms"] = hidden_list
                save_rgsx_settings(settings_local)
                load_sources()
                try:
                    systems_per_page = config.GRID_COLS * config.GRID_ROWS
                    platform_group_count = len(getattr(config, "platform_groups", []) or config.platforms)
                    if config.current_page * systems_per_page >= platform_group_count:
                        config.current_page = 0
                    if config.selected_platform >= platform_group_count:
                        config.selected_platform = 0
                except Exception:
                    config.current_page = 0
                    config.selected_platform = 0
                config.filter_platforms_dirty = False
                _return_from_filter()

            source_map = _build_source_map()
            config.filter_platforms_source_map = source_map
            _ensure_working_selection(source_map)

            expanded_raw = getattr(config, 'filter_platforms_expanded_sources', [])
            expanded_sources = set(expanded_raw if isinstance(expanded_raw, list) else [])
            expanded_sources = {source for source in expanded_sources if source in source_map}
            config.filter_platforms_expanded_sources = sorted(expanded_sources, key=lambda s: str(s).lower())

            rows = _build_rows(source_map, _hidden_map(), expanded_sources)
            total_rows = len(rows)

            if total_rows <= 0:
                config.selected_filter_index = 0
            else:
                if config.selected_filter_index < 0:
                    config.selected_filter_index = 0
                elif config.selected_filter_index >= total_rows:
                    config.selected_filter_index = total_rows - 1

            if is_input_matched(event, "up"):
                if total_rows > 0:
                    if config.selected_filter_index > 0:
                        config.selected_filter_index -= 1
                    else:
                        config.selected_filter_index = total_rows - 1
                    config.needs_redraw = True
                update_key_state("up", True, event.type, event.key if event.type == pygame.KEYDOWN else
                                event.button if event.type == pygame.JOYBUTTONDOWN else
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else
                                event.value)
            elif is_input_matched(event, "down"):
                if total_rows > 0:
                    if config.selected_filter_index < total_rows - 1:
                        config.selected_filter_index += 1
                    else:
                        config.selected_filter_index = 0
                    config.needs_redraw = True
                update_key_state("down", True, event.type, event.key if event.type == pygame.KEYDOWN else
                                event.button if event.type == pygame.JOYBUTTONDOWN else
                                (event.axis, event.value) if event.type == pygame.JOYAXISMOTION else
                                event.value)
            elif is_input_matched(event, "left"):
                if total_rows > 0:
                    current_row = rows[config.selected_filter_index]
                    if current_row.get("type") == "source":
                        source_name = current_row.get("source")
                        if source_name in expanded_sources:
                            expanded_sources.discard(source_name)
                            config.filter_platforms_expanded_sources = sorted(expanded_sources, key=lambda s: str(s).lower())
                            config.needs_redraw = True
                    elif current_row.get("type") == "platform":
                        source_name = current_row.get("source")
                        if source_name in expanded_sources:
                            expanded_sources.discard(source_name)
                            config.filter_platforms_expanded_sources = sorted(expanded_sources, key=lambda s: str(s).lower())
                            refreshed_rows = _build_rows(source_map, _hidden_map(), expanded_sources)
                            for idx, row in enumerate(refreshed_rows):
                                if row.get("type") == "source" and row.get("source") == source_name:
                                    config.selected_filter_index = idx
                                    break
                            config.needs_redraw = True
            elif is_input_matched(event, "right"):
                if total_rows > 0:
                    current_row = rows[config.selected_filter_index]
                    source_name = current_row.get("source")
                    if current_row.get("type") == "source" and source_name not in expanded_sources:
                        expanded_sources.add(source_name)
                        config.filter_platforms_expanded_sources = sorted(expanded_sources, key=lambda s: str(s).lower())
                        config.needs_redraw = True
            elif is_input_matched(event, "confirm"):
                if total_rows > 0:
                    current_row = rows[config.selected_filter_index]
                    hidden_map = _hidden_map()
                    if current_row.get("type") == "source":
                        platforms = current_row.get("platforms", [])
                        all_visible = all(not hidden_map.get(platform_name, False) for platform_name in platforms)
                        new_hidden = True if all_visible else False
                        for platform_name in platforms:
                            hidden_map[platform_name] = new_hidden
                    else:
                        platform_name = current_row.get("platform")
                        hidden_map[platform_name] = not hidden_map.get(platform_name, False)
                    _set_hidden_map(hidden_map, source_map)
                    config.filter_platforms_dirty = True
                    config.needs_redraw = True
            elif is_input_matched(event, "page_up"):
                hidden_map = _hidden_map()
                for platform_name in list(hidden_map.keys()):
                    hidden_map[platform_name] = False
                _set_hidden_map(hidden_map, source_map)
                config.filter_platforms_dirty = True
                config.needs_redraw = True
            elif is_input_matched(event, "page_down"):
                hidden_map = _hidden_map()
                for platform_name in list(hidden_map.keys()):
                    hidden_map[platform_name] = True
                _set_hidden_map(hidden_map, source_map)
                config.filter_platforms_dirty = True
                config.needs_redraw = True
            elif is_input_matched(event, "history") or is_input_matched(event, "start"):
                _apply_filter()
                config.needs_redraw = True
            elif is_input_matched(event, "cancel"):
                _show_unsaved_exit_toast()
                _return_from_filter()
                config.needs_redraw = True


    # Gestion des relâchements de touches
    if event.type == pygame.KEYUP:
        # Vérifier quelle touche a été relâchée
        # Définir le mapping clavier (même que dans is_input_matched)
        keyboard_fallback = {
            "up": pygame.K_UP,
            "down": pygame.K_DOWN,
            "left": pygame.K_LEFT,
            "right": pygame.K_RIGHT,
            "confirm": pygame.K_RETURN,
            "cancel": pygame.K_ESCAPE,
            "page_up": pygame.K_PAGEUP,
            "page_down": pygame.K_PAGEDOWN,
        }
        
        for action_name in ["up", "down", "left", "right", "page_up", "page_down", "confirm", "cancel"]:
            # Vérifier d'abord le keyboard_fallback
            if action_name in keyboard_fallback and keyboard_fallback[action_name] == event.key:
                update_key_state(action_name, False)
            # Sinon vérifier la config normale
            elif config.controls_config.get(action_name, {}).get("type") == "key" and \
               config.controls_config.get(action_name, {}).get("key") == event.key:
                update_key_state(action_name, False)
                
            # Gestion spéciale pour confirm dans le menu game (ne dépend pas du key_state)
            if action_name == "confirm" and config.menu_state == "game" and \
               ((action_name in keyboard_fallback and keyboard_fallback[action_name] == event.key) or \
                (config.controls_config.get(action_name, {}).get("type") == "key" and \
                 config.controls_config.get(action_name, {}).get("key") == event.key)):
                    press_duration = current_time - config.confirm_press_start_time
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not config.confirm_long_press_triggered:
                        # Déclencher le téléchargement normal
                        games = config.filtered_games if config.filter_active or config.search_mode else config.games
                        if games:
                            url = games[config.current_game].url
                            game_name = games[config.current_game].name
                            platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                            logger.debug(f"Appui court sur confirm ({press_duration}ms), téléchargement pour {game_name}, URL: {url}")
                            if not _has_download_url(url, game_name):
                                config.confirm_press_start_time = 0
                                config.confirm_long_press_triggered = False
                                return action
                            
                            # Vérifier d'abord l'extension avant d'ajouter à l'historique
                            if is_1fichier_url(url):
                                ensure_download_provider_keys(False)
                                
                                # Avertissement si pas de clé (utilisation mode gratuit)
                                if missing_all_provider_keys():
                                    logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
                                
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        load_extensions_json()
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        state, task_id = start_or_queue_download(url, platform, game_name, config.pending_download[3])
                                        logger.debug(f"Début du téléchargement 1fichier: {game_name} pour {platform}, task_id={task_id}, state={state}")
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    config.error_message = "Extension non supportée ou erreur de téléchargement"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                            else:
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    extensions_data = load_extensions_json()
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        extensions_data
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        start_or_queue_download(url, platform, game_name, config.pending_download[3])
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    try:
                                        config.error_message = _("error_invalid_download_data")
                                    except Exception:
                                        config.error_message = "Invalid download data"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                    # Réinitialiser les flags
                    config.confirm_press_start_time = 0
                    config.confirm_long_press_triggered = False
            
            # Gestion spéciale pour confirm dans le menu platform (appui court = aller aux jeux)
            if action_name == "confirm" and config.menu_state == "platform" and \
               ((action_name in keyboard_fallback and keyboard_fallback[action_name] == event.key) or \
                (config.controls_config.get(action_name, {}).get("type") == "key" and \
                 config.controls_config.get(action_name, {}).get("key") == event.key)):
                    press_duration = current_time - getattr(config, 'platform_confirm_press_start_time', 0)
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not getattr(config, 'platform_confirm_long_press_triggered', False):
                        if _open_selected_platform(screen):
                            logger.debug(f"Appui court clavier sur confirm ({press_duration}ms), navigation vers les jeux de {config.platforms[config.current_platform]}")
                    # Réinitialiser les flags platform
                    config.platform_confirm_press_start_time = 0
                    config.platform_confirm_long_press_triggered = False
    
    elif event.type == pygame.JOYBUTTONUP:
        # Vérifier quel bouton a été relâché
        for action_name in ["up", "down", "left", "right", "page_up", "page_down", "confirm", "cancel"]:
            if config.controls_config.get(action_name, {}).get("type") == "button" and \
               config.controls_config.get(action_name, {}).get("button") == event.button:
                # Vérifier que cette action était bien activée par un bouton gamepad
                if action_name in key_states and key_states[action_name].get("event_type") == pygame.JOYBUTTONDOWN:
                    update_key_state(action_name, False)
                
                # Gestion spéciale pour confirm dans le menu game (ne dépend pas du key_state)
                if action_name == "confirm" and config.menu_state == "game":
                    press_duration = current_time - config.confirm_press_start_time
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not config.confirm_long_press_triggered:
                        # Déclencher le téléchargement normal (même code que pour KEYUP)
                        games = config.filtered_games if config.filter_active or config.search_mode else config.games
                        if games:
                            url = games[config.current_game].url
                            game_name = games[config.current_game].name
                            platform = config.platforms[config.current_platform]["name"] if isinstance(config.platforms[config.current_platform], dict) else config.platforms[config.current_platform]
                            logger.debug(f"Appui court sur confirm ({press_duration}ms), téléchargement pour {game_name}, URL: {url}")
                            if not _has_download_url(url, game_name):
                                config.confirm_press_start_time = 0
                                config.confirm_long_press_triggered = False
                                return action
                            
                            # Vérifier d'abord l'extension avant d'ajouter à l'historique
                            if is_1fichier_url(url):
                                ensure_download_provider_keys(False)
                                
                                # Avertissement si pas de clé (utilisation mode gratuit)
                                if missing_all_provider_keys():
                                    logger.warning("Aucune clé API - Mode gratuit 1fichier sera utilisé (attente requise)")
                                
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        load_extensions_json()
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        state, task_id = start_or_queue_download(url, platform, game_name, config.pending_download[3])
                                        logger.debug(f"Début du téléchargement 1fichier: {game_name} pour {platform}, task_id={task_id}, state={state}")
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    config.error_message = "Extension non supportée ou erreur de téléchargement"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                            else:
                                config.pending_download = check_extension_before_download(url, platform, game_name)
                                if config.pending_download:
                                    extensions_data = load_extensions_json()
                                    is_supported = is_extension_supported(
                                        sanitize_filename(game_name),
                                        platform,
                                        extensions_data
                                    )
                                    zip_ok = bool(config.pending_download[3])
                                    allow_unknown = get_allow_unknown_extensions()
                                    if (not is_supported and not zip_ok) and not allow_unknown:
                                        config.previous_menu_state = config.menu_state
                                        config.menu_state = "extension_warning"
                                        config.extension_confirm_selection = 0
                                        config.needs_redraw = True
                                        logger.debug(f"Extension non supportée, passage à extension_warning pour {game_name}")
                                    else:
                                        start_or_queue_download(url, platform, game_name, config.pending_download[3])
                                        config.pending_download = None
                                else:
                                    config.menu_state = "error"
                                    try:
                                        config.error_message = _("error_invalid_download_data")
                                    except Exception:
                                        config.error_message = "Invalid download data"
                                    config.pending_download = None
                                    config.needs_redraw = True
                                    logger.error(f"config.pending_download est None pour {game_name}")
                    # Réinitialiser les flags
                    config.confirm_press_start_time = 0
                    config.confirm_long_press_triggered = False
                
                # Gestion spéciale pour confirm dans le menu platform (appui court = aller aux jeux)
                if action_name == "confirm" and config.menu_state == "platform":
                    press_duration = current_time - getattr(config, 'platform_confirm_press_start_time', 0)
                    # Si appui court (< 2 secondes) et pas déjà traité par l'appui long
                    if press_duration < config.confirm_long_press_threshold and not getattr(config, 'platform_confirm_long_press_triggered', False):
                        if _open_selected_platform(screen):
                            logger.debug(f"Appui court sur confirm ({press_duration}ms), navigation vers les jeux de {config.platforms[config.current_platform]}")
                    # Réinitialiser les flags platform
                    config.platform_confirm_press_start_time = 0
                    config.platform_confirm_long_press_triggered = False
    
    elif event.type == pygame.JOYAXISMOTION:
        # Détection de relâchement d'axe
        # Pour les triggers Xbox (axes 4 et 5), relâché = retour à -1.0
        # Pour les autres axes, relâché = proche de 0
        is_released = False
        if event.axis in [4, 5]:  # Triggers Xbox
            is_released = event.value < 0.5  # Relâché si < 0.5 (pas appuyé)
        else:  # Autres axes
            is_released = abs(event.value) < 0.5
        
        if is_released:
            for action_name in ["up", "down", "left", "right", "page_up", "page_down"]:
                if config.controls_config.get(action_name, {}).get("type") == "axis" and \
                   config.controls_config.get(action_name, {}).get("axis") == event.axis:
                    # Vérifier que cette action était bien activée par cet axe
                    if action_name in key_states and key_states[action_name].get("event_type") == pygame.JOYAXISMOTION:
                        update_key_state(action_name, False)
    
    elif event.type == pygame.JOYHATMOTION and event.value == (0, 0):
        # Vérifier quel hat a été relâché
        for action_name in ["up", "down", "left", "right", "page_up", "page_down"]:
            if config.controls_config.get(action_name, {}).get("type") == "hat":
                # Vérifier que cette action était bien activée par un hat
                if action_name in key_states and key_states[action_name].get("event_type") == pygame.JOYHATMOTION:
                    update_key_state(action_name, False)

    return action

# Nouvelle implémentation de la répétition des touches
def update_key_state(action, pressed, event_type=None, event_value=None):
    """Met à jour l'état d'une touche pour la répétition automatique."""
    current_time = pygame.time.get_ticks()
    
    if pressed:
        # La touche vient d'être pressée
        if action not in key_states:
            key_states[action] = {
                "pressed": True,
                "first_press_time": current_time,
                "last_repeat_time": current_time,
                "event_type": event_type,
                "event_value": event_value
            }
    else:
        # La touche vient d'être relâchée
        if action in key_states:
            del key_states[action]


def clear_joystick_repeat_states() -> None:
    """Supprime les états de répétition issus de la manette.

    Utile quand une manette Bluetooth se déconnecte sans envoyer tous les
    événements de relâchement, afin d'éviter des événements fantômes en boucle.
    """
    joystick_event_types = {
        pygame.JOYBUTTONDOWN,
        pygame.JOYAXISMOTION,
        pygame.JOYHATMOTION,
    }

    for action, state in list(key_states.items()):
        if state.get("event_type") in joystick_event_types:
            del key_states[action]

def process_key_repeats(sources, joystick, screen):
    """Traite la répétition des touches."""
    current_time = pygame.time.get_ticks()

    # Si aucune manette active, purge les états de répétition joystick pour
    # éviter la génération d'événements JOY* synthétiques bloquants.
    if not getattr(config, 'joystick', False) or joystick is None:
        clear_joystick_repeat_states()
    
    for action, state in list(key_states.items()):
        if not state["pressed"]:
            continue

        # En l'absence de manette, ignorer les repeats joystick résiduels.
        if state.get("event_type") in (pygame.JOYBUTTONDOWN, pygame.JOYAXISMOTION, pygame.JOYHATMOTION):
            if not getattr(config, 'joystick', False) or joystick is None:
                del key_states[action]
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

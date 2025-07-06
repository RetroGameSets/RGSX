import pygame
import config
import math
from utils import truncate_text_end, wrap_text, load_system_image, load_games
import logging

logger = logging.getLogger(__name__)

# Cache global pour l'overlay semi-transparent
OVERLAY = None  # Initialisé dans init_display()

def init_display():
    """Initialise l’écran Pygame et met à jour la résolution."""
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    config.screen_width, config.screen_height = screen.get_size()
    logger.debug(f"Résolution réelle : {config.screen_width}x{config.screen_height}")
    global OVERLAY
    OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
    OVERLAY.fill((0, 0, 0, 180))
    return screen

def draw_gradient(screen, top_color, bottom_color):
    """Dessine un fond dégradé vertical."""
    height = screen.get_height()
    top_color = pygame.Color(*top_color)
    bottom_color = pygame.Color(*bottom_color)
    for y in range(height):
        ratio = y / height
        color = top_color.lerp(bottom_color, ratio)
        pygame.draw.line(screen, color, (0, y), (screen.get_width(), y))

def draw_loading_screen(screen):
    """Affiche l’écran de chargement avec le disclaimer en haut, le texte de chargement et la barre de progression."""
    disclaimer_lines = [
        "Bienvenue dans RGSX",
        "It's dangerous to go alone, take all you need!",
        "Mais ne téléchargez que des jeux",
        "dont vous possédez les originaux !"
    ]

    margin_horizontal = int(config.screen_width * 0.025)  # 2.5% de la largeur
    padding_vertical = int(config.screen_height * 0.0185)  # ~20px pour 1080p
    padding_between = int(config.screen_height * 0.0074)  # ~8px pour 1080p
    border_radius = 16
    border_width = 3
    shadow_offset = 6

    line_height = config.font.get_height() + padding_between
    total_height = line_height * len(disclaimer_lines) - padding_between
    rect_width = config.screen_width - 2 * margin_horizontal
    rect_height = total_height + 2 * padding_vertical
    rect_x = margin_horizontal
    rect_y = int(config.screen_height * 0.0185)  # ~20px pour 1080p

    shadow_rect = pygame.Rect(rect_x + shadow_offset, rect_y + shadow_offset, rect_width, rect_height)
    shadow_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    disclaimer_rect = pygame.Rect(rect_x, rect_y, rect_width, rect_height)
    disclaimer_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(disclaimer_surface, (30, 30, 30, 220), disclaimer_surface.get_rect(), border_radius=border_radius)
    screen.blit(disclaimer_surface, disclaimer_rect.topleft)

    pygame.draw.rect(screen, (255, 255, 255), disclaimer_rect, border_width, border_radius=border_radius)

    max_text_width = rect_width - 2 * padding_vertical
    for i, line in enumerate(disclaimer_lines):
        wrapped_lines = wrap_text(line, config.font, max_text_width)
        for j, wrapped_line in enumerate(wrapped_lines):
            text_surface = config.font.render(wrapped_line, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(
                config.screen_width // 2,
                rect_y + padding_vertical + (i * len(wrapped_lines) + j + 0.5) * line_height - padding_between // 2
            ))
            screen.blit(text_surface, text_rect)

    loading_y = rect_y + rect_height + int(config.screen_height * 0.0926)  # ~100px pour 1080p
    text = config.font.render(truncate_text_end(f"{config.current_loading_system}", config.font, config.screen_width - 2 * margin_horizontal), True, (255, 255, 255))
    text_rect = text.get_rect(center=(config.screen_width // 2, loading_y))
    screen.blit(text, text_rect)

    progress_text = config.font.render(f"Progression : {int(config.loading_progress)}%", True, (255, 255, 255))
    progress_rect = progress_text.get_rect(center=(config.screen_width // 2, loading_y + int(config.screen_height * 0.0463)))  # ~50px pour 1080p
    screen.blit(progress_text, progress_rect)

    bar_width = int(config.screen_width * 0.2083)  # ~400px pour 1920p
    bar_height = int(config.screen_height * 0.037)  # ~40px pour 1080p
    progress_width = (bar_width * config.loading_progress) / 100
    pygame.draw.rect(screen, (100, 100, 100), (config.screen_width // 2 - bar_width // 2, loading_y + int(config.screen_height * 0.0926), bar_width, bar_height))
    pygame.draw.rect(screen, (0, 255, 0), (config.screen_width // 2 - bar_width // 2, loading_y + int(config.screen_height * 0.0926), progress_width, bar_height))

def draw_error_screen(screen):
    """Affiche l’écran d’erreur."""
    error_font = pygame.font.SysFont("arial", 28)
    wrapped_message = wrap_text(config.error_message, error_font, config.screen_width - 80)
    line_height = error_font.get_height() + 5
    for i, line in enumerate(wrapped_message):
        text = error_font.render(line, True, (255, 0, 0))
        text_rect = text.get_rect(center=(config.screen_width // 2, config.screen_height // 2 - (len(wrapped_message) // 2 - i) * line_height))
        screen.blit(text, text_rect)
    retry_text = config.font.render(f"{get_control_display('confirm', 'Entrée/A')} : retenter, {get_control_display('cancel', 'Échap/B')} : quitter", True, (255, 255, 255))
    retry_rect = retry_text.get_rect(center=(config.screen_width // 2, config.screen_height // 2 + int(config.screen_height * 0.0926)))  # ~100px pour 1080p
    screen.blit(retry_text, retry_rect)

def draw_platform_grid(screen):
    """Affiche la grille des plateformes avec un titre en haut."""
    # Configuration du titre
    if not config.platforms or config.selected_platform >= len(config.platforms):
        platform_name = "Aucune plateforme"
        logger.warning("Aucune plateforme ou selected_platform hors limites")
    else:
        platform = config.platforms[config.selected_platform]
        platform_name = config.platform_names.get(platform, platform)
    title_text = f"{platform_name}"
    title_surface = config.title_font.render(title_text, True, (255, 255, 255))
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 10))
    title_rect_inflated = title_rect.inflate(40, 20)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 0)
    
    # Dessiner le rectangle de fond du titre
    pygame.draw.rect(screen, (50, 50, 50, 200), title_rect_inflated, border_radius=10)
    pygame.draw.rect(screen, (255, 255, 255), title_rect_inflated, 2, border_radius=10)
    screen.blit(title_surface, title_rect)

    # Configuration de la grille
    margin_left = int(config.screen_width * 0.026)  # ~50px pour 1920p
    margin_right = int(config.screen_width * 0.026)
    margin_top = int(config.screen_height * 0.140)  # ~120px pour 1080p
    margin_bottom = int(config.screen_height * 0.0648)  # ~70px pour 1080p
    num_cols = 3
    num_rows = 3
    systems_per_page = num_cols * num_rows

    available_width = config.screen_width - margin_left - margin_right
    available_height = config.screen_height - margin_top - margin_bottom

    col_width = available_width // num_cols
    row_height = available_height // num_rows

    x_positions = [margin_left + col_width * i + col_width // 2 for i in range(num_cols)]
    y_positions = [margin_top + row_height * i + row_height // 2 for i in range(num_rows)]

    start_idx = config.current_page * systems_per_page
    logger.debug(f"Page {config.current_page}, start_idx: {start_idx}, total_platforms: {len(config.platforms)}")

    for idx in range(start_idx, start_idx + systems_per_page):
        if idx >= len(config.platforms):
            break
        grid_idx = idx - start_idx
        row = grid_idx // num_cols
        col = grid_idx % num_cols
        x = x_positions[col]
        y = y_positions[row]
        scale = 1.5 if idx == config.selected_platform else 1.0
        platform_dict = config.platform_dicts[idx]
        image = load_system_image(platform_dict)
        if image:
            orig_width, orig_height = image.get_width(), image.get_height()
            max_size = int(min(col_width, row_height) * scale * 0.9)
            ratio = min(max_size / orig_width, max_size / orig_height)
            new_width = int(orig_width * ratio)
            new_height = int(orig_height * ratio)
            image = pygame.transform.smoothscale(image, (new_width, new_height))
            image_rect = image.get_rect(center=(x, y))

            if idx == config.selected_platform:
                neon_color = (0, 255, 255)
                border_radius = 24
                padding = 24
                rect_width = image_rect.width + 2 * padding
                rect_height = image_rect.height + 2 * padding
                neon_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
                pygame.draw.rect(
                    neon_surface,
                    neon_color + (60,),
                    neon_surface.get_rect(),
                    width=1,
                    border_radius=border_radius + 8
                )
                pygame.draw.rect(
                    neon_surface,
                    neon_color + (180,),
                    neon_surface.get_rect().inflate(-8, -8),
                    width=2,
                    border_radius=border_radius
                )
                screen.blit(neon_surface, (image_rect.left - padding, image_rect.top - padding), special_flags=pygame.BLEND_RGBA_ADD)

            screen.blit(image, image_rect)

def draw_game_list(screen):
    """Affiche la liste des jeux avec défilement et rectangle de fond."""
    logger.debug("Début de draw_game_list")
    
    platform = config.platforms[config.current_platform]
    platform_name = config.platform_names.get(platform, platform)
    games = config.filtered_games if config.filter_active or config.search_mode else config.games
    game_count = len(games)

    if not games:
        logger.debug("Aucune liste de jeux disponible")
        message = "Aucun jeu disponible"
        lines = wrap_text(message, config.font, config.screen_width - 80)
        line_height = config.font.get_height() + 5
        text_height = len(lines) * line_height
        margin_top_bottom = 20
        rect_height = text_height + 2 * margin_top_bottom
        max_text_width = max([config.font.size(line)[0] for line in lines], default=300)
        rect_width = max_text_width + 40
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x, rect_y, rect_width, rect_height), border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255), (rect_x, rect_y, rect_width, rect_height), 2, border_radius=10)

        for i, line in enumerate(lines):
            text_surface = config.font.render(line, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
            screen.blit(text_surface, text_rect)
        return

    line_height = config.font.get_height() + 10
    margin_top_bottom = 20
    extra_margin_top = 5  # Marge supplémentaire pour éviter le chevauchement avec le titre
    extra_margin_bottom = 40  # Marge supplémentaire en bas pour éloigner du texte des contrôles
    title_height = max(config.title_font.get_height(), config.search_font.get_height(), config.small_font.get_height()) + 20  # Hauteur du titre avec padding réduit
    available_height = config.screen_height - title_height - extra_margin_top - extra_margin_bottom - 2 * margin_top_bottom
    games_per_page = available_height // line_height
    max_text_width = max([config.font.size(truncate_text_end(game[0] if isinstance(game, (list, tuple)) else game, config.font, config.screen_width - 80))[0] for game in games], default=300)
    rect_width = max_text_width + 40
    rect_height = games_per_page * line_height + 2 * margin_top_bottom
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = title_height + extra_margin_top + (config.screen_height - title_height - extra_margin_top - extra_margin_bottom - rect_height) // 2

    # Limiter scroll_offset pour éviter l'espace vide
    config.scroll_offset = max(0, min(config.scroll_offset, max(0, len(games) - games_per_page)))
    if config.current_game < config.scroll_offset:
        config.scroll_offset = config.current_game
    elif config.current_game >= config.scroll_offset + games_per_page:
        config.scroll_offset = config.current_game - games_per_page + 1

    screen.blit(OVERLAY, (0, 0))

    # Afficher le titre ou le texte de recherche/filtre
    if config.search_mode:
        search_text = f"Filtrer : {config.search_query}_"
        title_surface = config.search_font.render(search_text, True, (255, 255, 255))
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 10))
        title_rect_inflated = title_rect.inflate(40, 20)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 0)
        pygame.draw.rect(screen, (50, 50, 50, 200), title_rect_inflated, border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255), title_rect_inflated, 2, border_radius=10)
        screen.blit(title_surface, title_rect)
    elif config.filter_active:
        filter_text = f"Filtre actif : {config.search_query}"
        title_surface = config.small_font.render(filter_text, True, (255, 255, 255))
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 10))
        title_rect_inflated = title_rect.inflate(40, 20)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 0)
        pygame.draw.rect(screen, (50, 50, 50, 200), title_rect_inflated, border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255), title_rect_inflated, 2, border_radius=10)
        screen.blit(title_surface, title_rect)
    else:
        title_text = f"{platform_name} ({game_count} jeux)"
        title_surface = config.title_font.render(title_text, True, (255, 255, 255))
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 10))
        title_rect_inflated = title_rect.inflate(40, 20)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 0)
        pygame.draw.rect(screen, (50, 50, 50, 200), title_rect_inflated, border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255), title_rect_inflated, 2, border_radius=10)
        screen.blit(title_surface, title_rect)

    # Afficher le rectangle de fond et la liste des jeux
    pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x, rect_y, rect_width, rect_height), border_radius=10)
    pygame.draw.rect(screen, (255, 255, 255), (rect_x, rect_y, rect_width, rect_height), 2, border_radius=10)

    for i in range(config.scroll_offset, min(config.scroll_offset + games_per_page, len(games))):
        game_name = games[i][0] if isinstance(games[i], (list, tuple)) else games[i]
        color = (0, 150, 255) if i == config.current_game else (255, 255, 255)
        game_text = truncate_text_end(game_name, config.font, config.screen_width - 80)
        text_surface = config.font.render(game_text, True, color)
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + (i - config.scroll_offset) * line_height + line_height // 2))
        screen.blit(text_surface, text_rect)
        logger.debug(f"Jeu affiché : texte={game_text}, position={text_rect}, selected={i == config.current_game}")

    draw_scrollbar(screen)
    if config.search_mode and config.is_non_pc:
        draw_virtual_keyboard(screen)     
        
def draw_virtual_keyboard(screen):
    """Affiche un clavier virtuel pour la saisie dans search_mode, centré verticalement."""
    keyboard_layout = [
        ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
        ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
        ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
        ['W', 'X', 'C', 'V', 'B', 'N']
    ]
    key_width = int(config.screen_width * 0.03125)  # ~60px pour 1920p
    key_height = int(config.screen_height * 0.0556)  # ~60px pour 1080p
    key_spacing = int(config.screen_width * 0.0052)  # ~10px pour 1920p
    keyboard_width = len(keyboard_layout[0]) * (key_width + key_spacing) - key_spacing
    keyboard_height = len(keyboard_layout) * (key_height + key_spacing) - key_spacing
    start_x = (config.screen_width - keyboard_width) // 2
    search_bottom_y = int(config.screen_height * 0.111) + (config.search_font.get_height() + 40) // 2  # ~120px pour 1080p
    controls_y = config.screen_height - int(config.screen_height * 0.037)  # ~40px pour 1080p
    available_height = controls_y - search_bottom_y
    start_y = search_bottom_y + (available_height - keyboard_height - 40) // 2

    keyboard_rect = pygame.Rect(start_x - 20, start_y - 20, keyboard_width + 40, keyboard_height + 40)
    pygame.draw.rect(screen, (50, 50, 50, 200), keyboard_rect, border_radius=10)
    pygame.draw.rect(screen, (255, 255, 255), keyboard_rect, 2, border_radius=10)

    for row_idx, row in enumerate(keyboard_layout):
        for col_idx, key in enumerate(row):
            x = start_x + col_idx * (key_width + key_spacing)
            y = start_y + row_idx * (key_height + key_spacing)
            key_rect = pygame.Rect(x, y, key_width, key_height)
            if (row_idx, col_idx) == config.selected_key:
                pygame.draw.rect(screen, (0, 150, 255, 150), key_rect, border_radius=5)
            else:
                pygame.draw.rect(screen, (80, 80, 80, 255), key_rect, border_radius=5)
            pygame.draw.rect(screen, (255, 255, 255), key_rect, 1, border_radius=5)
            text = config.font.render(key, True, (255, 255, 255))
            text_rect = text.get_rect(center=key_rect.center)
            screen.blit(text, text_rect)

def draw_progress_screen(screen):
    """Affiche l'écran de progression des téléchargements avec taille en Mo."""
    logger.debug("Début de draw_progress_screen")
    
    if not config.download_tasks:
        logger.debug("Aucune tâche de téléchargement active")
        return

    task = list(config.download_tasks.keys())[0]
    game_name = config.download_tasks[task][2]
    url = config.download_tasks[task][1]
    progress = config.download_progress.get(url, {"downloaded_size": 0, "total_size": 0, "status": "Téléchargement", "progress_percent": 0})
    status = progress.get("status", "Téléchargement")
    downloaded_size = progress["downloaded_size"]
    total_size = progress["total_size"]
    progress_percent = progress["progress_percent"]
    logger.debug(f"Progression : game_name={game_name}, url={url}, status={status}, progress_percent={progress_percent}, downloaded_size={downloaded_size}, total_size={total_size}")

    screen.blit(OVERLAY, (0, 0))

    title_text = f"{status} : {truncate_text_end(game_name, config.font, config.screen_width - 200)}"
    title_lines = wrap_text(title_text, config.font, config.screen_width - 80)
    line_height = config.font.get_height() + 5
    text_height = len(title_lines) * line_height
    margin_top_bottom = 20
    bar_height = int(config.screen_height * 0.0278)  # ~30px pour 1080p
    percent_height = line_height  # Hauteur pour le texte de progression
    rect_height = text_height + bar_height + percent_height + 3 * margin_top_bottom
    max_text_width = max([config.font.size(line)[0] for line in title_lines], default=300)
    bar_width = max_text_width  # Ajuster la barre à la largeur du texte
    rect_width = max_text_width + 40
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x, rect_y, rect_width, rect_height), border_radius=10)
    pygame.draw.rect(screen, (255, 255, 255), (rect_x, rect_y, rect_width, rect_height), 2, border_radius=10)

    for i, line in enumerate(title_lines):
        title_render = config.font.render(line, True, (255, 255, 255))
        title_rect = title_render.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(title_render, title_rect)
        logger.debug(f"Titre affiché : texte={line}, position={title_rect}, taille={title_render.get_size()}")

    bar_y = rect_y + text_height + margin_top_bottom
    progress_width = 0
    pygame.draw.rect(screen, (100, 100, 100), (rect_x + 20, bar_y, bar_width, bar_height))
    if total_size > 0:
        progress_width = int(bar_width * (progress_percent / 100))
        pygame.draw.rect(screen, (0, 150, 255), (rect_x + 20, bar_y, progress_width, bar_height))
    pygame.draw.rect(screen, (255, 255, 255), (rect_x + 20, bar_y, bar_width, bar_height), 2)
    logger.debug(f"Barre de progression affichée : position=({rect_x + 20}, {bar_y}), taille=({bar_width}, {bar_height}), progress_width={progress_width}")

    downloaded_mb = downloaded_size / (1024 * 1024)
    total_mb = total_size / (1024 * 1024)
    size_text = f"{downloaded_mb:.1f} Mo / {total_mb:.1f} Mo"
    percent_text = f"{int(progress_percent)}%  {size_text}"
    percent_lines = wrap_text(percent_text, config.font, config.screen_width - 80)
    text_y = bar_y + bar_height + margin_top_bottom
    for i, line in enumerate(percent_lines):
        percent_render = config.font.render(line, True, (255, 255, 255))
        percent_rect = percent_render.get_rect(center=(config.screen_width // 2, text_y + i * line_height + line_height // 2))
        screen.blit(percent_render, percent_rect)
        logger.debug(f"Texte de progression affiché : texte={line}, position={percent_rect}, taille={percent_render.get_size()}")
        
def draw_scrollbar(screen):
    """Affiche la barre de défilement à droite de l’écran."""
    if len(config.filtered_games) <= config.visible_games:
        return

    game_area_height = config.screen_height - 150
    scrollbar_height = game_area_height * (config.visible_games / len(config.filtered_games))
    scrollbar_y = 120 + (game_area_height - scrollbar_height) * (config.scroll_offset / max(1, len(config.filtered_games) - config.visible_games))
    pygame.draw.rect(screen, (255, 255, 255), (config.screen_width - 25, scrollbar_y, 15, scrollbar_height))

def draw_confirm_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour quitter."""
    screen.blit(OVERLAY, (0, 0))

    message = "Voulez-vous vraiment quitter ?"
    wrapped_message = wrap_text(message, config.font, config.screen_width - 80)
    line_height = config.font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    button_height = line_height + 20
    margin_top_bottom = 20
    rect_height = text_height + button_height + 2 * margin_top_bottom
    max_text_width = max([config.font.size(line)[0] for line in wrapped_message], default=300)
    rect_width = max_text_width + 40
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x, rect_y, rect_width, rect_height), border_radius=10)
    pygame.draw.rect(screen, (255, 255, 255), (rect_x, rect_y, rect_width, rect_height), 2, border_radius=10)

    for i, line in enumerate(wrapped_message):
        text = config.font.render(line, True, (255, 255, 255))
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

    yes_text = config.font.render("Oui", True, (0, 150, 255) if config.confirm_selection == 1 else (255, 255, 255))
    no_text = config.font.render("Non", True, (0, 150, 255) if config.confirm_selection == 0 else (255, 255, 255))
    yes_rect = yes_text.get_rect(center=(config.screen_width // 2 - 100, rect_y + text_height + margin_top_bottom + line_height // 2))
    no_rect = no_text.get_rect(center=(config.screen_width // 2 + 100, rect_y + text_height + margin_top_bottom + line_height // 2))

    screen.blit(yes_text, yes_rect)
    screen.blit(no_text, no_rect)

def draw_popup_message(screen, message, is_error):
    """Affiche une popup avec un message de résultat."""
    screen.blit(OVERLAY, (0, 0))

    wrapped_message = wrap_text(message, config.font, config.screen_width - 80)
    line_height = config.font.get_height() + 5
    for i, line in enumerate(wrapped_message):
        text = config.font.render(line, True, (255, 0, 0) if is_error else (0, 255, 0))
        text_rect = text.get_rect(center=(config.screen_width // 2, config.screen_height // 2 - (len(wrapped_message) // 2 - i) * line_height))
        screen.blit(text, text_rect)

def draw_extension_warning(screen):
    """Affiche un avertissement pour une extension non reconnue ou un fichier ZIP."""
    logger.debug("Début de draw_extension_warning")
    
    if not config.pending_download:
        logger.error("config.pending_download est None ou vide dans extension_warning")
        message = "Erreur : Aucun téléchargement en attente."
        is_zip = False
        game_name = "Inconnu"
    else:
        url, platform, game_name, is_zip_non_supported = config.pending_download
        logger.debug(f"config.pending_download: url={url}, platform={platform}, game_name={game_name}, is_zip_non_supported={is_zip_non_supported}")
        is_zip = is_zip_non_supported
        if not game_name:
            game_name = "Inconnu"
            logger.warning("game_name vide, utilisation de 'Inconnu'")

    if is_zip:
        message = f"Le fichier '{game_name}' est une archive et Batocera ne prend pas en charge les archives pour ce système. L'extraction automatique du fichier aura lieu après le téléchargement, continuer ?"
    else:
        message = f"L'extension du fichier '{game_name}' n'est pas supportée par Batocera d'après le fichier info.txt. Voulez-vous continuer ?"

    max_width = config.screen_width - 80
    lines = wrap_text(message, config.font, max_width)
    logger.debug(f"Lignes générées : {lines}")

    try:
        line_height = config.font.get_height() + 5
        text_height = len(lines) * line_height
        button_height = line_height + 20
        margin_top_bottom = 20
        rect_height = text_height + button_height + 2 * margin_top_bottom
        max_text_width = max([config.font.size(line)[0] for line in lines], default=300)
        rect_width = max_text_width + 40
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x, rect_y, rect_width, rect_height), border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255), (rect_x, rect_y, rect_width, rect_height), 2, border_radius=10)

        for i, line in enumerate(lines):
            text_surface = config.font.render(line, True, (255, 255, 255))
            text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
            screen.blit(text_surface, text_rect)
        logger.debug(f"Lignes affichées : {[(rect.center, text_surface.get_size()) for rect, text_surface in zip([text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2)) for i in range(len(lines))], [config.font.render(line, True, (255, 255, 255)) for line in lines])]}")

        yes_text = "[Oui]" if config.extension_confirm_selection == 1 else "Oui"
        no_text = "[Non]" if config.extension_confirm_selection == 0 else "Non"
        yes_surface = config.font.render(yes_text, True, (0, 150, 255) if config.extension_confirm_selection == 1 else (255, 255, 255))
        no_surface = config.font.render(no_text, True, (0, 150, 255) if config.extension_confirm_selection == 0 else (255, 255, 255))
        
        button_y = rect_y + text_height + margin_top_bottom + line_height // 2
        yes_rect = yes_surface.get_rect(center=(config.screen_width // 2 - 100, button_y))
        no_rect = no_surface.get_rect(center=(config.screen_width // 2 + 100, button_y))
        
        screen.blit(yes_surface, yes_rect)
        screen.blit(no_surface, no_rect)
        logger.debug(f"Boutons affichés : Oui={yes_rect}, Non={no_rect}, selection={config.extension_confirm_selection}")

    except Exception as e:
        logger.error(f"Erreur lors du rendu de extension_warning : {str(e)}")
        error_message = "Erreur d'affichage de l'avertissement."
        wrapped_error = wrap_text(error_message, config.font, config.screen_width - 80)
        line_height = config.font.get_height() + 5
        rect_height = len(wrapped_error) * line_height + 2 * 20
        max_text_width = max([config.font.size(line)[0] for line in wrapped_error], default=300)
        rect_width = max_text_width + 40
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, (50, 50, 50, 200), (rect_x, rect_y, rect_width, rect_height), border_radius=10)
        pygame.draw.rect(screen, (255, 255, 255), (rect_x, rect_y, rect_width, rect_height), 2, border_radius=10)

        for i, line in enumerate(wrapped_error):
            error_surface = config.font.render(line, True, (255, 0, 0))
            error_rect = error_surface.get_rect(center=(config.screen_width // 2, rect_y + 20 + i * line_height + line_height // 2))
            screen.blit(error_surface, error_rect)

def draw_controls(screen, menu_state):
    """Affiche les contrôles sur une seule ligne en bas de l’écran pour tous les états du menu."""
    start_button = get_control_display('start', 'START')
    control_text = f"Menu {menu_state} - {start_button} : Options - Controls"
    max_width = config.screen_width - 40
    wrapped_controls = wrap_text(control_text, config.small_font, max_width)
    line_height = config.small_font.get_height() + 5
    rect_height = len(wrapped_controls) * line_height + 20
    rect_y = config.screen_height - rect_height - 40  # Marge inférieure de 40px

    for i, line in enumerate(wrapped_controls):
        text_surface = config.small_font.render(line, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + 10 + i * line_height + line_height // 2))
        screen.blit(text_surface, text_rect)

def draw_validation_transition(screen, platform_index):
    """Affiche une animation de transition pour la sélection d’une plateforme."""
    platform_dict = config.platform_dicts[platform_index]
    image = load_system_image(platform_dict)
    if not image:
        return
    orig_width, orig_height = image.get_width(), image.get_height()
    base_size = int(config.screen_width * 0.0781)  # ~150px pour 1920p
    start_time = pygame.time.get_ticks()
    duration = 500
    while pygame.time.get_ticks() - start_time < duration:
        draw_gradient(screen, (28, 37, 38), (47, 59, 61))
        elapsed = pygame.time.get_ticks() - start_time
        scale = 2.0 + (2.0 * elapsed / duration) if elapsed < duration / 2 else 3.0 - (2.0 * elapsed / duration)
        new_width = int(base_size * scale)
        new_height = int(base_size * scale)
        scaled_image = pygame.transform.smoothscale(image, (new_width, new_height))
        image_rect = scaled_image.get_rect(center=(config.screen_width // 2, config.screen_height // 2))
        screen.blit(scaled_image, image_rect)
        pygame.display.flip()
        pygame.time.wait(10)

def draw_pause_menu(screen, selected_option):
    """Dessine le menu pause avec les options Aide, Configurer contrôles, Quitter."""
    screen.blit(OVERLAY, (0, 0))

    options = [
        "Controls",
        "Remap controls",
        "Quit"
    ]
    
    menu_width = int(config.screen_width * 0.2083)  # ~400px pour 1920p
    line_height = config.font.get_height() + 10
    text_height = len(options) * line_height
    margin_top_bottom = 20
    menu_height = text_height + 2 * margin_top_bottom
    menu_x = (config.screen_width - menu_width) // 2
    menu_y = (config.screen_height - menu_height) // 2

    pygame.draw.rect(screen, (50, 50, 50, 200), (menu_x, menu_y, menu_width, menu_height), border_radius=10)
    pygame.draw.rect(screen, (255, 255, 255), (menu_x, menu_y, menu_width, menu_height), 2, border_radius=10)

    for i, option in enumerate(options):
        color = (0, 150, 255) if i == selected_option else (255, 255, 255)
        text_surface = config.font.render(option, True, color)
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, menu_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text_surface, text_rect)

def get_control_display(action, default):
    """Récupère le nom d'affichage d'une action depuis controls_config."""
    if not config.controls_config:
        logger.warning(f"controls_config vide pour l'action {action}, utilisation de la valeur par défaut")
        return default
    return config.controls_config.get(action, {}).get('display', default)

def draw_controls_help(screen, previous_state):
    """Affiche la liste des contrôles pour l'état précédent du menu."""
    common_controls = {
        "confirm": lambda action: f"{get_control_display('confirm', 'Entrée/A')} : {action}",
        "cancel": lambda action: f"{get_control_display('cancel', 'Échap/B')} : {action}",
        "start": lambda: f"{get_control_display('start', 'Start')} : Menu",
        "progress": lambda action: f"{get_control_display('progress', 'X')} : {action}",
        "up": lambda action: f"{get_control_display('up', 'Flèche Haut')} : {action}",
        "down": lambda action: f"{get_control_display('down', 'Flèche Bas')} : {action}",
        "page_up": lambda action: f"{get_control_display('page_up', 'Q/LB')} : {action}",
        "page_down": lambda action: f"{get_control_display('page_down', 'E/RB')} : {action}",
        "filter": lambda action: f"{get_control_display('filter', 'Select')} : {action}",
        "delete": lambda: f"{get_control_display('delete', 'Retour Arrière')} : Supprimer",
        "space": lambda: f"{get_control_display('space', 'Espace')} : Espace"
    }

    state_controls = {
        "error": [
            common_controls["confirm"]("Retenter"),
            common_controls["cancel"]("Quitter")
        ],
        "platform": [
            common_controls["confirm"]("Sélectionner"),
            common_controls["cancel"]("Quitter"),
            common_controls["start"](),
            *( [common_controls["progress"]("Progression")] if config.download_tasks else [])
        ],
        "game": [
            common_controls["confirm"](f"{'Valider' if config.search_mode else 'Télécharger'}"),
            common_controls["cancel"](f"{'Annuler' if config.search_mode else 'Retour'}"),
            *( [
                common_controls["delete"](),
                common_controls["space"]()
            ] if config.search_mode and config.is_non_pc else []),
            *( [
                f"Saisir texte : Filtrer" if config.search_mode else
                f"{common_controls['up']('Naviguer')} / {common_controls['down']('Naviguer')}",
                f"{common_controls['page_up']('Page')} / {common_controls['page_down']('Page')}",
                common_controls["filter"]("Filtrer")
            ] if not config.is_non_pc or not config.search_mode else []),
            common_controls["start"](),
            *( [common_controls["progress"]("Progression")] if config.download_tasks and not config.search_mode else [])
        ],
        "download_progress": [
            common_controls["cancel"]("Annuler le téléchargement"),
            common_controls["progress"]("Arrière plan"),
            common_controls["start"]()
        ],
        "download_result": [
            common_controls["confirm"]("Retour")
        ],
        "confirm_exit": [
            common_controls["confirm"]("Confirmer")
        ],
        "extension_warning": [
            common_controls["confirm"]("Confirmer")
        ]
    }

    controls = state_controls.get(previous_state, [])
    if not controls:
        return

    screen.blit(OVERLAY, (0, 0))

    max_width = config.screen_width - 80
    wrapped_controls = []
    current_line = ""
    for control in controls:
        test_line = f"{current_line} | {control}" if current_line else control
        if config.font.size(test_line)[0] <= max_width:
            current_line = test_line
        else:
            wrapped_controls.append(current_line)
            current_line = control
    if current_line:
        wrapped_controls.append(current_line)

    line_height = config.font.get_height() + 10
    popup_width = max_width + 40
    popup_height = len(wrapped_controls) * line_height + 60
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    for i, line in enumerate(wrapped_controls):
        text = config.font.render(line, True, (255, 255, 255))
        text_rect = text.get_rect(center=(config.screen_width // 2, popup_y + 40 + i * line_height))
        screen.blit(text, text_rect)
import pygame
import config
import math
from utils import truncate_text_end
from cache import get_system_image
import logging

logger = logging.getLogger(__name__)

def init_display():
    """Initialise l’écran Pygame."""
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
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
    # Texte du disclaimer
    disclaimer_lines = [
        "Bienvenue dans RGSX",
        "It's dangerous to go alone, take all you need!",
        "Mais ne téléchargez que des jeux",
        "dont vous possédez les originaux !"
    ]

    # Paramètres de style pour le disclaimer
    margin_horizontal = 20
    padding_vertical = 20
    padding_between = 8
    border_radius = 16
    border_width = 3
    shadow_offset = 6

    line_height = config.font.get_height() + padding_between
    total_height = line_height * len(disclaimer_lines) - padding_between
    rect_width = config.screen_width - 2 * margin_horizontal
    rect_height = total_height + 2 * padding_vertical
    rect_x = margin_horizontal
    rect_y = 20  # Position en haut de l'écran

    # Ombre portée
    shadow_rect = pygame.Rect(rect_x + shadow_offset, rect_y + shadow_offset, rect_width, rect_height)
    shadow_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    # Fond semi-transparent
    disclaimer_rect = pygame.Rect(rect_x, rect_y, rect_width, rect_height)
    disclaimer_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(disclaimer_surface, (30, 30, 30, 220), disclaimer_surface.get_rect(), border_radius=border_radius)
    screen.blit(disclaimer_surface, disclaimer_rect.topleft)

    # Bordure blanche
    pygame.draw.rect(screen, (255, 255, 255), disclaimer_rect, border_width, border_radius=border_radius)

    # Affichage du texte du disclaimer
    for i, line in enumerate(disclaimer_lines):
        text_surface = config.font.render(line, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=(
            config.screen_width // 2,
            rect_y + padding_vertical + (i + 0.5) * line_height - padding_between // 2
        ))
        screen.blit(text_surface, text_rect)

    # Texte de chargement (déplacé vers le bas pour laisser de la place)
    loading_y = rect_y + rect_height + 100
    text = config.font.render(f"Chargement {config.current_loading_system}", True, (255, 255, 255))
    text_rect = text.get_rect(center=(config.screen_width // 2, loading_y))
    screen.blit(text, text_rect)
    logger.debug(f"Affichage loading : {config.current_loading_system}, progression={config.loading_progress}%")

    progress_text = config.font.render(f"Progression : {int(config.loading_progress)}%", True, (255, 255, 255))
    progress_rect = progress_text.get_rect(center=(config.screen_width // 2, loading_y + 50))
    screen.blit(progress_text, progress_rect)

    bar_width = 400
    bar_height = 40
    progress_width = (bar_width * config.loading_progress) / 100
    pygame.draw.rect(screen, (100, 100, 100), (config.screen_width // 2 - bar_width // 2, loading_y + 100, bar_width, bar_height))
    pygame.draw.rect(screen, (0, 255, 0), (config.screen_width // 2 - bar_width // 2, loading_y + 100, progress_width, bar_height))
    
def draw_error_screen(screen):
    """Affiche l’écran d’erreur."""
    error_font = pygame.font.SysFont("arial", 28)
    text = error_font.render(config.error_message, True, (255, 0, 0))
    text_rect = text.get_rect(center=(config.screen_width // 2, config.screen_height // 2))
    screen.blit(text, text_rect)
    retry_text = config.font.render("Entrée/A : retenter, Echap/B : quitter", True, (255, 255, 255))
    retry_rect = retry_text.get_rect(center=(config.screen_width // 2, config.screen_height // 2 + 100))
    screen.blit(retry_text, retry_rect)

def draw_platform_grid(screen):
    margin_left = 50
    margin_right = 50
    margin_top = 90
    margin_bottom = 50
    num_cols = 3
    num_rows = 3
    systems_per_page = num_cols * num_rows  # 9 systèmes par page

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
        #logger.debug(f"Affichage plateforme idx {idx}: {config.platforms[idx]}")
        grid_idx = idx - start_idx
        row = grid_idx // num_cols
        col = grid_idx % num_cols
        x = x_positions[col]
        y = y_positions[row]
        scale = 1.5 if idx == config.selected_platform else 1.0
        image_size = int(min(col_width, row_height) * scale * 0.9)
        image = get_system_image(config.platforms[idx], width=image_size, height=image_size)
        if image:
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

def draw_virtual_keyboard(screen):
    """Affiche un clavier virtuel pour la saisie dans search_mode, centré verticalement."""
    keyboard_layout = [
        ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
        ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
        ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
        ['W', 'X', 'C', 'V', 'B', 'N']
    ]
    key_width = 60
    key_height = 60
    key_spacing = 10
    keyboard_width = len(keyboard_layout[0]) * (key_width + key_spacing) - key_spacing
    keyboard_height = len(keyboard_layout) * (key_height + key_spacing) - key_spacing
    start_x = (config.screen_width - keyboard_width) // 2
    search_bottom_y = 120 + (config.search_font.get_height() + 40) // 2
    controls_y = config.screen_height - 20
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
    import config
    import pygame
    from utils import truncate_text_end

    if not config.download_tasks:
        return

    task = list(config.download_tasks.keys())[0]
    game_name = config.download_tasks[task][2]
    url = config.download_tasks[task][1]
    progress = config.download_progress.get(url, {"downloaded_size": 0, "total_size": 0, "status": "Downloading", "progress_percent": 0})
    status = progress.get("status", "Downloading")
    downloaded_size = progress["downloaded_size"]
    total_size = progress["total_size"]
    progress_percent = progress["progress_percent"]

    # Fond semi-transparent
    overlay = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 180))
    screen.blit(overlay, (0, 0))

    # Titre
    title_text = f"{status} : {truncate_text_end(game_name, config.font, config.screen_width - 200)}"
    title_render = config.font.render(title_text, True, (255, 255, 255))
    title_rect = title_render.get_rect(center=(config.screen_width // 2, config.screen_height // 2 - 100))
    pygame.draw.rect(screen, (50, 50, 50, 200), title_rect.inflate(40, 20))
    pygame.draw.rect(screen, (255, 255, 255), title_rect.inflate(40, 20), 2)
    screen.blit(title_render, title_rect)

    # Barre de progression
    bar_width = config.screen_width // 2
    bar_height = 30
    bar_x = (config.screen_width - bar_width) // 2
    bar_y = config.screen_height // 2
    pygame.draw.rect(screen, (100, 100, 100), (bar_x, bar_y, bar_width, bar_height))
    if total_size > 0:
        progress_width = int(bar_width * (progress_percent / 100))
        pygame.draw.rect(screen, (0, 150, 255), (bar_x, bar_y, progress_width, bar_height))
    pygame.draw.rect(screen, (255, 255, 255), (bar_x, bar_y, bar_width, bar_height), 2)

    # Pourcentage et taille
    downloaded_mb = downloaded_size / (1024 * 1024)  # Convertir en Mo
    total_mb = total_size / (1024 * 1024)  # Convertir en Mo
    size_text = f"{downloaded_mb:.1f} Mo / {total_mb:.1f} Mo"
    percent_text = f"{int(progress_percent)}%  {size_text}"
    percent_render = config.progress_font.render(percent_text, True, (255, 255, 255))
    percent_rect = percent_render.get_rect(center=(config.screen_width // 2, bar_y + bar_height + 30))
    screen.blit(percent_render, percent_rect)
    
def draw_scrollbar(screen):
    """Affiche la barre de défilement."""
    game_area_height = config.screen_height - 150
    total_games = len(config.filtered_games)
    if total_games <= config.visible_games:
        return
    scrollbar_height = max(20, game_area_height * config.visible_games / total_games)
    scrollbar_y = 120 + (game_area_height - scrollbar_height) * config.scroll_offset / (total_games - config.visible_games)
    pygame.draw.rect(screen, (0, 150, 255), (config.screen_width - 25, scrollbar_y, 15, scrollbar_height))

def draw_confirm_dialog(screen):
    """Affiche la boîte de dialogue de confirmation de sortie, stylée et centrée."""
    lines = [
        "Tu me quittes déjà ?",
        "Tu es sûr de toi ??",
        "Bon voyage, sois prudent!"
    ]
    options = ["Oui", "Non"]

    popup_width = config.screen_width // 2
    padding_vertical = 30
    padding_between = 10
    border_radius = 24
    border_width = 4
    shadow_offset = 8

    line_height = config.font.get_height() + padding_between
    total_text_height = line_height * len(lines) - padding_between
    option_y_offset = 40

    popup_height = total_text_height + 2 * padding_vertical + option_y_offset + config.font.get_height()
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    shadow_rect = pygame.Rect(popup_x + shadow_offset, popup_y + shadow_offset, popup_width, popup_height)
    shadow_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    popup_rect = pygame.Rect(popup_x, popup_y, popup_width, popup_height)
    popup_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(popup_surface, (30, 30, 30, 220), popup_surface.get_rect(), border_radius=border_radius)
    screen.blit(popup_surface, popup_rect.topleft)

    pygame.draw.rect(screen, (255, 255, 255), popup_rect, border_width, border_radius=border_radius)

    start_y = popup_y + padding_vertical + (popup_height - 2 * padding_vertical - total_text_height - option_y_offset - config.font.get_height()) // 2
    for i, line in enumerate(lines):
        text_surface = config.font.render(line, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, start_y + i * line_height))
        screen.blit(text_surface, text_rect)

    yes_color = (0, 255, 0) if config.confirm_selection == 1 else (255, 255, 255)
    no_color = (255, 0, 0) if config.confirm_selection == 0 else (255, 255, 255)
    option_y = start_y + total_text_height + option_y_offset
    yes_text = config.font.render("Oui", True, yes_color)
    no_text = config.font.render("Non", True, no_color)
    yes_rect = yes_text.get_rect(center=(config.screen_width // 2 - 100, option_y))
    no_rect = no_text.get_rect(center=(config.screen_width // 2 + 100, option_y))
    screen.blit(yes_text, yes_rect)
    screen.blit(no_text, no_rect)

def draw_extension_warning(screen):
    """Affiche une popup d'avertissement pour les extensions non supportées."""
    from utils import wrap_text  # Importer wrap_text ici
    max_width = config.screen_width // 1.2
    padding_horizontal = 40
    padding_vertical = 30
    padding_between = 10
    border_radius = 24
    border_width = 4
    shadow_offset = 8
    button_y_offset = 40
    options = ["Oui", "Non"]

    # Diviser le message en plusieurs lignes
    lines = wrap_text(config.download_result_message, config.font, max_width - 2 * padding_horizontal)
    line_height = config.font.get_height() + padding_between
    text_height = len(lines) * line_height - padding_between

    # Hauteur pour les boutons Oui/Non
    yes_text = config.font.render("Oui", True, (255, 255, 255))
    no_text = config.font.render("Non", True, (255, 255, 255))
    ok_width, ok_height = yes_text.get_size()

    # Calculer la largeur maximale du texte
    text_width = max([config.font.render(line, True, (255, 255, 255)).get_width() for line in lines])

    # Calculer les dimensions de la popup
    popup_width = max(text_width, ok_width * 2 + 100) + 2 * padding_horizontal
    popup_height = text_height + button_y_offset + ok_height + 2 * padding_vertical
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    # Ombre portée
    shadow_rect = pygame.Rect(popup_x + shadow_offset, popup_y + shadow_offset, popup_width, popup_height)
    shadow_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    # Fond semi-transparent
    popup_rect = pygame.Rect(popup_x, popup_y, popup_width, popup_height)
    popup_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(popup_surface, (30, 30, 30, 220), popup_surface.get_rect(), border_radius=border_radius)
    screen.blit(popup_surface, popup_rect.topleft)

    # Bordure blanche
    pygame.draw.rect(screen, (255, 255, 255), popup_rect, border_width, border_radius=border_radius)

    # Afficher les lignes de texte
    start_y = popup_y + padding_vertical
    for i, line in enumerate(lines):
        text_surface = config.font.render(line, True, (255, 255, 255))
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, start_y + i * line_height))
        screen.blit(text_surface, text_rect)

    # Afficher les boutons Oui/Non
    yes_color = (0, 255, 0) if config.extension_confirm_selection == 1 else (255, 255, 255)
    no_color = (255, 0, 0) if config.extension_confirm_selection == 0 else (255, 255, 255)
    option_y = popup_y + padding_vertical + text_height + button_y_offset
    yes_text = config.font.render("Oui", True, yes_color)
    no_text = config.font.render("Non", True, no_color)
    yes_rect = yes_text.get_rect(center=(config.screen_width // 2 - 100, option_y))
    no_rect = no_text.get_rect(center=(config.screen_width // 2 + 100, option_y))
    screen.blit(yes_text, yes_rect)
    screen.blit(no_text, no_rect)
    
def draw_controls(screen, menu_state):
    """Affiche les indications de contrôles selon l'état du menu et le type de système."""
    if menu_state == "platform":
        if config.is_non_pc:
            controls_text = config.small_font.render("A: OK, B : Retour, X : Progress", True, (200, 200, 200))
        else:
            controls_text = config.small_font.render("Entrée: OK, Échap: Retour, X: Progress", True, (200, 200, 200))
    elif menu_state == "download_progress":
        if config.is_non_pc:
            controls_text = config.small_font.render("B: Annuler téléchargement, X: Retour à la liste", True, (200, 200, 200))
        else:
            controls_text = config.small_font.render("Échap: Annuler téléchargement, X: Retour à la liste", True, (200, 200, 200))
    elif menu_state == "game":
        if config.search_mode:
            if config.is_non_pc:
                controls_text = config.small_font.render("A: Select., START: OK, SELECT: Retour, LT: Suppr., RT: Espace", True, (200, 200, 200))
            else:
                controls_text = config.small_font.render("Entrée: Valider, Échap: Retour", True, (200, 200, 200))
        else:
            if config.is_non_pc:
                controls_text = config.small_font.render("A : OK, B : Retour, X : Progress, LB: Page-, RB: Page+, Select: Filtr.", True, (200, 200, 200))
            else:
                controls_text = config.small_font.render("Entrée: OK, Échap: Retour, X: Progress, Q: Page-, E: Page+, Espace: Filtr.", True, (200, 200, 200))
    elif menu_state == "extension_warning":
        if config.is_non_pc:
            controls_text = config.small_font.render("A: Valider, B: Annuler", True, (200, 200, 200))
        else:
            controls_text = config.small_font.render("Entrée: Valider, Échap: Annuler", True, (200, 200, 200))
    else:
        controls_text = config.small_font.render("", True, (200, 200, 200))
    controls_rect = controls_text.get_rect(center=(config.screen_width // 2, config.screen_height - 20))
    screen.blit(controls_text, controls_rect)
    
def draw_validation_transition(screen, platform_index):
    """Affiche une animation de transition pour la sélection d’une plateforme."""
    platform = config.platforms[platform_index]
    image = get_system_image(platform, width=150, height=150)
    if not image:
        return
    orig_width, orig_height = image.get_width(), image.get_height()
    start_time = pygame.time.get_ticks()
    duration = 500
    while pygame.time.get_ticks() - start_time < duration:
        draw_gradient(screen, (28, 37, 38), (47, 59, 61))
        elapsed = pygame.time.get_ticks() - start_time
        scale = 2.0 + (2.0 * elapsed / duration) if elapsed < duration / 2 else 3.0 - (2.0 * elapsed / duration)
        new_width = int(orig_width * scale)
        new_height = int(orig_height * scale)
        scaled_image = pygame.transform.smoothscale(image, (new_width, new_height))
        image_rect = scaled_image.get_rect(center=(config.screen_width // 2, config.screen_height // 2))
        screen.blit(scaled_image, image_rect)
        pygame.display.flip()
        pygame.time.wait(10)
        
def draw_popup_message(screen, message, is_error=False):
    """Affiche une popup générique avec un message."""
    max_width = config.screen_width // 1.2
    padding_horizontal = 40
    padding_vertical = 30
    padding_between = 10
    border_radius = 24
    border_width = 4
    shadow_offset = 8
    button_y_offset = 40

    truncated_message = truncate_text_end(message, config.font, max_width - 2 * padding_horizontal)
    text_surface = config.font.render(truncated_message, True, (255, 0, 0) if is_error else (255, 255, 255))
    text_width, text_height = text_surface.get_size()

    ok_text = config.font.render("OK", True, (255, 255, 255))
    ok_width, ok_height = ok_text.get_size()

    popup_width = max(text_width, ok_width) + 2 * padding_horizontal
    popup_height = text_height + button_y_offset + ok_height + 2 * padding_vertical
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    shadow_rect = pygame.Rect(popup_x + shadow_offset, popup_y + shadow_offset, popup_width, popup_height)
    shadow_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 255), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    popup_rect = pygame.Rect(popup_x, popup_y, popup_width, popup_height)
    popup_surface = pygame.Surface((popup_width, popup_height), pygame.SRCALPHA)
    pygame.draw.rect(popup_surface, (30, 30, 30, 220), popup_surface.get_rect(), border_radius=border_radius)
    screen.blit(popup_surface, popup_rect.topleft)

    pygame.draw.rect(screen, (255, 255, 255), popup_rect, border_width, border_radius=border_radius)

    text_rect = text_surface.get_rect(center=(config.screen_width // 2, popup_y + padding_vertical + text_height // 2))
    screen.blit(text_surface, text_rect)

    ok_rect = ok_text.get_rect(center=(config.screen_width // 2, popup_y + padding_vertical + text_height + button_y_offset + ok_height // 2))
    pygame.draw.rect(screen, (50, 50, 50, 255), ok_rect.inflate(40, 20))
    pygame.draw.rect(screen, (255, 255, 255), ok_rect.inflate(40, 20), 2)
    screen.blit(ok_text, ok_rect)
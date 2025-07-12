import pygame  # type: ignore
import config
import os
from utils import truncate_text_middle, wrap_text, load_system_image
import logging
import math
from history import load_history  # Ajout de l'import

logger = logging.getLogger(__name__)

OVERLAY = None  # Initialisé dans init_display()

# Couleurs modernes pour le thème
THEME_COLORS = {
    # Fond des lignes sélectionnées
    "fond_lignes": (0, 255, 0),  # vert
    # Fond par défaut des images de grille des systèmes
    "fond_image": (50, 50, 70),  # Bleu sombre métal
    # Néon image grille des systèmes
    "neon": (0, 134, 179),  # bleu
    # Dégradé sombre pour le fond
    "background_top": (30, 40, 50),  
    "background_bottom": (60, 80, 100), # noir vers bleu foncé
    # Fond des cadres
    "button_idle": (50, 50, 70, 150),  # Bleu sombre métal
    # Fond des boutons sélectionnés dans les popups ou menu
    "button_hover": (255, 0, 255, 220),  # Rose
    # Générique
    "text": (255, 255, 255),  # blanc
    # Erreur
    "error_text": (255, 0, 0),  # rouge
    # Avertissement
    "warning_text": (255, 100, 0),  # orange
    # Titres 
    "title_text": (200, 200, 200), # gris clair
    # Bordures
    "border": (150, 150, 150),  # Bordures grises subtiles
}

# Général, résolution, overlay
def init_display():
    """Initialise l'écran et les ressources globales."""
    global OVERLAY
    logger.debug("Initialisation de l'écran")
    display_info = pygame.display.Info()
    screen_width = display_info.current_w
    screen_height = display_info.current_h
    screen = pygame.display.set_mode((screen_width, screen_height))
    config.screen_width = screen_width
    config.screen_height = screen_height
    # Initialisation de OVERLAY
    OVERLAY = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
    OVERLAY.fill((0, 0, 0, 150))  # Transparence augmentée
    logger.debug(f"Écran initialisé avec résolution : {screen_width}x{screen_height}")
    return screen

# Fond d'écran dégradé
def draw_gradient(screen, top_color, bottom_color):
    """Dessine un fond dégradé vertical avec des couleurs vibrantes."""
    height = screen.get_height()
    top_color = pygame.Color(*top_color)
    bottom_color = pygame.Color(*bottom_color)
    for y in range(height):
        ratio = y / height
        color = top_color.lerp(bottom_color, ratio)
        pygame.draw.line(screen, color, (0, y), (screen.get_width(), y))

# Nouvelle fonction pour dessiner un bouton stylisé
def draw_stylized_button(screen, text, x, y, width, height, selected=False):
    """Dessine un bouton moderne avec effet de survol et bordure arrondie."""
    button_surface = pygame.Surface((width, height), pygame.SRCALPHA)
    button_color = THEME_COLORS["button_hover"] if selected else THEME_COLORS["button_idle"]
    pygame.draw.rect(button_surface, button_color, (0, 0, width, height), border_radius=12)
    pygame.draw.rect(button_surface, THEME_COLORS["border"], (0, 0, width, height), 2, border_radius=12)
    if selected:
        glow_surface = pygame.Surface((width + 10, height + 10), pygame.SRCALPHA)
        pygame.draw.rect(glow_surface, THEME_COLORS["fond_lignes"] + (50,), (5, 5, width, height), border_radius=12)
        screen.blit(glow_surface, (x - 5, y - 5))
    screen.blit(button_surface, (x, y))
    text_surface = config.font.render(text, True, THEME_COLORS["text"])
    text_rect = text_surface.get_rect(center=(x + width // 2, y + height // 2))
    screen.blit(text_surface, text_rect)

# Transition d'image lors de la sélection d'un système
def draw_validation_transition(screen, platform_index):
    """Affiche une animation de transition fluide pour la sélection d’une plateforme."""
    platform_dict = config.platform_dicts[platform_index]
    image = load_system_image(platform_dict)
    if not image:
        return

    # Dimensions originales et calcul du ratio pour préserver les proportions
    orig_width, orig_height = image.get_width(), image.get_height()
    base_size = int(config.screen_width * 0.0781)  # ~150px pour 1920p
    ratio = min(base_size / orig_width, base_size / orig_height)  # Maintenir les proportions
    base_width = int(orig_width * ratio)
    base_height = int(orig_height * ratio)

    # Paramètres de l'animation
    start_time = pygame.time.get_ticks()
    duration = 1000  # Durée augmentée à 1 seconde
    fps = 60
    frame_time = 1000 / fps  # Temps par frame en ms

    while pygame.time.get_ticks() - start_time < duration:
        # Fond dégradé
        draw_gradient(screen, THEME_COLORS["background_top"], THEME_COLORS["background_bottom"])

        # Calcul de l'échelle avec une courbe sinusoïdale pour une transition fluide
        elapsed = pygame.time.get_ticks() - start_time
        progress = elapsed / duration
        # Courbe sinusoïdale pour une montée/descente douce
        scale = 1.5 + 1.0 * math.sin(math.pi * progress)  # Échelle de 1.5 à 2.5
        new_width = int(base_width * scale)
        new_height = int(base_height * scale)

        # Redimensionner l'image en préservant les proportions
        scaled_image = pygame.transform.smoothscale(image, (new_width, new_height))
        image_rect = scaled_image.get_rect(center=(config.screen_width // 2, config.screen_height // 2))

        # Effet de fondu (opacité de 50% à 100% puis retour à 50%)
        alpha = int(128 + 127 * math.cos(math.pi * progress))  # Opacité entre 128 et 255
        scaled_image.set_alpha(alpha)

        # Effet de glow néon pour l'image sélectionnée
        neon_color = THEME_COLORS["neon"]  # Cyan vif
        padding = 24
        neon_surface = pygame.Surface((new_width + 2 * padding, new_height + 2 * padding), pygame.SRCALPHA)
        pygame.draw.rect(neon_surface, neon_color + (40,), neon_surface.get_rect(), border_radius=24)
        pygame.draw.rect(neon_surface, neon_color + (100,), neon_surface.get_rect().inflate(-10, -10), border_radius=18)
        screen.blit(neon_surface, (image_rect.left - padding, image_rect.top - padding), special_flags=pygame.BLEND_RGBA_ADD)

        # Afficher l'image
        screen.blit(scaled_image, image_rect)
        pygame.display.flip()

        # Contrôler la fréquence de rendu
        pygame.time.wait(int(frame_time))

    # Afficher l'image finale sans effet pour une transition propre
    draw_gradient(screen, THEME_COLORS["background_top"], THEME_COLORS["background_bottom"])
    final_image = pygame.transform.smoothscale(image, (base_width, base_height))
    final_image.set_alpha(255)  # Opacité complète
    final_rect = final_image.get_rect(center=(config.screen_width // 2, config.screen_height // 2))
    screen.blit(final_image, final_rect)
    pygame.display.flip()

# Écran de chargement
def draw_loading_screen(screen):
    """Affiche l’écran de chargement avec un style moderne."""
    disclaimer_lines = [
        "Bienvenue dans RGSX",
        "It's dangerous to go alone, take all you need!",
        "Mais ne téléchargez que des jeux",
        "dont vous possédez les originaux !"
    ]

    margin_horizontal = int(config.screen_width * 0.025)
    padding_vertical = int(config.screen_height * 0.0185)
    padding_between = int(config.screen_height * 0.0074)
    border_radius = 16
    border_width = 3
    shadow_offset = 6

    line_height = config.small_font.get_height() + padding_between
    total_height = line_height * len(disclaimer_lines) - padding_between
    rect_width = config.screen_width - 2 * margin_horizontal
    rect_height = total_height + 2 * padding_vertical
    rect_x = margin_horizontal
    rect_y = int(config.screen_height * 0.0185)

    shadow_rect = pygame.Rect(rect_x + shadow_offset, rect_y + shadow_offset, rect_width, rect_height)
    shadow_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surface, (0, 0, 0, 100), shadow_surface.get_rect(), border_radius=border_radius)
    screen.blit(shadow_surface, shadow_rect.topleft)

    disclaimer_rect = pygame.Rect(rect_x, rect_y, rect_width, rect_height)
    disclaimer_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(disclaimer_surface, THEME_COLORS["button_idle"], disclaimer_surface.get_rect(), border_radius=border_radius)
    screen.blit(disclaimer_surface, disclaimer_rect.topleft)

    pygame.draw.rect(screen, THEME_COLORS["border"], disclaimer_rect, border_width, border_radius=border_radius)

    max_text_width = rect_width - 2 * padding_vertical
    for i, line in enumerate(disclaimer_lines):
        wrapped_lines = wrap_text(line, config.small_font, max_text_width)
        for j, wrapped_line in enumerate(wrapped_lines):
            text_surface = config.small_font.render(wrapped_line, True, THEME_COLORS["title_text"])
            text_rect = text_surface.get_rect(center=(
                config.screen_width // 2,
                rect_y + padding_vertical + (i * len(wrapped_lines) + j + 0.5) * line_height - padding_between // 2
            ))
            screen.blit(text_surface, text_rect)

    loading_y = rect_y + rect_height + int(config.screen_height * 0.0926)
    text = config.small_font.render(truncate_text_middle(f"{config.current_loading_system}", config.small_font, config.screen_width - 2 * margin_horizontal), True, THEME_COLORS["text"])
    text_rect = text.get_rect(center=(config.screen_width // 2, loading_y))
    screen.blit(text, text_rect)

    progress_text = config.small_font.render(f"Progression : {int(config.loading_progress)}%", True, THEME_COLORS["text"])
    progress_rect = progress_text.get_rect(center=(config.screen_width // 2, loading_y + int(config.screen_height * 0.0463)))
    screen.blit(progress_text, progress_rect)

    bar_width = int(config.screen_width * 0.2083)
    bar_height = int(config.screen_height * 0.037)
    progress_width = (bar_width * config.loading_progress) / 100
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (config.screen_width // 2 - bar_width // 2, loading_y + int(config.screen_height * 0.0926), bar_width, bar_height), border_radius=8)
    pygame.draw.rect(screen, THEME_COLORS["fond_lignes"], (config.screen_width // 2 - bar_width // 2, loading_y + int(config.screen_height * 0.0926), progress_width, bar_height), border_radius=8)

# Écran d'erreur
def draw_error_screen(screen):
    """Affiche l’écran d’erreur avec un style moderne."""
    wrapped_message = wrap_text(config.error_message, config.small_font, config.screen_width - 80)
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 20
    rect_height = text_height + button_height + 2 * margin_top_bottom
    max_text_width = max([config.small_font.size(line)[0] for line in wrapped_message], default=300)
    rect_width = max_text_width + 80
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    screen.blit(OVERLAY, (0, 0))
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_message):
        text = config.small_font.render(line, True, THEME_COLORS["error_text"])
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

    draw_stylized_button(screen, "Valider", rect_x + rect_width // 2 - 80, rect_y + text_height + margin_top_bottom, 160, button_height, selected=True)

# Récupérer les noms d'affichage des contrôles
def get_control_display(action, default):
    """Récupère le nom d'affichage d'une action depuis controls_config."""
    if not config.controls_config:
        logger.warning(f"controls_config vide pour l'action {action}, utilisation de la valeur par défaut")
        return default
    return config.controls_config.get(action, {}).get('display', default)

# Grille des systèmes 3x3
def draw_platform_grid(screen):
    """Affiche la grille des plateformes avec un style moderne."""
    if not config.platforms or config.selected_platform >= len(config.platforms):
        platform_name = "Aucune plateforme"
        logger.warning("Aucune plateforme ou selected_platform hors limites")
    else:
        platform = config.platforms[config.selected_platform]
        platform_name = config.platform_names.get(platform, platform)
    title_text = f"{platform_name}"
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
    title_rect_inflated = title_rect.inflate(60, 30)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
    screen.blit(title_surface, title_rect)

    margin_left = int(config.screen_width * 0.026)
    margin_right = int(config.screen_width * 0.026)
    margin_top = int(config.screen_height * 0.140)
    margin_bottom = int(config.screen_height * 0.0648)
    num_cols = 3
    num_rows = 4
    systems_per_page = num_cols * num_rows

    available_width = config.screen_width - margin_left - margin_right
    available_height = config.screen_height - margin_top - margin_bottom

    col_width = available_width // num_cols
    row_height = available_height // num_rows

    x_positions = [margin_left + col_width * i + col_width // 2 for i in range(num_cols)]
    y_positions = [margin_top + row_height * i + row_height // 2 for i in range(num_rows)]

    start_idx = config.current_page * systems_per_page
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
            max_size = int(min(col_width, row_height) * scale * 1.1)  # Légèrement plus grand que la cellule
            ratio = min(max_size / orig_width, max_size / orig_height)
            new_width = int(orig_width * ratio)
            new_height = int(orig_height * ratio)
            image = pygame.transform.smoothscale(image, (new_width, new_height))
            image_rect = image.get_rect(center=(x, y))

            if idx == config.selected_platform:
                neon_color = THEME_COLORS["neon"]
                border_radius = 12
                padding = 12
                rect_width = image_rect.width + 2 * padding
                rect_height = image_rect.height + 2 * padding
                neon_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
                pygame.draw.rect(neon_surface, neon_color + (40,), neon_surface.get_rect(), border_radius=border_radius)
                pygame.draw.rect(neon_surface, neon_color + (100,), neon_surface.get_rect().inflate(-10, -10), border_radius=border_radius)
                pygame.draw.rect(neon_surface, neon_color + (200,), neon_surface.get_rect().inflate(-20, -20), width=1, border_radius=border_radius)
                screen.blit(neon_surface, (image_rect.left - padding, image_rect.top - padding), special_flags=pygame.BLEND_RGBA_ADD)

            background_surface = pygame.Surface((image_rect.width + 10, image_rect.height + 10), pygame.SRCALPHA)
            pygame.draw.rect(background_surface, THEME_COLORS["fond_image"] + (180,), background_surface.get_rect(), border_radius=12)
            screen.blit(background_surface, (image_rect.left - 5, image_rect.top - 5))

            screen.blit(image, image_rect)

# Liste des jeux
def draw_game_list(screen):
    """Affiche la liste des jeux avec un style moderne."""
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
        rect_width = max_text_width + 80
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

        for i, line in enumerate(lines):
            text_surface = config.font.render(line, True, THEME_COLORS["text"])
            text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
            screen.blit(text_surface, text_rect)
        return

    line_height = config.small_font.get_height() + 10
    margin_top_bottom = 20
    extra_margin_top = 20
    extra_margin_bottom = 60
    title_height = config.title_font.get_height() + 20

    available_height = config.screen_height - title_height - extra_margin_top - extra_margin_bottom - 2 * margin_top_bottom
    items_per_page = available_height // line_height

    rect_height = items_per_page * line_height + 2 * margin_top_bottom
    rect_width = int(0.95 * config.screen_width)
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = title_height + extra_margin_top + (config.screen_height - title_height - extra_margin_top - extra_margin_bottom - rect_height) // 2

    config.scroll_offset = max(0, min(config.scroll_offset, max(0, len(games) - items_per_page)))
    if config.current_game < config.scroll_offset:
        config.scroll_offset = config.current_game
    elif config.current_game >= config.scroll_offset + items_per_page:
        config.scroll_offset = config.current_game - items_per_page + 1

    screen.blit(OVERLAY, (0, 0))

    if config.search_mode:
        search_text = f"Filtrer : {config.search_query}_"
        title_surface = config.search_font.render(search_text, True, THEME_COLORS["text"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)
    elif config.filter_active:
        filter_text = f"Filtre actif : {config.search_query}"
        title_surface = config.small_font.render(filter_text, True, THEME_COLORS["text"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)
    else:
        title_text = f"{platform_name} ({game_count} jeux)"
        title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i in range(config.scroll_offset, min(config.scroll_offset + items_per_page, len(games))):
        game_name = games[i][0] if isinstance(games[i], (list, tuple)) else games[i]
        color = THEME_COLORS["fond_lignes"] if i == config.current_game else THEME_COLORS["text"]
        game_text = truncate_text_middle(game_name, config.small_font, rect_width - 40)
        text_surface = config.small_font.render(game_text, True, color)
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + (i - config.scroll_offset) * line_height + line_height // 2))
        if i == config.current_game:
            glow_surface = pygame.Surface((text_rect.width + 20, text_rect.height + 10), pygame.SRCALPHA)
            pygame.draw.rect(glow_surface, THEME_COLORS["fond_lignes"] + (50,), (10, 5, text_rect.width, text_rect.height), border_radius=8)
            screen.blit(glow_surface, (text_rect.left - 10, text_rect.top - 5))
        screen.blit(text_surface, text_rect)

    if len(games) > items_per_page:
        try:
            draw_game_scrollbar(
                screen,
                config.scroll_offset,
                len(games),
                items_per_page,
                rect_x + rect_width - 10,
                rect_y,
                rect_height
            )
        except NameError as e:
            logger.error(f"Erreur : draw_game_scrollbar non défini: {str(e)}")

# Barre de défilement des jeux
def draw_game_scrollbar(screen, scroll_offset, total_items, visible_items, x, y, height):
    """Affiche la barre de défilement pour la liste des jeux."""
    if total_items <= visible_items:
        return
    game_area_height = height
    scrollbar_height = game_area_height * (visible_items / total_items)
    scrollbar_y = y + (game_area_height - scrollbar_height) * (scroll_offset / max(1, total_items - visible_items))
    pygame.draw.rect(screen, THEME_COLORS["fond_lignes"], (x, scrollbar_y, 15, scrollbar_height), border_radius=4)

def draw_history_list(screen):
    """Affiche l'historique des téléchargements avec un style moderne."""
    history = config.history if hasattr(config, 'history') else load_history()
    history_count = len(history)

    col_platform_width = int((0.95 * config.screen_width - 60) * 0.33)
    col_game_width = int((0.95 * config.screen_width - 60) * 0.50)
    col_status_width = int((0.95 * config.screen_width - 60) * 0.17)
    rect_width = int(0.95 * config.screen_width)

    line_height = config.small_font.get_height() + 10
    header_height = line_height
    margin_top_bottom = 20
    extra_margin_top = 40
    extra_margin_bottom = 80
    title_height = config.title_font.get_height() + 20

    if not history:
        logger.debug("Aucun historique disponible")
        message = "Aucun téléchargement dans l'historique"
        lines = wrap_text(message, config.font, config.screen_width - 80)
        line_height = config.font.get_height() + 5
        text_height = len(lines) * line_height
        rect_height = text_height + 2 * margin_top_bottom
        max_text_width = max([config.font.size(line)[0] for line in lines], default=300)
        rect_width = max_text_width + 80
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

        for i, line in enumerate(lines):
            text_surface = config.font.render(line, True, THEME_COLORS["text"])
            text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
            screen.blit(text_surface, text_rect)
        return

    available_height = config.screen_height - title_height - extra_margin_top - extra_margin_bottom - 2 * margin_top_bottom
    items_per_page = available_height // line_height

    rect_height = header_height + items_per_page * line_height + 2 * margin_top_bottom
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = title_height + extra_margin_top + (config.screen_height - title_height - extra_margin_top - extra_margin_bottom - rect_height) // 2

    config.history_scroll_offset = max(0, min(config.history_scroll_offset, max(0, len(history) - items_per_page)))
    if config.current_history_item < config.history_scroll_offset:
        config.history_scroll_offset = config.current_history_item
    elif config.current_history_item >= config.history_scroll_offset + items_per_page:
        config.history_scroll_offset = config.current_history_item - items_per_page + 1

    screen.blit(OVERLAY, (0, 0))

    title_text = f"Historique des téléchargements ({history_count})"
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
    title_rect_inflated = title_rect.inflate(60, 30)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
    screen.blit(title_surface, title_rect)

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    headers = ["Système", "Nom du jeu", "État"]
    header_y = rect_y + margin_top_bottom + header_height // 2
    header_x_positions = [
        rect_x + 20 + col_platform_width // 2,
        rect_x + 20 + col_platform_width + col_game_width // 2,
        rect_x + 20 + col_platform_width + col_game_width + col_status_width // 2
    ]
    for header, x_pos in zip(headers, header_x_positions):
        text_surface = config.small_font.render(header, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(x_pos, header_y))
        screen.blit(text_surface, text_rect)

    # Ajouter un séparateur sous les en-têtes
    separator_y = rect_y + margin_top_bottom + header_height
    pygame.draw.line(screen, THEME_COLORS["border"], (rect_x + 20, separator_y), (rect_x + rect_width - 20, separator_y), 2)

    for idx, i in enumerate(range(config.history_scroll_offset, min(config.history_scroll_offset + items_per_page, len(history)))):
        entry = history[i]
        platform = entry.get("platform", "Inconnu")
        game_name = entry.get("game_name", "Inconnu")
        status = entry.get("status", "Inconnu")
        color = THEME_COLORS["fond_lignes"] if i == config.current_history_item else THEME_COLORS["text"]
        platform_text = truncate_text_middle(platform, config.small_font, col_platform_width - 10)
        game_text = truncate_text_middle(game_name, config.small_font, col_game_width - 10)
        status_text = truncate_text_middle(status, config.small_font, col_status_width - 10)

        y_pos = rect_y + margin_top_bottom + header_height + idx * line_height + line_height // 2
        platform_surface = config.small_font.render(platform_text, True, color)
        game_surface = config.small_font.render(game_text, True, color)
        status_surface = config.small_font.render(status_text, True, color)

        platform_rect = platform_surface.get_rect(center=(header_x_positions[0], y_pos))
        game_rect = game_surface.get_rect(center=(header_x_positions[1], y_pos))
        status_rect = status_surface.get_rect(center=(header_x_positions[2], y_pos))

        if i == config.current_history_item:
            glow_surface = pygame.Surface((rect_width - 40, line_height), pygame.SRCALPHA)
            pygame.draw.rect(glow_surface, THEME_COLORS["fond_lignes"] + (50,), (0, 0, rect_width - 40, line_height), border_radius=8)
            screen.blit(glow_surface, (rect_x + 20, y_pos - line_height // 2))

        screen.blit(platform_surface, platform_rect)
        screen.blit(game_surface, game_rect)
        screen.blit(status_surface, status_rect)

    if len(history) > items_per_page:
        try:
            draw_history_scrollbar(
                screen,
                config.history_scroll_offset,
                len(history),
                items_per_page,
                rect_x + rect_width - 10,
                rect_y,
                rect_height
            )
        except NameError as e:
            logger.error(f"Erreur : draw_history_scrollbar non défini: {str(e)}")

# Barre de défilement de l'historique
def draw_history_scrollbar(screen, scroll_offset, total_items, visible_items, x, y, height):
    """Affiche la barre de défilement avec un style moderne."""
    if total_items <= visible_items:
        return
    game_area_height = height
    scrollbar_height = game_area_height * (visible_items / total_items) - 10
    scrollbar_y = y + (game_area_height - scrollbar_height) * (scroll_offset / max(1, total_items - visible_items)) + 10
    pygame.draw.rect(screen, THEME_COLORS["fond_lignes"], (x, scrollbar_y, 5, scrollbar_height), border_radius=4)

# Écran confirmation vider historique
def draw_clear_history_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour vider l'historique."""
    screen.blit(OVERLAY, (0, 0))

    message = "Vider l'historique ?"
    wrapped_message = wrap_text(message, config.font, config.screen_width - 80)
    line_height = config.font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 20
    rect_height = text_height + button_height + 2 * margin_top_bottom
    max_text_width = max([config.font.size(line)[0] for line in wrapped_message], default=300)
    rect_width = max_text_width + 150
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_message):
        text = config.font.render(line, True, THEME_COLORS["text"])
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

    draw_stylized_button(screen, "Oui", rect_x + rect_width // 2 - 180, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.confirm_clear_selection == 1)
    draw_stylized_button(screen, "Non", rect_x + rect_width // 2 + 20, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.confirm_clear_selection == 0)

# Affichage du clavier virtuel sur non-PC
def draw_virtual_keyboard(screen):
    """Affiche un clavier virtuel avec un style moderne."""
    keyboard_layout = [
        ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
        ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
        ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
        ['W', 'X', 'C', 'V', 'B', 'N']
    ]
    key_width = int(config.screen_width * 0.03125)
    key_height = int(config.screen_height * 0.0556)
    key_spacing = int(config.screen_width * 0.0052)
    keyboard_width = len(keyboard_layout[0]) * (key_width + key_spacing) - key_spacing
    keyboard_height = len(keyboard_layout) * (key_height + key_spacing) - key_spacing
    start_x = (config.screen_width - keyboard_width) // 2
    search_bottom_y = int(config.screen_height * 0.111) + (config.search_font.get_height() + 40) // 2
    controls_y = config.screen_height - int(config.screen_height * 0.037)
    available_height = controls_y - search_bottom_y
    start_y = search_bottom_y + (available_height - keyboard_height - 40) // 2

    keyboard_rect = pygame.Rect(start_x - 20, start_y - 20, keyboard_width + 40, keyboard_height + 40)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], keyboard_rect, border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], keyboard_rect, 2, border_radius=12)

    for row_idx, row in enumerate(keyboard_layout):
        for col_idx, key in enumerate(row):
            x = start_x + col_idx * (key_width + key_spacing)
            y = start_y + row_idx * (key_height + key_spacing)
            key_rect = pygame.Rect(x, y, key_width, key_height)
            if (row_idx, col_idx) == config.selected_key:
                pygame.draw.rect(screen, THEME_COLORS["fond_lignes"] + (150,), key_rect, border_radius=8)
            else:
                pygame.draw.rect(screen, THEME_COLORS["button_idle"], key_rect, border_radius=8)
            pygame.draw.rect(screen, THEME_COLORS["border"], key_rect, 1, border_radius=8)
            text = config.font.render(key, True, THEME_COLORS["text"])
            text_rect = text.get_rect(center=key_rect.center)
            screen.blit(text, text_rect)

# Écran de progression de téléchargement/extraction
def draw_progress_screen(screen):
    """Affiche l'écran de progression des téléchargements avec un style moderne."""
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

    screen.blit(OVERLAY, (0, 0))

    title_text = f"{status} : {truncate_text_middle(game_name, config.font, config.screen_width - 200)}"
    title_lines = wrap_text(title_text, config.font, config.screen_width - 80)
    line_height = config.font.get_height() + 5
    text_height = len(title_lines) * line_height
    margin_top_bottom = 20
    bar_height = int(config.screen_height * 0.0278)
    percent_height = config.progress_font.get_height() + 5
    rect_height = text_height + bar_height + percent_height + 3 * margin_top_bottom
    max_text_width = max([config.font.size(line)[0] for line in title_lines], default=300)
    bar_width = max_text_width
    rect_width = max_text_width + 80
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i, line in enumerate(title_lines):
        title_render = config.font.render(line, True, THEME_COLORS["text"])
        title_rect = title_render.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(title_render, title_rect)

    bar_y = rect_y + text_height + margin_top_bottom
    progress_width = 0
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x + 20, bar_y, bar_width, bar_height), border_radius=8)
    if total_size > 0:
        progress_width = int(bar_width * (progress_percent / 100))
        pygame.draw.rect(screen, THEME_COLORS["fond_lignes"], (rect_x + 20, bar_y, progress_width, bar_height), border_radius=8)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x + 20, bar_y, bar_width, bar_height), 2, border_radius=8)

    downloaded_mb = downloaded_size / (1024 * 1024)
    total_mb = total_size / (1024 * 1024)
    size_text = f"{downloaded_mb:.1f} Mo / {total_mb:.1f} Mo"
    percent_text = f"{int(progress_percent)}%  {size_text}"
    percent_lines = wrap_text(percent_text, config.progress_font, config.screen_width - 80)
    text_y = bar_y + bar_height + margin_top_bottom
    for i, line in enumerate(percent_lines):
        percent_render = config.progress_font.render(line, True, THEME_COLORS["text"])
        percent_rect = percent_render.get_rect(center=(config.screen_width // 2, text_y + i * percent_height + percent_height // 2))
        screen.blit(percent_render, percent_rect)

# Écran popup résultat téléchargement
def draw_popup_result_download(screen, message, is_error):
    """Affiche une popup avec un message de résultat."""
    screen.blit(OVERLAY, (0, 0))
    if message is None:
        message = "Téléchargement annulé"
    logger.debug(f"Message popup : {message}, is_error={is_error}")
    # Réduire la largeur maximale pour le wrapping
    wrapped_message = wrap_text(message, config.small_font, config.screen_width - 160)
    # Débogage pour vérifier les lignes wrappées
    logger.debug(f"Lignes wrappées : {wrapped_message}")
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    margin_top_bottom = 20
    rect_height = text_height + 2 * margin_top_bottom
    max_text_width = max([config.small_font.size(line)[0] for line in wrapped_message], default=300)
    rect_width = max_text_width + 100  # Augmenter la marge
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_message):
        text = config.small_font.render(line, True, THEME_COLORS["error_text"] if is_error else THEME_COLORS["fond_lignes"])
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

# Écran avertissement extension non supportée téléchargement
def draw_extension_warning(screen):
    """Affiche un avertissement pour une extension non reconnue ou un fichier ZIP."""
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
        button_height = int(config.screen_height * 0.0463)
        margin_top_bottom = 20
        rect_height = text_height + button_height + 2 * margin_top_bottom
        max_text_width = max([config.font.size(line)[0] for line in lines], default=300)
        rect_width = max_text_width + 80
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

        for i, line in enumerate(lines):
            text_surface = config.font.render(line, True, THEME_COLORS["warning_text"])
            text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
            screen.blit(text_surface, text_rect)

        draw_stylized_button(screen, "Oui", rect_x + rect_width // 2 - 180, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.extension_confirm_selection == 1)
        draw_stylized_button(screen, "Non", rect_x + rect_width // 2 + 20, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.extension_confirm_selection == 0)

    except Exception as e:
        logger.error(f"Erreur lors du rendu de extension_warning : {str(e)}")
        error_message = "Erreur d'affichage de l'avertissement."
        wrapped_error = wrap_text(error_message, config.font, config.screen_width - 80)
        line_height = config.font.get_height() + 5
        rect_height = len(wrapped_error) * line_height + 2 * 20
        max_text_width = max([config.font.size(line)[0] for line in wrapped_error], default=300)
        rect_width = max_text_width + 80
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

        for i, line in enumerate(wrapped_error):
            error_surface = config.font.render(line, True, THEME_COLORS["error_text"])
            error_rect = error_surface.get_rect(center=(config.screen_width // 2, rect_y + 20 + i * line_height + line_height // 2))
            screen.blit(error_surface, error_rect)

# Affichage des contrôles en bas de page
def draw_controls(screen, menu_state):
    """Affiche les contrôles sur une seule ligne en bas de l’écran."""
    start_button = get_control_display('start', 'START')
    control_text = f"RGSX v{config.app_version} - {start_button} : Options - History - Help"
    max_width = config.screen_width - 40
    wrapped_controls = wrap_text(control_text, config.small_font, max_width)
    line_height = config.small_font.get_height() + 5
    rect_height = len(wrapped_controls) * line_height + 20
    rect_y = config.screen_height - rect_height - 5
    rect_x = (config.screen_width - max_width) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, max_width, rect_height), border_radius=8)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, max_width, rect_height), 1, border_radius=8)

    for i, line in enumerate(wrapped_controls):
        text_surface = config.small_font.render(line, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, rect_y + 10 + i * line_height + line_height // 2))
        screen.blit(text_surface, text_rect)

# Menu pause
def draw_pause_menu(screen, selected_option):
    """Dessine le menu pause avec un style moderne."""
    screen.blit(OVERLAY, (0, 0))

    options = [
        "Controls",
        "Remap controls",
        "History",
        "Redownload Games cache",
        "Quit"
    ]

    menu_width = int(config.screen_width * 0.8)
    line_height = config.font.get_height() + 10
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 20
    menu_height = len(options) * (button_height + 10) + 2 * margin_top_bottom
    menu_x = (config.screen_width - menu_width) // 2
    menu_y = (config.screen_height - menu_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (menu_x, menu_y, menu_width, menu_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (menu_x, menu_y, menu_width, menu_height), 2, border_radius=12)

    for i, option in enumerate(options):
        draw_stylized_button(
            screen,
            option,
            menu_x + 20,
            menu_y + margin_top_bottom + i * (button_height + 10),
            menu_width - 40,
            button_height,
            selected=i == selected_option
        )

# Menu aide contrôles
def draw_controls_help(screen, previous_state):
    """Affiche la liste des contrôles avec un style moderne."""
    common_controls = {
        "confirm": lambda action: f"{get_control_display('confirm', 'Entrée/A/Croix')} : {action}",
        "cancel": lambda action: f"{get_control_display('cancel', 'Échap/B/Rond')} : {action}",
        "start": lambda: f"{get_control_display('start', 'Start/')} : Menu",
        "progress": lambda action: f"{get_control_display('progress', 'X/Carré')} : {action}",
        "up": lambda action: f"{get_control_display('up', 'Flèche Haut')} : {action}",
        "down": lambda action: f"{get_control_display('down', 'Flèche Bas')} : {action}",
        "page_up": lambda action: f"{get_control_display('page_up', 'Q/LB/L1')} : {action}",
        "page_down": lambda action: f"{get_control_display('page_down', 'E/RB/R1')} : {action}",
        "filter": lambda action: f"{get_control_display('filter', 'Select')} : {action}",
        "history": lambda action: f"{get_control_display('history', 'H/Y/Triangle')} : {action}",
        "delete": lambda: f"{get_control_display('delete', 'Backspace/LT/L2')} : Supprimer",
        "space": lambda: f"{get_control_display('space', 'Espace/RT/R2')} : Espace"
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
            common_controls["history"]("Historique"),
            *( [common_controls["progress"]("Progression")] if config.download_tasks else [])
        ],
        "game": [
            common_controls["confirm"](f"{'Selectionner' if config.search_mode else 'Télécharger'}"),
            common_controls["filter"]("Filtrer"),
            common_controls["cancel"](f"{'Annuler' if config.search_mode else 'Retour'}"),
            common_controls["history"]("Historique"),
            *( [
                common_controls["delete"](),
                common_controls["space"]()
            ] if config.search_mode and config.is_non_pc else []),
            *( [
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
        ],
        "history": [
            common_controls["confirm"]("Retélécharger"),
            common_controls["cancel"]("Retour"),
            common_controls["progress"]("Vider l'historique"),
            f"{common_controls['up']('Naviguer')} / {common_controls['down']('Naviguer')}",
            f"{common_controls['page_up']('Page')} / {common_controls['page_down']('Page')}",
            common_controls["start"]()
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

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (popup_x, popup_y, popup_width, popup_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (popup_x, popup_y, popup_width, popup_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_controls):
        text = config.font.render(line, True, THEME_COLORS["text"])
        text_rect = text.get_rect(center=(config.screen_width // 2, popup_y + 40 + i * line_height))
        screen.blit(text, text_rect)

# Menu Quitter Appli
def draw_confirm_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour quitter."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))
        logger.debug("OVERLAY recréé dans draw_confirm_dialog")

    screen.blit(OVERLAY, (0, 0))
    message = "Quitter l'application ?"
    wrapped_message = wrap_text(message, config.font, config.screen_width - 80)
    line_height = config.font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 20
    rect_height = text_height + button_height + 2 * margin_top_bottom
    max_text_width = max([config.font.size(line)[0] for line in wrapped_message], default=300)
    rect_width = max_text_width + 150
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_message):
        text = config.font.render(line, True, THEME_COLORS["text"])
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

    draw_stylized_button(screen, "Oui", rect_x + rect_width // 2 - 180, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.confirm_selection == 1)
    draw_stylized_button(screen, "Non", rect_x + rect_width // 2 + 20, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.confirm_selection == 0)

# draw_redownload_game_cache_dialog
def draw_redownload_game_cache_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour retélécharger le cache des jeux."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))
        logger.debug("OVERLAY recréé dans draw_redownload_game_cache_dialog")

    screen.blit(OVERLAY, (0, 0))
    message = "Retélécharger le cache des jeux ?"
    wrapped_message = wrap_text(message, config.small_font, config.screen_width - 80)
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 20
    rect_height = text_height + button_height + 2 * margin_top_bottom
    max_text_width = max([config.small_font.size(line)[0] for line in wrapped_message], default=300)
    rect_width = max_text_width + 80
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_message):
        text = config.small_font.render(line, True, THEME_COLORS["text"])
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

    draw_stylized_button(screen, "Oui", rect_x + rect_width // 2 - 180, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.redownload_confirm_selection == 1)
    draw_stylized_button(screen, "Non", rect_x + rect_width // 2 + 20, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.redownload_confirm_selection == 0)

# Popup avec compte à rebours
def draw_popup(screen):
    """Dessine un popup avec un message et un compte à rebours."""
    screen.blit(OVERLAY, (0, 0))

    popup_width = int(config.screen_width * 0.8)
    line_height = config.small_font.get_height() + 10
    text_lines = config.popup_message.split('\n')
    text_height = len(text_lines) * line_height
    margin_top_bottom = 20
    popup_height = text_height + 2 * margin_top_bottom + line_height
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (popup_x, popup_y, popup_width, popup_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (popup_x, popup_y, popup_width, popup_height), 2, border_radius=12)

    for i, line in enumerate(text_lines):
        text_surface = config.small_font.render(line, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, popup_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text_surface, text_rect)

    remaining_time = max(0, config.popup_timer // 1000)
    countdown_text = f"Ce message se fermera dans {remaining_time} seconde{'s' if remaining_time != 1 else ''}"
    countdown_surface = config.small_font.render(countdown_text, True, THEME_COLORS["text"])
    countdown_rect = countdown_surface.get_rect(center=(config.screen_width // 2, popup_y + margin_top_bottom + len(text_lines) * line_height + line_height // 2))
    screen.blit(countdown_surface, countdown_rect)


# Variables globales pour la popup de musique
current_music_name = None
music_popup_start_time = None
MUSIC_POPUP_DURATION = 5  # Durée d'affichage en secondes

def draw_music_popup(screen):
    """Affiche une popup discrète en bas à droite avec le nom de la musique en cours."""
    global current_music_name, music_popup_start_time
    
    if current_music_name is None or music_popup_start_time is None:
        return
    
    # Vérifier si la popup doit encore être affichée
    current_time = pygame.time.get_ticks() / 1000  # Temps en secondes
    if current_time - music_popup_start_time > MUSIC_POPUP_DURATION:
        current_music_name = None
        music_popup_start_time = None
        return
    
    # Paramètres de la popup
    font = config.small_font
    text = font.render(current_music_name, True, THEME_COLORS["text"])
    text_width, text_height = font.size(current_music_name)
    padding = 10
    rect_width = text_width + 2 * padding
    rect_height = text_height + 2 * padding
    rect_x = config.screen_width - rect_width - 22 # 20 pixels de marge à droite
    rect_y = config.screen_height - rect_height - 8 # 20 pixels de marge en bas
    
    # Créer une surface semi-transparente
    popup_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
    pygame.draw.rect(popup_surface, THEME_COLORS["fond_image"] + (180,), (0, 0, rect_width, rect_height), border_radius=8)
    pygame.draw.rect(popup_surface, THEME_COLORS["border"] + (200,), (0, 0, rect_width, rect_height), 1, border_radius=8)
    
    # Ajouter le texte
    text_rect = text.get_rect(center=(rect_width // 2, rect_height // 2))
    popup_surface.blit(text, text_rect)
    
    # Afficher la popup
    screen.blit(popup_surface, (rect_x, rect_y))


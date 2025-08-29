import pygame  # type: ignore
import config
from utils import truncate_text_middle, wrap_text, load_system_image, truncate_text_end
import logging
import math
from history import load_history  # Ajout de l'import
from language import _  # Import de la fonction de traduction

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
        _("welcome_message"),
        _("disclaimer_line1"),
        _("disclaimer_line2"),
        _("disclaimer_line3"),
        _("disclaimer_line4"),
        _("disclaimer_line5"),
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

    progress_text = config.small_font.render(_("loading_progress").format(int(config.loading_progress)), True, THEME_COLORS["text"])
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

    draw_stylized_button(screen, _("button_OK"), rect_x + rect_width // 2 - 80, rect_y + text_height + margin_top_bottom, 160, button_height, selected=True)

# Récupérer les noms d'affichage des contrôles
def get_control_display(action, default):
    """Récupère le nom d'affichage d'une action depuis controls_config."""
    if not config.controls_config:
        logger.warning(f"controls_config vide pour l'action {action}, utilisation de la valeur par défaut")
        return default
    
    control_config = config.controls_config.get(action, {})
    control_type = control_config.get('type', '')
    
    # Générer le nom d'affichage basé sur la configuration réelle
    if control_type == 'key':
        key_code = control_config.get('key')
        key_names = {
            pygame.K_RETURN: "Enter",
            pygame.K_ESCAPE: "Échap",
            pygame.K_SPACE: "Espace",
            pygame.K_UP: "↑",
            pygame.K_DOWN: "↓",
            pygame.K_LEFT: "←",
            pygame.K_RIGHT: "→",
            pygame.K_BACKSPACE: "Backspace",
            pygame.K_TAB: "Tab",
            pygame.K_LALT: "Alt",
            pygame.K_RALT: "AltGR",
            pygame.K_LCTRL: "LCtrl",
            pygame.K_RCTRL: "RCtrl",
            pygame.K_LSHIFT: "LShift",
            pygame.K_RSHIFT: "RShift",
            pygame.K_LMETA: "LMeta",
            pygame.K_RMETA: "RMeta",
            pygame.K_CAPSLOCK: "Verr Maj",
            pygame.K_NUMLOCK: "Verr Num",
            pygame.K_SCROLLOCK: "Verr Déf",
            pygame.K_a: "A",
            pygame.K_b: "B",
            pygame.K_c: "C",
            pygame.K_d: "D",
            pygame.K_e: "E",
            pygame.K_f: "F",
            pygame.K_g: "G",
            pygame.K_h: "H",
            pygame.K_i: "I",
            pygame.K_j: "J",
            pygame.K_k: "K",
            pygame.K_l: "L",
            pygame.K_m: "M",
            pygame.K_n: "N",
            pygame.K_o: "O",
            pygame.K_p: "P",
            pygame.K_q: "Q",
            pygame.K_r: "R",
            pygame.K_s: "S",
            pygame.K_t: "T",
            pygame.K_u: "U",
            pygame.K_v: "V",
            pygame.K_w: "W",
            pygame.K_x: "X",
            pygame.K_y: "Y",
            pygame.K_z: "Z",
            pygame.K_0: "0",
            pygame.K_1: "1",
            pygame.K_2: "2",
            pygame.K_3: "3",
            pygame.K_4: "4",
            pygame.K_5: "5",
            pygame.K_6: "6",
            pygame.K_7: "7",
            pygame.K_8: "8",
            pygame.K_9: "9",
            pygame.K_KP0: "Num 0",
            pygame.K_KP1: "Num 1",
            pygame.K_KP2: "Num 2",
            pygame.K_KP3: "Num 3",
            pygame.K_KP4: "Num 4",
            pygame.K_KP5: "Num 5",
            pygame.K_KP6: "Num 6",
            pygame.K_KP7: "Num 7",
            pygame.K_KP8: "Num 8",
            pygame.K_KP9: "Num 9",
            pygame.K_KP_PERIOD: "Num .",
            pygame.K_KP_DIVIDE: "Num /",
            pygame.K_KP_MULTIPLY: "Num *",
            pygame.K_KP_MINUS: "Num -",
            pygame.K_KP_PLUS: "Num +",
            pygame.K_KP_ENTER: "Num Enter",
            pygame.K_KP_EQUALS: "Num =",
            pygame.K_F1: "F1",
            pygame.K_F2: "F2",
            pygame.K_F3: "F3",
            pygame.K_F4: "F4",
            pygame.K_F5: "F5",
            pygame.K_F6: "F6",
            pygame.K_F7: "F7",
            pygame.K_F8: "F8",
            pygame.K_F9: "F9",
            pygame.K_F10: "F10",
            pygame.K_F11: "F11",
            pygame.K_F12: "F12",
            pygame.K_F13: "F13",
            pygame.K_F14: "F14",
            pygame.K_F15: "F15",
            pygame.K_INSERT: "Inser",
            pygame.K_DELETE: "Suppr",
            pygame.K_HOME: "Début",
            pygame.K_END: "Fin",
            pygame.K_PAGEUP: "Page+",
            pygame.K_PAGEDOWN: "Page-",
            pygame.K_PRINT: "Printscreen",
            pygame.K_SYSREQ: "SysReq",
            pygame.K_BREAK: "Pause",
            pygame.K_PAUSE: "Pause",
            pygame.K_BACKQUOTE: "`",
            pygame.K_MINUS: "-",
            pygame.K_EQUALS: "=",
            pygame.K_LEFTBRACKET: "[",
            pygame.K_RIGHTBRACKET: "]",
            pygame.K_BACKSLASH: "\\",
            pygame.K_SEMICOLON: ";",
            pygame.K_QUOTE: "'",
            pygame.K_COMMA: ",",
            pygame.K_PERIOD: ".",
            pygame.K_SLASH: "/",
        }
        return key_names.get(key_code, chr(key_code) if 32 <= key_code <= 126 else f"Key{key_code}")
    
    elif control_type == 'button':
        button_id = control_config.get('button')
        button_names = {
            0: "A", 1: "B", 2: "X", 3: "Y",
            4: "LB", 5: "RB", 6: "Select", 7: "Start"
        }
        return button_names.get(button_id, f"Btn{button_id}")
    
    elif control_type == 'hat':
        hat_value = control_config.get('value', (0, 0))
        hat_names = {
            (0, 1): "D↑", (0, -1): "D↓",
            (-1, 0): "D←", (1, 0): "D→"
        }
        return hat_names.get(tuple(hat_value) if isinstance(hat_value, list) else hat_value, "D-Pad")
    
    elif control_type == 'axis':
        axis_id = control_config.get('axis')
        direction = control_config.get('direction')
        axis_names = {
            (0, -1): "J←", (0, 1): "J→",
            (1, -1): "J↑", (1, 1): "J↓"
        }
        return axis_names.get((axis_id, direction), f"Joy{axis_id}")
    
    # Fallback vers l'ancien système ou valeur par défaut
    return control_config.get('display', default)

# Cache pour les images des plateformes
platform_images_cache = {}

# Grille des systèmes 3x3
def draw_platform_grid(screen):
    """Affiche la grille des plateformes avec un style moderne et fluide."""
    global platform_images_cache
    
    if not config.platforms or config.selected_platform >= len(config.platforms):
        platform_name = _("platform_no_platform")
        logger.warning("Aucune plateforme ou selected_platform hors limites")
    else:
        platform = config.platforms[config.selected_platform]
        platform_name = config.platform_names.get(platform, platform)
    
    # Affichage du titre avec animation subtile
    title_text = f"{platform_name}"
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
    title_rect_inflated = title_rect.inflate(60, 30)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)

    # Effet de pulsation subtil pour le titre - calculé une seule fois par frame
    current_time = pygame.time.get_ticks()
    pulse_factor = 0.05 * (1 + math.sin(current_time / 500))
    title_glow = pygame.Surface((title_rect_inflated.width + 10, title_rect_inflated.height + 10), pygame.SRCALPHA)
    pygame.draw.rect(title_glow, THEME_COLORS["neon"] + (int(40 * pulse_factor),), 
                    title_glow.get_rect(), border_radius=14)
    screen.blit(title_glow, (title_rect_inflated.left - 5, title_rect_inflated.top - 5))
    
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
    screen.blit(title_surface, title_rect)

    # Configuration de la grille - calculée une seule fois
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

    # Affichage des indicateurs de page si nécessaire
    total_pages = (len(config.platforms) + systems_per_page - 1) // systems_per_page
    if total_pages > 1:
        page_indicator_text = _("platform_page").format(config.current_page + 1, total_pages)
        page_indicator = config.small_font.render(page_indicator_text, True, THEME_COLORS["text"])
        page_rect = page_indicator.get_rect(center=(config.screen_width // 2, config.screen_height - margin_bottom // 2))
        screen.blit(page_indicator, page_rect)

    # Calculer une seule fois la pulsation pour les éléments sélectionnés
    pulse = 0.1 * math.sin(current_time / 300)
    glow_intensity = 40 + int(30 * math.sin(current_time / 300))
    
    # Pré-calcul des images pour optimiser le rendu
    start_idx = config.current_page * systems_per_page
    for idx in range(start_idx, start_idx + systems_per_page):
        if idx >= len(config.platforms):
            break
        grid_idx = idx - start_idx
        row = grid_idx // num_cols
        col = grid_idx % num_cols
        x = x_positions[col]
        y = y_positions[row]
        
        # Animation fluide pour l'item sélectionné
        is_selected = idx == config.selected_platform
        scale_base = 1.5 if is_selected else 1.0
        scale = scale_base + pulse if is_selected else scale_base
            
        platform_dict = config.platform_dicts[idx]
        platform_id = platform_dict.get("platform", str(idx))
        
        # Utiliser le cache d'images pour éviter de recharger/redimensionner à chaque frame
        cache_key = f"{platform_id}_{scale:.2f}"
        if cache_key not in platform_images_cache:
            image = load_system_image(platform_dict)
            if image:
                orig_width, orig_height = image.get_width(), image.get_height()
                max_size = int(min(col_width, row_height) * scale * 1.1)  # Légèrement plus grand que la cellule
                ratio = min(max_size / orig_width, max_size / orig_height)
                new_width = int(orig_width * ratio)
                new_height = int(orig_height * ratio)
                scaled_image = pygame.transform.smoothscale(image, (new_width, new_height))
                platform_images_cache[cache_key] = {
                    "image": scaled_image,
                    "width": new_width,
                    "height": new_height,
                    "last_used": current_time
                }
            else:
                continue
        else:
            # Mettre à jour le timestamp de dernière utilisation
            platform_images_cache[cache_key]["last_used"] = current_time
            scaled_image = platform_images_cache[cache_key]["image"]
            new_width = platform_images_cache[cache_key]["width"]
            new_height = platform_images_cache[cache_key]["height"]
        
        image_rect = scaled_image.get_rect(center=(x, y))

        # Effet visuel amélioré pour l'item sélectionné
        if is_selected:
            neon_color = THEME_COLORS["neon"]
            border_radius = 12
            padding = 12
            rect_width = image_rect.width + 2 * padding
            rect_height = image_rect.height + 2 * padding
            
            # Effet de glow dynamique
            neon_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
            pygame.draw.rect(neon_surface, neon_color + (glow_intensity,), neon_surface.get_rect(), border_radius=border_radius)
            pygame.draw.rect(neon_surface, neon_color + (100,), neon_surface.get_rect().inflate(-10, -10), border_radius=border_radius)
            pygame.draw.rect(neon_surface, neon_color + (200,), neon_surface.get_rect().inflate(-20, -20), width=1, border_radius=border_radius)
            screen.blit(neon_surface, (image_rect.left - padding, image_rect.top - padding), special_flags=pygame.BLEND_RGBA_ADD)

        # Fond pour toutes les images
        background_surface = pygame.Surface((image_rect.width + 10, image_rect.height + 10), pygame.SRCALPHA)
        bg_alpha = 220 if is_selected else 180  # Plus opaque pour l'item sélectionné
        pygame.draw.rect(background_surface, THEME_COLORS["fond_image"] + (bg_alpha,), background_surface.get_rect(), border_radius=12)
        screen.blit(background_surface, (image_rect.left - 5, image_rect.top - 5))

        # Affichage de l'image avec un léger effet de transparence pour les items non sélectionnés
        if not is_selected:
            # Appliquer la transparence seulement si nécessaire
            temp_image = scaled_image.copy()
            temp_image.set_alpha(220)
            screen.blit(temp_image, image_rect)
        else:
            screen.blit(scaled_image, image_rect)
    
    # Nettoyer le cache périodiquement (garder seulement les images utilisées récemment)
    if len(platform_images_cache) > 50:  # Limite arbitraire pour éviter une croissance excessive
        current_time = pygame.time.get_ticks()
        cache_timeout = 30000  # 30 secondes
        keys_to_remove = [k for k, v in platform_images_cache.items() 
                         if current_time - v["last_used"] > cache_timeout]
        for key in keys_to_remove:
            del platform_images_cache[key]

# Liste des jeux
def draw_game_list(screen):
    """Affiche la liste des jeux avec un style moderne."""
    platform = config.platforms[config.current_platform]
    platform_name = config.platform_names.get(platform, platform)
    games = config.filtered_games if config.filter_active or config.search_mode else config.games
    game_count = len(games)

    if not games:
        logger.debug("Aucune liste de jeux disponible")
        message = _("game_no_games")
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
        search_text = _("game_search").format(config.search_query + "_")
        title_surface = config.search_font.render(search_text, True, THEME_COLORS["text"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)
    elif config.filter_active:
        filter_text = _("game_filter").format(config.search_query)
        title_surface = config.font.render(filter_text, True, THEME_COLORS["fond_lignes"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)
    else:
        title_text = _("game_count").format(platform_name, game_count)
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
        is_marked = i in getattr(config, 'selected_games', set())
        # Couleur verte si jeu sous curseur OU marqué en multi-sélection
        color = THEME_COLORS["fond_lignes"] if (i == config.current_game or is_marked) else THEME_COLORS["text"]
        # Préfixe ASCII pour distinguer les jeux marqués (éviter collision glyphes)
        prefix = "[X] " if is_marked else "    "
        game_text = truncate_text_middle(prefix + game_name, config.small_font, rect_width - 40, is_filename=False)
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

def format_size(size):
    """Convertit une taille en octets en format lisible."""
    if not isinstance(size, (int, float)) or size == 0:
        return "N/A"
    
    for unit in ['o', 'Ko', 'Mo', 'Go', 'To']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} Po"


def draw_history_list(screen):
    # logger.debug(f"Dessin historique, history={config.history}, needs_redraw={config.needs_redraw}")
    history = config.history if hasattr(config, 'history') else load_history()
    history_count = len(history)

    # Cherche une entrée en cours de téléchargement pour afficher la vitesse
    speed_str = ""
    for entry in history:
        if entry.get("status") in ["Téléchargement", "downloading"]:
            speed = entry.get("speed", 0.0)
            if speed and speed > 0:
                speed_str = f" - {speed:.2f} Mo/s"
            break

    screen.blit(OVERLAY, (0, 0))
    title_text = _("history_title").format(history_count) + speed_str
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
    title_rect_inflated = title_rect.inflate(60, 30)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)  # fond opaque
    pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
    screen.blit(title_surface, title_rect)

    # Define column widths as percentages of available space
    column_width_percentages = {
        "platform": 0.20,  # platform column
        "game_name": 0.50,  #  game name column
        "size": 0.10,  # size column
        "status": 0.20     #  status column
    }
    available_width = int(0.95 * config.screen_width - 60)  # Total available width for columns
    col_platform_width = int(available_width * column_width_percentages["platform"])
    col_game_width = int(available_width * column_width_percentages["game_name"])
    col_size_width = int(available_width * column_width_percentages["size"])
    col_status_width = int(available_width * column_width_percentages["status"])
    rect_width = int(0.95 * config.screen_width)

    line_height = config.small_font.get_height() + 10
    header_height = line_height
    margin_top_bottom = 20
    extra_margin_top = 40
    extra_margin_bottom = 80
    title_height = config.title_font.get_height() + 20

    # Sécuriser current_history_item pour éviter IndexError
    if history:
        if config.current_history_item < 0 or config.current_history_item >= len(history):
            config.current_history_item = max(0, min(len(history) - 1, config.current_history_item))
    else:
        config.current_history_item = 0

    speed = 0.0
    if history and history[config.current_history_item].get("status") in ["Téléchargement", "downloading"]:
        speed = history[config.current_history_item].get("speed", 0.0)
    if speed > 0:
        speed_str = f"{speed:.2f} Mo/s"
        title_text = _("history_title").format(history_count) + f" {speed_str}"
    else:
        title_text = _("history_title").format(history_count)
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
   

    if not history:
        logger.debug("Aucun historique disponible")
        message = _("history_empty")
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


    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    headers = [_("history_column_system"), _("history_column_game"), _("history_column_size"), _("history_column_status")]
    header_y = rect_y + margin_top_bottom + header_height // 2
    header_x_positions = [
        rect_x + 20 + col_platform_width // 2,
        rect_x + 20 + col_platform_width + col_game_width // 2,
        rect_x + 20 + col_platform_width + col_game_width + col_size_width // 2,
        rect_x + 20 + col_platform_width + col_game_width + col_size_width + col_status_width // 2
    ]
    for header, x_pos in zip(headers, header_x_positions):
        text_surface = config.small_font.render(header, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(x_pos, header_y))
        screen.blit(text_surface, text_rect)

    separator_y = rect_y + margin_top_bottom + header_height
    pygame.draw.line(screen, THEME_COLORS["border"], (rect_x + 20, separator_y), (rect_x + rect_width - 20, separator_y), 2)

    for idx, i in enumerate(range(config.history_scroll_offset, min(config.history_scroll_offset + items_per_page, len(history)))):
        entry = history[i]
        platform = entry.get("platform", "Inconnu")
        game_name = entry.get("game_name", "Inconnu")
        
        # Correction du calcul de la taille
        size = entry.get("total_size", 0)
        color = THEME_COLORS["fond_lignes"] if i == config.current_history_item else THEME_COLORS["text"]
        size_text = format_size(size)
        
        status = entry.get("status", "Inconnu")
        progress = entry.get("progress", 0)
        

        # Personnaliser l'affichage du statut
        if status in ["Téléchargement", "downloading"]:
            status_text = _("history_status_downloading").format(progress)
            # logger.debug(f"Affichage progression: {progress:.1f}% pour {game_name}, status={status_text}")
        elif status == "Extracting":
            status_text = _("history_status_extracting").format(progress)
            # logger.debug(f"Affichage extraction: {progress:.1f}% pour {game_name}, status={status_text}")
        elif status == "Download_OK":
            status_text = _("history_status_completed")
                 # S'assurer que le pourcentage est entre 0 et 100
        progress = max(0, min(100, progress))
        # Personnaliser l'affichage du statut
        if status in ["Téléchargement", "downloading"]:
            status_text = _("history_status_downloading").format(progress)
            # logger.debug(f"Affichage progression: {progress:.1f}% pour {game_name}, status={status_text}")
        elif status == "Extracting":
            status_text = _("history_status_extracting").format(progress)
            # logger.debug(f"Affichage extraction: {progress:.1f}% pour {game_name}, status={status_text}")
        elif status == "Download_OK":
            status_text = _("history_status_completed")
            # logger.debug(f"Affichage terminé: {game_name}, status={status_text}")
        elif status == "Erreur":
            status_text = _("history_status_error").format(entry.get('message', 'Échec'))
        elif status == "Canceled":
            status_text = _("history_status_canceled")
        else:
            status_text = status
            #logger.debug(f"Affichage statut inconnu: {game_name}, status={status_text}")

        platform_text = truncate_text_end(platform, config.small_font, col_platform_width - 10)
        game_text = truncate_text_end(game_name, config.small_font, col_game_width - 10)
        size_text = truncate_text_end(size_text, config.small_font, col_size_width - 10)
        status_text = truncate_text_middle(status_text, config.small_font, col_status_width - 10, is_filename=False)

        y_pos = rect_y + margin_top_bottom + header_height + idx * line_height + line_height // 2
        platform_surface = config.small_font.render(platform_text, True, color)
        game_surface = config.small_font.render(game_text, True, color)
        size_surface = config.small_font.render(size_text, True, color)  # Correction ici
        status_surface = config.small_font.render(status_text, True, color)

        platform_rect = platform_surface.get_rect(center=(header_x_positions[0], y_pos))
        game_rect = game_surface.get_rect(center=(header_x_positions[1], y_pos))
        size_rect = size_surface.get_rect(center=(header_x_positions[2], y_pos))
        status_rect = status_surface.get_rect(center=(header_x_positions[3], y_pos))

        if i == config.current_history_item:
            glow_surface = pygame.Surface((rect_width - 40, line_height), pygame.SRCALPHA)
            pygame.draw.rect(glow_surface, THEME_COLORS["fond_lignes"] + (50,), (0, 0, rect_width - 40, line_height), border_radius=8)
            screen.blit(glow_surface, (rect_x + 20, y_pos - line_height // 2))

        screen.blit(platform_surface, platform_rect)
        screen.blit(game_surface, game_rect)
        screen.blit(size_surface, size_rect)
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

    message = _("confirm_clear_history")
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

    button_width = min(160, (rect_width - 60) // 2)
    draw_stylized_button(screen, _("button_yes"), rect_x + rect_width // 2 - button_width - 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=config.confirm_clear_selection == 1)
    draw_stylized_button(screen, _("button_no"), rect_x + rect_width // 2 + 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=config.confirm_clear_selection == 0)

def draw_cancel_download_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour annuler un téléchargement."""
    screen.blit(OVERLAY, (0, 0))

    message = _("confirm_cancel_download")
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

    button_width = min(160, (rect_width - 60) // 2)
    draw_stylized_button(screen, _("button_yes"), rect_x + rect_width // 2 - button_width - 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=config.confirm_cancel_selection == 1)
    draw_stylized_button(screen, _("button_no"), rect_x + rect_width // 2 + 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=config.confirm_cancel_selection == 0)

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
    # S'assurer que le pourcentage est entre 0 et 100
    progress_percent = max(0, min(100, progress_percent))

    screen.blit(OVERLAY, (0, 0))

    title_text = _("download_status").format(status, truncate_text_middle(game_name, config.font, config.screen_width - 200))
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
        # Limiter le pourcentage entre 0 et 100 pour l'affichage de la barre
        progress_width = int(bar_width * (min(100, max(0, progress_percent)) / 100))


## Ancienne fonction draw_popup_result_download supprimée (popup de fin de téléchargement retiré)

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
        message = _("extension_warning_zip").format(game_name)
    else:
        message = _("extension_warning_unsupported").format(game_name)

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

        draw_stylized_button(screen, _("button_yes"), rect_x + rect_width // 2 - 180, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.extension_confirm_selection == 1)
        draw_stylized_button(screen, _("button_no"), rect_x + rect_width // 2 + 20, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.extension_confirm_selection == 0)

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
def draw_controls(screen, menu_state, current_music_name=None, music_popup_start_time=0):
    """Affiche les contrôles sur une seule ligne en bas de l’écran."""
    start_button = get_control_display('start', 'START')
    start_text = _("controls_action_start")
    control_text = f"RGSX v{config.app_version} - {start_button} : {start_text}"
    
    # Ajouter le nom de la musique si disponible
    if config.current_music_name and config.music_popup_start_time > 0:
        current_time = pygame.time.get_ticks() / 1000
        if current_time - config.music_popup_start_time < 3.0:  # Afficher pendant 3 secondes
            control_text += f" | {config.current_music_name}"
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
def draw_language_menu(screen):
    """Dessine le menu de sélection de langue avec un style moderne."""
    from language import get_available_languages, get_language_name
    
    screen.blit(OVERLAY, (0, 0))
    
    # Obtenir les langues disponibles
    available_languages = get_available_languages()
    
    if not available_languages:
        logger.error("Aucune langue disponible")
        return
    
    # Titre
    title_text = _("language_select_title")
    title_surface = config.font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, config.screen_height // 4))
    
    # Fond du titre
    title_bg_rect = title_rect.inflate(40, 20)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_bg_rect, border_radius=10)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_bg_rect, 2, border_radius=10)
    screen.blit(title_surface, title_rect)
    
    # Options de langue
    button_height = 60
    button_width = 300
    button_spacing = 20
    
    total_height = len(available_languages) * (button_height + button_spacing) - button_spacing
    start_y = (config.screen_height - total_height) // 2
    
    for i, lang_code in enumerate(available_languages):
        # Obtenir le nom de la langue
        lang_name = get_language_name(lang_code)
        
        # Position du bouton
        button_x = (config.screen_width - button_width) // 2
        button_y = start_y + i * (button_height + button_spacing)
        
        # Dessiner le bouton
        button_color = THEME_COLORS["button_hover"] if i == config.selected_language_index else THEME_COLORS["button_idle"]
        pygame.draw.rect(screen, button_color, (button_x, button_y, button_width, button_height), border_radius=10)
        pygame.draw.rect(screen, THEME_COLORS["border"], (button_x, button_y, button_width, button_height), 2, border_radius=10)
        
        # Texte du bouton
        text_surface = config.font.render(lang_name, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(button_x + button_width // 2, button_y + button_height // 2))
        screen.blit(text_surface, text_rect)
    
    # Instructions
    instruction_text = _("language_select_instruction")
    instruction_surface = config.small_font.render(instruction_text, True, THEME_COLORS["text"])
    instruction_rect = instruction_surface.get_rect(center=(config.screen_width // 2, config.screen_height - 50))
    screen.blit(instruction_surface, instruction_rect)

def draw_pause_menu(screen, selected_option):
    """Dessine le menu pause avec un style moderne."""
    screen.blit(OVERLAY, (0, 0))

    # Option musique dynamique
    if config.music_enabled:
        music_name = config.current_music_name or ""
        music_option = _("menu_music_enabled").format(music_name)
    else:
        music_option = _("menu_music_disabled")

    # Option symlink dynamique
    from rgsx_settings import get_symlink_option
    if get_symlink_option():
        symlink_option = _("symlink_option_enabled")
    else:
        symlink_option = _("symlink_option_disabled")

    options = [
        _("menu_controls"),
        _("menu_remap_controls"),
        _("menu_history"),
        _("menu_language"),
        _("menu_accessibility"),
        _("menu_redownload_cache"),
        music_option,  # Ici l'option dynamique
        symlink_option,
        _("menu_quit")
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
    """Affiche la liste des contrôles (aide) avec mise en page adaptative."""
    # Contenu des catégories
    control_categories = {
        _("controls_category_navigation"): [
            f"{get_control_display('up', '↑')} {get_control_display('down', '↓')} {get_control_display('left', '←')} {get_control_display('right', '→')} : {_('controls_navigation')}",
            f"{get_control_display('page_up', 'LB')} {get_control_display('page_down', 'RB')} : {_('controls_pages')}",
        ],
        _("controls_category_main_actions"): [
            f"{get_control_display('confirm', 'A')} : {_('controls_confirm_select')}",
            f"{get_control_display('cancel', 'B')} : {_('controls_cancel_back')}",
            f"{get_control_display('start', 'Start')} : {_('controls_action_start')}",
        ],
        _("controls_category_downloads"): [
            f"{get_control_display('history', 'Y')} : {_('controls_action_history')}",
            f"{get_control_display('clear_history', 'X')} : {_('controls_action_clear_history')}",
        ],
        _("controls_category_search"): [
            f"{get_control_display('filter', 'Select')} : {_('controls_filter_search')}",
            f"{get_control_display('delete', 'Suppr')} : {_('controls_action_delete')}",
            f"{get_control_display('space', 'Espace')} : {_('controls_action_space')}",
        ],
    }

    # États autorisés (même logique qu'avant)
    allowed_states = {
        "error", "platform", "game", "confirm_exit",
        "extension_warning", "history", "clear_history"
    }
    if previous_state not in allowed_states:
        return

    screen.blit(OVERLAY, (0, 0))

    # Paramètres d'affichage
    font = config.small_font
    title_font = config.title_font
    section_font = config.font
    line_spacing = max(4, font.get_height() // 6)
    section_spacing = font.get_height() // 2
    title_spacing = font.get_height()
    padding = 24
    inter_col_spacing = 48
    max_panel_width = int(config.screen_width * 0.9)
    max_panel_height = int(config.screen_height * 0.9)

    # Découpage en 2 colonnes (équilibré)
    categories_list = list(control_categories.items())
    mid = len(categories_list) // 2
    col1_categories = categories_list[:mid]
    col2_categories = categories_list[mid:]

    # Largeur cible par colonne (avant wrapping)
    target_col_width = (max_panel_width - 2 * padding - inter_col_spacing) // 2

    def wrap_lines_for_column(cat_pairs):
        wrapped = []  # liste de (is_section_title, surface)
        max_width = 0
        total_height = 0
        for section_title, lines in cat_pairs:
            # Titre section
            sec_surf = section_font.render(section_title, True, THEME_COLORS["fond_lignes"])
            wrapped.append((True, sec_surf))
            total_height += sec_surf.get_height() + line_spacing

            for raw_line in lines:
                # Wrap par mots
                words = raw_line.split()
                cur = ""
                for word in words:
                    test = (cur + " " + word).strip()
                    if font.size(test)[0] <= target_col_width:
                        cur = test
                    else:
                        if cur:
                            line_surf = font.render(cur, True, THEME_COLORS["text"])
                            wrapped.append((False, line_surf))
                            total_height += line_surf.get_height() + line_spacing
                            max_width = max(max_width, line_surf.get_width())
                        cur = word
                if cur:
                    line_surf = font.render(cur, True, THEME_COLORS["text"])
                    wrapped.append((False, line_surf))
                    total_height += line_surf.get_height() + line_spacing
                    max_width = max(max_width, line_surf.get_width())

            total_height += section_spacing  # espace après section
            max_width = max(max_width, sec_surf.get_width())

        if wrapped and not wrapped[-1][0]:
            total_height -= section_spacing  # retirer excédent final
        return wrapped, max_width, total_height

    col1_wrapped, col1_w, col1_h = wrap_lines_for_column(col1_categories)
    col2_wrapped, col2_w, col2_h = wrap_lines_for_column(col2_categories)

    col_widths_sum = col1_w + col2_w + inter_col_spacing
    content_width = min(max_panel_width - 2 * padding, max(col_widths_sum, col1_w + col2_w + inter_col_spacing))
    panel_width = content_width + 2 * padding

    title_surf = title_font.render(_("controls_help_title"), True, THEME_COLORS["text"])
    title_height = title_surf.get_height()

    content_height = max(col1_h, col2_h)
    panel_height = title_height + title_spacing + content_height + 2 * padding
    if panel_height > max_panel_height:
        panel_height = max_panel_height
        enable_clip = True
    else:
        enable_clip = False

    panel_x = (config.screen_width - panel_width) // 2
    panel_y = (config.screen_height - panel_height) // 2

    # Fond panel
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (panel_x, panel_y, panel_width, panel_height), border_radius=16)
    pygame.draw.rect(screen, THEME_COLORS["border"], (panel_x, panel_y, panel_width, panel_height), 2, border_radius=16)

    # Titre
    title_rect = title_surf.get_rect(center=(panel_x + panel_width // 2, panel_y + padding + title_height // 2))
    screen.blit(title_surf, title_rect)

    # Zones de colonnes
    col_top = panel_y + padding + title_height + title_spacing
    col1_x = panel_x + padding
    col2_x = panel_x + panel_width - padding - col2_w

    # Clip si nécessaire
    prev_clip = None
    if enable_clip:
        prev_clip = screen.get_clip()
        clip_rect = pygame.Rect(panel_x + padding, col_top, panel_width - 2 * padding, panel_height - (col_top - panel_y) - padding)
        screen.set_clip(clip_rect)

    # Dessin colonne 1
    y1 = col_top
    last_section = False
    for is_section, surf in col1_wrapped:
        if is_section:
            y1 += 0
        if y1 + surf.get_height() > panel_y + panel_height - padding:
            break
        screen.blit(surf, (col1_x, y1))
        y1 += surf.get_height() + (section_spacing if is_section else line_spacing)

    # Dessin colonne 2
    y2 = col_top
    for is_section, surf in col2_wrapped:
        if y2 + surf.get_height() > panel_y + panel_height - padding:
            break
        screen.blit(surf, (col2_x, y2))
        y2 += surf.get_height() + (section_spacing if is_section else line_spacing)

    if enable_clip and prev_clip is not None:
        screen.set_clip(prev_clip)


# Menu Quitter Appli
def draw_confirm_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour quitter."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))
        logger.debug("OVERLAY recréé dans draw_confirm_dialog")

    screen.blit(OVERLAY, (0, 0))
    message = _("confirm_exit")
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

    button_width = min(160, (rect_width - 60) // 2)
    draw_stylized_button(screen, _("button_yes"), rect_x + rect_width // 2 - button_width - 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=config.confirm_selection == 1)
    draw_stylized_button(screen, _("button_no"), rect_x + rect_width // 2 + 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=config.confirm_selection == 0)

# draw_redownload_game_cache_dialog
def draw_redownload_game_cache_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour retélécharger le cache des jeux."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))
        logger.debug("OVERLAY recréé dans draw_redownload_game_cache_dialog")

    screen.blit(OVERLAY, (0, 0))
    message = _("confirm_redownload_cache")
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

    # Calcule une largeur de bouton cohérente avec la boîte et centre les deux boutons
    button_width = min(160, (rect_width - 60) // 2)
    yes_x = rect_x + rect_width // 2 - button_width - 10
    no_x = rect_x + rect_width // 2 + 10
    buttons_y = rect_y + text_height + margin_top_bottom
    draw_stylized_button(screen, _("button_yes"), yes_x, buttons_y, button_width, button_height, selected=config.redownload_confirm_selection == 1)
    draw_stylized_button(screen, _("button_no"), no_x, buttons_y, button_width, button_height, selected=config.redownload_confirm_selection == 0)

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
    countdown_text = _("popup_countdown").format(remaining_time, 's' if remaining_time != 1 else '')
    countdown_surface = config.small_font.render(countdown_text, True, THEME_COLORS["text"])
    countdown_rect = countdown_surface.get_rect(center=(config.screen_width // 2, popup_y + margin_top_bottom + len(text_lines) * line_height + line_height // 2))
    screen.blit(countdown_surface, countdown_rect)


 

import pygame  # type: ignore
import os
import io
import platform
import random
import config
from utils import (truncate_text_middle, wrap_text, load_system_image, truncate_text_end,
                   check_web_service_status, check_custom_dns_status, load_api_keys,
                   _get_dest_folder_name, find_file_with_or_without_extension)
import logging
import math
from history import load_history, is_game_downloaded  
from language import _, get_size_units, get_speed_unit, get_available_languages, get_language_name
from rgsx_settings import (load_rgsx_settings, get_light_mode, get_show_unsupported_platforms,
                            get_allow_unknown_extensions, get_display_monitor, get_display_fullscreen,
                            get_available_monitors, get_font_family, get_sources_mode,
                            get_hide_premium_systems, get_symlink_option)
from game_filters import GameFilters  

logger = logging.getLogger(__name__)

OVERLAY = None  # Initialisé dans init_display()

# --- Helpers: SVG icons for controls (local cache, optional cairosvg) ---
_HELP_ICON_CACHE = {}

def _images_base_dir():
    try:
        base_dir = os.path.join(os.path.dirname(__file__), "assets", "images")
    except Exception:
        base_dir = "assets/images"
    return base_dir

def _action_icon_filename(action_name: str):
    mapping = {
        "up": "dpad_up.svg",
        "down": "dpad_down.svg",
        "left": "dpad_left.svg",
        "right": "dpad_right.svg",
        "confirm": "buttons_south.svg",
        "cancel": "buttons_east.svg",
        "clear_history": "buttons_west.svg",
        "history": "buttons_north.svg",
        "start": "button_start.svg",
        "filter": "button_select.svg",
        "delete": "button_l.svg",
        "space": "button_r.svg",
        "page_up": "button_lt.svg",
        "page_down": "button_rt.svg",
    }
    return mapping.get(action_name)

def _load_svg_icon_surface(svg_path: str, size: int):
    try:
        # Prefer cairosvg if available for crisp rasterization
        try:
            import cairosvg  # type: ignore
        except Exception:
            cairosvg = None  # type: ignore
        if cairosvg is not None:
            with open(svg_path, "rb") as f:
                svg_bytes = f.read()
            png_bytes = cairosvg.svg2png(bytestring=svg_bytes, output_width=size, output_height=size)
            return pygame.image.load(io.BytesIO(png_bytes), "icon.png").convert_alpha()
        # Fallback: try direct load (works if SDL_image has SVG support)
        surf = pygame.image.load(svg_path)
        w, h = surf.get_size()
        if w != size or h != size:
            scale = min(size / max(w, 1), size / max(h, 1))
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            surf = pygame.transform.smoothscale(surf, (new_w, new_h))
        return surf.convert_alpha()
    except Exception as e:
        try:
            logger.debug(f"Help icon load failed for {svg_path}: {e}")
        except Exception:
            pass
        return None

def get_help_icon_surface(action_name: str, size: int):
    key = (action_name, size)
    if key in _HELP_ICON_CACHE:
        return _HELP_ICON_CACHE[key]
    filename = _action_icon_filename(action_name)
    if not filename:
        _HELP_ICON_CACHE[key] = None
        return None
    full_path = os.path.join(_images_base_dir(), filename)
    if not os.path.exists(full_path):
        _HELP_ICON_CACHE[key] = None
        return None
    surf = _load_svg_icon_surface(full_path, size)
    _HELP_ICON_CACHE[key] = surf
    return surf

def _render_icons_line(actions, text, target_col_width, font, text_color, icon_size=28, icon_gap=8, icon_text_gap=12):
    """Compose une ligne avec une rangée d'icônes (actions) et un texte à droite.
    Renvoie un pygame.Surface prêt à être blité, limité à target_col_width.
    Si aucun joystick n'est détecté, affiche les touches clavier entre [ ] au lieu des icônes.
    """
    # Si aucun joystick détecté, afficher les touches clavier entre crochets au lieu des icônes
    if not getattr(config, 'joystick', True):
        # Mode clavier : afficher [Touche] : Description
        action_labels = []
        for a in actions:
            label = get_control_display(a, a.upper())
            action_labels.append(f"[{label}]")
        
        # Combiner les labels avec le texte
        full_text = " ".join(action_labels) + " : " + text
        
        try:
            lines = wrap_text(full_text, font, target_col_width)
        except Exception:
            lines = [full_text]
        line_surfs = [font.render(l, True, text_color) for l in lines]
        width = max((s.get_width() for s in line_surfs), default=1)
        height = sum(s.get_height() for s in line_surfs) + max(0, (len(line_surfs) - 1)) * 4
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        y = 0
        for s in line_surfs:
            surf.blit(s, (0, y))
            y += s.get_height() + 4
        return surf
    
    # Mode joystick : afficher les icônes normalement
    # Charger icônes (ignorer celles manquantes)
    icon_surfs = []
    for a in actions:
        surf = get_help_icon_surface(a, icon_size)
        if surf is not None:
            icon_surfs.append(surf)
    # Si aucune icône, rendre simplement le texte (le layout appelant ajoutera les espacements)
    if not icon_surfs:
        try:
            lines = wrap_text(text, font, target_col_width)
        except Exception:
            lines = [text]
        line_surfs = [font.render(l, True, text_color) for l in lines]
        width = max((s.get_width() for s in line_surfs), default=1)
        height = sum(s.get_height() for s in line_surfs) + max(0, (len(line_surfs) - 1)) * 4
        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        y = 0
        for s in line_surfs:
            surf.blit(s, (0, y))
            y += s.get_height() + 4
        return surf

    # Calcul largeur totale des icônes
    icons_width = sum(s.get_width() for s in icon_surfs) + (len(icon_surfs) - 1) * icon_gap
    if icons_width + icon_text_gap > target_col_width:
        scale = (target_col_width - icon_text_gap) / max(1, icons_width)
        scale = max(0.6, min(1.0, scale))
        new_icon_surfs = []
        for s in icon_surfs:
            new_size = (max(1, int(s.get_width() * scale)), max(1, int(s.get_height() * scale)))
            new_icon_surfs.append(pygame.transform.smoothscale(s, new_size))
        icon_surfs = new_icon_surfs
        icons_width = sum(s.get_width() for s in icon_surfs) + (len(icon_surfs) - 1) * icon_gap

    text_area_width = max(60, target_col_width - icons_width - icon_text_gap)
    try:
        lines = wrap_text(text, font, text_area_width)
    except Exception:
        lines = [text]
    line_surfs = [font.render(l, True, text_color) for l in lines]
    text_block_width = max((s.get_width() for s in line_surfs), default=1)
    text_block_height = sum(s.get_height() for s in line_surfs) + max(0, (len(line_surfs) - 1)) * 4

    total_width = min(target_col_width, icons_width + icon_text_gap + text_block_width)
    total_height = max(max((s.get_height() for s in icon_surfs), default=0), text_block_height)
    surf = pygame.Surface((total_width, total_height), pygame.SRCALPHA)

    x = 0
    icon_y_center = total_height // 2
    for idx, s in enumerate(icon_surfs):
        r = s.get_rect()
        y = icon_y_center - r.height // 2
        surf.blit(s, (x, y))
        x += r.width + (icon_gap if idx < len(icon_surfs) - 1 else 0)

    text_x = x + icon_text_gap
    y = (total_height - text_block_height) // 2
    for ls in line_surfs:
        surf.blit(ls, (text_x, y))
        y += ls.get_height() + 4
    return surf

# Couleurs modernes pour le thème
THEME_COLORS = {
    # Fond des lignes sélectionnées
    "fond_lignes": (0, 255, 0),  # vert
    # Fond par défaut des images de grille des systèmes
    "fond_image": (50, 50, 70),  # Bleu sombre métal
    # Néon image grille des systèmes
    "neon": (0, 134, 179),  # bleu
    # Dégradé sombre pour le fond
    "background_top": (20, 25, 35),  
    "background_bottom": (45, 55, 75), # noir vers bleu foncé
    # Fond des cadres
    "button_idle": (45, 50, 65, 180),  # Bleu sombre métal avec plus d'opacité
    # Fond des boutons sélectionnés
    "button_selected": (70, 80, 110, 220),  # Bleu plus clair
    # Fond des boutons hover dans les popups ou menu
    "button_hover": (255, 0, 255, 240),  # Rose vif
    # Générique
    "text": (255, 255, 255),  # blanc
    # Texte sélectionné (alias pour compatibilité)
    "text_selected": (0, 255, 0),  # utilise le même vert que fond_lignes
    # Erreur
    "error_text": (255, 60, 60),  # rouge vif
    # Succès
    "success_text": (0, 255, 150),  # vert cyan
    # Avertissement
    "warning_text": (255, 150, 0),  # orange vif
    # Titres 
    "title_text": (220, 220, 230), # gris très clair
    # Bordures
    "border": (100, 120, 150),  # Bordures bleutées
    "border_selected": (0, 255, 150),  # Bordure verte cyan pour sélection
    # Couleurs pour filtres
    "green": (0, 255, 0),  # vert
    "red": (255, 0, 0),  # rouge
    # Nouvelles couleurs pour effets modernes
    "shadow": (0, 0, 0, 100),  # Ombre portée
    "glow": (100, 180, 255, 40),  # Effet glow bleu doux
    "highlight": (255, 255, 255, 20),  # Reflet subtil
    "accent_gradient_start": (80, 120, 200),  # Début dégradé accent
    "accent_gradient_end": (120, 80, 200),  # Fin dégradé accent
}

# Général, résolution, overlay
def init_display():
    """Initialise l'écran et les ressources globales.
    Supporte la sélection de moniteur en plein écran.
    Compatible Windows et Linux (Batocera).
    """
    global OVERLAY
    
    
    # Charger les paramètres d'affichage
    settings = load_rgsx_settings()
    logger.debug(f"Settings chargés: display={settings.get('display', {})}")
    target_monitor = settings.get("display", {}).get("monitor", 0)
    
    
    # Vérifier les variables d'environnement (priorité sur les settings)
    env_display = os.environ.get("RGSX_DISPLAY")
    if env_display is not None:
        try:
            target_monitor = int(env_display)
            logger.debug(f"Override par RGSX_DISPLAY: monitor={target_monitor}")
        except ValueError:
            pass
    
    
    # Configurer SDL pour utiliser le bon moniteur
    # Cette variable d'environnement doit être définie AVANT la création de la fenêtre
    os.environ["SDL_VIDEO_FULLSCREEN_HEAD"] = str(target_monitor)
    
    # Obtenir les informations d'affichage
    num_displays = 1
    try:
        num_displays = pygame.display.get_num_displays()
    except Exception:
        pass
    
    # S'assurer que le moniteur cible existe
    if target_monitor >= num_displays:
        logger.warning(f"Monitor {target_monitor} not available, using monitor 0")
        target_monitor = 0
    
    # Obtenir la résolution du moniteur cible
    try:
        if hasattr(pygame.display, 'get_desktop_sizes') and num_displays > 1:
            desktop_sizes = pygame.display.get_desktop_sizes()
            if target_monitor < len(desktop_sizes):
                screen_width, screen_height = desktop_sizes[target_monitor]
            else:
                display_info = pygame.display.Info()
                screen_width = display_info.current_w
                screen_height = display_info.current_h
        else:
            display_info = pygame.display.Info()
            screen_width = display_info.current_w
            screen_height = display_info.current_h
    except Exception as e:
        logger.error(f"Error getting display info: {e}")
        display_info = pygame.display.Info()
        screen_width = display_info.current_w
        screen_height = display_info.current_h
    
    # Créer la fenêtre en plein écran
    flags = pygame.FULLSCREEN
    # Sur Linux/Batocera, utiliser SCALED pour respecter la résolution forcée d'EmulationStation
    if platform.system() == "Linux":
        flags |= pygame.SCALED
    # Sur certains systèmes Windows, NOFRAME aide pour le multi-écran
    elif platform.system() == "Windows":
        flags |= pygame.NOFRAME
    
    try:
        screen = pygame.display.set_mode((screen_width, screen_height), flags, display=target_monitor)
    except TypeError:
        # Anciennes versions de pygame ne supportent pas le paramètre display=
        screen = pygame.display.set_mode((screen_width, screen_height), flags)
    except Exception as e:
        logger.error(f"Error creating display on monitor {target_monitor}: {e}")
        screen = pygame.display.set_mode((screen_width, screen_height), flags)
    
    config.screen_width = screen_width
    config.screen_height = screen_height
    config.current_monitor = target_monitor
    
    # Initialisation de OVERLAY avec effet glassmorphism
    OVERLAY = pygame.Surface((screen_width, screen_height), pygame.SRCALPHA)
    OVERLAY.fill((5, 10, 20, 160))  # Bleu très foncé semi-transparent pour effet verre
    logger.debug(f"Écran initialisé: {screen_width}x{screen_height} sur moniteur {target_monitor}")
    return screen

# Fond d'écran dégradé
def draw_gradient(screen, top_color, bottom_color, light_mode=None):
    """Dessine un fond dégradé vertical avec des couleurs vibrantes et texture de grain.
    En mode light, utilise une couleur unie pour de meilleures performances."""
    if light_mode is None:
        light_mode = get_light_mode()
    
    height = screen.get_height()
    width = screen.get_width()
    
    if light_mode:
        # Mode light: couleur unie (moyenne des deux couleurs)
        avg_color = (
            (top_color[0] + bottom_color[0]) // 2,
            (top_color[1] + bottom_color[1]) // 2,
            (top_color[2] + bottom_color[2]) // 2
        )
        screen.fill(avg_color)
        return
    
    top_color = pygame.Color(*top_color)
    bottom_color = pygame.Color(*bottom_color)
    
    # Dégradé principal
    for y in range(height):
        ratio = y / height
        color = top_color.lerp(bottom_color, ratio)
        pygame.draw.line(screen, color, (0, y), (width, y))
    
    # Ajouter une texture de grain subtile pour plus de profondeur
    grain_surface = pygame.Surface((width, height), pygame.SRCALPHA)
    random.seed(42)  # Seed fixe pour cohérence
    for _ in range(width * height // 200):  # Réduire la densité pour performance
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        alpha = random.randint(5, 20)
        grain_surface.set_at((x, y), (255, 255, 255, alpha))
    screen.blit(grain_surface, (0, 0))


def draw_shadow(surface, rect, offset=6, alpha=120, light_mode=None):
    """Dessine une ombre portée pour un rectangle. Désactivé en mode light."""
    if light_mode is None:
        light_mode = get_light_mode()
    if light_mode:
        return None  # Pas d'ombre en mode light
    shadow = pygame.Surface((rect.width + offset, rect.height + offset), pygame.SRCALPHA)
    pygame.draw.rect(shadow, (0, 0, 0, alpha), (0, 0, rect.width + offset, rect.height + offset), border_radius=15)
    return shadow


def draw_glow_effect(screen, rect, color, intensity=80, size=10, light_mode=None):
    """Dessine un effet de glow autour d'un rectangle. Désactivé en mode light."""
    if light_mode is None:
        light_mode = get_light_mode()
    if light_mode:
        return  # Pas de glow en mode light
    glow = pygame.Surface((rect.width + size * 2, rect.height + size * 2), pygame.SRCALPHA)
    for i in range(size):
        alpha = int(intensity * (1 - i / size))
        pygame.draw.rect(glow, (*color[:3], alpha), 
                        (i, i, rect.width + (size - i) * 2, rect.height + (size - i) * 2), 
                        border_radius=15)
    screen.blit(glow, (rect.x - size, rect.y - size))

# Nouvelle fonction pour dessiner un bouton stylisé
def draw_stylized_button(screen, text, x, y, width, height, selected=False, light_mode=None):
    """Dessine un bouton moderne avec effet de survol, ombre et bordure arrondie.
    En mode light, utilise un style simplifié pour de meilleures performances."""
    if light_mode is None:
        light_mode = get_light_mode()
    
    button_color = THEME_COLORS["button_hover"] if selected else THEME_COLORS["button_idle"]
    
    if light_mode:
        # Mode light: bouton simple sans effets
        pygame.draw.rect(screen, button_color[:3], (x, y, width, height), border_radius=8)
        if selected:
            # Bordure simple pour indiquer la sélection
            pygame.draw.rect(screen, THEME_COLORS["neon"], (x, y, width, height), width=2, border_radius=8)
    else:
        # Mode normal avec tous les effets
        # Ombre portée subtile
        shadow_surf = pygame.Surface((width + 6, height + 6), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surf, THEME_COLORS["shadow"], (3, 3, width, height), border_radius=12)
        screen.blit(shadow_surf, (x - 3, y - 3))
        
        button_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        
        # Fond avec dégradé subtil pour bouton sélectionné
        if selected:
            # Créer le dégradé
            for i in range(height):
                ratio = i / height
                brightness = 1 + 0.2 * ratio
                r = min(255, int(button_color[0] * brightness))
                g = min(255, int(button_color[1] * brightness))
                b = min(255, int(button_color[2] * brightness))
                alpha = button_color[3] if len(button_color) > 3 else 255
                rect = pygame.Rect(0, i, width, 1)
                pygame.draw.rect(button_surface, (r, g, b, alpha), rect)
            
            # Appliquer les coins arrondis avec un masque
            mask_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            pygame.draw.rect(mask_surface, (255, 255, 255, 255), (0, 0, width, height), border_radius=12)
            button_surface.blit(mask_surface, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        else:
            pygame.draw.rect(button_surface, button_color, (0, 0, width, height), border_radius=12)
        
        # Reflet en haut
        highlight = pygame.Surface((width - 4, height // 3), pygame.SRCALPHA)
        highlight.fill(THEME_COLORS["highlight"])
        button_surface.blit(highlight, (2, 2))
        
        # Bordure
        pygame.draw.rect(button_surface, THEME_COLORS["border"], (0, 0, width, height), 2, border_radius=12)
        
        if selected:
            # Effet glow doux pour sélection
            glow_surface = pygame.Surface((width + 16, height + 16), pygame.SRCALPHA)
            for i in range(6):
                alpha = int(40 * (1 - i / 6))
                pygame.draw.rect(glow_surface, (*THEME_COLORS["glow"][:3], alpha), 
                               (i, i, width + 16 - i*2, height + 16 - i*2), border_radius=15)
            screen.blit(glow_surface, (x - 8, y - 8))
        
        screen.blit(button_surface, (x, y))
    
    # Vérifier si le texte dépasse la largeur disponible
    text_surface = config.font.render(text, True, THEME_COLORS["text"])
    available_width = width - 20  # Marge de 10px de chaque côté
    
    if text_surface.get_width() > available_width:
        # Tronquer le texte avec "..."
        truncated_text = text
        while text_surface.get_width() > available_width and len(truncated_text) > 0:
            truncated_text = truncated_text[:-1]
            text_surface = config.font.render(truncated_text + "...", True, THEME_COLORS["text"])
    
    text_rect = text_surface.get_rect(center=(x + width // 2, y + height // 2))
    screen.blit(text_surface, text_rect)

# Transition d'image lors de la sélection d'un système
def draw_validation_transition(screen, platform_index):
    """Affiche une animation de transition fluide pour la sélection d’une plateforme.
    Utilise le mapping par nom pour éviter les décalages d'image si l'ordre d'affichage
    diffère de l'ordre de stockage."""
    # Récupérer le nom affiché correspondant à l'index trié
    if platform_index < 0 or platform_index >= len(config.platforms):
        return
    platform_name = config.platforms[platform_index]
    platform_dict = getattr(config, 'platform_dict_by_name', {}).get(platform_name)
    if not platform_dict:
        # Fallback index direct si mapping absent
        try:
            platform_dict = config.platform_dicts[platform_index]
        except Exception:
            return
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
    
    # Si un libellé personnalisé est défini dans controls.json, on le privilégie
    custom_label = control_config.get('display')
    if isinstance(custom_label, str) and custom_label.strip():
        return custom_label
    
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
        # Étendre le mapping pour couvrir plus de manettes (incl. Trimui)
        button_names = {
            0: "A", 1: "B", 2: "X", 3: "Y",
            4: "LB", 5: "RB",
            6: "Select", 7: "Start",
            8: "Select", 9: "Start",
            10: "L3", 11: "R3",
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
    
    # Vérifier si le mode performance est activé
    from rgsx_settings import get_light_mode
    light_mode = get_light_mode()
    
    if not config.platforms or config.selected_platform >= len(config.platforms):
        platform_name = _("platform_no_platform")
        logger.warning("Aucune plateforme ou selected_platform hors limites")
    else:
        platform = config.platforms[config.selected_platform]
        platform_name = config.platform_names.get(platform, platform)
    
    # Affichage du titre avec animation subtile
    # Afficher le nombre total de jeux disponibles (tous systèmes) pour cohérence avec l'écran jeux
    # Nombre de jeux pour la plateforme sélectionnée (utilise le cache pre-calculé si disponible)
    game_count = 0
    try:
        if hasattr(config, 'games_count') and isinstance(config.games_count, dict):
            game_count = config.games_count.get(platform_name, 0)
        # Fallback dynamique si pas dans le cache (ex: plateformes modifiées à chaud)
        if game_count == 0 and hasattr(config, 'platform_dict_by_name'):
            from utils import load_games  # import local pour éviter import circulaire global
            game_count = len(load_games(platform_name))
    except Exception:
        game_count = 0
    title_text = f"{platform_name}  ({game_count})" if game_count > 0 else f"{platform_name}"
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
    title_rect_inflated = title_rect.inflate(60, 30)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)

    # Effet de pulsation subtil pour le titre - calculé une seule fois par frame
    current_time = pygame.time.get_ticks()
    
    if not light_mode:
        # Mode normal : effets visuels complets
        pulse_factor = 0.08 * (1 + math.sin(current_time / 400))
        
        # Ombre portée pour le titre
        shadow_surf = pygame.Surface((title_rect_inflated.width + 12, title_rect_inflated.height + 12), pygame.SRCALPHA)
        pygame.draw.rect(shadow_surf, (0, 0, 0, 140), (6, 6, title_rect_inflated.width, title_rect_inflated.height), border_radius=16)
        screen.blit(shadow_surf, (title_rect_inflated.left - 6, title_rect_inflated.top - 6))
        
        # Glow multicouche pour le titre
        for i in range(2):
            glow_size = title_rect_inflated.inflate(15 + i * 8, 15 + i * 8)
            title_glow = pygame.Surface((glow_size.width, glow_size.height), pygame.SRCALPHA)
            alpha = int((30 + 20 * pulse_factor) * (1 - i / 2))
            pygame.draw.rect(title_glow, (*THEME_COLORS["neon"][:3], alpha), 
                            title_glow.get_rect(), border_radius=16 + i * 2)
            screen.blit(title_glow, (title_rect_inflated.left - 8 - i * 4, title_rect_inflated.top - 8 - i * 4))
        
        # Fond du titre avec dégradé
        title_bg = pygame.Surface((title_rect_inflated.width, title_rect_inflated.height), pygame.SRCALPHA)
        for i in range(title_rect_inflated.height):
            ratio = i / title_rect_inflated.height
            alpha = int(THEME_COLORS["button_idle"][3] * (1 + ratio * 0.1))
            pygame.draw.line(title_bg, (*THEME_COLORS["button_idle"][:3], alpha), 
                            (0, i), (title_rect_inflated.width, i))
        screen.blit(title_bg, title_rect_inflated.topleft)
        
        # Reflet en haut du titre
        highlight = pygame.Surface((title_rect_inflated.width - 8, title_rect_inflated.height // 3), pygame.SRCALPHA)
        highlight.fill((255, 255, 255, 25))
        screen.blit(highlight, (title_rect_inflated.left + 4, title_rect_inflated.top + 4))
        
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=14)
    else:
        # Mode performance : rendu simplifié
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=14)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=14)
    
    screen.blit(title_surface, title_rect)

    # Configuration de la grille - calculée une seule fois
    margin_left = int(config.screen_width * 0.026)
    margin_right = int(config.screen_width * 0.026)
    margin_top = int(config.screen_height * 0.140)
    margin_bottom = int(config.screen_height * 0.0648)
    num_cols = getattr(config, 'GRID_COLS', 3)
    num_rows = getattr(config, 'GRID_ROWS', 4)
    systems_per_page = num_cols * num_rows

    available_width = config.screen_width - margin_left - margin_right
    available_height = config.screen_height - margin_top - margin_bottom

    # Calculer la taille des cellules en tenant compte de l'espace nécessaire pour le glow
    # Réduire la taille effective pour laisser de l'espace entre les éléments
    col_width = available_width // num_cols
    row_height = available_height // num_rows
    
    # Calculer la taille du container basée sur la cellule la plus petite
    # avec marges pour éviter les chevauchements (20% de marge)
    cell_size = min(col_width, row_height)
    container_size = int(cell_size * 0.70)  # 70% de la cellule pour laisser de l'espace
    
    # Espacement entre les cellules pour éviter les chevauchements
    cell_padding = int(cell_size * 0.15)  # 15% d'espacement

    x_positions = [margin_left + col_width * i + col_width // 2 for i in range(num_cols)]
    y_positions = [margin_top + row_height * i + row_height // 2 for i in range(num_rows)]

    # Filtrage éventuel des systèmes premium selon réglage
    try:
        from rgsx_settings import get_hide_premium_systems
        hide_premium = get_hide_premium_systems()
    except Exception:
        hide_premium = False
    premium_markers = getattr(config, 'PREMIUM_HOST_MARKERS', [])
    if hide_premium and premium_markers:
        visible_platforms = [p for p in config.platforms if not any(m.lower() in p.lower() for m in premium_markers)]
    else:
        visible_platforms = list(config.platforms)

    # Ajuster selected_platform et current_platform/page si liste réduite
    if config.selected_platform >= len(visible_platforms):
        config.selected_platform = max(0, len(visible_platforms) - 1)
    # Recalcule la page courante en fonction de selected_platform
    systems_per_page = num_cols * num_rows
    if systems_per_page <= 0:
        systems_per_page = 1
    config.current_page = config.selected_platform // systems_per_page if systems_per_page else 0

    total_pages = (len(visible_platforms) + systems_per_page - 1) // systems_per_page
    if total_pages > 1:
        page_indicator_text = _("platform_page").format(config.current_page + 1, total_pages)
        page_indicator = config.small_font.render(page_indicator_text, True, THEME_COLORS["text"])
        # Position en haut à gauche
        page_x = 10
        page_y = 10
        screen.blit(page_indicator, (page_x, page_y))

    # Calculer une seule fois la pulsation pour les éléments sélectionnés (réduite)
    if not light_mode:
        pulse = 0.05 * math.sin(current_time / 300)  # Réduit de 0.1 à 0.05
        glow_intensity = 40 + int(30 * math.sin(current_time / 300))
    else:
        pulse = 0
        glow_intensity = 0
    
    # Pré-calcul des images pour optimiser le rendu
    start_idx = config.current_page * systems_per_page
    for idx in range(start_idx, start_idx + systems_per_page):
        if idx >= len(visible_platforms):
            break
        grid_idx = idx - start_idx
        row = grid_idx // num_cols
        col = grid_idx % num_cols
        x = x_positions[col]
        y = y_positions[row]
        
        # Animation fluide pour l'item sélectionné (réduite pour éviter chevauchement)
        is_selected = idx == config.selected_platform
        if light_mode:
            # Mode performance : pas d'animation, taille fixe
            scale_base = 1.0
            scale = 1.0
        else:
            # Mode normal : animation réduite
            scale_base = 1.15 if is_selected else 1.0  # Réduit de 1.5 à 1.15
            scale = scale_base + pulse if is_selected else scale_base
            
        # Récupération robuste du dict via nom
        display_name = visible_platforms[idx]
        platform_dict = getattr(config, 'platform_dict_by_name', {}).get(display_name)
        if not platform_dict:
            # Fallback index brut
            # Chercher en parcourant platform_dicts pour correspondance nom
            for pd in config.platform_dicts:
                n = pd.get("platform_name") or pd.get("platform")
                if n == display_name:
                    platform_dict = pd
                    break
            else:
                continue
        platform_id = platform_dict.get("platform_name") or platform_dict.get("platform") or display_name
        
        # Utiliser le cache d'images pour éviter de recharger/redimensionner à chaque frame
        cache_key = f"{platform_id}_{scale:.2f}_{container_size}"
        if cache_key not in platform_images_cache:
            image = load_system_image(platform_dict)
            if image:
                orig_width, orig_height = image.get_width(), image.get_height()
                
                # Taille normalisée basée sur container_size calculé en fonction de la grille
                # Le scale affecte uniquement l'item sélectionné
                # Adapter la largeur en fonction du nombre de colonnes pour occuper ~25-30% de l'écran
                if num_cols == 3:
                    # En 3 colonnes, augmenter significativement la largeur (15% de l'écran par carte)
                    actual_container_width = int(config.screen_width * 0.15 * scale)
                elif num_cols == 4:
                    # En 4 colonnes, largeur plus modérée (10% de l'écran par carte)
                    actual_container_width = int(config.screen_width * 0.15 * scale)
                else:
                    # Par défaut, utiliser container_size * 1.3
                    actual_container_width = int(container_size * scale * 1.3)
                
                actual_container_height = int(container_size * scale)  # Hauteur normale
                
                # Calculer le ratio pour fit dans le container en gardant l'aspect ratio
                ratio = min(actual_container_width / orig_width, actual_container_height / orig_height)
                new_width = int(orig_width * ratio)
                new_height = int(orig_height * ratio)
                
                scaled_image = pygame.transform.smoothscale(image, (new_width, new_height))
                platform_images_cache[cache_key] = {
                    "image": scaled_image,
                    "width": new_width,
                    "height": new_height,
                    "container_width": actual_container_width,
                    "container_height": actual_container_height,
                    "last_used": current_time
                }
            else:
                continue
        
        # Récupérer les données du cache (que ce soit nouveau ou existant)
        if cache_key in platform_images_cache:
            platform_images_cache[cache_key]["last_used"] = current_time
            scaled_image = platform_images_cache[cache_key]["image"]
            new_width = platform_images_cache[cache_key]["width"]
            new_height = platform_images_cache[cache_key]["height"]
            container_width = platform_images_cache[cache_key]["container_width"]
            container_height = platform_images_cache[cache_key]["container_height"]
        else:
            continue
        
        image_rect = scaled_image.get_rect(center=(x, y))


        # Effet visuel moderne similaire au titre pour toutes les images
        border_radius = 12
        padding = 12
        
        # Utiliser la taille du container normalisé au lieu de la taille variable de l'image
        rect_width = container_width + 2 * padding
        rect_height = container_height + 2 * padding
        
        # Centrer le conteneur sur la position (x, y)
        container_left = x - rect_width // 2
        container_top = y - rect_height // 2
        
        if not light_mode:
            # Mode normal : effets visuels complets
            # Ombre portée
            shadow_surf = pygame.Surface((rect_width + 12, rect_height + 12), pygame.SRCALPHA)
            pygame.draw.rect(shadow_surf, (0, 0, 0, 160), (6, 6, rect_width, rect_height), border_radius=border_radius + 4)
            screen.blit(shadow_surf, (container_left - 6, container_top - 6))
            
            # Effet de glow multicouche pour l'item sélectionné
            if is_selected:
                neon_color = THEME_COLORS["neon"]
                
                # Glow multicouche (2 couches pour effet profondeur)
                for i in range(2):
                    glow_size = (rect_width + 15 + i * 8, rect_height + 15 + i * 8)
                    glow_surf = pygame.Surface(glow_size, pygame.SRCALPHA)
                    alpha = int((glow_intensity + 40) * (1 - i / 2))
                    pygame.draw.rect(glow_surf, neon_color + (alpha,), glow_surf.get_rect(), border_radius=border_radius + i * 2)
                    screen.blit(glow_surf, (container_left - 8 - i * 4, container_top - 8 - i * 4))
            
            # Fond avec dégradé vertical (similaire au titre)
            bg_surface = pygame.Surface((rect_width, rect_height), pygame.SRCALPHA)
            base_color = THEME_COLORS["button_idle"] if is_selected else THEME_COLORS["fond_image"]
            
            for i in range(rect_height):
                ratio = i / rect_height
                # Dégradé du haut (plus clair) vers le bas (plus foncé)
                alpha = int(base_color[3] * (1 + ratio * 0.15)) if len(base_color) > 3 else int(200 * (1 + ratio * 0.15))
                color = (*base_color[:3], min(255, alpha))
                pygame.draw.line(bg_surface, color, (0, i), (rect_width, i))
            
            screen.blit(bg_surface, (container_left, container_top))
            
            # Reflet en haut (highlight pour effet glossy)
            highlight_height = rect_height // 3
            highlight = pygame.Surface((rect_width - 8, highlight_height), pygame.SRCALPHA)
            highlight.fill((255, 255, 255, 35 if is_selected else 20))
            screen.blit(highlight, (container_left + 4, container_top + 4))
        else:
            # Mode performance : fond simple sans effets
            bg_color = THEME_COLORS["button_idle"] if is_selected else THEME_COLORS["fond_image"]
            pygame.draw.rect(screen, bg_color, (container_left, container_top, rect_width, rect_height), border_radius=border_radius)
        
        # Bordure
        if light_mode and is_selected:
            # Mode performance : bordure épaisse et très visible pour l'item sélectionné
            border_color = THEME_COLORS["neon"]  # Couleur verte bien visible
            border_width = 4  # Bordure plus épaisse
        elif not light_mode and is_selected:
            # Mode normal : bordure neon
            border_color = THEME_COLORS["neon"]
            border_width = 2
        else:
            # Non sélectionné : bordure standard
            border_color = THEME_COLORS["border"]
            border_width = 2
        
        border_rect = pygame.Rect(container_left, container_top, rect_width, rect_height)
        pygame.draw.rect(screen, border_color, border_rect, border_width, border_radius=border_radius)

        # Centrer l'image dans le container (l'image peut être plus petite que le container)
        centered_image_rect = scaled_image.get_rect(center=(x, y))
        
        # Affichage de l'image
        if light_mode:
            # Mode performance : pas d'effet de transparence
            screen.blit(scaled_image, centered_image_rect)
        else:
            # Mode normal : effet de transparence pour les items non sélectionnés
            if not is_selected:
                temp_image = scaled_image.copy()
                temp_image.set_alpha(220)
                screen.blit(temp_image, centered_image_rect)
            else:
                screen.blit(scaled_image, centered_image_rect)
    
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
    #logger.debug(f"[DRAW_GAME_LIST] Called - platform={config.current_platform}, search_mode={config.search_mode}, filter_active={config.filter_active}")
    platform = config.platforms[config.current_platform]
    platform_name = config.platform_names.get(platform, platform)
    games = config.filtered_games if config.filter_active or config.search_mode else config.games
    game_count = len(games)
    #logger.debug(f"[DRAW_GAME_LIST] Games count={game_count}, current_game={config.current_game}, filtered_games={len(config.filtered_games) if config.filtered_games else 0}, config.games={len(config.games) if config.games else 0}")

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
    header_height = line_height  # hauteur de l'en-tête identique à une ligne
    margin_top_bottom = 20
    extra_margin_top = 20
    extra_margin_bottom = 60
    title_height = config.title_font.get_height() + 20

    # Réserver de l'espace pour l'en-tête (header_height)
    available_height = config.screen_height - title_height - extra_margin_top - extra_margin_bottom - 2 * margin_top_bottom - header_height
    items_per_page = max(1, available_height // line_height)

    rect_height = header_height + items_per_page * line_height + 2 * margin_top_bottom
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
        
        # Ombre pour le titre de recherche
        shadow = pygame.Surface((title_rect_inflated.width + 10, title_rect_inflated.height + 10), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 120), (5, 5, title_rect_inflated.width, title_rect_inflated.height), border_radius=14)
        screen.blit(shadow, (title_rect_inflated.left - 5, title_rect_inflated.top - 5))
        
        # Glow pour recherche active
        glow = pygame.Surface((title_rect_inflated.width + 20, title_rect_inflated.height + 20), pygame.SRCALPHA)
        pygame.draw.rect(glow, (*THEME_COLORS["glow"][:3], 60), glow.get_rect(), border_radius=16)
        screen.blit(glow, (title_rect_inflated.left - 10, title_rect_inflated.top - 10))
        
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)
    elif config.filter_active:
        # Afficher le nom de la plateforme avec indicateur de filtre actif
        filter_indicator = " (Active Filter)"
        if config.search_query:
            # Si recherche par nom active, afficher aussi la recherche
            filter_indicator = f" - {_('game_filter').format(config.search_query)}"
        
        title_text = _("game_count").format(platform_name, game_count) + filter_indicator
        title_surface = config.title_font.render(title_text, True, THEME_COLORS["green"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border_selected"], title_rect_inflated, 3, border_radius=12)
        screen.blit(title_surface, title_rect)
    else:
        # Ajouter indicateur de filtre actif si filtres avancés sont actifs
        filter_indicator = ""
        if hasattr(config, 'game_filter_obj') and config.game_filter_obj and config.game_filter_obj.is_active():
            filter_indicator = " (Active Filter)"
        
        title_text = _("game_count").format(platform_name, game_count) + filter_indicator
        title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
        title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 20))
        title_rect_inflated = title_rect.inflate(60, 30)
        title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
        
        # Ombre et glow pour titre normal
        shadow = pygame.Surface((title_rect_inflated.width + 10, title_rect_inflated.height + 10), pygame.SRCALPHA)
        pygame.draw.rect(shadow, (0, 0, 0, 120), (5, 5, title_rect_inflated.width, title_rect_inflated.height), border_radius=14)
        screen.blit(shadow, (title_rect_inflated.left - 5, title_rect_inflated.top - 5))
        
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
        screen.blit(title_surface, title_rect)

    # Ombre portée pour le cadre principal
    shadow_rect = pygame.Rect(rect_x + 6, rect_y + 6, rect_width, rect_height)
    shadow_surf = pygame.Surface((rect_width + 8, rect_height + 8), pygame.SRCALPHA)
    pygame.draw.rect(shadow_surf, (0, 0, 0, 100), (4, 4, rect_width, rect_height), border_radius=14)
    screen.blit(shadow_surf, (rect_x - 4, rect_y - 4))
    
    # Fond du cadre avec légère transparence glassmorphism
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    
    # Reflet en haut du cadre
    highlight = pygame.Surface((rect_width - 8, 40), pygame.SRCALPHA)
    highlight.fill((255, 255, 255, 15))
    screen.blit(highlight, (rect_x + 4, rect_y + 4))
    
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    # Largeur colonne taille (15%) mini 120px, reste pour nom
    size_col_width = max(120, int(rect_width * 0.15))
    name_col_width = rect_width - 40 - size_col_width  # padding horizontal 40

    # ---- En-tête ----
    header_name = _("game_header_name")
    header_size = _("game_header_size")
    header_y_center = rect_y + margin_top_bottom + header_height // 2
    # Nom aligné gauche
    header_name_surface = config.small_font.render(header_name, True, THEME_COLORS["text"])
    header_name_rect = header_name_surface.get_rect()
    header_name_rect.midleft = (rect_x + 20, header_y_center)
    # Taille alignée droite
    header_size_surface = config.small_font.render(header_size, True, THEME_COLORS["text"])
    header_size_rect = header_size_surface.get_rect()
    header_size_rect.midright = (rect_x + rect_width - 20, header_y_center)
    screen.blit(header_name_surface, header_name_rect)
    screen.blit(header_size_surface, header_size_rect)
    # Ligne de séparation sous l'en-tête
    separator_y = rect_y + margin_top_bottom + header_height
    pygame.draw.line(screen, THEME_COLORS["border"], (rect_x + 20, separator_y), (rect_x + rect_width - 20, separator_y), 2)

    # Position de départ des lignes après l'en-tête
    list_start_y = rect_y + margin_top_bottom + header_height

    for i in range(config.scroll_offset, min(config.scroll_offset + items_per_page, len(games))):
        item = games[i]
        if isinstance(item, (list, tuple)) and item:
            game_name = item[0]
            size_val = item[2] if len(item) > 2 else None
        else:
            game_name = str(item)
            size_val = None
        
        # Vérifier si le jeu est déjà téléchargé
        is_downloaded = is_game_downloaded(platform_name, game_name)
        
        size_text = size_val if (isinstance(size_val, str) and size_val.strip()) else "N/A"
        color = THEME_COLORS["fond_lignes"] if i == config.current_game else THEME_COLORS["text"]
        
        # Ajouter un marqueur vert si le jeu est déjà téléchargé
        prefix = "[>] " if is_downloaded else ""
        truncated_name = truncate_text_middle(prefix + game_name, config.small_font, name_col_width, is_filename=False)
        
        # Utiliser une couleur verte pour les jeux téléchargés
        name_color = (100, 255, 100) if is_downloaded else color  # Vert clair si téléchargé
        name_surface = config.small_font.render(truncated_name, True, name_color)
        size_surface = config.small_font.render(size_text, True, THEME_COLORS["text"])
        row_center_y = list_start_y + (i - config.scroll_offset) * line_height + line_height // 2
        # Position nom (aligné à gauche dans la boite)
        name_rect = name_surface.get_rect()
        name_rect.midleft = (rect_x + 20, row_center_y)
        size_rect = size_surface.get_rect()
        size_rect.midright = (rect_x + rect_width - 20, row_center_y)
        if i == config.current_game:
            glow_width = rect_width - 40
            glow_height = name_rect.height + 12
            
            # Effet de glow plus doux pour la sélection
            glow_surface = pygame.Surface((glow_width + 6, glow_height + 6), pygame.SRCALPHA)
            alpha = 50
            pygame.draw.rect(glow_surface, (*THEME_COLORS["fond_lignes"][:3], alpha), 
                           (3, 3, glow_width, glow_height), 
                           border_radius=8)
            screen.blit(glow_surface, (rect_x + 17, row_center_y - glow_height // 2 - 3))
            
            # Fond principal de la sélection avec dégradé subtil
            selection_bg = pygame.Surface((glow_width, glow_height), pygame.SRCALPHA)
            for j in range(glow_height):
                ratio = j / glow_height
                alpha = int(60 + 20 * ratio)
                pygame.draw.line(selection_bg, (*THEME_COLORS["fond_lignes"][:3], alpha), 
                               (0, j), (glow_width, j))
            screen.blit(selection_bg, (rect_x + 20, row_center_y - glow_height // 2))
            
            # Bordure lumineuse plus subtile
            border_rect = pygame.Rect(rect_x + 20, row_center_y - glow_height // 2, glow_width, glow_height)
            pygame.draw.rect(screen, (*THEME_COLORS["fond_lignes"][:3], 120), border_rect, width=1, border_radius=8)
        
        screen.blit(name_surface, name_rect)
        screen.blit(size_surface, size_rect)

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
    """Convertit une taille en octets en format lisible avec unités adaptées à la langue."""
    if not isinstance(size, (int, float)) or size == 0:
        return "N/A"
    
    units = get_size_units()
    for unit in units[:-1]:  # Tous sauf le dernier (Po/PB)
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} {units[-1]}"  # Dernier niveau (Po/PB)


def draw_history_list(screen):
    # logger.debug(f"Dessin historique, history={config.history}, needs_redraw={config.needs_redraw}")
    history = config.history if hasattr(config, 'history') else load_history()
    history_count = len(history)
    
    # Inverser l'historique pour afficher les plus récents en premier
    # Convertir l'index sélectionné de l'original au tableau inversé
    original_index = config.current_history_item
    history = list(reversed(history))
    
    # Calcul de l'index dans la liste inversée
    # Si original_index=0 (premier), devient len-1 (dernier dans la liste inversée)
    # Si original_index=len-1 (dernier), devient 0 (premier dans la liste inversée)
    if history_count > 0 and original_index >= 0 and original_index < history_count:
        current_history_item_inverted = history_count - 1 - original_index
    else:
        current_history_item_inverted = 0

    # Cherche une entrée en cours de téléchargement pour afficher la vitesse
    speed_str = ""
    for entry in history:
        if entry.get("status") in ["Téléchargement", "Downloading"]:
            speed = entry.get("speed", 0.0)
            if speed and speed > 0:
                speed_str = f" - {speed:.2f} {get_speed_unit()}"
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

    # Define column widths as percentages of available space (give more space to status/error messages)
    column_width_percentages = {
        "platform": 0.15,   # narrower platform column
        "game_name": 0.45,  # game name column
        "size": 0.10,       # size column remains compact
        "status": 0.30      # wider status column for long error codes/messages
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

    # Sécuriser current_history_item_inverted pour éviter IndexError
    if history:
        if current_history_item_inverted < 0 or current_history_item_inverted >= len(history):
            current_history_item_inverted = max(0, min(len(history) - 1, current_history_item_inverted))
    else:
        current_history_item_inverted = 0

    speed = 0.0
    if history and history[current_history_item_inverted].get("status") in ["Téléchargement", "Downloading"]:
        speed = history[current_history_item_inverted].get("speed", 0.0)
    if speed > 0:
        speed_str = f"{speed:.2f} {get_speed_unit()}"
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

    # Espace visible garanti entre le titre et la liste, et au-dessus du footer
    top_gap = 20
    bottom_reserved = 70  # réserve pour le footer (barre des contrôles) + marge visuelle (réduit)

    # Positionner la liste juste après le titre, avec un espace dédié
    # Utiliser le rectangle du titre déjà dessiné pour une meilleure précision
    title_bottom = title_rect_inflated.bottom
    rect_y = title_bottom + top_gap

    # Calculer l'espace disponible en bas en réservant une zone pour le footer
    available_height = max(0, config.screen_height - rect_y - bottom_reserved)
    # Déterminer le nombre d'éléments par page en tenant compte de l'en-tête et des marges internes
    items_per_page = max(1, (available_height - header_height - 2 * margin_top_bottom) // line_height)

    rect_height = header_height + items_per_page * line_height + 2 * margin_top_bottom
    rect_x = (config.screen_width - rect_width) // 2

    config.history_scroll_offset = max(0, min(config.history_scroll_offset, max(0, len(history) - items_per_page)))
    if current_history_item_inverted < config.history_scroll_offset:
        config.history_scroll_offset = current_history_item_inverted
    elif current_history_item_inverted >= config.history_scroll_offset + items_per_page:
        config.history_scroll_offset = current_history_item_inverted - items_per_page + 1


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
        color = THEME_COLORS["fond_lignes"] if i == current_history_item_inverted else THEME_COLORS["text"]
        size_text = format_size(size)
        
        status = entry.get("status", "Inconnu")
        progress = entry.get("progress", 0)
        progress = max(0, min(100, progress))  # Clamp progress between 0 and 100

        # Precompute provider prefix once
        provider_prefix = entry.get("provider_prefix") or (entry.get("provider") + ":" if entry.get("provider") else "")
        
        # Compute status text (optimized version without redundant prefix for errors)
        if status in ["Téléchargement", "Downloading"]:
            # Vérifier si un message personnalisé existe (ex: mode gratuit avec attente)
            custom_message = entry.get('message', '')
            # Détecter les messages du mode gratuit (commencent par '[' dans toutes les langues)
            if custom_message and custom_message.strip().startswith('['):
                # Utiliser le message personnalisé pour le mode gratuit
                status_text = custom_message
            else:
                # Comportement normal: afficher le pourcentage
                status_text = _("history_status_downloading").format(progress)
                # Coerce to string and prefix provider when relevant
                status_text = str(status_text or "")
                if provider_prefix and not status_text.startswith(provider_prefix):
                    status_text = f"{provider_prefix} {status_text}"
        elif status == "Extracting":
            status_text = _("history_status_extracting").format(progress)
            status_text = str(status_text or "")
            if provider_prefix and not status_text.startswith(provider_prefix):
                status_text = f"{provider_prefix} {status_text}"
        elif status == "Download_OK":
            # Completed: no provider prefix (per requirement)
            status_text = _("history_status_completed")
            status_text = str(status_text or "")
        elif status == "Erreur":
            # Prefer friendly mapped message now stored in 'message'
            status_text = entry.get('message')
            if not status_text:
                # Some legacy entries might have only raw in result[1] or auxiliary field
                status_text = entry.get('raw_error_realdebrid') or entry.get('error') or 'Échec'
            # Coerce to string early for safe operations
            status_text = str(status_text or "")
            # Strip redundant prefixes if any
            for prefix in ["Erreur :", "Erreur:", "Error:", "Error :"]:
                if status_text.startswith(prefix):
                    status_text = status_text[len(prefix):].strip()
                    break
            if provider_prefix and not status_text.startswith(provider_prefix):
                status_text = f"{provider_prefix} {status_text}"
        elif status == "Canceled":
            status_text = _("history_status_canceled")
            status_text = str(status_text or "")
        else:
            status_text = str(status or "")

        # Determine color dedicated to status (independent from selection for better readability)
        if status == "Erreur" or status == "Error":
            status_color = THEME_COLORS.get("error_text", (255, 0, 0))
        elif status == "Canceled":
            status_color = THEME_COLORS.get("warning_text", (255, 100, 0))
        elif status == "Download_OK" or status == "Completed":
            # Use green OK color
            status_color = THEME_COLORS.get("success_text", (0, 255, 0))
        elif status in ("Downloading", "Téléchargement", "downloading", "Extracting", "Converting", "Queued", "Connecting"):
            # En cours - couleur bleue/cyan pour différencier des autres
            status_color = THEME_COLORS.get("text_selected", (100, 180, 255))
        else:
            status_color = THEME_COLORS.get("text", (255, 255, 255))

        platform_text = truncate_text_end(platform, config.small_font, col_platform_width - 10)
        game_text = truncate_text_end(game_name, config.small_font, col_game_width - 10)
        size_text = truncate_text_end(size_text, config.small_font, col_size_width - 10)
        status_text = truncate_text_middle(str(status_text or ""), config.small_font, col_status_width - 10, is_filename=False)

        y_pos = rect_y + margin_top_bottom + header_height + idx * line_height + line_height // 2
        platform_surface = config.small_font.render(platform_text, True, color)
        game_surface = config.small_font.render(game_text, True, color)
        size_surface = config.small_font.render(size_text, True, color)  # Correction ici
        status_surface = config.small_font.render(status_text, True, status_color)

        platform_rect = platform_surface.get_rect(center=(header_x_positions[0], y_pos))
        game_rect = game_surface.get_rect(center=(header_x_positions[1], y_pos))
        size_rect = size_surface.get_rect(center=(header_x_positions[2], y_pos))
        status_rect = status_surface.get_rect(center=(header_x_positions[3], y_pos))

        if i == current_history_item_inverted:
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

# Écran avertissement extension non supportée téléchargement
def draw_extension_warning(screen):
    """Affiche un avertissement pour une extension non reconnue ou un fichier ZIP."""
    if not config.pending_download:
        logger.error("config.pending_download est None ou vide dans extension_warning, retour anticipé")
        return
    
    url, platform, game_name, is_zip_non_supported = config.pending_download
    # Log réduit: pas de détail verbeux ici
    is_zip = is_zip_non_supported
    if not game_name:
        game_name = "Inconnu"
        logger.warning("game_name vide, utilisation de 'Inconnu'")

    if is_zip:
        core = _("extension_warning_zip").format(game_name)
        hint = ""
    else:
        # Ajout d'un indice pour activer le téléchargement des extensions inconnues
        try:
            hint = _("extension_warning_enable_unknown_hint")
        except Exception:
            hint = ""
        core = _("extension_warning_unsupported").format(game_name)

    # Nettoyer et préparer les lignes
    max_width = config.screen_width - 80
    core_lines = wrap_text(core, config.font, max_width)
    hint_text = (hint or "").replace("\n", " ").strip()
    hint_lines = wrap_text(hint_text, config.small_font, max_width) if hint_text else []

    try:
        line_height_core = config.font.get_height() + 5
        line_height_hint = config.small_font.get_height() + 4
        spacing_between = 6 if hint_lines else 0
        text_height = len(core_lines) * line_height_core + (spacing_between) + len(hint_lines) * line_height_hint
        button_height = int(config.screen_height * 0.0463)
        margin_top_bottom = 20
        rect_height = text_height + button_height + 2 * margin_top_bottom
        max_text_width = max(
            [config.font.size(l)[0] for l in core_lines] + ([config.small_font.size(l)[0] for l in hint_lines] if hint_lines else []),
            default=300,
        )
        rect_width = max_text_width + 80
        rect_x = (config.screen_width - rect_width) // 2
        rect_y = (config.screen_height - rect_height) // 2

        screen.blit(OVERLAY, (0, 0))
        pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
        pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

        # Lignes du cœur du message (orange)
        for i, line in enumerate(core_lines):
            text_surface = config.font.render(line, True, THEME_COLORS["warning_text"])
            text_rect = text_surface.get_rect(center=(
                config.screen_width // 2,
                rect_y + margin_top_bottom + i * line_height_core + line_height_core // 2,
            ))
            screen.blit(text_surface, text_rect)

        # Lignes d'indice (blanc/gris) si présentes
        if hint_lines:
            hint_start_y = rect_y + margin_top_bottom + len(core_lines) * line_height_core + spacing_between
            for j, hline in enumerate(hint_lines):
                hsurf = config.small_font.render(hline, True, THEME_COLORS["text"])
                hrect = hsurf.get_rect(center=(
                    config.screen_width // 2,
                    hint_start_y + j * line_height_hint + line_height_hint // 2,
                ))
                screen.blit(hsurf, hrect)

        draw_stylized_button(screen, _("button_yes"), rect_x + rect_width // 2 - 180, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.extension_confirm_selection == 0)
        draw_stylized_button(screen, _("button_no"), rect_x + rect_width // 2 + 20, rect_y + text_height + margin_top_bottom, 160, button_height, selected=config.extension_confirm_selection == 1)

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
    """Affiche les contrôles contextuels en bas de l'écran selon le menu_state."""
    
    # Mapping des contrôles par menu_state
    controls_map = {
        "platform": [
            ("history", _("controls_action_history")),
            ("confirm", _("controls_confirm_select")),
            ("start", _("controls_action_start")),
        ],
        "game": [
            ("confirm", _("controls_confirm_select")),
            ("clear_history", _("controls_action_queue")),
            (("page_up", "page_down"), _("controls_pages")),
            ("filter", _("controls_filter_search")),
            ("history", _("controls_action_history")),
        ],
        "history": [
            ("confirm", _("history_game_options_title")),
            ("clear_history", _("controls_action_clear_history")),
            ("history", _("controls_action_close_history")),
            ("cancel", _("controls_cancel_back")),
        ],
        "scraper": [
            ("confirm", _("controls_confirm_select")),
            ("cancel", _("controls_cancel_back")),
        ],
        "error": [
            ("confirm", _("controls_confirm_select")),
        ],
        "confirm_exit": [
            ("confirm", _("controls_confirm_select")),
            ("cancel", _("controls_cancel_back")),
        ],
        "extension_warning": [
            ("confirm", _("controls_confirm_select")),
        ],
        "folder_browser": [
            ("confirm", _("folder_browser_enter")),
            ("history", _("folder_browser_select")),
            ("clear_history", _("folder_new_folder")),
            ("cancel", _("controls_cancel_back")),
        ],
        "folder_browser_new_folder": [
            ("confirm", _("controls_action_select_char")),
            ("delete", _("controls_action_delete")),
            ("space", _("controls_action_space")),
            ("history", _("folder_new_confirm")),
            ("cancel", _("controls_cancel_back")),
        ],
        "platform_folder_config": [
            ("confirm", _("controls_confirm_select")),
            ("cancel", _("controls_cancel_back")),
        ],
        "pause_settings_roms_folder": [
            ("confirm", _("folder_browser_browse")),
            ("clear_history", _("settings_roms_folder_default")),
            ("cancel", _("controls_cancel_back")),
        ],
    }
    
    # Cas spécial : pause_settings_menu avec option roms_folder sélectionnée
    if menu_state == "pause_settings_menu":
        roms_folder_index = 3  # Index de l'option Dossier ROMs
        if getattr(config, 'pause_settings_selection', 0) == roms_folder_index:
            menu_state = "pause_settings_roms_folder"
    
    # Récupérer les contrôles pour ce menu, sinon affichage par défaut
    controls_list = controls_map.get(menu_state, [
        ("confirm", _("controls_confirm_select")),
        ("cancel", _("controls_cancel_back")),
    ])
    
    # Construire les lignes avec icônes
    icon_lines = []
    
    # Sur la page d'accueil et la page loading afficher version et musique
    if menu_state == "platform" or menu_state == "loading":
        control_parts = []
        
        start_button = get_control_display('start', 'START')
        # Si aucun joystick, afficher la touche entre crochets
        if not getattr(config, 'joystick', True):
            start_button = f"[{start_button}]"
        start_text = _("controls_action_start")
        control_parts.append(f"RGSX v{config.app_version} - {start_button} : {start_text}")
        
        # Afficher le nom du joystick s'il est détecté
        try:
            device_name = getattr(config, 'controller_device_name', '') or ''
            if device_name:
                try:
                    joy_label = _("footer_joystick")
                except Exception:
                    joy_label = "Joystick: {0}"
                if isinstance(joy_label, str) and "{0}" in joy_label:
                    joy_text = joy_label.format(device_name)
                else:
                    joy_text = f"{joy_label} {device_name}" if joy_label else f"Joystick: {device_name}"
                control_parts.append(f"| {joy_text}")
        except Exception:
            pass
        
        # Ajouter le nom de la musique si disponible
        if config.current_music_name and config.music_popup_start_time > 0:
            current_time = pygame.time.get_ticks() / 1000
            if current_time - config.music_popup_start_time < 3.0:
                control_parts.append(f"| {config.current_music_name}")
        
        control_text = " ".join(control_parts)
        icon_lines.append(control_text)
    else:
        # Pour les autres menus: affichage avec icônes et contrôles contextuels sur une seule ligne
        all_controls = []
        for action, label in controls_list:
            # Gérer les cas où action peut être une tuple (ex: ("page_up", "page_down"))
            if isinstance(action, tuple):
                # Afficher plusieurs touches avec icônes
                all_controls.append(("icons", list(action), label))
            else:
                # Une seule touche avec icône
                all_controls.append(("icons", [action], label))
        
        # Combiner tous les contrôles sur une seule ligne avec séparateurs
        icon_lines.append(("icons_combined", all_controls))
    
    # Rendu des lignes avec icônes
    max_width = config.screen_width - 40
    icon_surfs = []
    
    # Calculer la taille des icônes en fonction du footer_font_scale
    footer_scale = config.accessibility_settings.get("footer_font_scale", 1.0)
    base_icon_size = 20
    scaled_icon_size = int(base_icon_size * footer_scale)
    base_icon_gap = 6
    scaled_icon_gap = int(base_icon_gap * footer_scale)
    base_icon_text_gap = 10
    scaled_icon_text_gap = int(base_icon_text_gap * footer_scale)
    
    for line_data in icon_lines:
        if isinstance(line_data, tuple) and len(line_data) >= 2:
            if line_data[0] == "icons_combined":
                # Combiner tous les contrôles sur une seule ligne
                all_controls = line_data[1]
                combined_surf = pygame.Surface((max_width, 50), pygame.SRCALPHA)
                x_pos = 10
                for action_tuple in all_controls:
                    ignored, actions, label = action_tuple
                    try:
                        surf = _render_icons_line(actions, label, max_width - x_pos - 10, config.tiny_font, THEME_COLORS["text"], icon_size=scaled_icon_size, icon_gap=scaled_icon_gap, icon_text_gap=scaled_icon_text_gap)
                        if x_pos + surf.get_width() > max_width - 10:
                            break  # Pas assez de place
                        combined_surf.blit(surf, (x_pos, (50 - surf.get_height()) // 2))
                        x_pos += surf.get_width() + 20  # Espacement entre contrôles
                    except Exception:
                        pass
                # Redimensionner la surface au contenu réel
                if x_pos > 10:
                    final_surf = pygame.Surface((x_pos - 10, 50), pygame.SRCALPHA)
                    final_surf.blit(combined_surf, (0, 0), (0, 0, x_pos - 10, 50))
                    icon_surfs.append(final_surf)
            elif line_data[0] == "icons" and len(line_data) == 3:
                ignored, actions, label = line_data
                try:
                    surf = _render_icons_line(actions, label, max_width, config.tiny_font, THEME_COLORS["text"], icon_size=scaled_icon_size, icon_gap=scaled_icon_gap, icon_text_gap=scaled_icon_text_gap)
                    icon_surfs.append(surf)
                except Exception:
                    text_surface = config.tiny_font.render(f"{label}", True, THEME_COLORS["text"])
                    icon_surfs.append(text_surface)
        else:
            # Texte simple (pour la ligne platform)
            text_surface = config.tiny_font.render(line_data, True, THEME_COLORS["text"])
            icon_surfs.append(text_surface)
    
    # Calculer hauteur totale
    total_height = sum(s.get_height() for s in icon_surfs) + max(0, (len(icon_surfs) - 1)) * 4 + 8
    rect_height = total_height
    rect_y = config.screen_height - rect_height - 5
    rect_x = (config.screen_width - max_width) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, max_width, rect_height), border_radius=8)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, max_width, rect_height), 1, border_radius=8)

    # Afficher les lignes
    y = rect_y + 4
    for surf in icon_surfs:
        x_centered = rect_x + (max_width - surf.get_width()) // 2
        screen.blit(surf, (x_centered, y))
        y += surf.get_height() + 4


# Menu pause
def draw_language_menu(screen):
    """Dessine le menu de sélection de langue avec un style moderne.

    Améliorations:
    - Hauteur des boutons réduite et responsive selon la taille d'écran.
    - Bloc (titre + liste de langues) centré verticalement.
    - Gestion d'overflow: réduit légèrement la hauteur/espacement si nécessaire.
    """
    
    screen.blit(OVERLAY, (0, 0))
    
    # Obtenir les langues disponibles
    available_languages = get_available_languages()
    
    if not available_languages:
        logger.error("Aucune langue disponible")
        return
    
    # Instruction en haut - calculer d'abord pour connaître l'espace disponible
    instruction_text = _("language_select_instruction")
    instruction_height = get_top_instruction_height(instruction_text)
    footer_height = 70
    
    # Espace disponible pour le contenu (entre instruction et footer)
    available_h = config.screen_height - instruction_height - footer_height - 20
    
    # Titre (mesuré d'abord pour connaître la hauteur réelle du fond)
    title_text = _("language_select_title")
    title_surface = config.font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect()
    # Padding responsive plus léger
    hpad = max(20, min(30, int(config.screen_width * 0.03)))
    vpad = max(6, min(10, int(title_surface.get_height() * 0.3)))
    title_bg_rect = title_rect.inflate(hpad, vpad)

    # Calculer hauteur dynamique basée sur la taille de police
    sample_text = config.font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    
    # Calculer largeur maximale nécessaire pour les noms de langues
    max_text_width = 0
    for lang_code in available_languages:
        lang_name = get_language_name(lang_code)
        text_surface = config.font.render(lang_name, True, THEME_COLORS["text"])
        if text_surface.get_width() > max_text_width:
            max_text_width = text_surface.get_width()
    
    # Largeur bornée entre valeur calculée et limites raisonnables
    button_width = max(200, min(400, max_text_width + 40))
    
    # Nombre de langues
    n = len(available_languages)
    
    # Calculer la hauteur de bouton idéale en fonction de l'espace disponible
    # Espace pour les boutons = available_h - titre - espacement titre
    title_total_height = title_bg_rect.height + 8  # titre + petit espace
    space_for_buttons = available_h - title_total_height
    
    # Calculer hauteur et espacement optimaux
    # On veut : n * button_height + (n-1) * spacing <= space_for_buttons
    # Avec spacing = 0.2 * button_height environ
    # Donc : n * h + (n-1) * 0.2 * h = h * (n + 0.2*(n-1)) <= space_for_buttons
    # h <= space_for_buttons / (n + 0.2*(n-1))
    
    max_button_height = space_for_buttons / (n + 0.15 * max(0, n - 1))
    
    # Borner la hauteur des boutons
    button_height = int(min(50, max(24, min(max_button_height, font_height + 12))))
    button_spacing = max(4, min(8, int(button_height * 0.15)))
    
    # Recalculer la hauteur totale
    total_buttons_height = n * button_height + (n - 1) * button_spacing
    content_height = title_bg_rect.height + 8 + total_buttons_height
    
    # Réduction supplémentaire si nécessaire
    safety_counter = 0
    while content_height > available_h and safety_counter < 30:
        if button_height > 24:
            button_height -= 1
        elif button_spacing > 2:
            button_spacing -= 1
        else:
            break
        total_buttons_height = n * button_height + (n - 1) * button_spacing
        content_height = title_bg_rect.height + 8 + total_buttons_height
        safety_counter += 1
    
    # Positionner le bloc au centre verticalement
    content_top = instruction_height + max(5, (available_h - content_height) // 2)
    
    # Positionner le titre
    title_bg_rect.centerx = config.screen_width // 2
    title_bg_rect.y = content_top
    title_rect.center = (title_bg_rect.centerx, title_bg_rect.y + title_bg_rect.height // 2)

    # Dessiner le titre
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_bg_rect, border_radius=8)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_bg_rect, 2, border_radius=8)
    screen.blit(title_surface, title_rect)

    # Démarrer la liste juste sous le titre
    start_y = title_bg_rect.bottom + 8
    
    for i, lang_code in enumerate(available_languages):
        # Obtenir le nom de la langue
        lang_name = get_language_name(lang_code)

        # Position du bouton
        button_x = (config.screen_width - button_width) // 2
        button_y = start_y + i * (button_height + button_spacing)

        # Dessiner le bouton
        button_color = THEME_COLORS["button_hover"] if i == config.selected_language_index else THEME_COLORS["button_idle"]
        pygame.draw.rect(screen, button_color, (button_x, button_y, button_width, button_height), border_radius=8)
        pygame.draw.rect(screen, THEME_COLORS["border"], (button_x, button_y, button_width, button_height), 2, border_radius=8)

        # Texte avec gestion du dépassement
        text_surface = config.font.render(lang_name, True, THEME_COLORS["text"])
        available_width = button_width - 16  # Marge de 8px de chaque côté
        
        if text_surface.get_width() > available_width:
            # Tronquer le texte avec "..."
            truncated_text = lang_name
            while text_surface.get_width() > available_width and len(truncated_text) > 0:
                truncated_text = truncated_text[:-1]
                text_surface = config.font.render(truncated_text + "...", True, THEME_COLORS["text"])
        
        text_rect = text_surface.get_rect(center=(button_x + button_width // 2, button_y + button_height // 2))
        screen.blit(text_surface, text_rect)
    
    # Dessiner l'instruction en haut
    draw_menu_instruction(screen, instruction_text)

def get_top_instruction_height(instruction_text):
    """Calcule la hauteur totale occupée par l'instruction en haut (cadre + marge).
    
    Retourne 0 si pas d'instruction.
    """
    if not instruction_text:
        return 0
    try:
        margin_top = 3
        margin_bottom = 6  # Espace entre l'instruction et le menu
        padding_y = 4
        text_surface = config.small_font.render(instruction_text, True, THEME_COLORS["text"])
        frame_height = text_surface.get_height() + (padding_y * 2)
        return margin_top + frame_height + margin_bottom
    except Exception:
        return 0

def draw_top_instruction(screen, instruction_text):
    """Dessine une instruction en haut de l'écran dans un cadre élégant sur une ligne.
    
    - Largeur maximale de l'écran avec marges
    - Centré horizontalement
    - Fond semi-transparent avec bordure
    
    Retourne la hauteur totale occupée (pour le positionnement des menus).
    """
    if not instruction_text:
        return 0
    try:
        # Marges réduites pour coller au haut
        margin_x = 20
        margin_top = 3
        margin_bottom = 6  # Espace entre l'instruction et le menu
        padding_x = 15
        padding_y = 4
        
        # Rendre le texte
        text_surface = config.small_font.render(instruction_text, True, THEME_COLORS["text"])
        
        # Calculer les dimensions du cadre
        max_width = config.screen_width - (margin_x * 2)
        frame_width = min(text_surface.get_width() + (padding_x * 2), max_width)
        frame_height = text_surface.get_height() + (padding_y * 2)
        
        # Position du cadre (centré en haut)
        frame_x = (config.screen_width - frame_width) // 2
        frame_y = margin_top
        
        # Créer surface avec transparence pour le fond
        frame_surface = pygame.Surface((frame_width, frame_height), pygame.SRCALPHA)
        
        # Dessiner le fond semi-transparent avec coins arrondis
        pygame.draw.rect(frame_surface, THEME_COLORS["button_idle"], 
                        (0, 0, frame_width, frame_height), border_radius=10)
        
        # Dessiner la bordure
        pygame.draw.rect(frame_surface, THEME_COLORS["border"], 
                        (0, 0, frame_width, frame_height), 2, border_radius=10)
        
        # Blitter le cadre sur l'écran
        screen.blit(frame_surface, (frame_x, frame_y))
        
        # Calculer la position du texte (centré dans le cadre)
        text_x = frame_x + (frame_width - text_surface.get_width()) // 2
        text_y = frame_y + padding_y
        
        # Dessiner le texte
        screen.blit(text_surface, (text_x, text_y))
        
        return margin_top + frame_height + margin_bottom
        
    except Exception as e:
        logger.error(f"Erreur draw_top_instruction: {e}")
        return 0

def draw_menu_instruction(screen, instruction_text, last_button_bottom=None):
    """Dessine une ligne d'instruction centrée en haut de l'écran dans un cadre.

    Utilise draw_top_instruction pour un affichage cohérent.
    Le paramètre last_button_bottom est conservé pour compatibilité mais n'est plus utilisé.
    Retourne la hauteur totale occupée.
    """
    return draw_top_instruction(screen, instruction_text)

def draw_display_menu(screen):
    """Affiche le sous-menu Affichage (layout, taille de police, systèmes non supportés, moniteur)."""
    screen.blit(OVERLAY, (0, 0))

    # États actuels
    layout_str = f"{getattr(config, 'GRID_COLS', 3)}x{getattr(config, 'GRID_ROWS', 4)}"
    font_scale = config.accessibility_settings.get("font_scale", 1.0)
    show_unsupported = get_show_unsupported_platforms()
    allow_unknown = get_allow_unknown_extensions()
    
    # Monitor info
    current_monitor = get_display_monitor()
    is_fullscreen = get_display_fullscreen()
    monitors = get_available_monitors()
    num_monitors = len(monitors)
    
    # Construire le label du moniteur
    if num_monitors > 1:
        monitor_info = monitors[current_monitor] if current_monitor < num_monitors else monitors[0]
        monitor_label = f"{_('display_monitor')}: {monitor_info['name']} ({monitor_info['resolution']})"
    else:
        monitor_label = f"{_('display_monitor')}: {_('display_monitor_single')}"
    
    # Label mode écran
    fullscreen_label = f"{_('display_mode')}: {_('display_fullscreen') if is_fullscreen else _('display_windowed')}"

    # Compter les systèmes non supportés actuellement masqués
    unsupported_list = getattr(config, "unsupported_platforms", []) or []
    try:
        hidden_count = 0 if show_unsupported else len(list(unsupported_list))
    except Exception:
        hidden_count = 0
    if hidden_count > 0:
        unsupported_label = _("menu_show_unsupported_and_hidden").format(hidden_count)
    else:
        unsupported_label = _("menu_show_unsupported_all_displayed")

    # Libellés - ajout des options moniteur et mode écran
    options = [
        f"{_('display_layout')}: {layout_str}",
        _("accessibility_font_size").format(f"{font_scale:.1f}"),
        monitor_label,
        fullscreen_label,
        unsupported_label,
        _("menu_allow_unknown_ext_on") if allow_unknown else _("menu_allow_unknown_ext_off"),
        _("menu_filter_platforms"),
    ]

    selected = getattr(config, 'display_menu_selection', 0)
    
    # Instruction à afficher en haut
    instruction_text = _("language_select_instruction")
    instruction_height = get_top_instruction_height(instruction_text)

    # Dimensions du cadre (cohérent avec le menu pause)
    title_text = _("menu_display")
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_height = title_surface.get_height() + 10
    menu_width = int(config.screen_width * 0.7)
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 20
    vertical_spacing = 10
    footer_height = 70
    menu_height = title_height + len(options) * (button_height + vertical_spacing) + 2 * margin_top_bottom
    menu_x = (config.screen_width - menu_width) // 2
    
    # Calculer menu_y en tenant compte de l'instruction et du footer
    available_height = config.screen_height - instruction_height - footer_height
    menu_y = instruction_height + (available_height - menu_height) // 2

    # Cadre
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (menu_x, menu_y, menu_width, menu_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (menu_x, menu_y, menu_width, menu_height), 2, border_radius=12)

    # Titre centré dans le cadre
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, menu_y + margin_top_bottom + title_surface.get_height() // 2))
    screen.blit(title_surface, title_rect)

    # Boutons des options
    for i, option_text in enumerate(options):
        y = menu_y + margin_top_bottom + title_height + i * (button_height + vertical_spacing)
        draw_stylized_button(
            screen,
            option_text,
            menu_x + 20,
            y,
            menu_width - 40,
            button_height,
            selected=(i == selected)
        )

    # Dessiner l'instruction en haut
    draw_menu_instruction(screen, instruction_text)

def draw_pause_menu(screen, selected_option):
    """Dessine le menu pause racine (catégories)."""
    screen.blit(OVERLAY, (0, 0))
    # Nouvel ordre: Games / Language / Controls / Display / Settings / Support / Quit
    options = [
        _("menu_games") if _ else "Games",                  # 0 -> sous-menu games (history + sources + update)
        _("menu_language") if _ else "Language",            # 1 -> sélecteur de langue direct
        _("menu_controls"),                                 # 2 -> sous-menu controls
        _("menu_display"),                                  # 3 -> sous-menu display
        _("menu_settings_category") if _ else "Settings",   # 4 -> sous-menu settings
        _("menu_support"),                                  # 5 -> support
        _("menu_quit")                                      # 6 -> sous-menu quit (quit + restart)
    ]
    
    # Instruction contextuelle pour l'option sélectionnée
    instruction_keys = [
        "instruction_pause_games",
        "instruction_pause_language",
        "instruction_pause_controls",
        "instruction_pause_display",
        "instruction_pause_settings",
        "instruction_pause_support",
        "instruction_pause_quit",
    ]
    try:
        key = instruction_keys[selected_option]
        instruction_text = _(key)
    except Exception:
        instruction_text = ""
    
    # Calculer la hauteur de l'instruction AVANT de dessiner le menu
    instruction_height = get_top_instruction_height(instruction_text) if instruction_text else 0
    
    # Calculer hauteur dynamique basée sur la taille de police
    sample_text = config.font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    button_height = max(int(config.screen_height * 0.048), font_height + 20)
    
    # Calculer largeur maximale nécessaire pour le texte
    max_text_width = 0
    for option in options:
        text_surface = config.font.render(option, True, THEME_COLORS["text"])
        if text_surface.get_width() > max_text_width:
            max_text_width = text_surface.get_width()
    
    # Largeur du menu basée sur le texte le plus long + marges
    menu_width = min(int(config.screen_width * 0.8), max(int(config.screen_width * 0.5), max_text_width + 80))
    margin_top_bottom = 24
    menu_height = len(options) * (button_height + 12) + 2 * margin_top_bottom
    menu_x = (config.screen_width - menu_width) // 2
    
    # Calculer menu_y en tenant compte de l'instruction en haut
    # Zone disponible = écran - instruction_height - footer (70px)
    footer_height = 70
    available_height = config.screen_height - instruction_height - footer_height
    menu_y = instruction_height + (available_height - menu_height) // 2
    
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (menu_x, menu_y, menu_width, menu_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (menu_x, menu_y, menu_width, menu_height), 2, border_radius=12)
    for i, option in enumerate(options):
        draw_stylized_button(
            screen,
            option,
            menu_x + 20,
            menu_y + margin_top_bottom + i * (button_height + 12),
            menu_width - 40,
            button_height,
            selected=i == selected_option
        )
    config.pause_menu_total_options = len(options)

    # Dessiner l'instruction en haut
    if instruction_text:
        draw_menu_instruction(screen, instruction_text)

def _calc_submenu_dimensions(num_options, instruction_height=0):
    """Calcule les dimensions adaptatives pour un sous-menu.
    
    Args:
        num_options: Nombre d'options dans le menu
        instruction_height: Hauteur de l'instruction en haut (0 si pas d'instruction)
    """
    sample_text = config.font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    title_height = font_height + 10
    margin_top_bottom = 20
    footer_height = 70
    
    max_menu_height = int(config.screen_height * 0.85)
    available_height_for_buttons = max_menu_height - title_height - 2 * margin_top_bottom
    
    ideal_button_height = max(int(config.screen_height * 0.040), font_height + 12)
    ideal_spacing = 6
    total_ideal_height = num_options * ideal_button_height + (num_options - 1) * ideal_spacing
    
    if total_ideal_height <= available_height_for_buttons:
        button_height = ideal_button_height
        button_spacing = ideal_spacing
    else:
        min_spacing = 3
        min_button_height = font_height + 6
        available_for_buttons = available_height_for_buttons - (num_options - 1) * min_spacing
        button_height = max(min_button_height, available_for_buttons // num_options)
        button_spacing = min_spacing
        total_height = num_options * button_height + (num_options - 1) * button_spacing
        if total_height > available_height_for_buttons:
            button_height = min_button_height
            button_spacing = max(1, (available_height_for_buttons - num_options * button_height) // max(1, num_options - 1))
    
    menu_height = title_height + num_options * button_height + (num_options - 1) * button_spacing + 2 * margin_top_bottom
    
    # Calculer menu_y en tenant compte de l'instruction en haut et du footer
    available_height = config.screen_height - instruction_height - footer_height
    menu_y = instruction_height + (available_height - menu_height) // 2
    
    start_y = menu_y + margin_top_bottom + title_height
    last_button_bottom = start_y + (num_options - 1) * (button_height + button_spacing) + button_height
    
    return {
        'button_height': button_height,
        'button_spacing': button_spacing,
        'menu_height': menu_height,
        'menu_y': menu_y,
        'start_y': start_y,
        'last_button_bottom': last_button_bottom,
        'margin_top_bottom': margin_top_bottom
    }

def _draw_submenu_generic(screen, title, options, selected_index, instruction_text=None):
    """Helper générique pour dessiner un sous-menu hiérarchique.
    
    Args:
        screen: Surface pygame
        title: Titre du menu
        options: Liste des options
        selected_index: Index de l'option sélectionnée
        instruction_text: Texte d'instruction optionnel à afficher en haut
    """
    screen.blit(OVERLAY, (0, 0))
    
    # Calculer la hauteur de l'instruction si présente
    instruction_height = get_top_instruction_height(instruction_text) if instruction_text else 0
    
    # Calculer les dimensions adaptatives en tenant compte de l'instruction
    dims = _calc_submenu_dimensions(len(options), instruction_height)
    button_height = dims['button_height']
    button_spacing = dims['button_spacing']
    menu_height = dims['menu_height']
    menu_y = dims['menu_y']
    margin_top_bottom = dims['margin_top_bottom']
    
    # Calculer largeur maximale nécessaire pour le texte (titre + options)
    max_text_width = 0
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    max_text_width = title_surface.get_width()
    for option in options:
        text_surface = config.font.render(option, True, THEME_COLORS["text"])
        if text_surface.get_width() > max_text_width:
            max_text_width = text_surface.get_width()
    
    # Largeur du menu basée sur le texte le plus long + marges
    menu_width = min(int(config.screen_width * 0.85), max(int(config.screen_width * 0.55), max_text_width + 80))
    menu_x = (config.screen_width - menu_width) // 2
    
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (menu_x, menu_y, menu_width, menu_height), border_radius=14)
    pygame.draw.rect(screen, THEME_COLORS["border"], (menu_x, menu_y, menu_width, menu_height), 2, border_radius=14)
    # Title
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width//2, menu_y + margin_top_bottom//2 + title_surface.get_height()//2))
    screen.blit(title_surface, title_rect)
    # Options
    start_y = title_rect.bottom + 10
    for i, opt in enumerate(options):
        draw_stylized_button(
            screen,
            opt,
            menu_x + 20,
            start_y + i * (button_height + button_spacing),
            menu_width - 40,
            button_height,
            selected=(i == selected_index)
        )
    
    # Dessiner l'instruction en haut si présente
    if instruction_text:
        draw_menu_instruction(screen, instruction_text)

def draw_pause_controls_menu(screen, selected_index):
    options = [
        _("menu_controls"),        # aide contrôles (réutilisée)
        _("menu_remap_controls"),  # remap
        _("menu_back") if _ else "Back"
    ]
    # Instructions contextuelles
    instruction_keys = [
        "instruction_controls_help",   # pour menu_controls (afficher l'aide)
        "instruction_controls_remap",  # remap
        "instruction_generic_back",    # retour
    ]
    key = instruction_keys[selected_index] if 0 <= selected_index < len(instruction_keys) else None
    instruction_text = _(key) if key else None
    
    # Dessiner le menu avec l'instruction
    _draw_submenu_generic(screen, _("menu_controls") if _ else "Controls", options, selected_index, instruction_text)

def draw_pause_display_menu(screen, selected_index):
    # Layout label - now opens a submenu
    layout_txt = f"{_('submenu_display_layout') if _ else 'Layout'} >"
    # Font size
    opts = getattr(config, 'font_scale_options', [0.75, 1.0, 1.25, 1.5, 1.75])
    cur_idx = getattr(config, 'current_font_scale_index', 1)
    font_value = f"{opts[cur_idx]}x"
    font_txt = f"{_('submenu_display_font_size') if _ else 'Font Size'}: < {font_value} >"
    # Footer font size
    footer_opts = getattr(config, 'footer_font_scale_options', [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0])
    footer_cur_idx = getattr(config, 'current_footer_font_scale_index', 3)
    footer_font_value = f"{footer_opts[footer_cur_idx]}x"
    footer_font_txt = f"{_('accessibility_footer_font_size').split(':')[0] if _ else 'Footer Font Size'}: < {footer_font_value} >"
    # Font family
    current_family = get_font_family()
    # Nom user-friendly
    family_map = {
        "pixel": "Pixel",
        "dejavu": "DejaVu Sans"
    }
    fam_label = family_map.get(current_family, current_family)
    font_family_txt = f"{_('submenu_display_font_family') if _ else 'Font'}: < {fam_label} >"

    # Monitor selection - only show if multiple monitors
    current_monitor = get_display_monitor()
    monitors = get_available_monitors()
    num_monitors = len(monitors)
    show_monitor_option = num_monitors > 1
    
    if show_monitor_option:
        monitor_info = monitors[current_monitor] if current_monitor < num_monitors else monitors[0]
        monitor_value = f"{monitor_info['name']} ({monitor_info['resolution']})"
        monitor_txt = f"{_('display_monitor') if _ else 'Monitor'}: < {monitor_value} >"
    
    # Allow unknown extensions
    allow_unknown = get_allow_unknown_extensions()
    status_unknown = _('status_on') if allow_unknown else _('status_off')
    raw_unknown_label = _('submenu_display_allow_unknown_ext') if _ else 'Hide unknown ext warn: {status}'
    if '{status}' in raw_unknown_label:
        raw_unknown_label = raw_unknown_label.split('{status}')[0].rstrip(' :')
    unknown_txt = f"{raw_unknown_label}: < {status_unknown} >"

    # Light mode (performance)
    light_mode = get_light_mode()
    light_status = _('status_on') if light_mode else _('status_off')
    light_txt = f"{_('display_light_mode') if _ else 'Light mode'}: < {light_status} >"

    back_txt = _("menu_back") if _ else "Back"
    
    # Build options list - conditional monitor option
    # layout, font submenu, family, [monitor if multi], light, unknown, back
    font_submenu_txt = f"{_('submenu_display_font_size') if _ else 'Font Size'} >"
    options = [layout_txt, font_submenu_txt, font_family_txt]
    instruction_keys = [
        "instruction_display_layout",
        "instruction_display_font_size",
        "instruction_display_font_family",
    ]
    
    if show_monitor_option:
        options.append(monitor_txt)
        instruction_keys.append("instruction_display_monitor")
    
    options.extend([light_txt, unknown_txt, back_txt])
    instruction_keys.extend([
        "instruction_display_light_mode",
        "instruction_display_unknown_ext",
        "instruction_generic_back",
    ])
    
    key = instruction_keys[selected_index] if 0 <= selected_index < len(instruction_keys) else None
    instruction_text = _(key) if key else None
    
    _draw_submenu_generic(screen, _("menu_display"), options, selected_index, instruction_text)

def draw_pause_display_layout_menu(screen, selected_index):
    """Sous-menu pour la disposition avec visualisation schématique des grilles."""
    layouts = [(3,3),(3,4),(4,3),(4,4)]
    layout_labels = ["3x3", "3x4", "4x3", "4x4"]
    
    # Trouver le layout actuel
    try:
        current_idx = layouts.index((config.GRID_COLS, config.GRID_ROWS))
    except ValueError:
        current_idx = 0
    
    # Créer les options avec indicateur du layout actuel
    options = []
    for i, label in enumerate(layout_labels):
        if i == current_idx:
            options.append(f"{label} [CURRENT]" if not _ else f"{label} [{_('status_current') if _ else 'ACTUEL'}]")
        else:
            options.append(label)
    options.append(_("menu_back") if _ else "Back")
    
    # Déterminer l'instruction
    if selected_index < len(layouts):
        instruction = _("instruction_display_layout") if _ else "Left/Right: Navigate • Confirm: Select"
    else:
        instruction = _("instruction_generic_back") if _ else "Confirm: Go back"
    
    # Calculer la hauteur de l'instruction
    instruction_height = get_top_instruction_height(instruction)
    
    # Dessiner le menu de base
    title = _("submenu_display_layout") if _ else "Layout"
    
    # Calculer les dimensions
    button_height = int(config.screen_height * 0.045)
    menu_width = int(config.screen_width * 0.72)
    margin_top_bottom = 26
    footer_height = 70
    
    # Calculer la hauteur nécessaire pour les boutons
    menu_height = (len(options)+1) * (button_height + 10) + 2 * margin_top_bottom
    menu_x = (config.screen_width - menu_width) // 2
    
    # Calculer menu_y en tenant compte de l'instruction et du footer
    available_height = config.screen_height - instruction_height - footer_height
    menu_y = instruction_height + (available_height - menu_height) // 2
    
    # Fond du menu
    menu_rect = pygame.Rect(menu_x, menu_y, menu_width, menu_height)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], menu_rect, border_radius=14)
    pygame.draw.rect(screen, THEME_COLORS["border"], menu_rect, 3, border_radius=14)
    
    # Titre
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, menu_y + margin_top_bottom//2 + title_surface.get_height()//2))
    screen.blit(title_surface, title_rect)
    
    # Position de départ pour le contenu
    content_start_y = title_rect.bottom + 20
    
    # Division en deux colonnes : gauche pour la grille, droite pour les options
    left_column_x = menu_x + 20
    left_column_width = int(menu_width * 0.4)
    right_column_x = left_column_x + left_column_width + 20
    right_column_width = menu_width - left_column_width - 60
    
    # COLONNE GAUCHE : Dessiner uniquement la grille sélectionnée
    if selected_index < len(layouts):
        cols, rows = layouts[selected_index]
        
        # Calculer la taille des cellules pour le schéma
        cell_size = min(60, (left_column_width - 20) // max(cols, rows))
        grid_width = cols * cell_size
        grid_height = rows * cell_size
        
        # Centrer la grille verticalement dans l'espace disponible
        available_height = (len(options) * (button_height + 10)) - 10
        grid_x = left_column_x + (left_column_width - grid_width) // 2
        grid_y = content_start_y + (available_height - grid_height) // 2
        
        # Dessiner le schéma de la grille sélectionnée
        for row in range(rows):
            for col in range(cols):
                cell_rect = pygame.Rect(
                    grid_x + col * cell_size,
                    grid_y + row * cell_size,
                    cell_size - 3,
                    cell_size - 3
                )
                # Couleur selon si c'est aussi le layout actuel
                if selected_index == current_idx:
                    # Sélectionné ET actuel : vert brillant
                    pygame.draw.rect(screen, THEME_COLORS["fond_lignes"], cell_rect)
                    pygame.draw.rect(screen, THEME_COLORS["text"], cell_rect, 2)
                else:
                    # Seulement sélectionné : bleu clair
                    pygame.draw.rect(screen, THEME_COLORS["button_selected"], cell_rect)
                    pygame.draw.rect(screen, THEME_COLORS["text"], cell_rect, 2)
    
    # COLONNE DROITE : Dessiner les boutons d'options
    for i, option in enumerate(options):
        button_x = right_column_x
        button_y = content_start_y + i * (button_height + 10)
        button_width = right_column_width
        
        button_rect = pygame.Rect(button_x, button_y, button_width, button_height)
        
        if i == selected_index:
            pygame.draw.rect(screen, THEME_COLORS["button_selected"], button_rect, border_radius=8)
        else:
            pygame.draw.rect(screen, THEME_COLORS["button_idle"], button_rect, border_radius=8)
        
        pygame.draw.rect(screen, THEME_COLORS["border"], button_rect, 2, border_radius=8)
        
        text_surface = config.font.render(option, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=button_rect.center)
        screen.blit(text_surface, text_rect)
    
    # Dessiner l'instruction en haut
    draw_menu_instruction(screen, instruction)

def draw_pause_display_font_menu(screen, selected_index):
    """Sous-menu pour les tailles de police."""
    # Font size
    opts = getattr(config, 'font_scale_options', [0.75, 1.0, 1.25, 1.5, 1.75])
    cur_idx = getattr(config, 'current_font_scale_index', 1)
    font_value = f"{opts[cur_idx]}x"
    font_txt = f"{_('submenu_display_font_size') if _ else 'Font Size'}: < {font_value} >"
    
    # Footer font size
    footer_opts = getattr(config, 'footer_font_scale_options', [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0])
    footer_cur_idx = getattr(config, 'current_footer_font_scale_index', 3)
    footer_font_value = f"{footer_opts[footer_cur_idx]}x"
    footer_font_txt = f"{_('accessibility_footer_font_size').split(':')[0] if _ else 'Footer Font Size'}: < {footer_font_value} >"
    
    back_txt = _("menu_back") if _ else "Back"
    
    options = [font_txt, footer_font_txt, back_txt]
    instruction_keys = [
        "instruction_display_font_size",
        "instruction_display_footer_font_size",
        "instruction_generic_back",
    ]
    
    key = instruction_keys[selected_index] if 0 <= selected_index < len(instruction_keys) else None
    instruction_text = _(key) if key else None
    _draw_submenu_generic(screen, _("submenu_display_font_size") if _ else "Font Size", options, selected_index, instruction_text)

def draw_pause_games_menu(screen, selected_index):
    mode = get_sources_mode()
    source_label = _("games_source_rgsx") if mode == "rgsx" else _("games_source_custom")
    source_txt = f"{_('menu_games_source_prefix')}: < {source_label} >"
    update_txt = _("menu_redownload_cache")
    history_txt = _("menu_history") if _ else "History"
    
    # Show unsupported systems
    unsupported = get_show_unsupported_platforms()
    status_unsupported = _('status_on') if unsupported else _('status_off')
    raw_unsupported_label = _('submenu_display_show_unsupported') if _ else 'Show unsupported systems: {status}'
    if '{status}' in raw_unsupported_label:
        raw_unsupported_label = raw_unsupported_label.split('{status}')[0].rstrip(' :')
    unsupported_txt = f"{raw_unsupported_label}: < {status_unsupported} >"
    
    # Hide premium systems
    hide_premium = get_hide_premium_systems()
    status_hide_premium = _('status_on') if hide_premium else _('status_off')
    hide_premium_label = _('menu_hide_premium_systems') if _ else 'Hide Premium systems'
    hide_premium_txt = f"{hide_premium_label}: < {status_hide_premium} >"
    
    # Filter platforms
    filter_txt = _("submenu_display_filter_platforms") if _ else "Filter Platforms"
    
    back_txt = _("menu_back") if _ else "Back"
    options = [update_txt, history_txt, source_txt, unsupported_txt, hide_premium_txt, filter_txt, back_txt]
    instruction_keys = [
        "instruction_games_update_cache",
        "instruction_games_history",
        "instruction_games_source_mode",
        "instruction_display_show_unsupported",
        "instruction_display_hide_premium",
        "instruction_display_filter_platforms",
        "instruction_generic_back",
    ]
    key = instruction_keys[selected_index] if 0 <= selected_index < len(instruction_keys) else None
    instruction_text = None
    if key:
        instruction_text = _(key)
        if key == "instruction_display_hide_premium":
            # Inject dynamic list of premium providers from config.PREMIUM_HOST_MARKERS
            try:
                from config import PREMIUM_HOST_MARKERS
                # Clean, preserve order, remove duplicates (case-insensitive)
                seen = set()
                providers_clean = []
                for p in PREMIUM_HOST_MARKERS:
                    p_lower = p.lower()
                    if p_lower not in seen:
                        seen.add(p_lower)
                        providers_clean.append(p)
                providers_str = ", ".join(providers_clean)
                if not providers_str:
                    providers_str = "1fichier, etc."
                if "{providers}" in instruction_text:
                    instruction_text = instruction_text.format(providers=providers_str)
                else:
                    # fallback si placeholder absent
                    instruction_text = f"{instruction_text} ({providers_str})"
                    
            except Exception:
                pass
    
    _draw_submenu_generic(screen, _("menu_games") if _ else "Games", options, selected_index, instruction_text)

def draw_pause_settings_menu(screen, selected_index):
    from rgsx_settings import get_auto_extract, get_roms_folder
    # Music
    if config.music_enabled:
        music_name = config.current_music_name or ""
        music_option = _("menu_music_enabled").format(music_name)
    else:
        music_option = _("menu_music_disabled")
    # Uniformiser en < value > pour les réglages basculables
    if ' : ' in music_option:
        base, val = music_option.split(' : ',1)
        music_option = f"{base} : < {val.strip()} >"
    symlink_option = _("symlink_option_enabled") if get_symlink_option() else _("symlink_option_disabled")
    if ' ' in symlink_option:
        parts = symlink_option.split(' ',1)
        # On garde phrase intacte si elle n'a pas de forme label: valeur ; sinon transformer
    if ' : ' in symlink_option:
        base, val = symlink_option.split(' : ',1)
        symlink_option = f"{base} : < {val.strip()} >"
    
    # Auto Extract option
    auto_extract_enabled = get_auto_extract()
    auto_extract_status = _("settings_auto_extract_enabled") if auto_extract_enabled else _("settings_auto_extract_disabled")
    auto_extract_txt = f"{_('settings_auto_extract')} : < {auto_extract_status} >"
    
    # ROMs folder option
    roms_folder_custom = get_roms_folder()
    if roms_folder_custom:
        # Tronquer si trop long pour affichage
        max_display = 25
        display_path = roms_folder_custom if len(roms_folder_custom) <= max_display else "..." + roms_folder_custom[-(max_display-3):]
        roms_folder_txt = f"{_('settings_roms_folder')} : {display_path}"
    else:
        roms_folder_txt = f"{_('settings_roms_folder')} : < {_('settings_roms_folder_default')} >"
    
    # Web Service at boot (only on Linux/Batocera)
    web_service_txt = ""
    custom_dns_txt = ""
    if config.OPERATING_SYSTEM == "Linux":
        web_service_enabled = check_web_service_status()
        web_service_status = _("settings_web_service_enabled") if web_service_enabled else _("settings_web_service_disabled")
        web_service_txt = f"{_('settings_web_service')} : < {web_service_status} >"
        
        # Custom DNS at boot
        custom_dns_enabled = check_custom_dns_status()
        custom_dns_status = _("settings_custom_dns_enabled") if custom_dns_enabled else _("settings_custom_dns_disabled")
        custom_dns_txt = f"{_('settings_custom_dns')} : < {custom_dns_status} >"
    
    api_keys_txt = _("menu_api_keys_status") if _ else "API Keys"
    back_txt = _("menu_back") if _ else "Back"
    
    # Construction de la liste des options
    options = [music_option, symlink_option, auto_extract_txt, roms_folder_txt]
    if web_service_txt:  # Ajouter seulement si Linux/Batocera
        options.append(web_service_txt)
    if custom_dns_txt:  # Ajouter seulement si Linux/Batocera
        options.append(custom_dns_txt)
    options.extend([api_keys_txt, back_txt])
    
    # Index de l'option Dossier ROMs
    roms_folder_index = 3
    
    # Instructions textuelles pour chaque option
    instruction_keys = [
        "instruction_settings_music",
        "instruction_settings_symlink",
        "instruction_settings_auto_extract",
        "instruction_settings_roms_folder",
    ]
    if web_service_txt:
        instruction_keys.append("instruction_settings_web_service")
    if custom_dns_txt:
        instruction_keys.append("instruction_settings_custom_dns")
    instruction_keys.extend([
        "instruction_settings_api_keys",
        "instruction_generic_back",
    ])
    key = instruction_keys[selected_index] if 0 <= selected_index < len(instruction_keys) else None
    instruction_text = _(key) if key else None
    
    _draw_submenu_generic(screen, _("menu_settings_category") if _ else "Settings", options, selected_index, instruction_text)

def draw_pause_api_keys_status(screen):
    screen.blit(OVERLAY, (0,0))
    keys = load_api_keys()
    title = _("api_keys_status_title") if _ else "API Keys Status"
    # Préparer données avec masquage partiel des clés (afficher 4 premiers et 2 derniers caractères si longueur > 10)
    def mask_key(value: str|None):
        if not value:
            return ""  # rien si absent
        v = value.strip()
        if len(v) <= 10:
            return v  # courte, afficher entière
        return f"{v[:4]}…{v[-2:]}"  # masque au milieu

    providers = [
        ("1fichier", keys.get('1fichier')),
        ("AllDebrid", keys.get('alldebrid')),
        ("RealDebrid", keys.get('realdebrid'))
    ]
    # Dimensions dynamiques en fonction du contenu
    row_height = config.small_font.get_height() + 14
    header_height = 60
    inner_rows = len(providers)
    menu_width = int(config.screen_width * 0.60)
    menu_height = header_height + inner_rows * row_height + 80
    menu_x = (config.screen_width - menu_width)//2
    menu_y = (config.screen_height - menu_height)//2
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (menu_x, menu_y, menu_width, menu_height), border_radius=22)
    pygame.draw.rect(screen, THEME_COLORS["border"], (menu_x, menu_y, menu_width, menu_height), 2, border_radius=22)

    # Titre
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width//2, menu_y + 36))
    screen.blit(title_surface, title_rect)

    status_present_txt = _("status_present") if _ else "Present"
    status_missing_txt = _("status_missing") if _ else "Missing"
    # Plus de légende textuelle Présent / Missing (demandé) – seules les pastilles couleur serviront.
    legend_rect = pygame.Rect(0,0,0,0)

    # Colonnes: Provider | Status badge | (key masked)
    col_provider_x = menu_x + 40
    col_status_x = menu_x + int(menu_width * 0.40)
    col_key_x = menu_x + int(menu_width * 0.58)

    # Démarrage des lignes sous le titre avec un padding
    y = title_rect.bottom + 24
    badge_font = config.tiny_font if hasattr(config, 'tiny_font') else config.small_font
    for provider, value in providers:
        present = bool(value)
        # Provider name
        prov_surf = config.small_font.render(provider, True, THEME_COLORS["text"])
        screen.blit(prov_surf, (col_provider_x, y))

        # Pastille circulaire simple (couleur = statut)
        circle_color = (60, 170, 60) if present else (180, 55, 55)
        circle_bg = (30, 70, 30) if present else (70, 25, 25)
        radius = 14
        center_x = col_status_x + radius
        center_y = y + badge_font.get_height()//2
        pygame.draw.circle(screen, circle_bg, (center_x, center_y), radius)
        pygame.draw.circle(screen, circle_color, (center_x, center_y), radius, 2)

        # Masked key (dim color) or hint
        if present:
            masked = mask_key(value)
            key_color = THEME_COLORS.get("text_dim", (180,180,180))
            key_label = masked
        else:
            key_color = THEME_COLORS.get("text_dim", (150,150,150))
            # Afficher nom de fichier + 'empty'
            filename_display = {
                '1fichier': '1FichierAPI.txt',
                'AllDebrid': 'AllDebridAPI.txt',
                'RealDebrid': 'RealDebridAPI.txt'
            }.get(provider, 'key.txt')
            empty_suffix = _("api_key_empty_suffix") if _ and _("api_key_empty_suffix") != "api_key_empty_suffix" else "empty"
            key_label = f"{filename_display} {empty_suffix}"
        key_surf = config.tiny_font.render(key_label, True, key_color) if hasattr(config, 'tiny_font') else config.small_font.render(key_label, True, key_color)
        screen.blit(key_surf, (col_key_x, y))

        # Ligne séparatrice (optionnelle)
        sep_y = y + row_height - 8
        if provider != providers[-1][0]:
            pygame.draw.line(screen, THEME_COLORS["border"], (menu_x + 25, sep_y), (menu_x + menu_width - 25, sep_y), 1)
        y += row_height

    # Indication basique: utiliser config.SAVE_FOLDER (chemin dynamique)
    save_folder_path = config.SAVE_FOLDER
    # Utiliser placeholder {path} si traduction fournie
    if _ and _("api_keys_hint_manage") != "api_keys_hint_manage":
        try:
            hint_txt = _("api_keys_hint_manage").format(path=save_folder_path)
        except Exception:
            hint_txt = f"Put your keys in {save_folder_path}"
    else:
        hint_txt = f"Put your keys in {save_folder_path}"
    hint_font = config.tiny_font if hasattr(config, 'tiny_font') else config.small_font
    hint_surf = hint_font.render(hint_txt, True, THEME_COLORS.get("text_dim", THEME_COLORS["text"]))
    # Positionné un peu plus haut pour aérer
    hint_rect = hint_surf.get_rect(center=(config.screen_width//2, menu_y + menu_height - 30))
    screen.blit(hint_surf, hint_rect)


def draw_filter_platforms_menu(screen):
    """Affiche le menu de filtrage des plateformes (afficher/masquer)."""
    screen.blit(OVERLAY, (0, 0))
    settings = load_rgsx_settings()
    hidden = set(settings.get("hidden_platforms", [])) if isinstance(settings, dict) else set()

    # Initialiser la copie de travail si vide ou taille différente
    if not config.filter_platforms_selection or len(config.filter_platforms_selection) != len(config.platform_dicts):
        # Liste alphabétique complète (sans filtrer hidden existant)
        all_names = sorted([d.get("platform_name", "") for d in config.platform_dicts if d.get("platform_name")])
        config.filter_platforms_selection = [(name, name in hidden) for name in all_names]
        config.selected_filter_index = 0
        config.filter_platforms_scroll_offset = 0
        config.filter_platforms_dirty = False

    title_text = _("filter_platforms_title")
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, title_surface.get_height() // 2 + 14))
    # Padding responsive réduit
    hpad = max(36, min(64, int(config.screen_width * 0.06)))
    vpad = max(10, min(20, int(title_surface.get_height() * 0.45)))
    title_rect_inflated = title_rect.inflate(hpad, vpad)
    title_rect_inflated.topleft = ((config.screen_width - title_rect_inflated.width) // 2, 10)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_rect_inflated, border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_rect_inflated, 2, border_radius=12)
    screen.blit(title_surface, title_rect)

    # Boutons d'action en haut (avant la liste)
    btn_width = 220
    btn_height = int(config.screen_height * 0.0463)
    spacing = 30
    buttons_y = title_rect_inflated.bottom + 20
    center_x = config.screen_width // 2
    actions = [
        ("filter_all", 0),
        ("filter_none", 1),
        ("filter_apply", 2),
        ("filter_back", 3)
    ]
    total_items = len(config.filter_platforms_selection)
    action_buttons = len(actions)
    
    for idx, (key, btn_idx) in enumerate(actions):
        btn_x = center_x - (len(actions) * (btn_width + spacing) - spacing) // 2 + idx * (btn_width + spacing)
        is_selected = (config.selected_filter_index == btn_idx)
        label = _(key)
        draw_stylized_button(screen, label, btn_x, buttons_y, btn_width, btn_height, selected=is_selected)

    # Zone liste (après les boutons)
    list_width = int(config.screen_width * 0.7)
    list_height = int(config.screen_height * 0.5)
    list_x = (config.screen_width - list_width) // 2
    list_y = buttons_y + btn_height + 20
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (list_x, list_y, list_width, list_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (list_x, list_y, list_width, list_height), 2, border_radius=12)

    line_height = config.small_font.get_height() + 8
    visible_items = list_height // line_height - 1  # laisser un peu d'espace bas
    total_items = len(config.filter_platforms_selection)
    if config.selected_filter_index < 0:
        config.selected_filter_index = 0
    # Ne pas forcer la réduction si on est sur les boutons (indices >= total_items)
    # Laisser controls.py gérer la borne max étendue
    # Ajuster scroll
    if config.selected_filter_index < config.filter_platforms_scroll_offset:
        config.filter_platforms_scroll_offset = config.selected_filter_index
    elif config.selected_filter_index >= config.filter_platforms_scroll_offset + visible_items:
        config.filter_platforms_scroll_offset = config.selected_filter_index - visible_items + 1

    # Dessiner items (les indices de la liste commencent à action_buttons)
    for i in range(config.filter_platforms_scroll_offset, min(config.filter_platforms_scroll_offset + visible_items, total_items)):
        name, is_hidden = config.filter_platforms_selection[i]
        idx_on_screen = i - config.filter_platforms_scroll_offset
        y_center = list_y + 10 + idx_on_screen * line_height + line_height // 2
        # Les éléments de la liste ont des indices à partir de action_buttons
        selected = (config.selected_filter_index == action_buttons + i)
        checkbox = "[ ]" if is_hidden else "[X]"  # inversé: coché signifie visible
        # Correction: on veut [X] si visible => is_hidden False
        checkbox = "[X]" if not is_hidden else "[ ]"
        display_text = f"{checkbox} {name}"
        color = THEME_COLORS["fond_lignes"] if selected else THEME_COLORS["text"]
        text_surface = config.small_font.render(display_text, True, color)
        text_rect = text_surface.get_rect(midleft=(list_x + 20, y_center))
        if selected:
            glow_surface = pygame.Surface((list_width - 40, line_height), pygame.SRCALPHA)
            pygame.draw.rect(glow_surface, THEME_COLORS["fond_lignes"] + (50,), (0, 0, list_width - 40, line_height), border_radius=8)
            screen.blit(glow_surface, (list_x + 20, y_center - line_height // 2))
        screen.blit(text_surface, text_rect)

    # Scrollbar
    if total_items > visible_items:
        scroll_height = int((visible_items / total_items) * (list_height - 20))
        scroll_y = int((config.filter_platforms_scroll_offset / max(1, total_items - visible_items)) * (list_height - 20 - scroll_height))
        pygame.draw.rect(screen, THEME_COLORS["fond_lignes"], (list_x + list_width - 25, list_y + 10 + scroll_y, 10, scroll_height), border_radius=4)

    # Infos bas
    hidden_count = sum(1 for _, h in config.filter_platforms_selection if h)
    visible_count = total_items - hidden_count
    info_text = _("filter_platforms_info").format(visible_count, hidden_count, total_items)
    info_surface = config.small_font.render(info_text, True, THEME_COLORS["text"])
    info_rect = info_surface.get_rect(center=(config.screen_width // 2, list_y + list_height + 20))
    screen.blit(info_surface, info_rect)

    if config.filter_platforms_dirty:
        dirty_text = _("filter_unsaved_warning")
        dirty_surface = config.small_font.render(dirty_text, True, THEME_COLORS["warning_text"])
        dirty_rect = dirty_surface.get_rect(center=(config.screen_width // 2, info_rect.bottom + 25))
        screen.blit(dirty_surface, dirty_rect)

# Menu aide contrôles
def draw_controls_help(screen, previous_state):
    """Affiche la liste des contrôles (aide) avec mise en page adaptative."""
    # Contenu des catégories (avec icônes si disponibles)
    control_categories = {
        _("controls_category_navigation"): [
            ("icons", ["up", "down", "left", "right"], _('controls_navigation')),
            ("icons", ["page_up", "page_down"], _('controls_pages')),
        ],
        _("controls_category_main_actions"): [
            ("icons", ["confirm"], _('controls_confirm_select')),
            ("icons", ["cancel"], _('controls_cancel_back')),
            ("icons", ["start"], _('controls_action_start')),
        ],
        _("controls_category_downloads"): [
            ("icons", ["history"], _('controls_action_history')),
            ("icons", ["clear_history"], _('controls_action_clear_history')),
        ],
        _("controls_category_search"): [
            ("icons", ["filter"], _('controls_filter_search')),
            ("icons", ["delete"], _('controls_action_delete')),
            ("icons", ["space"], _('controls_action_space')),
        ],
    }

    # États autorisés (même logique qu'avant)
    allowed_states = {
        # États classiques où l'aide était accessible
        "error", "platform", "game", "confirm_exit",
        "extension_warning", "history", "clear_history",
        # Nouveaux états hiérarchiques pause
        "pause_controls_menu", "pause_menu"
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
                # Deux formats possibles:
                # - tuple ("icons", [actions], text)
                # - chaîne texte simple
                line_surface = None
                if isinstance(raw_line, tuple) and len(raw_line) >= 3 and raw_line[0] == "icons":
                    _, actions, text = raw_line
                    try:
                        line_surface = _render_icons_line(actions, text, target_col_width, font, THEME_COLORS["text"])
                    except Exception:
                        line_surface = None
                if line_surface is None:
                    # Fallback: traitement texte comme avant
                    words = str(raw_line).split()
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
                else:
                    wrapped.append((False, line_surface))
                    total_height += line_surface.get_height() + line_spacing
                    max_width = max(max_width, line_surface.get_width())

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
    """Affiche le sous-menu Quit avec les options Quit et Restart."""
    options = [
        _("menu_quit_app") if _ else "Quit RGSX",
        _("menu_restart") if _ else "Restart RGSX",
        _("menu_back") if _ else "Back"
    ]
    instruction_keys = [
        "instruction_quit_app",
        "instruction_quit_restart",
        "instruction_generic_back",
    ]
    key = instruction_keys[config.confirm_selection] if 0 <= config.confirm_selection < len(instruction_keys) else None
    instruction_text = _(key) if key else None
    _draw_submenu_generic(screen, _("menu_quit") if _ else "Quit", options, config.confirm_selection, instruction_text)


def draw_reload_games_data_dialog(screen):
    """Affiche la boîte de dialogue de confirmation pour retélécharger le cache des jeux."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))

    screen.blit(OVERLAY, (0, 0))
    message = _("confirm_redownload_cache")
    wrapped_message = wrap_text(message, config.small_font, config.screen_width - 80)
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    # Adapter hauteur bouton en fonction de la taille de police
    sample_text = config.small_font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    button_height = max(int(config.screen_height * 0.0463), font_height + 15)
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


def draw_gamelist_update_prompt(screen):
    """Affiche la boîte de dialogue pour proposer la mise à jour de la liste des jeux."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))

    screen.blit(OVERLAY, (0, 0))
    
    from config import GAMELIST_UPDATE_DAYS
    from rgsx_settings import get_last_gamelist_update
    
    last_update = get_last_gamelist_update()
    if last_update:
        message = _("gamelist_update_prompt_with_date").format(GAMELIST_UPDATE_DAYS, last_update) if _ else f"Game list hasn't been updated for more than {GAMELIST_UPDATE_DAYS} days (last update: {last_update}). Download the latest version?"
    else:
        message = _("gamelist_update_prompt_first_time") if _ else "Would you like to download the latest game list?"
    
    wrapped_message = wrap_text(message, config.small_font, config.screen_width - 80)
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    
    sample_text = config.small_font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    button_height = max(int(config.screen_height * 0.0463), font_height + 15)
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

    button_width = min(160, (rect_width - 60) // 2)
    yes_x = rect_x + rect_width // 2 - button_width - 10
    no_x = rect_x + rect_width // 2 + 10
    buttons_y = rect_y + text_height + margin_top_bottom
    draw_stylized_button(screen, _("button_yes"), yes_x, buttons_y, button_width, button_height, selected=config.gamelist_update_selection == 1)
    draw_stylized_button(screen, _("button_no"), no_x, buttons_y, button_width, button_height, selected=config.gamelist_update_selection == 0)


def draw_platform_folder_config_dialog(screen):
    """Affiche le dialogue de configuration du dossier personnalisé pour une plateforme."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))

    screen.blit(OVERLAY, (0, 0))
    
    from rgsx_settings import get_platform_custom_path
    platform_name = getattr(config, 'platform_config_name', '')
    current_path = get_platform_custom_path(platform_name)
    
    # Message d'information
    if current_path:
        message = _("platform_folder_config_current").format(platform_name, current_path) if _ else f"Configure download folder for {platform_name}\nCurrent: {current_path}"
    else:
        message = _("platform_folder_config_default").format(platform_name) if _ else f"Configure download folder for {platform_name}\nUsing default location"
    
    # Traiter les sauts de ligne explicites, puis wrapper chaque partie
    wrapped_message = []
    for part in message.split('\n'):
        wrapped_message.extend(wrap_text(part, config.small_font, config.screen_width - 100))
    
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    
    # Options
    options = [
        _("platform_folder_show_current") if _ else "Show current path",
        _("platform_folder_browse") if _ else "Browse",
        _("platform_folder_reset") if _ else "Reset to default",
        _("web_cancel") if _ else "Cancel"
    ]
    
    sample_text = config.small_font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    button_height = max(int(config.screen_height * 0.0463), font_height + 15)
    margin_top_bottom = 20
    buttons_spacing = 10
    
    rect_height = text_height + len(options) * (button_height + buttons_spacing) + 2 * margin_top_bottom
    max_text_width = max([config.small_font.size(line)[0] for line in wrapped_message], default=400)
    max_button_width = max([config.small_font.size(opt)[0] for opt in options], default=200) + 60  # Plus de marge pour les boutons
    rect_width = max(max_text_width + 80, max_button_width + 40, 550)  # Largeur minimale augmentée
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    # Afficher le message
    for i, line in enumerate(wrapped_message):
        text = config.small_font.render(line, True, THEME_COLORS["text"])
        text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text, text_rect)

    # Afficher les boutons
    button_width = min(max_button_width, rect_width - 60)
    buttons_start_y = rect_y + text_height + margin_top_bottom
    
    for i, option in enumerate(options):
        button_x = rect_x + (rect_width - button_width) // 2
        button_y = buttons_start_y + i * (button_height + buttons_spacing)
        selected = config.platform_folder_selection == i
        draw_stylized_button(screen, option, button_x, button_y, button_width, button_height, selected=selected)


def draw_folder_browser(screen):
    """Affiche le navigateur de dossiers intégré."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 180))

    screen.blit(OVERLAY, (0, 0))
    
    browser_mode = getattr(config, 'folder_browser_mode', 'platform')
    platform_name = getattr(config, 'platform_config_name', '')
    current_path = config.folder_browser_path
    items = config.folder_browser_items
    selection = config.folder_browser_selection
    scroll_offset = config.folder_browser_scroll_offset
    visible_items = config.folder_browser_visible_items
    
    # Dimensions du panneau
    panel_width = int(config.screen_width * 0.8)
    panel_height = int(config.screen_height * 0.85)
    panel_x = (config.screen_width - panel_width) // 2
    panel_y = (config.screen_height - panel_height) // 2
    
    # Fond du panneau
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (panel_x, panel_y, panel_width, panel_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (panel_x, panel_y, panel_width, panel_height), 2, border_radius=12)
    
    # Titre selon le mode
    if browser_mode == "roms_root":
        title = _("folder_browser_title_roms_root") if _ else "Select default ROMs folder"
    else:
        title = _("folder_browser_title").format(platform_name) if _ else f"Select folder for {platform_name}"
    title_text = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_text.get_rect(center=(config.screen_width // 2, panel_y + 30))
    screen.blit(title_text, title_rect)
    
    # Chemin actuel (tronqué si trop long)
    path_max_width = panel_width - 40
    path_display = current_path
    while config.small_font.size(path_display)[0] > path_max_width and len(path_display) > 10:
        path_display = "..." + path_display[4:]
    path_text = config.small_font.render(path_display, True, THEME_COLORS["highlight"])
    path_rect = path_text.get_rect(center=(config.screen_width // 2, panel_y + 70))
    screen.blit(path_text, path_rect)
    
    # Zone de liste des dossiers
    list_y = panel_y + 100
    list_height = panel_height - 180
    item_height = max(35, config.small_font.get_height() + 10)
    visible_items = min(visible_items, list_height // item_height)
    config.folder_browser_visible_items = visible_items
    
    # Afficher les éléments visibles
    for i in range(visible_items):
        item_index = scroll_offset + i
        if item_index >= len(items):
            break
        
        item = items[item_index]
        item_y = list_y + i * item_height
        is_selected = item_index == selection
        
        # Fond de l'élément sélectionné
        if is_selected:
            sel_rect = (panel_x + 20, item_y, panel_width - 40, item_height)
            pygame.draw.rect(screen, THEME_COLORS["button_hover"], sel_rect, border_radius=6)
            pygame.draw.rect(screen, THEME_COLORS["highlight"], sel_rect, 2, border_radius=6)
        
        # Icône dossier (texte simple au lieu d'emoji)
        folder_icon = "[..]" if item == ".." else "[D]"
        icon_text = config.small_font.render(folder_icon, True, THEME_COLORS["highlight"] if item == ".." else THEME_COLORS["text"])
        screen.blit(icon_text, (panel_x + 30, item_y + (item_height - icon_text.get_height()) // 2))
        
        # Nom du dossier
        display_name = _("folder_browser_parent") if item == ".." and _ else (".." if item == ".." else item)
        text_color = THEME_COLORS["highlight"] if is_selected else THEME_COLORS["text"]
        item_text = config.small_font.render(display_name, True, text_color)
        screen.blit(item_text, (panel_x + 70, item_y + (item_height - item_text.get_height()) // 2))
    
    # Indicateur de scroll si nécessaire
    if len(items) > visible_items:
        scrollbar_x = panel_x + panel_width - 25
        scrollbar_y = list_y
        scrollbar_height = list_height
        scrollbar_width = 8
        
        # Fond de la scrollbar
        pygame.draw.rect(screen, THEME_COLORS["border"], (scrollbar_x, scrollbar_y, scrollbar_width, scrollbar_height), border_radius=4)
        
        # Curseur de la scrollbar
        cursor_height = max(20, scrollbar_height * visible_items // len(items))
        cursor_y = scrollbar_y + (scrollbar_height - cursor_height) * scroll_offset // max(1, len(items) - visible_items)
        pygame.draw.rect(screen, THEME_COLORS["highlight"], (scrollbar_x, cursor_y, scrollbar_width, cursor_height), border_radius=4)


def draw_folder_browser_new_folder(screen):
    """Affiche l'écran de création d'un nouveau dossier avec clavier virtuel."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 200))

    screen.blit(OVERLAY, (0, 0))
    
    # Dimensions du panneau
    panel_width = int(config.screen_width * 0.7)
    panel_height = int(config.screen_height * 0.6)
    panel_x = (config.screen_width - panel_width) // 2
    panel_y = (config.screen_height - panel_height) // 2
    
    # Fond du panneau
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (panel_x, panel_y, panel_width, panel_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (panel_x, panel_y, panel_width, panel_height), 2, border_radius=12)
    
    # Titre
    title = _("folder_new_title") if _ else "Create New Folder"
    title_text = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_text.get_rect(center=(config.screen_width // 2, panel_y + 30))
    screen.blit(title_text, title_rect)
    
    # Champ de saisie avec le nom actuel
    folder_name = getattr(config, 'new_folder_name', '')
    input_y = panel_y + 70
    input_width = panel_width - 60
    input_height = 40
    input_x = panel_x + 30
    
    # Fond du champ de saisie
    pygame.draw.rect(screen, THEME_COLORS["button_selected"], (input_x, input_y, input_width, input_height), border_radius=6)
    pygame.draw.rect(screen, THEME_COLORS["border_selected"], (input_x, input_y, input_width, input_height), 2, border_radius=6)
    
    # Texte du champ de saisie avec curseur
    display_text = folder_name + "_"
    input_text = config.font.render(display_text, True, THEME_COLORS["text"])
    input_rect = input_text.get_rect(midleft=(input_x + 10, input_y + input_height // 2))
    screen.blit(input_text, input_rect)
    
    # Clavier virtuel
    keyboard_layout = [
        ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'],
        ['A', 'Z', 'E', 'R', 'T', 'Y', 'U', 'I', 'O', 'P'],
        ['Q', 'S', 'D', 'F', 'G', 'H', 'J', 'K', 'L', 'M'],
        ['W', 'X', 'C', 'V', 'B', 'N', '-', '_', '.']
    ]
    
    selected_row, selected_col = getattr(config, 'new_folder_selected_key', (0, 0))
    
    keyboard_y = input_y + input_height + 30
    key_size = min(40, (panel_width - 60) // 10)
    key_gap = 5
    
    for row_idx, row in enumerate(keyboard_layout):
        row_width = len(row) * (key_size + key_gap) - key_gap
        row_x = (config.screen_width - row_width) // 2
        
        for col_idx, key in enumerate(row):
            key_x = row_x + col_idx * (key_size + key_gap)
            key_y = keyboard_y + row_idx * (key_size + key_gap)
            
            is_selected = (row_idx == selected_row and col_idx == selected_col)
            
            # Fond de la touche
            if is_selected:
                pygame.draw.rect(screen, THEME_COLORS["button_hover"], (key_x, key_y, key_size, key_size), border_radius=4)
                pygame.draw.rect(screen, THEME_COLORS["border_selected"], (key_x, key_y, key_size, key_size), 2, border_radius=4)
            else:
                pygame.draw.rect(screen, THEME_COLORS["button_idle"], (key_x, key_y, key_size, key_size), border_radius=4)
                pygame.draw.rect(screen, THEME_COLORS["border"], (key_x, key_y, key_size, key_size), 1, border_radius=4)
            
            # Lettre
            key_text = config.small_font.render(key, True, THEME_COLORS["text_selected"] if is_selected else THEME_COLORS["text"])
            key_rect = key_text.get_rect(center=(key_x + key_size // 2, key_y + key_size // 2))
            screen.blit(key_text, key_rect)


def draw_support_dialog(screen):
    """Affiche la boîte de dialogue du fichier de support généré."""
    global OVERLAY
    if OVERLAY is None or OVERLAY.get_size() != (config.screen_width, config.screen_height):
        OVERLAY = pygame.Surface((config.screen_width, config.screen_height), pygame.SRCALPHA)
        OVERLAY.fill((0, 0, 0, 150))
        logger.debug("OVERLAY recréé dans draw_support_dialog")

    screen.blit(OVERLAY, (0, 0))
    
    # Récupérer le nom du bouton "cancel/back" depuis la configuration des contrôles
    cancel_key = "SELECT"
    try:
        from controls_mapper import get_mapped_button
        cancel_key = get_mapped_button("cancel") or "SELECT"
    except Exception:
        pass
    
    # Déterminer le message à afficher (succès ou erreur)
    if hasattr(config, 'support_zip_error') and config.support_zip_error:
        title = _("support_dialog_title")
        message = _("support_dialog_error").format(config.support_zip_error, cancel_key)
    else:
        title = _("support_dialog_title")
        zip_path = getattr(config, 'support_zip_path', 'rgsx_support.zip')
        message = _("support_dialog_message").format(zip_path, cancel_key)
    
    # Diviser le message par les retours à la ligne puis wrapper chaque segment
    raw_segments = message.split('\n') if message else []
    wrapped_message = []
    for seg in raw_segments:
        if seg.strip() == "":
            wrapped_message.append("")  # Ligne vide pour espacement
        else:
            wrapped_message.extend(wrap_text(seg, config.small_font, config.screen_width - 100))
    
    line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_message) * line_height
    
    # Calculer la hauteur du titre
    title_height = config.font.get_height() + 10
    
    # Calculer les dimensions de la boîte
    margin_top_bottom = 20
    rect_height = title_height + text_height + 2 * margin_top_bottom
    max_text_width = max([config.small_font.size(line)[0] for line in wrapped_message if line], default=300)
    title_width = config.font.size(title)[0]
    rect_width = max(max_text_width, title_width) + 100
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2

    # Dessiner la boîte
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)

    # Afficher le titre
    title_surf = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surf.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + title_height // 2))
    screen.blit(title_surf, title_rect)

    # Afficher le message
    for i, line in enumerate(wrapped_message):
        if line:  # Ne pas rendre les lignes vides
            text = config.small_font.render(line, True, THEME_COLORS["text"])
            text_rect = text.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom + title_height + i * line_height + line_height // 2))
            screen.blit(text, text_rect)


# Popup avec compte à rebours
def draw_popup(screen):
    """Dessine un popup avec un message (adapté en largeur) et un compte à rebours."""
    screen.blit(OVERLAY, (0, 0))

    # Largeur de base (peut s'élargir un peu si très petit écran)
    popup_width = int(config.screen_width * 0.8)
    max_inner_width = popup_width - 60  # padding horizontal interne pour le texte
    line_height = config.small_font.get_height() + 8
    margin_top_bottom = 24

    raw_segments = config.popup_message.split('\n') if config.popup_message else []
    wrapped_lines = []
    for seg in raw_segments:
        if seg.strip() == "":
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(wrap_text(seg, config.small_font, max_inner_width))
    if not wrapped_lines:
        wrapped_lines = [""]

    text_height = len(wrapped_lines) * line_height
    # Ajouter une ligne pour le compte à rebours
    popup_height = text_height + 2 * margin_top_bottom + line_height
    popup_x = (config.screen_width - popup_width) // 2
    popup_y = (config.screen_height - popup_height) // 2

    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (popup_x, popup_y, popup_width, popup_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (popup_x, popup_y, popup_width, popup_height), 2, border_radius=12)

    for i, line in enumerate(wrapped_lines):
        # Alignment centre horizontal global
        text_surface = config.small_font.render(line, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, popup_y + margin_top_bottom + i * line_height + line_height // 2))
        screen.blit(text_surface, text_rect)

    remaining_time = max(0, config.popup_timer // 1000)
    countdown_text = _("popup_countdown").format(remaining_time, 's' if remaining_time != 1 else '')
    countdown_surface = config.small_font.render(countdown_text, True, THEME_COLORS["text"])
    countdown_rect = countdown_surface.get_rect(center=(config.screen_width // 2, popup_y + margin_top_bottom + len(wrapped_lines) * line_height + line_height // 2))
    screen.blit(countdown_surface, countdown_rect)


def draw_toast(screen):
    """Affiche une notification toast dans le coin supérieur droit (2s max).
    
    Utilise config.toast_message pour le contenu.
    Utilise config.toast_duration (par défaut 2000ms) pour la durée.
    """
    if not hasattr(config, 'toast_message') or not config.toast_message:
        return
    
    if not hasattr(config, 'toast_start_time'):
        config.toast_start_time = pygame.time.get_ticks()
    
    current_time = pygame.time.get_ticks()
    elapsed = current_time - config.toast_start_time
    
    # Durée configurable (par défaut 2000ms)
    toast_duration = getattr(config, 'toast_duration', 2000)
    
    # Disparaître après la durée définie
    if elapsed > toast_duration:
        config.toast_message = ""
        config.toast_start_time = 0
        return
    
    # Animation: fade out dans les 300ms finales
    opacity = 255
    fade_start = max(0, toast_duration - 300)
    if elapsed > fade_start:
        opacity = int(255 * (1 - (elapsed - fade_start) / 300))
    
    # Créer une surface temporaire pour le toast
    toast_padding = 15
    line_height = config.small_font.get_height() + 6
    
    text_lines = config.toast_message.split('\n')
    wrapped_lines = []
    max_width = int(config.screen_width * 0.3)  # Max 30% de la largeur
    
    for line in text_lines:
        if line.strip() == "":
            wrapped_lines.append("")
        else:
            wrapped_lines.extend(wrap_text(line, config.small_font, max_width - 2 * toast_padding))
    
    toast_width = max_width
    toast_height = len(wrapped_lines) * line_height + 2 * toast_padding
    
    # Position: coin supérieur droit
    margin = 20
    toast_x = config.screen_width - toast_width - margin
    toast_y = margin
    
    # Créer une surface avec transparence
    toast_surface = pygame.Surface((toast_width, toast_height), pygame.SRCALPHA)
    
    # Fond avec bordure (couleur vert succès - fond_lignes)
    toast_bg_color = (*THEME_COLORS["fond_lignes"], int(opacity * 0.4))  # vert semi-transparent
    toast_border_color = (*THEME_COLORS["fond_lignes"], int(opacity))  # vert opaque
    
    pygame.draw.rect(toast_surface, toast_bg_color, (0, 0, toast_width, toast_height), border_radius=8)
    pygame.draw.rect(toast_surface, toast_border_color, (0, 0, toast_width, toast_height), 2, border_radius=8)
    
    # Afficher le texte
    for i, line in enumerate(wrapped_lines):
        text_render = config.small_font.render(line, True, THEME_COLORS["text"])
        toast_surface.blit(text_render, (toast_padding, toast_padding + i * line_height))
    
    # Blit sur l'écran
    screen.blit(toast_surface, (toast_x, toast_y))


def show_toast(message, duration=2000):
    """Fonction helper pour afficher un toast de notification.
    
    Args:
        message (str): Le message à afficher (peut contenir des sauts de ligne)
        duration (int): Durée d'affichage en millisecondes (par défaut 2000)
    """
    config.toast_message = message
    config.toast_duration = duration
    config.toast_start_time = pygame.time.get_ticks()
def draw_history_game_options(screen):
    """Affiche le menu d'options pour un jeu de l'historique."""
    
    screen.blit(OVERLAY, (0, 0))
    
    if not config.history or config.current_history_item >= len(config.history):
        return
    
    entry = config.history[config.current_history_item]
    status = entry.get("status", "")
    game_name = entry.get("game_name", "Unknown")
    platform = entry.get("platform", "Unknown")
    
    # Vérifier l'existence du fichier (avec ou sans extension)
    dest_folder = _get_dest_folder_name(platform)
    base_path = os.path.join(config.ROMS_FOLDER, dest_folder)
    file_exists, actual_filename, actual_path = find_file_with_or_without_extension(base_path, game_name)
    
    # Déterminer les options disponibles selon le statut
    options = []
    option_labels = []
    
    # Options communes

    options.append("scraper")
    option_labels.append(_("history_option_scraper"))
 
    # Options selon statut
    if status == "Queued":
        # En attente dans la queue
        options.append("remove_from_queue")
        option_labels.append(_("history_option_remove_from_queue"))
    elif status in ["Downloading", "Téléchargement", "Extracting", "Paused"]:
        # Téléchargement en cours ou en pause
        options.append("pause_resume_download")
        # Afficher le bon label selon l'état actuel
        if status == "Paused":
            option_labels.append(_("history_option_resume_download"))
        else:
            option_labels.append(_("history_option_pause_download"))
        options.append("cancel_download")
        option_labels.append(_("history_option_cancel_download"))
    elif status == "Download_OK" or status == "Completed":
        # Vérifier si c'est une archive ET si le fichier existe
        if actual_filename and file_exists:
            ext = os.path.splitext(actual_filename)[1].lower()
            if ext in ['.zip', '.rar']:
                options.append("extract_archive")
                option_labels.append(_("history_option_extract_archive"))
            elif ext == '.txt':
                options.append("open_file")
                option_labels.append(_("history_option_open_file"))
    elif status in ["Erreur", "Error", "Canceled"]:
        options.append("error_info")
        option_labels.append(_("history_option_error_info"))
        options.append("retry")
        option_labels.append(_("history_option_retry"))

    # Options communes
    if file_exists:
        options.append("download_folder")
        option_labels.append(_("history_option_download_folder"))
        options.append("delete_game")
        option_labels.append(_("history_option_delete_game"))
    options.append("back")
    option_labels.append(_("history_option_back"))
    
    # Calculer dimensions
    title = _("history_game_options_title")
    line_height = config.font.get_height() + 10
    margin_top_bottom = 30
    margin_sides = 40
    
    # Hauteur pour titre + options
    total_height = margin_top_bottom * 2 + line_height + len(option_labels) * line_height
    max_width = max(
        config.font.size(title)[0],
        max([config.font.size(label)[0] for label in option_labels], default=300)
    ) + margin_sides * 2
    
    rect_width = min(max_width + 100, config.screen_width - 100)
    rect_height = total_height
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2
    
    # Fond
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)
    
    # Titre
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom))
    screen.blit(title_surface, title_rect)
    
    # Options
    sel = getattr(config, 'history_game_option_selection', 0)
    for i, label in enumerate(option_labels):
        y_pos = rect_y + margin_top_bottom + line_height + i * line_height
        
        if i == sel:
            # Option sélectionnée
            highlight_rect = pygame.Rect(rect_x + 20, y_pos - 5, rect_width - 40, line_height)
            pygame.draw.rect(screen, THEME_COLORS["button_hover"], highlight_rect, border_radius=8)
            text_color = THEME_COLORS["text_selected"]
        else:
            text_color = THEME_COLORS["text"]
        
        text_surface = config.font.render(label, True, text_color)
        text_rect = text_surface.get_rect(left=rect_x + margin_sides, centery=y_pos + line_height // 2 - 5)
        screen.blit(text_surface, text_rect)


def draw_history_show_folder(screen):
    """Affiche le chemin complet du fichier téléchargé."""
    
    screen.blit(OVERLAY, (0, 0))
    
    if not config.history or config.current_history_item >= len(config.history):
        return
    
    entry = config.history[config.current_history_item]
    game_name = entry.get("game_name", "Unknown")
    platform = entry.get("platform", "Unknown")
    
    # Utiliser le chemin réel trouvé (avec ou sans extension)
    actual_path = getattr(config, 'history_actual_path', None)
    actual_filename = getattr(config, 'history_actual_filename', None)
    
    if not actual_path or not actual_filename:
        # Fallback si pas trouvé
        dest_folder = _get_dest_folder_name(platform)
        actual_path = os.path.join(config.ROMS_FOLDER, dest_folder, game_name)
        actual_filename = game_name
    
    # Vérifier si le fichier existe
    file_exists = os.path.exists(actual_path)
    
    # Message
    title = _("history_folder_path_label") if _ else "Destination path:"
    
    # Calculer dimensions d'abord pour avoir la largeur correcte
    line_height = config.font.get_height() + 10
    small_line_height = config.small_font.get_height() + 5
    margin_top_bottom = 30
    rect_width = min(config.screen_width - 100, 800)
    
    # Wrapper le chemin avec la bonne largeur (largeur de la boîte - marges)
    path_wrapped = wrap_text(actual_path, config.small_font, rect_width - 80)
    
    # Ajouter un message si le fichier n'existe pas
    warning_lines = []
    if not file_exists:
        warning_text = "⚠️ " + (_("history_file_not_found") if _ else "File not found")
        warning_lines = wrap_text(warning_text, config.small_font, rect_width - 80)
    
    total_height = margin_top_bottom * 2 + line_height + len(path_wrapped) * small_line_height + len(warning_lines) * small_line_height + 60
    rect_height = total_height
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2
    
    # Fond
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)
    
    # Titre
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom))
    screen.blit(title_surface, title_rect)
    
    # Chemin
    current_y = rect_y + margin_top_bottom + line_height + 10
    for i, line in enumerate(path_wrapped):
        color = THEME_COLORS["text_selected"] if file_exists else THEME_COLORS["error_text"]
        path_surface = config.small_font.render(line, True, color)
        path_rect = path_surface.get_rect(left=rect_x + 40, top=current_y + i * small_line_height)
        screen.blit(path_surface, path_rect)
    
    # Avertissement si fichier non trouvé
    if warning_lines:
        current_y += len(path_wrapped) * small_line_height + 10
        for i, line in enumerate(warning_lines):
            warning_surface = config.small_font.render(line, True, THEME_COLORS["error_text"])
            warning_rect = warning_surface.get_rect(left=rect_x + 40, top=current_y + i * small_line_height)
            screen.blit(warning_surface, warning_rect)
    
    # Bouton OK
    button_height = int(config.screen_height * 0.0463)
    button_width = 120
    draw_stylized_button(screen, _("button_OK"), rect_x + (rect_width - button_width) // 2, rect_y + rect_height - button_height - 20, button_width, button_height, selected=True)


def draw_history_scraper_info(screen):
    """Affiche l'information que le scraper n'est pas implémenté."""
    screen.blit(OVERLAY, (0, 0))
    
    message = _("history_scraper_not_implemented")
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
    
    button_width = 120
    draw_stylized_button(screen, _("button_OK"), rect_x + (rect_width - button_width) // 2, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=True)


def draw_history_error_details(screen):
    """Affiche les détails de l'erreur du téléchargement."""
    screen.blit(OVERLAY, (0, 0))
    
    if not config.history or config.current_history_item >= len(config.history):
        return
    
    entry = config.history[config.current_history_item]
    error_message = entry.get("message", _("history_no_error_message"))
    
    title = _("history_error_details_title")
    wrapped_error = wrap_text(error_message, config.small_font, config.screen_width - 120)
    
    line_height = config.font.get_height() + 10
    small_line_height = config.small_font.get_height() + 5
    text_height = len(wrapped_error) * small_line_height
    button_height = int(config.screen_height * 0.0463)
    margin_top_bottom = 30
    rect_height = text_height + button_height + line_height + 3 * margin_top_bottom
    max_text_width = max([config.small_font.size(line)[0] for line in wrapped_error], default=300)
    rect_width = min(max_text_width + 150, config.screen_width - 100)
    rect_x = (config.screen_width - rect_width) // 2
    rect_y = (config.screen_height - rect_height) // 2
    
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)
    
    # Titre
    title_surface = config.font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, rect_y + margin_top_bottom))
    screen.blit(title_surface, title_rect)
    
    # Message d'erreur
    for i, line in enumerate(wrapped_error):
        text = config.small_font.render(line, True, THEME_COLORS["text_selected"])
        text_rect = text.get_rect(left=rect_x + 40, top=rect_y + margin_top_bottom + line_height + 10 + i * small_line_height)
        screen.blit(text, text_rect)
    
    button_width = 120
    draw_stylized_button(screen, _("button_OK"), rect_x + (rect_width - button_width) // 2, rect_y + rect_height - button_height - 20, button_width, button_height, selected=True)


def draw_history_confirm_delete(screen):
    """Affiche la confirmation de suppression d'un jeu."""
    screen.blit(OVERLAY, (0, 0))
    
    message = _("history_confirm_delete")
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
    sel = getattr(config, 'history_delete_confirm_selection', 0)
    draw_stylized_button(screen, _("button_yes"), rect_x + rect_width // 2 - button_width - 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=sel == 1)
    draw_stylized_button(screen, _("button_no"), rect_x + rect_width // 2 + 10, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=sel == 0)


def draw_history_extract_archive(screen):
    """Affiche la confirmation d'extraction d'archive."""
    screen.blit(OVERLAY, (0, 0))
    
    if not config.history or config.current_history_item >= len(config.history):
        return
    
    entry = config.history[config.current_history_item]
    game_name = entry.get("game_name", "Unknown")
    
    message = f"Extract archive: {game_name}?"
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
    
    button_width = 120
    draw_stylized_button(screen, _("button_OK"), rect_x + (rect_width - button_width) // 2, rect_y + text_height + margin_top_bottom, button_width, button_height, selected=True)


def draw_text_file_viewer(screen):
    """Affiche le contenu d'un fichier texte avec défilement."""
    screen.blit(OVERLAY, (0, 0))
    
    # Récupérer les données du fichier texte
    content = getattr(config, 'text_file_content', '')
    filename = getattr(config, 'text_file_name', 'Unknown')
    scroll_offset = getattr(config, 'text_file_scroll_offset', 0)
    
    # Dimensions
    margin = 40
    header_height = 60
    controls_y = config.screen_height - int(config.screen_height * 0.037)
    bottom_margin = 10
    
    rect_width = config.screen_width - 2 * margin
    rect_height = controls_y - 2 * margin - bottom_margin
    rect_x = margin
    rect_y = margin
    
    content_area_y = rect_y + header_height
    content_area_height = rect_height - header_height - 20
    
    # Fond principal
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)
    
    # Titre/nom du fichier
    title_text = f"{filename}"
    title_surface = config.font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, rect_y + 30))
    screen.blit(title_surface, title_rect)
    
    # Séparateur
    pygame.draw.line(screen, THEME_COLORS["border"], (rect_x + 20, content_area_y - 10), (rect_x + rect_width - 20, content_area_y - 10), 2)
    
    # Contenu du fichier
    if content:
        # Diviser le contenu en lignes et appliquer le word wrap
        original_lines = content.split('\n')
        wrapped_lines = []
        max_width = rect_width - 60
        
        # Appliquer wrap_text à chaque ligne originale
        for original_line in original_lines:
            if original_line.strip():  # Si la ligne n'est pas vide
                wrapped = wrap_text(original_line, config.small_font, max_width)
                wrapped_lines.extend(wrapped)
            else:  # Ligne vide
                wrapped_lines.append('')
        
        line_height = config.small_font.get_height() + 2
        
        # Calculer le nombre de lignes visibles
        visible_lines = int(content_area_height / line_height)
        
        # Appliquer le scroll
        start_line = scroll_offset
        end_line = min(start_line + visible_lines, len(wrapped_lines))
        
        # Afficher les lignes visibles
        for i, line_index in enumerate(range(start_line, end_line)):
            if line_index < len(wrapped_lines):
                line = wrapped_lines[line_index]
                line_surface = config.small_font.render(line, True, THEME_COLORS["text"])
                line_rect = line_surface.get_rect(left=rect_x + 30, top=content_area_y + i * line_height)
                screen.blit(line_surface, line_rect)
        
        # Scrollbar si nécessaire
        if len(wrapped_lines) > visible_lines:
            scrollbar_height = int((visible_lines / len(wrapped_lines)) * content_area_height)
            scrollbar_y = content_area_y + int((scroll_offset / len(wrapped_lines)) * content_area_height)
            scrollbar_x = rect_x + rect_width - 15
            
            # Fond de la scrollbar
            pygame.draw.rect(screen, THEME_COLORS["border"], (scrollbar_x, content_area_y, 8, content_area_height), border_radius=4)
            # Barre de défilement
            pygame.draw.rect(screen, THEME_COLORS["button_hover"], (scrollbar_x, scrollbar_y, 8, scrollbar_height), border_radius=4)
        
        # Indicateur de position
        position_text = f"{scroll_offset + 1}-{end_line}/{len(wrapped_lines)}"
        position_surface = config.small_font.render(position_text, True, THEME_COLORS["title_text"])
        position_rect = position_surface.get_rect(right=rect_x + rect_width - 30, bottom=rect_y + rect_height - 10)
        screen.blit(position_surface, position_rect)
    else:
        # Aucun contenu
        no_content_text = "Empty file"
        no_content_surface = config.font.render(no_content_text, True, THEME_COLORS["title_text"])
        no_content_rect = no_content_surface.get_rect(center=(config.screen_width // 2, content_area_y + content_area_height // 2))
        screen.blit(no_content_surface, no_content_rect)


def draw_scraper_screen(screen):
    screen.blit(OVERLAY, (0, 0))
    
    # Dimensions de l'écran avec marge pour les contrôles en bas
    margin = 40
    # Calcul exact de la position des contrôles (même formule que draw_controls)
    controls_y = config.screen_height - int(config.screen_height * 0.037)
    bottom_margin = 10
    
    rect_width = config.screen_width - 2 * margin
    rect_height = controls_y - 2 * margin - bottom_margin
    rect_x = margin
    rect_y = margin
    
    # Fond principal
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (rect_x, rect_y, rect_width, rect_height), border_radius=12)
    pygame.draw.rect(screen, THEME_COLORS["border"], (rect_x, rect_y, rect_width, rect_height), 2, border_radius=12)
    
    # Titre
    title_text = f"Scraper: {config.scraper_game_name}"
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, rect_y + 40))
    screen.blit(title_surface, title_rect)
    
    # Sous-titre avec plateforme
    subtitle_text = f"Platform: {config.scraper_platform_name}"
    subtitle_surface = config.font.render(subtitle_text, True, THEME_COLORS["title_text"])
    subtitle_rect = subtitle_surface.get_rect(center=(config.screen_width // 2, rect_y + 80))
    screen.blit(subtitle_surface, subtitle_rect)
    
    # Zone de contenu (après titre et sous-titre)
    content_y = rect_y + 120
    content_height = rect_height - 140  # Ajusté pour ne pas inclure les marges du bas
    
    # Si chargement en cours
    if config.scraper_loading:
        loading_text = "Searching for metadata..."
        loading_surface = config.font.render(loading_text, True, THEME_COLORS["text"])
        loading_rect = loading_surface.get_rect(center=(config.screen_width // 2, config.screen_height // 2))
        screen.blit(loading_surface, loading_rect)
    
    # Si erreur
    elif config.scraper_error_message:
        error_lines = wrap_text(config.scraper_error_message, config.font, rect_width - 80)
        line_height = config.font.get_height() + 10
        start_y = config.screen_height // 2 - (len(error_lines) * line_height) // 2
        
        for i, line in enumerate(error_lines):
            error_surface = config.font.render(line, True, THEME_COLORS["error_text"])
            error_rect = error_surface.get_rect(center=(config.screen_width // 2, start_y + i * line_height))
            screen.blit(error_surface, error_rect)
    
    # Si données disponibles
    else:
        # Division en deux colonnes: image à gauche, métadonnées à droite
        left_width = int(rect_width * 0.4)
        right_width = rect_width - left_width - 20
        left_x = rect_x + 20
        right_x = left_x + left_width + 20
        
        # === COLONNE GAUCHE: IMAGE ===
        if config.scraper_image_surface:
            # Calculer la taille max pour l'image
            max_image_width = left_width - 20
            max_image_height = content_height - 20
            
            # Redimensionner l'image en conservant le ratio
            image = config.scraper_image_surface
            img_width, img_height = image.get_size()
            
            # Calculer le ratio de redimensionnement
            width_ratio = max_image_width / img_width
            height_ratio = max_image_height / img_height
            scale_ratio = min(width_ratio, height_ratio, 1.0)
            
            new_width = int(img_width * scale_ratio)
            new_height = int(img_height * scale_ratio)
            
            # Redimensionner l'image
            scaled_image = pygame.transform.smoothscale(image, (new_width, new_height))
            
            # Centrer l'image dans la colonne gauche
            image_x = left_x + (left_width - new_width) // 2
            image_y = content_y + (content_height - new_height) // 2
            
            # Fond derrière l'image
            padding = 10
            bg_rect = pygame.Rect(image_x - padding, image_y - padding, new_width + 2 * padding, new_height + 2 * padding)
            pygame.draw.rect(screen, THEME_COLORS["fond_image"], bg_rect, border_radius=8)
            pygame.draw.rect(screen, THEME_COLORS["neon"], bg_rect, 2, border_radius=8)
            
            # Afficher l'image
            screen.blit(scaled_image, (image_x, image_y))
        else:
            # Pas d'image disponible
            no_image_text = "No image available"
            no_image_surface = config.font.render(no_image_text, True, THEME_COLORS["title_text"])
            no_image_rect = no_image_surface.get_rect(center=(left_x + left_width // 2, content_y + content_height // 2))
            screen.blit(no_image_surface, no_image_rect)
        
        # === COLONNE DROITE: METADONNEES (centrées verticalement) ===
        line_height = config.font.get_height() + 8
        small_line_height = config.small_font.get_height() + 5
        
        # Calculer la hauteur totale des métadonnées pour centrer verticalement
        total_metadata_height = 0
        
        # Compter les lignes de genre
        if config.scraper_genre:
            total_metadata_height += line_height * 2 + 10  # Label + valeur + espace
        
        # Compter les lignes de date
        if config.scraper_release_date:
            total_metadata_height += line_height * 2 + 10  # Label + valeur + espace
        
        # Compter les lignes de description
        if config.scraper_description:
            desc_lines = wrap_text(config.scraper_description, config.small_font, right_width - 100)
            max_desc_lines = min(len(desc_lines), int((content_height - total_metadata_height - 100) / small_line_height))
            total_metadata_height += line_height + 5  # Label + espace
            total_metadata_height += max_desc_lines * small_line_height
        
        # Calculer le Y de départ pour centrer verticalement
        metadata_y = content_y + (content_height - total_metadata_height) // 2
        
        # Genre
        if config.scraper_genre:
            genre_label = config.font.render("Genre:", True, THEME_COLORS["neon"])
            screen.blit(genre_label, (right_x, metadata_y))
            metadata_y += line_height
            
            genre_value = config.font.render(config.scraper_genre, True, THEME_COLORS["text"])
            screen.blit(genre_value, (right_x + 10, metadata_y))
            metadata_y += line_height + 10
        
        # Date de sortie
        if config.scraper_release_date:
            date_label = config.font.render("Release Date:", True, THEME_COLORS["neon"])
            screen.blit(date_label, (right_x, metadata_y))
            metadata_y += line_height
            
            date_value = config.font.render(config.scraper_release_date, True, THEME_COLORS["text"])
            screen.blit(date_value, (right_x + 10, metadata_y))
            metadata_y += line_height + 10
        
        # Description
        if config.scraper_description:
            desc_label = config.font.render("Description:", True, THEME_COLORS["neon"])
            screen.blit(desc_label, (right_x, metadata_y))
            metadata_y += line_height + 5
            
            # Wrapper la description avec plus de padding à droite
            desc_lines = wrap_text(config.scraper_description, config.small_font, right_width - 40)
            max_desc_lines = min(len(desc_lines), int((content_height - (metadata_y - content_y)) / small_line_height))
            
            for i, line in enumerate(desc_lines[:max_desc_lines]):
                desc_surface = config.small_font.render(line, True, THEME_COLORS["text"])
                screen.blit(desc_surface, (right_x + 10, metadata_y))
                metadata_y += small_line_height
            
            # Si trop de lignes, afficher "..."
            if len(desc_lines) > max_desc_lines:
                more_text = config.small_font.render("...", True, THEME_COLORS["title_text"])
                screen.blit(more_text, (right_x + 10, metadata_y))
        
        # URL de la source en bas (si disponible)
        if config.scraper_game_page_url:
            url_text = truncate_text_middle(config.scraper_game_page_url, config.small_font, rect_width - 80, is_filename=False)
            url_surface = config.small_font.render(url_text, True, THEME_COLORS["title_text"])
            url_rect = url_surface.get_rect(center=(config.screen_width // 2, rect_y + rect_height - 20))
            screen.blit(url_surface, url_rect)


def draw_filter_menu_choice(screen):
    """Affiche le menu de choix entre recherche par nom et filtrage avancé"""
    screen.blit(OVERLAY, (0, 0))
    
    # Titre
    title = _("filter_menu_title")
    title_surface = config.title_font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, 60))
    screen.blit(title_surface, title_rect)
    
    # Options
    options = [
        _("filter_search_by_name"),
        _("filter_advanced")
    ]
    
    # Calculer hauteur dynamique basée sur la taille de police
    sample_text = config.font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    button_height = max(60, font_height + 30)
    
    # Calculer largeur maximale nécessaire pour le texte
    max_text_width = 0
    for option in options:
        text_surface = config.font.render(option, True, THEME_COLORS["text"])
        if text_surface.get_width() > max_text_width:
            max_text_width = text_surface.get_width()
    
    # Largeur du bouton basée sur le texte le plus long + marges
    button_width = max(400, max_text_width + 80)
    
    # Calculer positions
    menu_y = 150
    button_spacing = 20
    
    for i, option in enumerate(options):
        y = menu_y + i * (button_height + button_spacing)
        x = (config.screen_width - button_width) // 2
        
        # Couleur selon sélection
        if i == config.selected_filter_choice:
            color = THEME_COLORS["button_selected"]
            border_color = THEME_COLORS["border_selected"]
        else:
            color = THEME_COLORS["button_idle"]
            border_color = THEME_COLORS["border"]
        
        # Dessiner bouton
        pygame.draw.rect(screen, color, (x, y, button_width, button_height), border_radius=12)
        pygame.draw.rect(screen, border_color, (x, y, button_width, button_height), 3, border_radius=12)
        
        # Texte avec gestion du dépassement
        text_surface = config.font.render(option, True, THEME_COLORS["text"])
        available_width = button_width - 40  # Marge de 20px de chaque côté
        
        if text_surface.get_width() > available_width:
            # Tronquer le texte avec "..."
            truncated_text = option
            while text_surface.get_width() > available_width and len(truncated_text) > 0:
                truncated_text = truncated_text[:-1]
                text_surface = config.font.render(truncated_text + "...", True, THEME_COLORS["text"])
        
        text_rect = text_surface.get_rect(center=(config.screen_width // 2, y + button_height // 2))
        screen.blit(text_surface, text_rect)


def draw_filter_advanced(screen):
    """Affiche l'écran de filtrage avancé"""
    
    screen.blit(OVERLAY, (0, 0))
    
    # Initialiser le filtre si nécessaire
    if not hasattr(config, 'game_filter_obj'):
        config.game_filter_obj = GameFilters()
        # Charger depuis settings
        from rgsx_settings import load_game_filters
        filter_dict = load_game_filters()
        if filter_dict:
            config.game_filter_obj.load_from_dict(filter_dict)
    
    # Liste des options (sans les régions pour l'instant)
    options = []
    
    # Section Régions (titre seulement)
    region_title = _("filter_region_title")
    options.append(('header', region_title))
    
    # On va afficher les régions en grille 3x3, donc on ajoute des placeholders
    regions_list = []
    for region in GameFilters.REGIONS:
        region_key = f"filter_region_{region.lower()}"
        region_label = _(region_key)
        filter_state = config.game_filter_obj.region_filters.get(region, 'include')  # Par défaut: include
        
        if filter_state == 'exclude':
            status = f"[X] {_('filter_region_exclude')}"
            color = THEME_COLORS["red"]
        else:  # 'include'
            status = f"[V] {_('filter_region_include')}"
            color = THEME_COLORS["green"]
        
        regions_list.append(('region', region, f"{region_label}: {status}", color))
    
    # Ajouter les régions comme une seule entrée "grid" dans options
    options.append(('region_grid', regions_list))
    
    # Section Autres options
    options.append(('separator', ''))
    options.append(('header', _("filter_other_options")))
    
    hide_text = _("filter_hide_non_release")
    hide_status = "[X]" if config.game_filter_obj.hide_non_release else "[ ]"
    options.append(('toggle', 'hide_non_release', f"{hide_text}: {hide_status}"))
    
    one_rom_text = _("filter_one_rom_per_game")
    one_rom_status = "[X]" if config.game_filter_obj.one_rom_per_game else "[ ]"
    # Afficher les 3 premières régions de priorité
    priority_preview = " → ".join(config.game_filter_obj.region_priority[:3]) + "..."
    options.append(('toggle', 'one_rom_per_game', f"{one_rom_text}: {one_rom_status}"))
    options.append(('button_inline', 'priority_config', f"{_('filter_priority_order')}: {priority_preview}"))
    
    # Boutons d'action (seront affichés séparément en bas)
    buttons = [
        ('apply', _("filter_apply_filters")),
        ('reset', _("filter_reset_filters")),
        ('back', _("filter_back"))
    ]
    
    # Afficher les options (sans les boutons)
    if not hasattr(config, 'selected_filter_option'):
        config.selected_filter_option = 0
    
    # Calculer le nombre total d'items sélectionnables (régions individuelles + autres options + boutons)
    total_items = len(regions_list) + len([opt for opt in options if opt[0] in ['toggle', 'button_inline']]) + len(buttons)
    if config.selected_filter_option >= total_items:
        config.selected_filter_option = total_items - 1
    
    # Calculer d'abord la hauteur totale nécessaire
    # Adapter la hauteur en fonction de la taille de police
    sample_text = config.font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    line_height = max(50, font_height + 30)
    item_height = max(45, font_height + 20)
    item_spacing_y = 10
    items_per_row = 3
    
    # Titre
    title_height = 60
    
    # Hauteur du header régions
    header_height = line_height
    
    # Hauteur de la grille de régions
    num_rows = (len(regions_list) + items_per_row - 1) // items_per_row
    grid_height = num_rows * (item_height + item_spacing_y)
    
    # Hauteur du séparateur
    separator_height = 10
    
    # Hauteur du header autres options
    header2_height = line_height
    
    # Hauteur des autres options (3 options)
    num_other_options = len([opt for opt in options if opt[0] in ['toggle', 'button_inline']])
    other_options_height = num_other_options * (item_height + 10)
    
    # Hauteur des boutons
    # Adapter en fonction de la taille de police
    sample_text = config.font.render("Sample", True, THEME_COLORS["text"])
    font_height = sample_text.get_height()
    button_height = max(50, font_height + 20)
    buttons_top_margin = 30
    
    # Hauteur totale du contenu
    total_content_height = (title_height + header_height + grid_height + separator_height + 
                           header2_height + other_options_height + buttons_top_margin + button_height)
    
    # Calculer position de départ pour centrer verticalement
    control_bar_estimated_height = 80
    available_height = config.screen_height - control_bar_estimated_height
    start_y = (available_height - total_content_height) // 2
    if start_y < 20:
        start_y = 20  # Marge minimale du haut
    
    current_y = start_y
    
    # Titre
    title = _("filter_advanced_title")
    title_surface = config.title_font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, current_y + 20))
    screen.blit(title_surface, title_rect)
    current_y += title_height
    
    region_index_start = 0  # Les régions commencent à l'index 0
    
    for option in options:
        option_type = option[0]
        
        if option_type == 'header':
            # En-tête de section
            text_surface = config.font.render(option[1], True, THEME_COLORS["title_text"])
            text_rect = text_surface.get_rect(center=(config.screen_width // 2, current_y + 20))
            screen.blit(text_surface, text_rect)
            current_y += line_height
        
        elif option_type == 'separator':
            current_y += separator_height
        
        elif option_type == 'region_grid':
            # Afficher les régions en grille 3 par ligne
            regions_data = option[1]
            item_spacing_x = 20
            
            # Calculer la largeur maximale nécessaire pour les boutons de régions
            max_region_width = 0
            for region_data in regions_data:
                text = region_data[2]
                text_surface = config.font.render(text, True, THEME_COLORS["text"])
                text_width = text_surface.get_width() + 30  # Padding de 30px
                if text_width > max_region_width:
                    max_region_width = text_width
            
            # Largeur minimale de 200px
            item_width = max(max_region_width, 200)
            
            # Calculer la largeur totale de la grille
            total_grid_width = items_per_row * item_width + (items_per_row - 1) * item_spacing_x
            grid_start_x = (config.screen_width - total_grid_width) // 2
            
            for idx, region_data in enumerate(regions_data):
                row = idx // items_per_row
                col = idx % items_per_row
                
                x = grid_start_x + col * (item_width + item_spacing_x)
                y = current_y + row * (item_height + item_spacing_y)
                
                # Index global de cette région
                global_idx = region_index_start + idx
                
                # Couleur selon sélection
                if global_idx == config.selected_filter_option:
                    bg_color = THEME_COLORS["button_selected"]
                    border_color = THEME_COLORS["border_selected"]
                else:
                    bg_color = THEME_COLORS["button_idle"]
                    border_color = THEME_COLORS["border"]
                
                # Dessiner fond
                pygame.draw.rect(screen, bg_color, (x, y, item_width, item_height), border_radius=8)
                pygame.draw.rect(screen, border_color, (x, y, item_width, item_height), 2, border_radius=8)
                
                # Texte centré
                text = region_data[2]
                text_color = region_data[3]
                
                text_surface = config.font.render(text, True, text_color)
                text_rect = text_surface.get_rect(center=(x + item_width // 2, y + item_height // 2))
                screen.blit(text_surface, text_rect)
            
            # Calculer la hauteur occupée par la grille
            current_y += num_rows * (item_height + item_spacing_y) + 10
        
        elif option_type in ['toggle', 'button_inline']:
            # Option sélectionnable - largeur adaptée au texte
            text = option[2]
            text_surface = config.font.render(text, True, THEME_COLORS["text"])
            text_width = text_surface.get_width()
            
            # Largeur avec padding
            width = text_width + 40
            x = (config.screen_width - width) // 2  # Centrer
            height = item_height
            
            # Index global de cette option (après les régions)
            global_idx = len(regions_list) + len([opt for opt in options[:options.index(option)] if opt[0] in ['toggle', 'button_inline']])
            
            # Couleur selon sélection
            if global_idx == config.selected_filter_option:
                bg_color = THEME_COLORS["button_selected"]
                border_color = THEME_COLORS["border_selected"]
            else:
                bg_color = THEME_COLORS["button_idle"]
                border_color = THEME_COLORS["border"]
            
            # Dessiner fond
            pygame.draw.rect(screen, bg_color, (x, current_y, width, height), border_radius=8)
            pygame.draw.rect(screen, border_color, (x, current_y, width, height), 2, border_radius=8)
            
            # Texte centré
            text_color = THEME_COLORS["text"]
            text_rect = text_surface.get_rect(center=(x + width // 2, current_y + height // 2))
            screen.blit(text_surface, text_rect)
            
            current_y += height + 10
    
    # Afficher les 3 boutons côte à côte en bas
    current_y += buttons_top_margin
    button_y = current_y
    button_spacing = 20
    
    # Calculer la largeur de chaque bouton en fonction du texte
    button_widths = []
    for button_id, button_text in buttons:
        text_surface = config.font.render(button_text, True, THEME_COLORS["text"])
        button_widths.append(text_surface.get_width() + 40)  # Padding de 40px
    
    # Largeur totale des boutons
    total_buttons_width = sum(button_widths) + button_spacing * (len(buttons) - 1)
    button_start_x = (config.screen_width - total_buttons_width) // 2
    
    # Calculer l'index de début des boutons (après toutes les régions et autres options)
    button_index_start = len(regions_list) + num_other_options
    
    current_button_x = button_start_x
    for i, (button_id, button_text) in enumerate(buttons):
        button_index = button_index_start + i
        button_width = button_widths[i]
        
        # Couleur selon sélection
        if button_index == config.selected_filter_option:
            bg_color = THEME_COLORS["button_selected"]
            border_color = THEME_COLORS["border_selected"]
        else:
            bg_color = THEME_COLORS["button_idle"]
            border_color = THEME_COLORS["border"]
        
        # Dessiner bouton
        pygame.draw.rect(screen, bg_color, (current_button_x, button_y, button_width, button_height), border_radius=8)
        pygame.draw.rect(screen, border_color, (current_button_x, button_y, button_width, button_height), 2, border_radius=8)
        
        # Texte centré
        text_surface = config.font.render(button_text, True, THEME_COLORS["text"])
        text_rect = text_surface.get_rect(center=(current_button_x + button_width // 2, button_y + button_height // 2))
        screen.blit(text_surface, text_rect)
        
        current_button_x += button_width + button_spacing
    
    # Info filtre actif (au-dessus des boutons)
    if config.game_filter_obj.is_active():
        info_text = _("filter_active")
        info_surface = config.small_font.render(info_text, True, THEME_COLORS["green"])
        info_rect = info_surface.get_rect(center=(config.screen_width // 2, button_y - 20))
        screen.blit(info_surface, info_rect)


def draw_filter_priority_config(screen):
    """Affiche l'écran de configuration de la priorité des régions pour One ROM per game"""
    
    screen.blit(OVERLAY, (0, 0))
    
    # Titre
    title = _("filter_priority_title")
    title_surface = config.title_font.render(title, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, 40))
    screen.blit(title_surface, title_rect)
    
    # Description
    desc = _("filter_priority_desc")
    desc_surface = config.small_font.render(desc, True, THEME_COLORS["title_text"])
    desc_rect = desc_surface.get_rect(center=(config.screen_width // 2, 85))
    screen.blit(desc_surface, desc_rect)
    
    # Initialiser le filtre si nécessaire
    if not hasattr(config, 'game_filter_obj'):
        from rgsx_settings import load_game_filters
        config.game_filter_obj = GameFilters()
        filter_dict = load_game_filters()
        if filter_dict:
            config.game_filter_obj.load_from_dict(filter_dict)
    
    # Liste des régions avec leur priorité
    start_y = 130
    line_height = 60
    
    if not hasattr(config, 'selected_priority_index'):
        config.selected_priority_index = 0
    
    priority_list = config.game_filter_obj.region_priority.copy()
    
    # Afficher chaque région avec sa position
    for i, region in enumerate(priority_list):
        y = start_y + i * line_height
        x = 120
        width = config.screen_width - 240
        height = 50
        
        # Couleur selon sélection
        if i == config.selected_priority_index:
            bg_color = THEME_COLORS["button_selected"]
            border_color = THEME_COLORS["border_selected"]
        else:
            bg_color = THEME_COLORS["button_idle"]
            border_color = THEME_COLORS["border"]
        
        # Dessiner fond
        pygame.draw.rect(screen, bg_color, (x, y, width, height), border_radius=8)
        pygame.draw.rect(screen, border_color, (x, y, width, height), 2, border_radius=8)
        
        # Numéro de priorité
        priority_text = f"#{i+1}"
        priority_surface = config.font.render(priority_text, True, THEME_COLORS["text"])
        screen.blit(priority_surface, (x + 15, y + (height - priority_surface.get_height()) // 2))
        
        # Nom de la région (traduit si possible)
        region_key = f"filter_region_{region.lower()}"
        region_label = _(region_key)
        region_surface = config.font.render(region_label, True, THEME_COLORS["text"])
        screen.blit(region_surface, (x + 80, y + (height - region_surface.get_height()) // 2))
        
        # Flèches pour réorganiser (si sélectionné)
        if i == config.selected_priority_index:
            arrows_text = "← →"
            arrows_surface = config.font.render(arrows_text, True, THEME_COLORS["green"])
            screen.blit(arrows_surface, (x + width - 50, y + (height - arrows_surface.get_height()) // 2))
    
    # Boutons en bas
    control_bar_estimated_height = 80
    button_width = 300
    button_height = 50
    button_x = (config.screen_width - button_width) // 2
    button_y = config.screen_height - control_bar_estimated_height - button_height - 20
    
    # Bouton Back
    is_button_selected = config.selected_priority_index >= len(priority_list)
    bg_color = THEME_COLORS["button_selected"] if is_button_selected else THEME_COLORS["button_idle"]
    border_color = THEME_COLORS["border_selected"] if is_button_selected else THEME_COLORS["border"]
    
    pygame.draw.rect(screen, bg_color, (button_x, button_y, button_width, button_height), border_radius=8)
    pygame.draw.rect(screen, border_color, (button_x, button_y, button_width, button_height), 2, border_radius=8)
    
    back_text = _("filter_back")
    text_surface = config.font.render(back_text, True, THEME_COLORS["text"])
    text_rect = text_surface.get_rect(center=(button_x + button_width // 2, button_y + button_height // 2))
    screen.blit(text_surface, text_rect)

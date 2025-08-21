import pygame #type:ignore
import config
from rgsx_settings import load_rgsx_settings, save_rgsx_settings
from logging import getLogger
from language import _

logger = getLogger(__name__)

def load_accessibility_settings():
    """Charge les paramètres d'accessibilité depuis rgsx_settings.json."""
    
    try:
        settings = load_rgsx_settings()
        return settings.get("accessibility", {"font_scale": 1.0})
    except Exception as e:
        logger.error(f"Erreur lors du chargement des paramètres d'accessibilité: {str(e)}")
    return {"font_scale": 1.0}

def save_accessibility_settings(accessibility_settings):
    """Sauvegarde les paramètres d'accessibilité dans rgsx_settings.json."""
    
    try:
        settings = load_rgsx_settings()
        settings["accessibility"] = accessibility_settings
        save_rgsx_settings(settings)
        logger.debug(f"Paramètres d'accessibilité sauvegardés: {accessibility_settings}")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde des paramètres d'accessibilité: {str(e)}")

def draw_accessibility_menu(screen):
    """Affiche le menu d'accessibilité avec curseur pour la taille de police."""
    from display import OVERLAY, THEME_COLORS, draw_stylized_button
    
    screen.blit(OVERLAY, (0, 0))
    
    # Titre
    title_text = _("menu_accessibility")
    title_surface = config.title_font.render(title_text, True, THEME_COLORS["text"])
    title_rect = title_surface.get_rect(center=(config.screen_width // 2, config.screen_height // 4))
    
    # Fond du titre
    title_bg_rect = title_rect.inflate(40, 20)
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], title_bg_rect, border_radius=10)
    pygame.draw.rect(screen, THEME_COLORS["border"], title_bg_rect, 2, border_radius=10)
    screen.blit(title_surface, title_rect)
    
    # Curseur de taille de police
    current_scale = config.font_scale_options[config.current_font_scale_index]
    font_text = _("accessibility_font_size").format(f"{current_scale:.1f}")
    
    # Position du curseur
    cursor_y = config.screen_height // 2
    cursor_width = 400
    cursor_height = 60
    cursor_x = (config.screen_width - cursor_width) // 2
    
    # Fond du curseur
    pygame.draw.rect(screen, THEME_COLORS["button_idle"], (cursor_x, cursor_y, cursor_width, cursor_height), border_radius=10)
    pygame.draw.rect(screen, THEME_COLORS["border"], (cursor_x, cursor_y, cursor_width, cursor_height), 2, border_radius=10)
    
    # Flèches gauche/droite
    arrow_size = 30
    left_arrow_x = cursor_x + 20
    right_arrow_x = cursor_x + cursor_width - arrow_size - 20
    arrow_y = cursor_y + (cursor_height - arrow_size) // 2
    
    # Flèche gauche
    left_color = THEME_COLORS["fond_lignes"] if config.current_font_scale_index > 0 else THEME_COLORS["border"]
    pygame.draw.polygon(screen, left_color, [
        (left_arrow_x + arrow_size, arrow_y),
        (left_arrow_x, arrow_y + arrow_size // 2),
        (left_arrow_x + arrow_size, arrow_y + arrow_size)
    ])
    
    # Flèche droite
    right_color = THEME_COLORS["fond_lignes"] if config.current_font_scale_index < len(config.font_scale_options) - 1 else THEME_COLORS["border"]
    pygame.draw.polygon(screen, right_color, [
        (right_arrow_x, arrow_y),
        (right_arrow_x + arrow_size, arrow_y + arrow_size // 2),
        (right_arrow_x, arrow_y + arrow_size)
    ])
    
    # Texte au centre
    text_surface = config.font.render(font_text, True, THEME_COLORS["text"])
    text_rect = text_surface.get_rect(center=(cursor_x + cursor_width // 2, cursor_y + cursor_height // 2))
    screen.blit(text_surface, text_rect)
    
    # Instructions
    instruction_text = _("language_select_instruction")
    instruction_surface = config.small_font.render(instruction_text, True, THEME_COLORS["text"])
    instruction_rect = instruction_surface.get_rect(center=(config.screen_width // 2, config.screen_height - 100))
    screen.blit(instruction_surface, instruction_rect)

def handle_accessibility_events(event):
    """Gère les événements du menu d'accessibilité avec support clavier et manette."""
    # Gestion des touches du clavier
    if event.type == pygame.KEYDOWN:
        if event.key == pygame.K_LEFT and config.current_font_scale_index > 0:
            config.current_font_scale_index -= 1
            update_font_scale()
            return True
        elif event.key == pygame.K_RIGHT and config.current_font_scale_index < len(config.font_scale_options) - 1:
            config.current_font_scale_index += 1
            update_font_scale()
            return True
        elif event.key == pygame.K_RETURN or event.key == pygame.K_ESCAPE:
            config.menu_state = "pause_menu"
            return True
    
    # Gestion des boutons de la manette
    elif event.type == pygame.JOYBUTTONDOWN:
        if event.button == 0:  # Bouton A (valider)
            config.menu_state = "pause_menu"
            return True
        elif event.button == 1:  # Bouton B (annuler)
            config.menu_state = "pause_menu"
            return True
    
    # Gestion du D-pad
    elif event.type == pygame.JOYHATMOTION:
        if event.value == (-1, 0):  # Gauche
            if config.current_font_scale_index > 0:
                config.current_font_scale_index -= 1
                update_font_scale()
                return True
        elif event.value == (1, 0):  # Droite
            if config.current_font_scale_index < len(config.font_scale_options) - 1:
                config.current_font_scale_index += 1
                update_font_scale()
                return True
    
    # Gestion du joystick analogique (axe horizontal)
    elif event.type == pygame.JOYAXISMOTION:
        if event.axis == 0 and abs(event.value) > 0.5:  # Joystick gauche horizontal
            if event.value < -0.5 and config.current_font_scale_index > 0:  # Gauche
                config.current_font_scale_index -= 1
                update_font_scale()
                return True
            elif event.value > 0.5 and config.current_font_scale_index < len(config.font_scale_options) - 1:  # Droite
                config.current_font_scale_index += 1
                update_font_scale()
                return True
    
    return False
def update_font_scale():
    """Met à jour l'échelle de police et sauvegarde."""
    new_scale = config.font_scale_options[config.current_font_scale_index]
    config.accessibility_settings["font_scale"] = new_scale
    save_accessibility_settings(config.accessibility_settings)
    
    # Réinitialiser les polices
    config.init_font()
    config.needs_redraw = True
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
        return settings.get("accessibility", {"font_scale": 1.0, "footer_font_scale": 1.0})
    except Exception as e:
        logger.error(f"Erreur lors du chargement des paramètres d'accessibilité: {str(e)}")
    return {"font_scale": 1.0, "footer_font_scale": 1.0}

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
    """Affiche le menu d'accessibilité avec curseurs pour la taille de police générale et du footer."""
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
    
    # Déterminer quel curseur est sélectionné (0 = général, 1 = footer)
    selected_cursor = getattr(config, 'accessibility_selected_cursor', 0)
    
    # Curseur 1: Taille de police générale
    current_scale = config.font_scale_options[config.current_font_scale_index]
    font_text = _("accessibility_font_size").format(f"{current_scale:.1f}")
    
    cursor_y1 = config.screen_height // 2 - 50
    cursor_width = 400
    cursor_height = 60
    cursor_x = (config.screen_width - cursor_width) // 2
    
    # Fond du curseur 1
    cursor1_color = THEME_COLORS["fond_lignes"] if selected_cursor == 0 else THEME_COLORS["button_idle"]
    pygame.draw.rect(screen, cursor1_color, (cursor_x, cursor_y1, cursor_width, cursor_height), border_radius=10)
    border_width = 3 if selected_cursor == 0 else 2
    pygame.draw.rect(screen, THEME_COLORS["border"], (cursor_x, cursor_y1, cursor_width, cursor_height), border_width, border_radius=10)
    
    # Flèches gauche/droite pour curseur 1
    arrow_size = 30
    left_arrow_x = cursor_x + 20
    right_arrow_x = cursor_x + cursor_width - arrow_size - 20
    arrow_y1 = cursor_y1 + (cursor_height - arrow_size) // 2
    
    # Flèche gauche
    left_color = THEME_COLORS["text"] if config.current_font_scale_index > 0 else THEME_COLORS["border"]
    pygame.draw.polygon(screen, left_color, [
        (left_arrow_x + arrow_size, arrow_y1),
        (left_arrow_x, arrow_y1 + arrow_size // 2),
        (left_arrow_x + arrow_size, arrow_y1 + arrow_size)
    ])
    
    # Flèche droite
    right_color = THEME_COLORS["text"] if config.current_font_scale_index < len(config.font_scale_options) - 1 else THEME_COLORS["border"]
    pygame.draw.polygon(screen, right_color, [
        (right_arrow_x, arrow_y1),
        (right_arrow_x + arrow_size, arrow_y1 + arrow_size // 2),
        (right_arrow_x, arrow_y1 + arrow_size)
    ])
    
    # Texte au centre
    text_surface = config.font.render(font_text, True, THEME_COLORS["text"])
    text_rect = text_surface.get_rect(center=(cursor_x + cursor_width // 2, cursor_y1 + cursor_height // 2))
    screen.blit(text_surface, text_rect)
    
    # Curseur 2: Taille de police du footer
    current_footer_scale = config.footer_font_scale_options[config.current_footer_font_scale_index]
    footer_font_text = _("accessibility_footer_font_size").format(f"{current_footer_scale:.1f}")
    
    cursor_y2 = cursor_y1 + cursor_height + 20
    
    # Fond du curseur 2
    cursor2_color = THEME_COLORS["fond_lignes"] if selected_cursor == 1 else THEME_COLORS["button_idle"]
    pygame.draw.rect(screen, cursor2_color, (cursor_x, cursor_y2, cursor_width, cursor_height), border_radius=10)
    border_width = 3 if selected_cursor == 1 else 2
    pygame.draw.rect(screen, THEME_COLORS["border"], (cursor_x, cursor_y2, cursor_width, cursor_height), border_width, border_radius=10)
    
    # Flèches gauche/droite pour curseur 2
    arrow_y2 = cursor_y2 + (cursor_height - arrow_size) // 2
    
    # Flèche gauche
    left_color2 = THEME_COLORS["text"] if config.current_footer_font_scale_index > 0 else THEME_COLORS["border"]
    pygame.draw.polygon(screen, left_color2, [
        (left_arrow_x + arrow_size, arrow_y2),
        (left_arrow_x, arrow_y2 + arrow_size // 2),
        (left_arrow_x + arrow_size, arrow_y2 + arrow_size)
    ])
    
    # Flèche droite
    right_color2 = THEME_COLORS["text"] if config.current_footer_font_scale_index < len(config.footer_font_scale_options) - 1 else THEME_COLORS["border"]
    pygame.draw.polygon(screen, right_color2, [
        (right_arrow_x, arrow_y2),
        (right_arrow_x + arrow_size, arrow_y2 + arrow_size // 2),
        (right_arrow_x, arrow_y2 + arrow_size)
    ])
    
    # Texte au centre
    text_surface2 = config.font.render(footer_font_text, True, THEME_COLORS["text"])
    text_rect2 = text_surface2.get_rect(center=(cursor_x + cursor_width // 2, cursor_y2 + cursor_height // 2))
    screen.blit(text_surface2, text_rect2)
    
    # Instructions
    instruction_text = _("language_select_instruction")
    instruction_surface = config.small_font.render(instruction_text, True, THEME_COLORS["text"])
    instruction_rect = instruction_surface.get_rect(center=(config.screen_width // 2, config.screen_height - 100))
    screen.blit(instruction_surface, instruction_rect)

def handle_accessibility_events(event):
    """Gère les événements du menu d'accessibilité avec support clavier et manette."""
    # Initialiser le curseur sélectionné si non défini
    if not hasattr(config, 'accessibility_selected_cursor'):
        config.accessibility_selected_cursor = 0
    
    # Gestion des touches du clavier
    if event.type == pygame.KEYDOWN:
        # Navigation haut/bas entre les curseurs
        if event.key == pygame.K_UP:
            config.accessibility_selected_cursor = max(0, config.accessibility_selected_cursor - 1)
            config.needs_redraw = True
            return True
        elif event.key == pygame.K_DOWN:
            config.accessibility_selected_cursor = min(1, config.accessibility_selected_cursor + 1)
            config.needs_redraw = True
            return True
        # Navigation gauche/droite pour modifier les valeurs
        elif event.key == pygame.K_LEFT:
            if config.accessibility_selected_cursor == 0:
                if config.current_font_scale_index > 0:
                    config.current_font_scale_index -= 1
                    update_font_scale()
                    return True
            else:
                if config.current_footer_font_scale_index > 0:
                    config.current_footer_font_scale_index -= 1
                    update_footer_font_scale()
                    return True
        elif event.key == pygame.K_RIGHT:
            if config.accessibility_selected_cursor == 0:
                if config.current_font_scale_index < len(config.font_scale_options) - 1:
                    config.current_font_scale_index += 1
                    update_font_scale()
                    return True
            else:
                if config.current_footer_font_scale_index < len(config.footer_font_scale_options) - 1:
                    config.current_footer_font_scale_index += 1
                    update_footer_font_scale()
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
        if event.value == (0, 1):  # Haut
            config.accessibility_selected_cursor = max(0, config.accessibility_selected_cursor - 1)
            config.needs_redraw = True
            return True
        elif event.value == (0, -1):  # Bas
            config.accessibility_selected_cursor = min(1, config.accessibility_selected_cursor + 1)
            config.needs_redraw = True
            return True
        elif event.value == (-1, 0):  # Gauche
            if config.accessibility_selected_cursor == 0:
                if config.current_font_scale_index > 0:
                    config.current_font_scale_index -= 1
                    update_font_scale()
                    return True
            else:
                if config.current_footer_font_scale_index > 0:
                    config.current_footer_font_scale_index -= 1
                    update_footer_font_scale()
                    return True
        elif event.value == (1, 0):  # Droite
            if config.accessibility_selected_cursor == 0:
                if config.current_font_scale_index < len(config.font_scale_options) - 1:
                    config.current_font_scale_index += 1
                    update_font_scale()
                    return True
            else:
                if config.current_footer_font_scale_index < len(config.footer_font_scale_options) - 1:
                    config.current_footer_font_scale_index += 1
                    update_footer_font_scale()
                    return True
    
    # Gestion du joystick analogique
    elif event.type == pygame.JOYAXISMOTION:
        if event.axis == 1 and abs(event.value) > 0.5:  # Joystick vertical
            if event.value < -0.5:  # Haut
                config.accessibility_selected_cursor = max(0, config.accessibility_selected_cursor - 1)
                config.needs_redraw = True
                return True
            elif event.value > 0.5:  # Bas
                config.accessibility_selected_cursor = min(1, config.accessibility_selected_cursor + 1)
                config.needs_redraw = True
                return True
        elif event.axis == 0 and abs(event.value) > 0.5:  # Joystick horizontal
            if event.value < -0.5:  # Gauche
                if config.accessibility_selected_cursor == 0:
                    if config.current_font_scale_index > 0:
                        config.current_font_scale_index -= 1
                        update_font_scale()
                        return True
                else:
                    if config.current_footer_font_scale_index > 0:
                        config.current_footer_font_scale_index -= 1
                        update_footer_font_scale()
                        return True
            elif event.value > 0.5:  # Droite
                if config.accessibility_selected_cursor == 0:
                    if config.current_font_scale_index < len(config.font_scale_options) - 1:
                        config.current_font_scale_index += 1
                        update_font_scale()
                        return True
                else:
                    if config.current_footer_font_scale_index < len(config.footer_font_scale_options) - 1:
                        config.current_footer_font_scale_index += 1
                        update_footer_font_scale()
                        return True
    
    return False
def update_font_scale():
    """Met à jour l'échelle de police générale et sauvegarde."""
    new_scale = config.font_scale_options[config.current_font_scale_index]
    config.accessibility_settings["font_scale"] = new_scale
    save_accessibility_settings(config.accessibility_settings)
    
    # Réinitialiser les polices
    config.init_font()
    config.needs_redraw = True

def update_footer_font_scale():
    """Met à jour l'échelle de police du footer et sauvegarde."""
    new_scale = config.footer_font_scale_options[config.current_footer_font_scale_index]
    config.accessibility_settings["footer_font_scale"] = new_scale
    save_accessibility_settings(config.accessibility_settings)
    
    # Réinitialiser les polices du footer
    config.init_footer_font()
    config.needs_redraw = True
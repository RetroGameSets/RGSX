import pygame
import re
import config
import logging

logger = logging.getLogger(__name__)

def create_placeholder(width=400):
    """Crée une image de substitution pour les jeux sans vignette."""
    logger.debug(f"Création placeholder: largeur={width}")
    if config.font is None:
        # Police de secours si config.font n’est pas initialisé
        fallback_font = pygame.font.SysFont("arial", 24)
        text = fallback_font.render("No Image", True, (255, 255, 255))
    else:
        text = config.font.render("No Image", True, (255, 255, 255))
    
    height = int(150 * (width / 200))
    placeholder = pygame.Surface((width, height))
    placeholder.fill((50, 50, 50))
    text_rect = text.get_rect(center=(width // 2, height // 2))
    placeholder.blit(text, text_rect)
    return placeholder

def truncate_text_middle(text, font, max_width):
    """Tronque le texte en insérant '...' au milieu."""
    #logger.debug(f"Troncature texte au milieu : {text[:20]}..., max_width={max_width}")
    text_width = font.size(text)[0]
    if text_width <= max_width:
        return text
    ellipsis = "..."
    ellipsis_width = font.size(ellipsis)[0]
    max_text_width = max_width - ellipsis_width
    while text_width > max_text_width and len(text) > 0:
        text = text[:-1]
        text_width = font.size(text)[0]
    mid = len(text) // 2
    return text[:mid] + ellipsis + text[mid:]

def truncate_text_end(text, font, max_width):
    """Tronque le texte en supprimant '...' à la fin."""
    #logger.debug(f"Troncature texte à la fin : {text[:20]}..., max_width={max_width}")
    if font.size(text)[0] <= max_width:
        return text
    while True:
        if text and font.size(text + "...")[0] > max_width:
            text = text[:-1]
        else:
            break
    return text + "..." if text.strip() else ""

def sanitize_filename(name):
    """Sanitise les noms de fichiers en remplaçant les caractères interdits."""
   # logger.debug(f"Sanitisation du nom : {name}")
    return re.sub(r'[<>:"/\/\\|?*]', '_', name).strip()
    
def wrap_text(text, font, max_width):
    """Divise le texte en lignes pour respecter la largeur maximale."""
    words = text.split(' ')
    lines = []
    current_line = ''
    
    for word in words:
        # Tester si ajouter le mot dépasse la largeur
        test_line = current_line + (' ' if current_line else '') + word
        test_surface = font.render(test_line, True, (255, 255, 255))
        if test_surface.get_width() <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word
    
    if current_line:
        lines.append(current_line)
    
    return lines
import pygame # type: ignore
import re
import json
import os
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
    """Tronque le texte en insérant '...' au milieu, en préservant le début et la fin, sans extension de fichier."""
    # Supprimer l'extension de fichier
    text = text.rsplit('.', 1)[0] if '.' in text else text
    text_width = font.size(text)[0]
    if text_width <= max_width:
        return text
    ellipsis = "..."
    ellipsis_width = font.size(ellipsis)[0]
    max_text_width = max_width - ellipsis_width
    if max_text_width <= 0:
        return ellipsis

    # Diviser la largeur disponible entre début et fin
    chars = list(text)
    left = []
    right = []
    left_width = 0
    right_width = 0
    left_idx = 0
    right_idx = len(chars) - 1

    while left_idx <= right_idx and (left_width + right_width) < max_text_width:
        if left_idx < right_idx:
            left.append(chars[left_idx])
            left_width = font.size(''.join(left))[0]
            if left_width + right_width > max_text_width:
                left.pop()
                break
            left_idx += 1
        if left_idx <= right_idx:
            right.insert(0, chars[right_idx])
            right_width = font.size(''.join(right))[0]
            if left_width + right_width > max_text_width:
                right.pop(0)
                break
            right_idx -= 1

    # Reculer jusqu'à un espace pour éviter de couper un mot
    while left and left[-1] != ' ' and left_width + right_width > max_text_width:
        left.pop()
        left_width = font.size(''.join(left))[0] if left else 0
    while right and right[0] != ' ' and left_width + right_width > max_text_width:
        right.pop(0)
        right_width = font.size(''.join(right))[0] if right else 0

    return ''.join(left).rstrip() + ellipsis + ''.join(right).lstrip()

def truncate_text_end(text, font, max_width):
    """Tronque le texte à la fin pour qu'il tienne dans max_width avec la police donnée."""
    if not isinstance(text, str):
        logger.error(f"Texte non valide: {text}")
        return ""
    if not isinstance(font, pygame.font.Font):
        logger.error("Police non valide dans truncate_text_end")
        return text  # Retourne le texte brut si la police est invalide

    try:
        if font.size(text)[0] <= max_width:
            return text

        truncated = text
        while len(truncated) > 0 and font.size(truncated + "...")[0] > max_width:
            truncated = truncated[:-1]
        return truncated + "..." if len(truncated) < len(text) else text
    except Exception as e:
        logger.error(f"Erreur lors du rendu du texte '{text}': {str(e)}")
        return text  # Retourne le texte brut en cas d'erreur

def sanitize_filename(name):
    """Sanitise les noms de fichiers en remplaçant les caractères interdits."""
    return re.sub(r'[<>:"/\/\\|?*]', '_', name).strip()
    
def wrap_text(text, font, max_width):
    """Divise le texte en lignes pour respecter la largeur maximale, en coupant les mots longs si nécessaire."""
    if not isinstance(text, str):
        text = str(text) if text is not None else ""
    
    words = text.split(' ')
    lines = []
    current_line = ''
    
    for word in words:
        # Si le mot seul dépasse max_width, le couper caractère par caractère
        if font.render(word, True, (255, 255, 255)).get_width() > max_width:
            temp_line = current_line
            for char in word:
                test_line = temp_line + (' ' if temp_line else '') + char
                test_surface = font.render(test_line, True, (255, 255, 255))
                if test_surface.get_width() <= max_width:
                    temp_line = test_line
                else:
                    if temp_line:
                        lines.append(temp_line)
                    temp_line = char
            current_line = temp_line
        else:
            # Comportement standard pour les mots normaux
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
    
def load_system_image(platform_dict):
    """Charge une image système depuis le chemin spécifié dans system_image."""
    image_path = platform_dict.get("system_image")
    platform_name = platform_dict.get("platform", "unknown")
    #logger.debug(f"Chargement de l'image système pour {platform_name} depuis {image_path}")
    try:
        if not os.path.exists(image_path):
            logger.error(f"Image introuvable pour {platform_name} à {image_path}")
            return None
        return pygame.image.load(image_path).convert_alpha()
    except Exception as e:
        logger.error(f"Erreur lors du chargement de l'image pour {platform_name} : {str(e)}")
        return None

def load_games(platform_id):
    """Charge les jeux pour une plateforme donnée en utilisant platform_id."""
    games_path = f"/userdata/roms/ports/RGSX/games/{platform_id}.json"
    #logger.debug(f"Chargement des jeux pour {platform_id} depuis {games_path}")
    try:
        with open(games_path, 'r', encoding='utf-8') as f:
            games = json.load(f)
        return games
    except Exception as e:
        logger.error(f"Erreur lors du chargement des jeux pour {platform_id} : {str(e)}")
        return []
        
def load_json_file(path, default=None):
    """Charge un fichier JSON avec gestion d'erreur."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Erreur lors de la lecture de {path} : {e}")
        return default if default is not None else {}
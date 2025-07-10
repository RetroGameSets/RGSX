import pygame # type: ignore
import re
import json
import os
import logging
import requests

from datetime import datetime


logger = logging.getLogger(__name__)

# Liste globale pour stocker les systèmes avec une erreur 404
unavailable_systems = []

def load_games(platform_id):
    """Charge les jeux pour une plateforme donnée en utilisant platform_id et teste la première URL."""
    games_path = f"/userdata/roms/ports/RGSX/games/{platform_id}.json"
    try:
        with open(games_path, 'r', encoding='utf-8') as f:
            games = json.load(f)
        
        # Tester la première URL si la liste n'est pas vide
        if games and len(games) > 0 and len(games[0]) > 1:
            first_url = games[0][1]
            try:
                response = requests.head(first_url, timeout=5, allow_redirects=True)
                if response.status_code == 404:
                    logger.error(f"URL non accessible pour {platform_id} : {first_url} (code 404)")
                    unavailable_systems.append(platform_id)  # Ajouter à la liste globale
            except requests.RequestException as e:
                logger.error(f"Erreur lors du test de l'URL pour {platform_id} : {first_url} ({str(e)})")
        else:
            logger.debug(f"Aucune URL à tester pour {platform_id} (liste vide ou mal formée)")
        
        logger.debug(f"Jeux chargés pour {platform_id}: {len(games)} jeux")
        return games
    except Exception as e:
        logger.error(f"Erreur lors du chargement des jeux pour {platform_id} : {str(e)}")
        return []

def write_unavailable_systems():
    """Écrit la liste des systèmes avec une erreur 404 dans un fichier texte."""
    if not unavailable_systems:
        logger.debug("Aucun système avec une erreur 404, aucun fichier écrit")
        return
    
    # Formater la date et l'heure pour le nom du fichier
    current_time = datetime.now()
    timestamp = current_time.strftime("%d-%m-%Y-%H-%M")
    log_dir = "/userdata/roms/ports/logs/RGSX"
    log_file = f"{log_dir}/systemes_unavailable_{timestamp}.txt"
    
    try:
        # Créer le répertoire s'il n'existe pas
        os.makedirs(log_dir, exist_ok=True)
        
        # Écrire les systèmes dans le fichier
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write("Systèmes avec une erreur 404 :\n")
            for system in unavailable_systems:
                f.write(f"{system}\n")
        logger.debug(f"Fichier écrit : {log_file} avec {len(unavailable_systems)} systèmes")
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture du fichier {log_file} : {str(e)}")

        
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

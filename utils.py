import pygame # type: ignore
import re
import json
import os
import logging
import threading
import requests
import config
import random
import platform
import subprocess


logger = logging.getLogger(__name__)


unavailable_systems = []  # Liste globale pour stocker les systèmes avec une erreur 404

def check_url(url, platform_id, unavailable_systems_lock=None, unavailable_systems=None):
    """Vérifie si une URL est accessible via une requête HEAD."""
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        if response.status_code == 404:
            logger.error(f"URL non accessible pour {platform_id}: {url} (code 404)")
            if unavailable_systems_lock and unavailable_systems is not None:
                with unavailable_systems_lock:
                    unavailable_systems.append(platform_id)
            elif unavailable_systems is not None:
                unavailable_systems.append(platform_id)
    except requests.RequestException as e:
        logger.error(f"Erreur lors du test de l'URL pour {platform_id}: {url} ({str(e)})")
        if unavailable_systems_lock and unavailable_systems is not None:
            with unavailable_systems_lock:
                unavailable_systems.append(platform_id)
        elif unavailable_systems is not None:
            unavailable_systems.append(platform_id)

def load_games(platform_id, unavailable_systems_lock=None, unavailable_systems=None):
    """Charge les jeux pour une plateforme donnée en utilisant platform_id et teste la première URL."""
    games_path = f"/userdata/roms/ports/RGSX/games/{platform_id}.json"
    try:
        with open(games_path, 'r', encoding='utf-8') as f:
            games = json.load(f)
        
        # Tester la première URL si la liste n'est pas vide
        if games and len(games) > 0 and len(games[0]) > 1:
            first_url = games[0][1]
            check_url(first_url, platform_id, unavailable_systems_lock, unavailable_systems)
        else:
            logger.debug(f"Aucune URL à tester pour {platform_id} (liste vide ou mal formée)")
        
        logger.debug(f"Jeux chargés pour {platform_id}: {len(games)} jeux")
        return games
    except Exception as e:
        logger.error(f"Erreur lors du chargement des jeux pour {platform_id}: {str(e)}")
        return []

def write_unavailable_systems():
    """Écrit la liste des systèmes avec une erreur 404 dans un fichier texte."""
    if not unavailable_systems:
        logger.debug("Aucun système avec une erreur 404, aucun fichier écrit")
        return
    
    from datetime import datetime
    current_time = datetime.now()
    timestamp = current_time.strftime("%d-%m-%Y-%H-%M")
    log_dir = "/userdata/roms/ports/logs/RGSX"
    log_file = f"{log_dir}/systemes_unavailable_{timestamp}.txt"
    
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_file, 'w', encoding='utf-8') as f:
            f.write("Systèmes avec une erreur 404 :\n")
            for system in unavailable_systems:
                f.write(f"{system}\n")
        logger.debug(f"Fichier écrit : {log_file} avec {len(unavailable_systems)} systèmes")
    except Exception as e:
        logger.error(f"Erreur lors de l'écriture du fichier {log_file}: {str(e)}")

def load_sources():
    """Charge sources.json et les jeux pour toutes les plateformes en parallèle."""
    sources_path = "/userdata/roms/ports/RGSX/sources.json"
    logger.debug(f"Chargement de {sources_path}")
    try:
        with open(sources_path, 'r', encoding='utf-8') as f:
            sources = json.load(f)
        sources = sorted(sources, key=lambda x: x.get("nom", x.get("platform", "")).lower())
        config.platforms = [source["platform"] for source in sources]
        config.platform_dicts = sources
        config.platform_names = {source["platform"]: source["nom"] for source in sources}
        config.games_count = {platform: 0 for platform in config.platforms}

        # Créer un verrou pour unavailable_systems
        unavailable_systems_lock = threading.Lock()
        global unavailable_systems
        unavailable_systems = []

        # Lancer les chargements des jeux en parallèle avec threading
        threads = []
        results = [None] * len(config.platforms)
        for i, platform in enumerate(config.platforms):
            thread = threading.Thread(target=lambda idx=i, plat=platform: results.__setitem__(idx, load_games(plat, unavailable_systems_lock, unavailable_systems)))
            threads.append(thread)
            thread.start()
        
        # Attendre que tous les threads se terminent
        for thread in threads:
            thread.join()

        # Mettre à jour games_count avec les résultats
        for platform, games in zip(config.platforms, results):
            if games:
                config.games_count[platform] = len(games)
                logger.debug(f"Jeux chargés pour {platform}: {len(games)} jeux")
            else:
                config.games_count[platform] = 0
                logger.error(f"Échec du chargement des jeux pour {platform}")

        write_unavailable_systems()
        return sources
    except Exception as e:
        logger.error(f"Erreur lors du chargement de sources.json: {str(e)}")
        return []

# Détection système non-PC
def detect_non_pc():
    arch = platform.machine()
    try:
        result = subprocess.run(["batocera-es-swissknife", "--arch"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            arch = result.stdout.strip()
            logger.debug(f"Architecture via batocera-es-swissknife: {arch}")
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.debug(f"batocera-es-swissknife non disponible, utilisation de platform.machine(): {arch}")
    
    is_non_pc = arch not in ["x86_64", "amd64"]
    logger.debug(f"Système détecté: {platform.system()}, architecture: {arch}, is_non_pc={is_non_pc}")
    return is_non_pc

        
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

# Dossier musique Batocera
music_folder = "/userdata/roms/ports/RGSX/assets/music"
music_files = [f for f in os.listdir(music_folder) if f.lower().endswith(('.ogg', '.mp3'))]
current_music = None  # Suivre la musique en cours
loading_step = "none"

def play_random_music():
    """Joue une musique aléatoire et configure l'événement de fin."""
    global current_music
    if music_files:
        # Éviter de rejouer la même musique consécutivement
        available_music = [f for f in music_files if f != current_music]
        if not available_music:  # Si une seule musique, on la reprend
            available_music = music_files
        music_file = random.choice(available_music)
        music_path = os.path.join(music_folder, music_file)
        logger.debug(f"Lecture de la musique : {music_path}")
        pygame.mixer.music.load(music_path)
        pygame.mixer.music.set_volume(0.5)
        pygame.mixer.music.play(loops=0)  # Jouer une seule fois
        pygame.mixer.music.set_endevent(pygame.USEREVENT + 1)  # Événement de fin
        current_music = music_file  # Mettre à jour la musique en cours
        set_music_popup(music_file)  # Afficher le nom de la musique dans la popup
    else:
        logger.debug("Aucune musique trouvée dans /userdata/roms/ports/RGSX/assets/music")

def set_music_popup(music_name):
    """Définit le nom de la musique à afficher dans la popup."""
    global current_music_name, music_popup_start_time
    current_music_name = f"♬ {os.path.splitext(music_name)[0]}"  # Utilise l'emoji ♬ directement
    music_popup_start_time = pygame.time.get_ticks() / 1000  # Temps actuel en secondes


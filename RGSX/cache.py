import json
import os
import pygame
import re
import config
from utils import create_placeholder
from network import scrape_games
import logging

logger = logging.getLogger(__name__)

def load_sources():
    """Charge les sources depuis sources.json, génère les caches de jeux si nécessaire, filtre les plateformes et importe les noms d'affichage."""
    sources_file = "/userdata/roms/ports/RGSX/sources.json"
    logger.debug(f"Chargement de {sources_file}")
    
    # Créer le fichier s'il n'existe pas
    if not os.path.exists(sources_file):
        with open(sources_file, 'w') as f:
            json.dump([{"platform": "", "game": "", "url": "", "image": "", "system_image": "", "nom": ""}], f)
        logger.debug(f"Fichier sources.json créé")
    
    # Charger les sources
    with open(sources_file, 'r') as f:
        sources = json.load(f)
    
    # Créer un dictionnaire pour associer platform à nom
    platform_names_map = {s["platform"]: s.get("nom", s["platform"]) for s in sources if s["platform"]}
    
    # Extraire toutes les plateformes uniques
    all_platforms = sorted(list(set([s["platform"] for s in sources if s["platform"]])))
    
    # Générer les caches de jeux pour chaque plateforme si nécessaire
    for platform in all_platforms:
        games_path = os.path.join(config.games_cache_dir, f"{platform}.json")
        if not os.path.exists(games_path):
            logger.debug(f"Génération cache pour {platform}")
            cache_games_list(platform, sources)
    
    # Filtrer les plateformes ayant plus d'un jeu
    config.platforms = [platform for platform in all_platforms if len(load_games(platform)) > 1]
    
    # Mettre à jour config.platform_names pour les plateformes filtrées
    config.platform_names = {platform: platform_names_map.get(platform, platform) for platform in config.platforms}
    
    # Fallback si aucune plateforme valide
    if not config.platforms:
        config.platforms = ['default']
        config.platform_names = {'default': 'Default'}
        logger.warning("Aucune plateforme avec plus d'un jeu détectée, utilisation de 'default'")
    else:
        logger.debug(f"Plateformes détectées et filtrées: {config.platforms}")
        logger.debug(f"Noms d'affichage des plateformes: {config.platform_names}")
    
    return sources
def cache_system_image(platform, system_image_url):
    image_path = os.path.join(config.images_cache_dir, f"{platform}.png")
    #logger.debug(f"Vérification image pour {platform}: {image_path}")
    if os.path.exists(image_path):
        #logger.debug(f"Image déjà en cache: {image_path}")
        return image_path
    try:
        import requests
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(system_image_url, headers=headers, timeout=5)
        response.raise_for_status()
        with open(image_path, 'wb') as f:
            f.write(response.content)
        logger.debug(f"Image téléchargée et sauvegardée: {image_path}")
        return image_path
    except Exception as e:
        logger.debug(f"Erreur téléchargement image {system_image_url}: {str(e)}")
        return None

def cache_games_list(platform, sources):
    games_path = os.path.join(config.games_cache_dir, f"{platform}.json")
    #logger.debug(f"Vérification liste jeux pour {platform}: {games_path}")
    if os.path.exists(games_path):
        try:
            with open(games_path, 'r') as f:
                games_list = json.load(f)
            logger.debug(f"Liste jeux chargée depuis cache: {len(games_list)} jeux")
            return games_list
        except Exception as e:
            logger.debug(f"Erreur lecture cache {games_path}: {str(e)}")
            games_list = []
    games_list = []
    for source in sources:
        if source["platform"] == platform and "url" in source and not source.get("game"):
            games_list = [(name, url, "") for name, url in scrape_games(source["url"])]
            break
    if not games_list:
        games_list = [(s.get("game", ""), s["url"], s.get("image", "")) for s in sources if s["platform"] == platform]
    try:
        with open(games_path, 'w') as f:
            json.dump(games_list, f)
        logger.debug(f"Liste jeux sauvegardée: {games_path}, {len(games_list)} jeux")
    except Exception as e:
        logger.debug(f"Erreur sauvegarde cache {games_path}: {str(e)}")
    return games_list

def get_system_image(platform, width=None, height=None):
    """Charge une image système et la redimensionne en préservant le ratio si width ou height est fourni."""
    image_path = os.path.join(config.images_cache_dir, f"{platform}.png")
    #logger.debug(f"Recherche image système : {image_path}")
    if os.path.exists(image_path):
        try:
            image = pygame.image.load(image_path).convert_alpha()
            if width or height:
                orig_width, orig_height = image.get_size()
                if width and height:
                    # Calculer le ratio pour préserver les proportions
                    aspect_ratio = orig_width / orig_height
                    target_ratio = width / height
                    if aspect_ratio > target_ratio:
                        # Image plus large : ajuster la hauteur
                        new_height = int(width / aspect_ratio)
                        image = pygame.transform.smoothscale(image, (width, new_height))
                    else:
                        # Image plus haute : ajuster la largeur
                        new_width = int(height * aspect_ratio)
                        image = pygame.transform.smoothscale(image, (new_width, height))
                elif width:
                    # Seulement width fourni : ajuster height proportionnellement
                    new_height = int(width * (orig_height / orig_width))
                    image = pygame.transform.smoothscale(image, (width, new_height))
                elif height:
                    # Seulement height fourni : ajuster width proportionnellement
                    new_width = int(height * (orig_width / orig_height))
                    image = pygame.transform.smoothscale(image, (new_width, height))
            #logger.debug(f"Image chargée pour {platform} avec taille {image.get_size()}")
            return image
        except pygame.error as e:
            logger.debug(f"Erreur lors du chargement de l'image {image_path} : {e}")
            return None
    logger.debug(f"Image non trouvée pour {platform}")
    return None

def load_games(platform):
    games_path = os.path.join(config.games_cache_dir, f"{platform}.json")
    logger.debug(f"Chargement jeux pour {platform}: {games_path}")
    try:
        with open(games_path, 'r') as f:
            games_list = json.load(f)
        config.games_count[platform] = len(games_list)
        logger.debug(f"Jeux chargés: {len(games_list)}")
        return games_list
    except Exception as e:
        logger.debug(f"Erreur chargement jeux {games_path}: {str(e)}")
        config.games_count[platform] = 0
        return []

def load_image(path, width=200):
    logger.debug(f"Chargement image: {path}, largeur={width}")
    cache_key = f"{path}_{width}"
    if cache_key in config.images and config.images[cache_key]:
        logger.debug(f"Image en cache mémoire: {cache_key}")
        return config.images[cache_key]
    try:
        image_data = pygame.image.load(path)
        orig_width, orig_height = image_data.get_size()
        new_width = width
        new_height = int(orig_height * (new_width / orig_width))
        max_height = config.screen_height - 150
        if new_height > max_height:
            new_height = max_height
            new_width = int(orig_width * (new_height / orig_height))
        image_data = pygame.transform.scale(image_data, (new_width, new_height))
        config.images[cache_key] = image_data
        logger.debug(f"Image chargée et mise en cache: {cache_key}")
        return image_data
    except Exception as e:
        logger.debug(f"Erreur chargement image {path}: {str(e)}")
        return create_placeholder(width=width)
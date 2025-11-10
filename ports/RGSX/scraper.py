"""
Module de scraping pour récupérer les métadonnées des jeux depuis TheGamesDB.net API v1
"""
import logging
import requests
import re
from io import BytesIO
import pygame

logger = logging.getLogger(__name__)

# Clé API publique pour TheGamesDB
API_KEY = "bdbb4a1ce5f1c12c1bcc119aeb4d4923d3887e22ad336d576e9b9e5da5ecaa3c"
API_BASE_URL = "https://api.thegamesdb.net/v1"

# Mapping des noms de plateformes vers leurs IDs sur TheGamesDB API
# Documentation: https://api.thegamesdb.net/#/Platforms
PLATFORM_MAPPING = {
    # Noms exacts du systems_list.json
    "3DO Interactive Multiplayer": 25,
    "3DS": 4912,
    "Adventure Vision": 4974,
    "Amiga CD32": 4947,
    "Amiga CDTV": 4947,
    "Amiga OCS ECS": 4911,
    "Apple II": 4942,
    "Apple IIGS": 4942,
    "Arcadia 2001": 4963,
    "Archimedes": 4944,
    "Astrocade": 4968,
    "Atari 2600": 22,
    "Atari 5200": 26,
    "Atari 7800": 27,
    "Atari Lynx": 4924,
    "Atari ST": 4937,
    "Atom": 5014,
    "Channel-F": 4928,
    "ColecoVision": 31,
    "Commodore 64": 40,
    "Commodore Plus4": 5007,
    "Commodore VIC-20": 4945,
    "CreatiVision": 5005,
    "Dos (x86)": 1,
    "Dreamcast": 16,
    "Family Computer Disk System": 4936,
    "Final Burn Neo": 23,
    "FM-TOWNS": 4932,
    "Gamate": 5004,
    "Game Boy": 4,
    "Game Boy Advance": 5,
    "Game Boy Color": 41,
    "Game Cube": 2,
    "Game Gear": 20,
    "Game Master": 4948,
    "Game.com": 4940,
    "Jaguar": 28,
    "Macintosh": 37,
    "Master System": 35,
    "Mattel Intellivision": 32,
    "Mega CD": 21,
    "Mega Drive": 36,
    "Mega Duck Cougar Boy": 4948,
    "MSX1": 4929,
    "MSX2+": 4929,
    "Namco System 246 256": 23,
    "Naomi": 23,
    "Naomi 2": 23,
    "Neo-Geo CD": 4956,
    "Neo-Geo Pocket": 4922,
    "Neo-Geo Pocket Color": 4923,
    "Neo-Geo": 24,
    "Nintendo 64": 3,
    "Nintendo 64 Disk Drive": 3,
    "Nintendo DS": 8,
    "Nintendo DSi": 8,
    "Nintendo Entertainment System": 7,
    "Odyssey2": 4927,
    "PC Engine": 34,
    "PC Engine CD": 4955,
    "PC Engine SuperGrafx": 34,
    "PC-9800": 4934,
    "PlayStation": 10,
    "PlayStation 2": 11,
    "PlayStation 3": 12,
    "PlayStation Portable": 13,
    "PlayStation Vita": 39,
    "Pokemon Mini": 4957,
    "PV-1000": 4964,
    "Satellaview": 6,
    "Saturn": 17,
    "ScummVM": 1,
    "Sega 32X": 33,
    "Sega Chihiro": 23,
    "Sega Pico": 4958,
    "SG-1000": 4949,
    "Sharp X1": 4977,
    "SuFami Turbo": 6,
    "Super A'Can": 4918,
    "Super Cassette Vision": 4966,
    "Super Nintendo Entertainment System": 6,
    "Supervision": 4959,
    "Switch (1Fichier)": 4971,
    "TI-99": 4953,
    "V.Smile": 4988,
    "Vectrex": 4939,
    "Virtual Boy": 4918,
    "Wii": 9,
    "Wii (Virtual Console)": 9,
    "Wii U": 38,
    "Windows (1Fichier)": 1,
    "WonderSwan": 4925,
    "WonderSwan Color": 4926,
    "Xbox": 14,
    "Xbox 360": 15,
    "ZX Spectrum": 4913,
    "Game and Watch": 4950,
    "Nintendo Famicom Disk System": 4936,
    
    # Aliases communs (pour compatibilité)
    "3DO": 25,
    "NES": 7,
    "SNES": 6,
    "GBA": 5,
    "GBC": 41,
    "GameCube": 2,
    "N64": 3,
    "NDS": 8,
    "PSX": 10,
    "PS1": 10,
    "PS2": 11,
    "PS3": 12,
    "PSP": 13,
    "PS Vita": 39,
    "Genesis": 18,
    "32X": 33,
    "Game & Watch": 4950,
    "PC-98": 4934,
    "TurboGrafx 16": 34,
    "TurboGrafx CD": 4955,
    "Mega Duck": 4948,
    "Amiga": 4911
}


def clean_game_name(game_name):
    """
    Nettoie le nom du jeu en supprimant les extensions et tags
    
    Args:
        game_name (str): Nom brut du jeu
    
    Returns:
        str: Nom nettoyé
    """
    clean_name = game_name
    
    # Supprimer les extensions communes
    extensions = ['.zip', '.7z', '.rar', '.iso', '.chd', '.cue', '.bin', '.gdi', '.cdi', 
                  '.nsp', '.xci', '.wbfs', '.rvz', '.gcz', '.wad', '.3ds', '.cia']
    for ext in extensions:
        if clean_name.lower().endswith(ext):
            clean_name = clean_name[:-len(ext)]
    
    # Supprimer les tags entre parenthèses et crochets
    clean_name = re.sub(r'\s*[\(\[].*?[\)\]]', '', clean_name)
    
    return clean_name.strip()


def get_game_metadata(game_name, platform_name):
    """
    Récupère les métadonnées complètes d'un jeu depuis TheGamesDB.net API
    
    Args:
        game_name (str): Nom du jeu à rechercher
        platform_name (str): Nom de la plateforme
    
    Returns:
        dict: Dictionnaire contenant les métadonnées ou message d'erreur
              Keys: image_url, game_page_url, description, genre, release_date, error
    """
    clean_name = clean_game_name(game_name)
    logger.info(f"Recherche métadonnées pour: '{clean_name}' sur plateforme '{platform_name}'")
    
    # Obtenir l'ID de la plateforme
    platform_id = PLATFORM_MAPPING.get(platform_name)
    if not platform_id:
        logger.warning(f"Plateforme '{platform_name}' non trouvée dans le mapping")
        return {"error": f"Plateforme '{platform_name}' non supportée"}
    
    try:
        # Endpoint: Games/ByGameName
        # Documentation: https://api.thegamesdb.net/#/Games/GamesbyName
        url = f"{API_BASE_URL}/Games/ByGameName"
        params = {
            "apikey": API_KEY,
            "name": clean_name,
            "filter[platform]": platform_id,
            "fields": "players,publishers,genres,overview,last_updated,rating,platform,coop,youtube,os,processor,ram,hdd,video,sound,alternates",
            "include": "boxart"
        }
        
        logger.debug(f"Requête API: {url} avec name='{clean_name}', platform={platform_id}")
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code != 200:
            logger.error(f"Erreur HTTP {response.status_code}: {response.text}")
            return {"error": f"Erreur HTTP {response.status_code}"}
        
        data = response.json()
        
        # Vérifier si des résultats ont été trouvés
        if "data" not in data or "games" not in data["data"] or not data["data"]["games"]:
            logger.warning(f"Aucun résultat trouvé pour '{clean_name}'")
            return {"error": f"No result found for '{clean_name}'"}
        
        # Prendre le premier résultat (meilleure correspondance)
        games = data["data"]["games"]
        game = games[0]
        game_id = game.get("id")
        
        logger.info(f"Jeu trouvé: '{game.get('game_title')}' (ID: {game_id})")
        
        # Construire l'URL de la page du jeu
        game_page_url = f"https://thegamesdb.net/game.php?id={game_id}"
        
        # Extraire les métadonnées de base
        description = game.get("overview", "").strip() or None
        release_date = game.get("release_date", "").strip() or None
        
        # Extraire les genres
        genre = None
        if "genres" in game and game["genres"]:
            genre_ids = game["genres"]
            # Les noms des genres sont dans data.genres
            if "genres" in data["data"]:
                genre_names = []
                for gid in genre_ids:
                    if str(gid) in data["data"]["genres"]:
                        genre_names.append(data["data"]["genres"][str(gid)]["name"])
                if genre_names:
                    genre = ", ".join(genre_names)
        
        # Extraire l'image de couverture (boxart)
        # Utiliser l'endpoint dédié /v1/Games/Images pour récupérer les images du jeu
        image_url = None
        try:
            images_url = f"{API_BASE_URL}/Games/Images"
            images_params = {
                "apikey": API_KEY,
                "games_id": game_id,
                "filter[type]": "boxart"
            }
            
            logger.debug(f"Récupération des images pour game_id={game_id}")
            images_response = requests.get(images_url, params=images_params, timeout=10)
            
            if images_response.status_code == 200:
                images_data = images_response.json()
                
                # Récupérer l'URL de base
                base_url_original = ""
                if "data" in images_data and "base_url" in images_data["data"]:
                    base_url_original = images_data["data"]["base_url"].get("original", "")
                
                # Parcourir les images
                if "data" in images_data and "images" in images_data["data"]:
                    images_dict = images_data["data"]["images"]
                    
                    # Les images sont organisées par game_id
                    if str(game_id) in images_dict:
                        game_images = images_dict[str(game_id)]
                        
                        # Chercher front boxart en priorité
                        for img in game_images:
                            if img.get("type") == "boxart" and img.get("side") == "front":
                                filename = img.get("filename")
                                if filename:
                                    image_url = f"{base_url_original}{filename}"
                                    logger.info(f"Image front trouvée: {image_url}")
                                    break
                        
                        # Si pas de front, prendre n'importe quelle boxart
                        if not image_url:
                            for img in game_images:
                                if img.get("type") == "boxart":
                                    filename = img.get("filename")
                                    if filename:
                                        image_url = f"{base_url_original}{filename}"
                                        logger.info(f"Image boxart trouvée: {image_url}")
                                        break
                        
                        # Si toujours rien, prendre la première image
                        if not image_url and game_images:
                            filename = game_images[0].get("filename")
                            if filename:
                                image_url = f"{base_url_original}{filename}"
                                logger.info(f"Première image trouvée: {image_url}")
            else:
                logger.warning(f"Erreur lors de la récupération des images: HTTP {images_response.status_code}")
        
        except Exception as img_error:
            logger.warning(f"Erreur lors de la récupération des images: {img_error}")
        
        # Construire le résultat
        result = {
            "image_url": image_url,
            "game_page_url": game_page_url,
            "description": description,
            "genre": genre,
            "release_date": release_date
        }
        
        logger.info(f"Métadonnées récupérées: image={bool(image_url)}, desc={bool(description)}, genre={bool(genre)}, date={bool(release_date)}")
        
        return result
    
    except requests.RequestException as e:
        logger.error(f"Erreur lors de la requête API: {str(e)}")
        return {"error": f"Erreur réseau: {str(e)}"}
    except Exception as e:
        logger.error(f"Erreur inattendue: {str(e)}", exc_info=True)
        return {"error": f"Erreur: {str(e)}"}


def download_image_to_surface(image_url):
    """
    Télécharge une image depuis une URL et la convertit en surface Pygame
    
    Args:
        image_url (str): URL de l'image à télécharger
    
    Returns:
        pygame.Surface ou None: Surface Pygame contenant l'image, ou None en cas d'erreur
    """
    try:
        logger.debug(f"Téléchargement de l'image: {image_url}")
        response = requests.get(image_url, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Erreur HTTP {response.status_code} lors du téléchargement de l'image")
            return None
        
        # Charger l'image depuis les bytes
        image_data = BytesIO(response.content)
        image_surface = pygame.image.load(image_data)
        logger.info("Image téléchargée et chargée avec succès")
        return image_surface
    
    except Exception as e:
        logger.error(f"Erreur lors du téléchargement de l'image: {str(e)}")
        return None

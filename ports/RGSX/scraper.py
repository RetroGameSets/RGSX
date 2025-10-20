"""
Module de scraping pour récupérer les métadonnées des jeux depuis TheGamesDB.net
"""
import logging
import requests
import re
from io import BytesIO
import pygame

logger = logging.getLogger(__name__)

# Mapping des noms de plateformes vers leurs IDs sur TheGamesDB
# Les noms correspondent exactement à ceux utilisés dans systems_list.json
PLATFORM_MAPPING = {
    # Noms exacts du systems_list.json
    "3DO Interactive Multiplayer": "25",
    "3DS": "4912",
    "Adventure Vision": "4974",
    "Amiga CD32": "4947",
    "Amiga CDTV": "4947",  # Même ID que CD32
    "Amiga OCS ECS": "4911",
    "Apple II": "4942",
    "Apple IIGS": "4942",  # Même famille
    "Arcadia 2001": "4963",
    "Archimedes": "4944",
    "Astrocade": "4968",
    "Atari 2600": "22",
    "Atari 5200": "26",
    "Atari 7800": "27",
    "Atari Lynx": "4924",
    "Atari ST": "4937",
    "Atom": "5014",
    "Channel-F": "4928",
    "ColecoVision": "31",
    "Commodore 64": "40",
    "Commodore Plus4": "5007",
    "Commodore VIC-20": "4945",
    "CreatiVision": "5005",
    "Dos (x86)": "1",
    "Dreamcast": "16",
    "Family Computer Disk System": "4936",
    "Final Burn Neo": "23",  # Arcade
    "FM-TOWNS": "4932",
    "Gamate": "5004",
    "Game Boy": "4",
    "Game Boy Advance": "5",
    "Game Boy Color": "41",
    "Game Cube": "2",
    "Game Gear": "20",
    "Game Master": "4948",  # Mega Duck
    "Game.com": "4940",
    "Jaguar": "28",
    "Macintosh": "37",
    "Master System": "35",
    "Mattel Intellivision": "32",
    "Mega CD": "21",
    "Mega Drive": "36",
    "Mega Duck Cougar Boy": "4948",
    "MSX1": "4929",
    "MSX2+": "4929",
    "Namco System 246 256": "23",  # Arcade
    "Naomi": "23",  # Arcade
    "Naomi 2": "23",  # Arcade
    "Neo-Geo CD": "4956",
    "Neo-Geo Pocket": "4922",
    "Neo-Geo Pocket Color": "4923",
    "Neo-Geo": "24",
    "Nintendo 64": "3",
    "Nintendo 64 Disk Drive": "3",
    "Nintendo DS": "8",
    "Nintendo DSi": "8",
    "Nintendo Entertainment System": "7",
    "Odyssey2": "4927",
    "PC Engine": "34",
    "PC Engine CD": "4955",
    "PC Engine SuperGrafx": "34",
    "PC-9800": "4934",
    "PlayStation": "10",
    "PlayStation 2": "11",
    "PlayStation 3": "12",
    "PlayStation Portable": "13",
    "PlayStation Vita": "39",
    "Pokemon Mini": "4957",
    "PV-1000": "4964",
    "Satellaview": "6",  # SNES addon
    "Saturn": "17",
    "ScummVM": "1",  # PC
    "Sega 32X": "33",
    "Sega Chihiro": "23",  # Arcade
    "Sega Pico": "4958",
    "SG-1000": "4949",
    "Sharp X1": "4977",
    "SuFami Turbo": "6",  # SNES addon
    "Super A'Can": "4918",  # Pas d'ID exact, utilise Virtual Boy
    "Super Cassette Vision": "4966",
    "Super Nintendo Entertainment System": "6",
    "Supervision": "4959",
    "Switch (1Fichier)": "4971",
    "TI-99": "4953",
    "V.Smile": "4988",
    "Vectrex": "4939",
    "Virtual Boy": "4918",
    "Wii": "9",
    "Wii (Virtual Console)": "9",
    "Wii U": "38",
    "Windows (1Fichier)": "1",
    "WonderSwan": "4925",
    "WonderSwan Color": "4926",
    "Xbox": "14",
    "Xbox 360": "15",
    "ZX Spectrum": "4913",
    "Game and Watch": "4950",
    "Nintendo Famicom Disk System": "4936",
    
    # Aliases communs (pour compatibilité)
    "3DO": "25",
    "NES": "7",
    "SNES": "6",
    "GBA": "5",
    "GBC": "41",
    "GameCube": "2",
    "N64": "3",
    "NDS": "8",
    "PSX": "10",
    "PS1": "10",
    "PS2": "11",
    "PS3": "12",
    "PSP": "13",
    "PS Vita": "39",
    "Genesis": "18",
    "32X": "33",
    "Game & Watch": "4950",
    "PC-98": "4934",
    "TurboGrafx 16": "34",
    "TurboGrafx CD": "4955",
    "Mega Duck": "4948",
    "Amiga": "4911"
}


def get_game_metadata(game_name, platform_name):
    """
    Récupère les métadonnées complètes d'un jeu depuis TheGamesDB.net
    
    Args:
        game_name (str): Nom du jeu à rechercher
        platform_name (str): Nom de la plateforme
    
    Returns:
        dict: Dictionnaire contenant les métadonnées ou message d'erreur
              Keys: image_url, game_page_url, description, genre, release_date, error
    """
    # Nettoyer le nom du jeu
    clean_game_name = game_name
    for ext in ['.zip', '.7z', '.rar', '.iso', '.chd', '.cue', '.bin', '.gdi', '.cdi']:
        if clean_game_name.lower().endswith(ext):
            clean_game_name = clean_game_name[:-len(ext)]
    clean_game_name = re.sub(r'\s*[\(\[].*?[\)\]]', '', clean_game_name)
    clean_game_name = clean_game_name.strip()
    
    logger.info(f"Recherche métadonnées pour: '{clean_game_name}' sur plateforme '{platform_name}'")
    
    # Obtenir l'ID de la plateforme
    platform_id = PLATFORM_MAPPING.get(platform_name)
    if not platform_id:
        return {"error": f"Plateforme '{platform_name}' non supportée"}
    
    # Construire l'URL de recherche
    base_url = "https://thegamesdb.net/search.php"
    params = {
        "name": clean_game_name,
        "platform_id[]": platform_id
    }
    
    try:
        # Envoyer la requête GET pour la recherche
        logger.debug(f"Recherche sur TheGamesDB: {base_url} avec params={params}")
        response = requests.get(base_url, params=params, timeout=10)
        
        if response.status_code != 200:
            return {"error": f"Erreur HTTP {response.status_code}"}
        
        html_content = response.text
        
        # Trouver la première carte avec class 'card border-primary'
        card_start = html_content.find('div class="card border-primary"')
        if card_start == -1:
            return {"error": "Aucun résultat trouvé"}
        
        # Extraire l'URL de la page du jeu
        href_match = re.search(r'<a href="(\.\/game\.php\?id=\d+)">', html_content[card_start-100:card_start+500])
        game_page_url = None
        if href_match:
            game_page_url = f"https://thegamesdb.net/{href_match.group(1)[2:]}"  # Enlever le ./
            logger.info(f"Page du jeu trouvée: {game_page_url}")
        
        # Extraire l'URL de l'image
        img_start = html_content.find('<img class="card-img-top"', card_start)
        image_url = None
        if img_start != -1:
            src_match = re.search(r'src="([^"]+)"', html_content[img_start:img_start+200])
            if src_match:
                image_url = src_match.group(1)
                if not image_url.startswith("https://"):
                    image_url = f"https://thegamesdb.net{image_url}"
                logger.info(f"Image trouvée: {image_url}")
        
        # Extraire la date de sortie depuis les résultats de recherche
        release_date = None
        card_footer_start = html_content.find('class="card-footer', card_start)
        if card_footer_start != -1:
            # Chercher une date au format YYYY-MM-DD
            date_match = re.search(r'<p>(\d{4}-\d{2}-\d{2})</p>', html_content[card_footer_start:card_footer_start+300])
            if date_match:
                release_date = date_match.group(1)
                logger.info(f"Date de sortie trouvée: {release_date}")
        
        # Si on a l'URL de la page, récupérer la description et le genre
        description = None
        genre = None
        if game_page_url:
            try:
                logger.debug(f"Récupération de la page du jeu: {game_page_url}")
                game_response = requests.get(game_page_url, timeout=10)
                
                if game_response.status_code == 200:
                    game_html = game_response.text
                    
                    # Extraire la description
                    desc_match = re.search(r'<p class="game-overview">(.*?)</p>', game_html, re.DOTALL)
                    if desc_match:
                        description = desc_match.group(1).strip()
                        # Nettoyer les entités HTML
                        description = description.replace('&#039;', "'")
                        description = description.replace('&quot;', '"')
                        description = description.replace('&amp;', '&')
                        logger.info(f"Description trouvée ({len(description)} caractères)")
                    
                    # Extraire le genre
                    genre_match = re.search(r'<p>Genre\(s\): (.*?)</p>', game_html)
                    if genre_match:
                        genre = genre_match.group(1).strip()
                        logger.info(f"Genre trouvé: {genre}")
            
            except Exception as e:
                logger.warning(f"Erreur lors de la récupération de la page du jeu: {e}")
        
        # Construire le résultat
        result = {
            "image_url": image_url,
            "game_page_url": game_page_url,
            "description": description,
            "genre": genre,
            "release_date": release_date
        }
        
        # Vérifier qu'on a au moins quelque chose
        if not any([image_url, description, genre]):
            result["error"] = "Métadonnées incomplètes"
        
        return result
    
    except requests.RequestException as e:
        logger.error(f"Erreur lors de la requête: {str(e)}")
        return {"error": f"Erreur réseau: {str(e)}"}


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

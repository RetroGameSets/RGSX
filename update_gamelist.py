import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GAMELIST_FILE = "/userdata/roms/ports/gamelist.xml"
RGSX_ENTRY = {
    "path": "./RGSX/RGSX.sh",
    "name": "RGSX",
    "desc": "Retro Games Sets X - Games Downloader",
    "image": "./images/RGSX.png",
    "video": "./videos/RGSX.mp4"
    "marquee": "./images/RGSX.png",
    "thumbnail": "./images/RGSX.png",
    "fanart": "./images/RGSX.png",
    "rating": "1",
    "releasedate": "20250620T165718",
    "developer": "RetroGameSets.fr",
    "genre": "Compilation, Various / Utilities",
    "playcount": "666",
    "lastplayed": "20250621T234656",
    "gametime": "9999999",
    "lang": "fr"
}

def update_gamelist():
    try:
        # Si le fichier n'existe pas, est vide ou non valide, créer une nouvelle structure
        if not os.path.exists(GAMELIST_FILE) or os.path.getsize(GAMELIST_FILE) == 0:
            logger.info(f"Création de {GAMELIST_FILE}")
            root = ET.Element("gameList")
        else:
            try:
                logger.info(f"Lecture de {GAMELIST_FILE}")
                tree = ET.parse(GAMELIST_FILE)
                root = tree.getroot()
                if root.tag != "gameList":
                    logger.info(f"{GAMELIST_FILE} n'a pas de balise <gameList>, création d'une nouvelle structure")
                    root = ET.Element("gameList")
            except ET.ParseError:
                logger.info(f"{GAMELIST_FILE} est invalide, création d'une nouvelle structure")
                root = ET.Element("gameList")

        # Supprimer l'ancienne entrée RGSX
        for game in root.findall("game"):
            path = game.find("path")
            if path is not None and path.text == "./RGSX/RGSX.sh":
                root.remove(game)
                logger.info("Ancienne entrée RGSX supprimée")

        # Ajouter la nouvelle entrée
        game_elem = ET.SubElement(root, "game")
        for key, value in RGSX_ENTRY.items():
            elem = ET.SubElement(game_elem, key)
            elem.text = value
        logger.info("Nouvelle entrée RGSX ajoutée")

        # Générer le XML avec minidom pour une indentation correcte
        rough_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
        parsed = xml.dom.minidom.parseString(rough_string)
        pretty_xml = parsed.toprettyxml(indent="\t", encoding='utf-8').decode('utf-8')
        # Supprimer les lignes vides inutiles générées par minidom
        pretty_xml = '\n'.join(line for line in pretty_xml.split('\n') if line.strip())
        with open(GAMELIST_FILE, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
        logger.info(f"{GAMELIST_FILE} mis à jour avec succès")

        # Définir les permissions
        os.chmod(GAMELIST_FILE, 0o644)

    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour de {GAMELIST_FILE}: {e}")
        raise
        
def load_gamelist(path):
    """Charge le fichier gamelist.xml."""
    try:
        tree = ET.parse(path)
        return tree.getroot()
    except (FileNotFoundError, ET.ParseError) as e:
        logging.error(f"Erreur lors de la lecture de {path} : {e}")
        return None

if __name__ == "__main__":
    update_gamelist()
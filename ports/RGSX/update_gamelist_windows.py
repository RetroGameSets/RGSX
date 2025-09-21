import os
import xml.dom.minidom
import xml.etree.ElementTree as ET
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


RGSX_ENTRY = {
    "path": "./RGSX Retrobat.bat",
    "name": "RGSX",
    "desc": "Retro Games Sets X - Games Downloader",
    "image": "./images/RGSX.png",
    "video": "./videos/RGSX.mp4",
    "marquee": "./images/RGSX.png",
    "thumbnail": "./images/RGSX.png",
    "fanart": "./images/RGSX.png",
    "releasedate": "20250620T165718",
    "developer": "RetroGameSets.fr",
    "genre": "Various / Utilities"
}


def update_gamelist():
    try:
        from config import GAMELISTXML_WINDOWS
        # Si le fichier n'existe pas, est vide ou non valide, créer une nouvelle structure
        if not os.path.exists(GAMELISTXML_WINDOWS) or os.path.getsize(GAMELISTXML_WINDOWS) == 0:
            logger.info(f"Création de {GAMELISTXML_WINDOWS}")
            root = ET.Element("gameList")
        else:
            try:
                logger.info(f"Lecture de {GAMELISTXML_WINDOWS}")
                tree = ET.parse(GAMELISTXML_WINDOWS)
                root = tree.getroot()
                if root.tag != "gameList":
                    logger.info(f"{GAMELISTXML_WINDOWS} n'a pas de balise <gameList>, création d'une nouvelle structure")
                    root = ET.Element("gameList")
            except ET.ParseError:
                logger.info(f"{GAMELISTXML_WINDOWS} est invalide, création d'une nouvelle structure")
                root = ET.Element("gameList")

        # Rechercher une entrée existante pour ce chemin
        game_elem = None
        for game in root.findall("game"):
            path = game.find("path")
            if path is not None and path.text == RGSX_ENTRY["path"]:
                game_elem = game
                break

        if game_elem is None:
            # Créer une nouvelle entrée si absente
            game_elem = ET.SubElement(root, "game")
            for key, value in RGSX_ENTRY.items():
                elem = ET.SubElement(game_elem, key)
                elem.text = value
            logger.info("Nouvelle entrée RGSX ajoutée")
        # else:
        #     # Fusionner: préserver les champs gérés par ES, compléter/mettre à jour nos champs
        #     def ensure(tag, value):
        #         elem = game_elem.find(tag)
        #         if elem is None:
        #             elem = ET.SubElement(game_elem, tag)
        #         if elem.text is None or elem.text.strip() == "":
        #             elem.text = value

        #     # S'assurer du chemin
        #     ensure("path", RGSX_ENTRY["path"])
        #     # Ne pas écraser le nom s'il existe déjà (ES peut le définir selon le fichier)
        #     name_elem = game_elem.find("name")
        #     existing_name = ""
        #     if name_elem is not None and name_elem.text:
        #         existing_name = name_elem.text.strip()
        #     if not existing_name:
        #         ensure("name", RGSX_ENTRY.get("name", "RGSX"))

        #     # Champs d'habillage que nous voulons imposer/mettre à jour
        #     for tag in ("desc", "image", "video", "marquee", "thumbnail", "fanart", "developer", "genre", "releasedate"):
        #         val = RGSX_ENTRY.get(tag)
        #         if val:
        #             elem = game_elem.find(tag)
        #             if elem is None:
        #                 elem = ET.SubElement(game_elem, tag)
        #             # Toujours aligner ces champs sur nos valeurs pour garder l'expérience RGSX
        #             elem.text = val

        #     # Ne pas toucher aux champs: playcount, lastplayed, gametime, lang, favorite, kidgame, hidden, rating
        #     logger.info("Entrée RGSX mise à jour (fusion)")

        # Générer le XML avec minidom pour une indentation correcte
        rough_string = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding='unicode')
        parsed = xml.dom.minidom.parseString(rough_string)
        pretty_xml = parsed.toprettyxml(indent="\t", encoding='utf-8').decode('utf-8')
        # Supprimer les lignes vides inutiles générées par minidom
        pretty_xml = '\n'.join(line for line in pretty_xml.split('\n') if line.strip())
        with open(GAMELISTXML_WINDOWS, 'w', encoding='utf-8') as f:
            f.write(pretty_xml)
        logger.info(f"{GAMELISTXML_WINDOWS} mis à jour avec succès")

        # Définir les permissions
        try:
            os.chmod(GAMELISTXML_WINDOWS, 0o644)
        except Exception:
            # Sur Windows, chmod peut être partiel; ignorer silencieusement
            pass

    except Exception as e:
        logger.error(f"Erreur lors de la mise à jour de la gamelist Windows: {e}")
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
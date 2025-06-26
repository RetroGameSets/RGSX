import os
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROM_DIR = "/userdata/roms"
OUTPUT_JSON = "/userdata/roms/ports/RGSX/rom_extensions.json"
INFO_FILE = "_info.txt"
EXTENSIONS_KEY = "ROM files extensions accepted:"

def get_system_name(info_file_path):
    """Extrait le nom du système depuis la première ligne de _info.txt."""
    try:
        with open(info_file_path, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
            # Supprimer les caractères décoratifs et le préfixe "SYSTEM "
            system_name = first_line.strip('#').strip('-').strip().replace("SYSTEM ", "")
            if system_name:
                return system_name
            logger.warning(f"Nom du système vide dans {info_file_path}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors de la lecture du nom du système dans {info_file_path}: {e}")
        return None

def get_extensions(info_file_path):
    """Extrait les extensions de la ligne 'ROM files extensions accepted:'."""
    try:
        with open(info_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if EXTENSIONS_KEY in line:
                    # Extraire la partie après la clé
                    extensions = line.split(EXTENSIONS_KEY)[-1].strip()
                    # Supprimer les guillemets et séparer les extensions
                    extensions = [ext.strip().strip('"').lower() for ext in extensions.replace(',', ' ').split() if ext.strip()]
                    return extensions
        logger.warning(f"Aucune ligne '{EXTENSIONS_KEY}' trouvée dans {info_file_path}")
        return []
    except Exception as e:
        logger.error(f"Erreur lors de la lecture des extensions dans {info_file_path}: {e}")
        return []

def generate_rom_extensions():
    """Parcourt les dossiers dans ROM_DIR et génère un fichier JSON avec les systèmes et extensions."""
    systems = []
    
    try:
        # Parcourir tous les dossiers dans ROM_DIR
        for folder in os.listdir(ROM_DIR):
            folder_path = os.path.join(ROM_DIR, folder)
            if os.path.isdir(folder_path):
                info_file_path = os.path.join(folder_path, INFO_FILE)
                if os.path.isfile(info_file_path):
                    system_name = get_system_name(info_file_path)
                    extensions = get_extensions(info_file_path)
                    if system_name and extensions:
                        systems.append({
                            "system": system_name,
                            "folder": folder_path,
                            "extensions": extensions
                        })
                        logger.info(f"Système {system_name} ajouté avec extensions {extensions} depuis {folder_path}")
                    else:
                        logger.warning(f"Ignorer {folder_path}: nom du système ou extensions manquants")
                else:
                    logger.info(f"Aucun fichier {INFO_FILE} trouvé dans {folder_path}")
        
        # Générer le fichier JSON
        with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
            json.dump(systems, f, indent=2, ensure_ascii=False)
        logger.info(f"Fichier JSON généré avec succès à {OUTPUT_JSON}")

        # Définir les permissions
        os.chmod(OUTPUT_JSON, 0o644)

    except Exception as e:
        logger.error(f"Erreur lors de la génération du fichier JSON: {e}")
        raise

if __name__ == "__main__":
    generate_rom_extensions()
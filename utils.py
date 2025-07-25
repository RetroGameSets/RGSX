import shutil
import pygame # type: ignore
import re
import json
import os
import logging
import platform
import subprocess
import config
import threading
import zipfile
import time
import random
import random
from config import JSON_EXTENSIONS, SAVE_FOLDER
from history import save_history
from language import _  # Import de la fonction de traduction
from datetime import datetime

from datetime import datetime


logger = logging.getLogger(__name__)
# Désactiver les logs DEBUG de urllib3 e requests pour supprimer les messages de connexion HTTP
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# Liste globale pour stocker les systèmes avec une erreur 404
unavailable_systems = []


# Détection système non-PC
def detect_non_pc():
    arch = platform.machine()
    try:
        result = subprocess.run(["batocera-es-swissknife", "--arch"], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            arch = result.stdout.strip()
            #logger.debug(f"Architecture via batocera-es-swissknife: {arch}")
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.debug(f"batocera-es-swissknife non disponible, utilisation de platform.machine(): {arch}")
    
    is_non_pc = arch not in ["x86_64", "amd64"]
    logger.debug(f"Système détecté: {platform.system()}, architecture: {arch}, is_non_pc={is_non_pc}")
    return is_non_pc


# Fonction pour charger le fichier JSON des extensions supportées
def load_extensions_json():
    """Charge le fichier JSON contenant les extensions supportées."""
    try:
        with open(JSON_EXTENSIONS, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de {JSON_EXTENSIONS}: {e}")
        return []
    
def check_extension_before_download(url, platform, game_name):
    """Vérifie l'extension avant de lancer le téléchargement et retourne un tuple de 4 éléments."""
    try:
        sanitized_name = sanitize_filename(game_name)
        extensions_data = load_extensions_json()
        if not extensions_data:
            logger.error(f"Fichier {JSON_EXTENSIONS} vide ou introuvable")
            return None

        is_supported = is_extension_supported(sanitized_name, platform, extensions_data)
        extension = os.path.splitext(sanitized_name)[1].lower()
        is_archive = extension in (".zip", ".rar")

        if is_supported:
            logger.debug(f"L'extension de {sanitized_name} est supportée pour {platform}")
            return (url, platform, game_name, False)
        elif is_archive:
            logger.debug(f"Archive {extension.upper()} détectée pour {sanitized_name}, extraction automatique prévue")
            return (url, platform, game_name, True)
        else:
            logger.debug(f"Extension non supportée ({extension}) pour {sanitized_name}, avertissement affiché")
            return (url, platform, game_name, False)
    except Exception as e:
        logger.error(f"Erreur vérification extension {url}: {str(e)}")
        return None

# Fonction pour vérifier si l'extension est supportée pour une plateforme donnée
def is_extension_supported(filename, platform, extensions_data):
    """Vérifie si l'extension du fichier est supportée pour la plateforme donnée."""
    extension = os.path.splitext(filename)[1].lower()
    dest_dir = None
    for platform_dict in config.platform_dicts:
        if platform_dict["platform"] == platform:
            dest_dir = os.path.join(config.ROMS_FOLDER, platform_dict.get("folder", platform.lower().replace(" ", "")))
            break
    if not dest_dir:
        logger.warning(f"Aucun dossier 'folder' trouvé pour la plateforme {platform}")
        dest_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), platform)
    for system in extensions_data:
        if system["folder"] == dest_dir:
            return extension in system["extensions"]
    logger.warning(f"Aucun système trouvé pour le dossier {dest_dir}")
    return False




# Fonction pour charger sources.json
def load_sources():
    """Charge les sources depuis sources.json et initialise les plateformes."""
    sources_path = os.path.join(config.APP_FOLDER, "sources.json")
    logger.debug(f"Chargement de {sources_path}")
    try:
        with open(sources_path, 'r', encoding='utf-8') as f:
            sources = json.load(f)
        sources = sorted(sources, key=lambda x: x.get("nom", x.get("platform", "")).lower())
        config.platforms = [source["platform"] for source in sources]
        config.platform_dicts = sources
        config.platform_names = {source["platform"]: source["nom"] for source in sources}
        config.games_count = {platform: 0 for platform in config.platforms}  # Initialiser à 0
        # Charger les jeux pour chaque plateforme
        loaded_platforms = set()  # Pour suivre les plateformes déjà loguées
        for platform in config.platforms:
            games = load_games(platform)
            config.games_count[platform] = len(games)
            if platform not in loaded_platforms:
                loaded_platforms.add(platform)
        # Appeler write_unavailable_systems une seule fois après la boucle
        write_unavailable_systems()  # Assurez-vous que cette fonction est définie
        return sources
    except Exception as e:
        logger.error(f"Erreur lors du chargement de sources.json : {str(e)}")
        return []

def load_games(platform_id):
    """Charge les jeux pour une plateforme donnée en utilisant platform_id et teste la première URL."""
    games_path = os.path.join(config.APP_FOLDER, "games", f"{platform_id}.json")
    #logger.debug(f"Chargement des jeux pour {platform_id} depuis {games_path}")
    try:
        with open(games_path, 'r', encoding='utf-8') as f:
            games = json.load(f)
        
        #  Tester la première URL si la liste n'est pas vide
        # if games and len(games) > 0 and len(games[0]) > 1:
        #     first_url = games[0][1]
        #     try:
        #         response = requests.head(first_url, timeout=5, allow_redirects=True)
        #         if response.status_code not in (200, 303):  # Ne logger que les codes autres que 200 et 303
        #             logger.debug(f"https://{first_url} \"HEAD {first_url} HTTP/1.1\" {response.status_code} 0")
        #         if response.status_code == 404:
        #             logger.error(f"URL non accessible pour {platform_id} : {first_url} (code 404)")
        #             unavailable_systems.append(platform_id)  # Assurez-vous que unavailable_systems est défini
        #     except requests.RequestException as e:
        #         logger.error(f"Erreur lors du test de l'URL pour {platform_id} : {first_url} ({str(e)})")
        # else:
        #     logger.debug(f"Aucune URL à tester pour {platform_id} (liste vide ou mal formée)")
        
        logger.debug(f"Jeux chargés pour {platform_id}: {len(games)} jeux")
        return games
    except Exception as e:
        logger.error(f"Erreur lors du chargement des jeux pour {platform_id} : {str(e)}")
        return []

def write_unavailable_systems():
    """Écrit la liste des systèmes avec une erreur 404 dans un fichier texte."""
    if not unavailable_systems:
        logger.debug("Aucun système avec des liens HS, rien à écrire dans le fichier.")
        return
    
    # Formater la date et l'heure pour le nom du fichier
    current_time = datetime.now()
    timestamp = current_time.strftime("%d-%m-%Y-%H-%M")
    log_dir = os.path.join(os.path.dirname(config.APP_FOLDER), "logs", "RGSX")
    log_file = os.path.join(log_dir, f"systemes_unavailable_{timestamp}.txt")
    
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

def truncate_text_middle(text, font, max_width, is_filename=True):
    """Tronque le texte en insérant '...' au milieu, en préservant le début et la fin.
    Si is_filename=False, ne supprime pas l'extension."""
    # Supprimer l'extension uniquement si is_filename est True
    if is_filename:
        text = text.rsplit('.', 1)[0] if '.' in text else text
    text_width = font.size(text)[0]
    if text_width <= max_width:
        return text
    ellipsis = "..."
    ellipsis_width = font.size(ellipsis)[0]
    max_text_width = max_width - ellipsis_width
    if max_text_width <= 0:
        return ellipsis

    # Diviser la largeur disponible entre début et fin, en priorisant la fin
    chars = list(text)
    left = []
    right = []
    left_width = 0
    right_width = 0
    left_idx = 0
    right_idx = len(chars) - 1

    # Préserver plus de caractères à droite pour garder le '%'
    while left_idx <= right_idx and (left_width + right_width) < max_text_width:
        # Ajouter à droite en priorité
        if left_idx <= right_idx:
            right.insert(0, chars[right_idx])
            right_width = font.size(''.join(right))[0]
            if left_width + right_width > max_text_width:
                right.pop(0)
                break
            right_idx -= 1
        # Ajouter à gauche seulement si nécessaire
        if left_idx < right_idx:
            left.append(chars[left_idx])
            left_width = font.size(''.join(left))[0]
            if left_width + right_width > max_text_width:
                left.pop()
                break
            left_idx += 1

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
    image_path = os.path.join(config.IMAGES_FOLDER, platform_dict.get("system_image", "default.png"))
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

def extract_zip_data(zip_path, dest_dir, url):
    """Extrait le contenu du fichier ZIP  dans le dossier config.APP_FOLDER sans progression a l'ecran"""
    logger.debug(f"Extraction de {zip_path} dans {dest_dir}")
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.testzip()  # Vérifier l'intégrité de l'archive
            for info in zip_ref.infolist():
                if info.is_dir():
                    continue
                file_path = os.path.join(dest_dir, info.filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with zip_ref.open(info) as source, open(file_path, 'wb') as dest:
                    shutil.copyfileobj(source, dest)
        logger.info(f"Extraction terminée de {zip_path}")
        return True, "Extraction terminée avec succès"
    except zipfile.BadZipFile as e:
        logger.error(f"Erreur: Archive ZIP corrompue: {str(e)}")
        return False, _("utils_corrupt_zip").format(str(e))

    

def extract_zip(zip_path, dest_dir, url):
    """Extrait le contenu du fichier ZIP dans le dossier cible avec un suivi progressif de la progression."""
    logger.debug(f"Extraction de {zip_path} dans {dest_dir}")
    try:
        lock = threading.Lock()
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.testzip()  # Vérifier l'intégrité de l'archive
            total_size = sum(info.file_size for info in zip_ref.infolist() if not info.is_dir())
            logger.info(f"Taille totale à extraire: {total_size} octets")
            if total_size == 0:
                logger.warning("ZIP vide ou ne contenant que des dossiers")
                return True, "ZIP vide extrait avec succès"

            extracted_size = 0
            os.makedirs(dest_dir, exist_ok=True)
            chunk_size = 2048  # Réduire pour plus de mises à jour
            last_save_time = time.time()
            save_interval = 0.5  # Sauvegarder toutes les 0.5 secondes
            for info in zip_ref.infolist():
                if info.is_dir():
                    continue
                file_path = os.path.join(dest_dir, info.filename)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with zip_ref.open(info) as source, open(file_path, 'wb') as dest:
                    file_size = info.file_size
                    file_extracted = 0
                    while True:
                        chunk = source.read(chunk_size)
                        if not chunk:
                            break
                        dest.write(chunk)
                        file_extracted += len(chunk)
                        extracted_size += len(chunk)
                        current_time = time.time()
                        with lock:
                            # Vérifier si config.history est une liste avant d'itérer
                            if isinstance(config.history, list):
                                for entry in config.history:
                                    # Vérifier si l'entrée a les clés nécessaires et correspond à notre téléchargement
                                    if "status" in entry and entry["status"] in ["Téléchargement", "Extracting", "downloading"]:
                                        # Chercher par URL si disponible
                                        if "url" in entry and entry["url"] == url:
                                            # Calculer le pourcentage correctement et le limiter entre 0 et 100
                                            progress_percent = int(extracted_size / total_size * 100) if total_size > 0 else 0
                                            progress_percent = max(0, min(100, progress_percent))
                                            
                                            entry["status"] = "Extracting"
                                            entry["progress"] = progress_percent
                                            entry["message"] = "Extraction en cours"
                                            
                                            if current_time - last_save_time >= save_interval:
                                                save_history(config.history)
                                                last_save_time = current_time
                                                logger.debug(f"Extraction en cours: {info.filename}, file_extracted={file_extracted}/{file_size}, total_extracted={extracted_size}/{total_size}, progression={progress_percent:.1f}%")
                                            
                                            config.needs_redraw = True
                                            break
                os.chmod(file_path, 0o644)

        for root, dirs, files in os.walk(dest_dir):
            for dir_name in dirs:
                os.chmod(os.path.join(root, dir_name), 0o755)

        try:
            os.remove(zip_path)
            logger.info(f"Fichier ZIP {zip_path} extrait dans {dest_dir} et supprimé")
            
            # Mettre à jour le statut final dans l'historique
            if isinstance(config.history, list):
                for entry in config.history:
                    if "status" in entry and entry["status"] == "Extracting":
                        entry["status"] = "Download_OK"
                        entry["progress"] = 100
                        # Utiliser une variable intermédiaire pour stocker le message
                        message_text = _("utils_extracted").format(os.path.basename(zip_path))
                        entry["message"] = message_text
                        save_history(config.history)
                        config.needs_redraw = True
                        break
            
            return True, _("utils_extracted").format(os.path.basename(zip_path))
        except Exception as e:
            logger.error(f"Erreur lors de la finalisation de l'extraction: {str(e)}")
            return True, _("utils_extracted").format(os.path.basename(zip_path))
    except zipfile.BadZipFile as e:
        logger.error(f"Erreur: Archive ZIP corrompue: {str(e)}")
        return False, _("utils_corrupt_zip").format(str(e))
    except PermissionError as e:
        logger.error(f"Erreur: Permission refusée lors de l'extraction: {str(e)}")
        return False, _("utils_permission_denied").format(str(e))
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de {zip_path}: {str(e)}")
        return False, _("utils_extraction_failed").format(str(e))
     

# Fonction pour extraire le contenu d'un fichier RAR
def extract_rar(rar_path, dest_dir, url):
    """Extrait le contenu du fichier RAR dans le dossier cible, préservant la structure des dossiers."""
    try:
        lock = threading.Lock()
        os.makedirs(dest_dir, exist_ok=True)
        
        result = subprocess.run(['unrar'], capture_output=True, text=True)
        if result.returncode not in [0, 1]:
            logger.error("Commande unrar non disponible")
            return False, _("utils_unrar_unavailable")

        result = subprocess.run(['unrar', 'l', '-v', rar_path], capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            logger.error(f"Erreur lors de la liste des fichiers RAR: {error_msg}")
            return False, _("utils_rar_list_failed").format(error_msg)

        logger.debug(f"Sortie brute de 'unrar l -v {rar_path}':\n{result.stdout}")

        total_size = 0
        files_to_extract = []
        root_dirs = set()
        lines = result.stdout.splitlines()
        in_file_list = False
        for line in lines:
            if line.startswith("----"):
                in_file_list = not in_file_list
                continue
            if in_file_list:
                match = re.match(r'^\s*(\S+)\s+(\d+)\s+\d*\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s+(.+)$', line)
                if match:
                    attrs = match.group(1)
                    file_size = int(match.group(2))
                    file_date = match.group(3)
                    file_name = match.group(4).strip()
                    if 'D' not in attrs:
                        files_to_extract.append((file_name, file_size))
                        total_size += file_size
                        root_dir = file_name.split('/')[0] if '/' in file_name else ''
                        if root_dir:
                            root_dirs.add(root_dir)
                        logger.debug(f"Ligne parsée: {file_name}, taille: {file_size}, date: {file_date}")
                    else:
                        logger.debug(f"Dossier ignoré: {file_name}")
                else:
                    logger.debug(f"Ligne ignorée (format inattendu): {line}")

        logger.info(f"Taille totale à extraire (RAR): {total_size} octets")
        logger.debug(f"Fichiers à extraire: {files_to_extract}")
        logger.debug(f"Dossiers racines détectés: {root_dirs}")
        if total_size == 0:
            logger.warning("RAR vide, ne contenant que des dossiers, ou erreur de parsing")
            return False, "RAR vide ou erreur lors de la liste des fichiers"

        try:
            with lock:
                # Vérifier si l'URL existe dans config.download_progress
                if url not in config.download_progress:
                    config.download_progress[url] = {}
                config.download_progress[url]["downloaded_size"] = 0
                config.download_progress[url]["total_size"] = total_size
                config.download_progress[url]["status"] = "Extracting"
                config.download_progress[url]["progress_percent"] = 0
                config.needs_redraw = True
        except Exception as e:
            logger.error(f"Erreur lors de la mise à jour de la progression: {str(e)}")
            # Continuer l'extraction même en cas d'erreur de mise à jour de la progression

        escaped_rar_path = rar_path.replace(" ", "\\ ")
        escaped_dest_dir = dest_dir.replace(" ", "\\ ")
        process = subprocess.Popen(['unrar', 'x', '-y', escaped_rar_path, escaped_dest_dir], 
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            logger.error(f"Erreur lors de l'extraction de {rar_path}: {stderr}")
            return False, f"Erreur lors de l'extraction: {stderr}"

        extracted_size = 0
        extracted_files = []
        total_files = len(files_to_extract)
        for i, (expected_file, file_size) in enumerate(files_to_extract):
            file_path = os.path.join(dest_dir, expected_file)
            if os.path.exists(file_path):
                extracted_size += file_size
                extracted_files.append(expected_file)
                os.chmod(file_path, 0o644)
                logger.debug(f"Fichier extrait: {expected_file}, taille: {file_size}, chemin: {file_path}")
                try:
                    with lock:
                        if url in config.download_progress:
                            config.download_progress[url]["downloaded_size"] = extracted_size
                            config.download_progress[url]["status"] = "Extracting"
                            config.download_progress[url]["progress_percent"] = ((i + 1) / total_files * 100) if total_files > 0 else 0
                            config.needs_redraw = True
                except Exception as e:
                    logger.error(f"Erreur lors de la mise à jour de la progression d'extraction: {str(e)}")
                    # Continuer l'extraction même en cas d'erreur de mise à jour de la progression
            else:
                logger.warning(f"Fichier non trouvé après extraction: {expected_file}")

        missing_files = [f for f, _ in files_to_extract if f not in extracted_files]
        if missing_files:
            logger.warning(f"Fichiers non extraits: {', '.join(missing_files)}")
            return False, f"Fichiers non extraits: {', '.join(missing_files)}"

        ps3_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), "ps3")
        if dest_dir == ps3_dir and len(root_dirs) == 1:
            root_dir = root_dirs.pop()
            old_path = os.path.join(dest_dir, root_dir)
            new_path = os.path.join(dest_dir, f"{root_dir}.ps3")
            if os.path.isdir(old_path):
                try:
                    os.rename(old_path, new_path)
                    logger.info(f"Dossier renommé: {old_path} -> {new_path}")
                except Exception as e:
                    logger.error(f"Erreur lors du renommage de {old_path} en {new_path}: {str(e)}")
                    return False, f"Erreur lors du renommage du dossier: {str(e)}"
            else:
                logger.warning(f"Dossier racine {old_path} non trouvé après extraction")
        elif dest_dir == ps3_dir and len(root_dirs) > 1:
            logger.warning(f"Plusieurs dossiers racines détectés dans l'archive: {root_dirs}. Aucun renommage effectué.")

        for root, dirs, files in os.walk(dest_dir):
            for dir_name in dirs:
                os.chmod(os.path.join(root, dir_name), 0o755)

        os.remove(rar_path)
        logger.info(f"Fichier RAR {rar_path} extrait dans {dest_dir} et supprimé")
        return True, "RAR extrait avec succès"
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de {rar_path}: {str(e)}")
        # Ne pas renvoyer l'URL comme message d'erreur
        return False, f"Erreur lors de l'extraction: {str(e)}"
    finally:
        if os.path.exists(rar_path):
            try:
                os.remove(rar_path)
                logger.info(f"Fichier RAR {rar_path} supprimé après échec de l'extraction")
            except Exception as e:
                logger.error(f"Erreur lors de la suppression de {rar_path}: {str(e)}")

def play_random_music(music_files, music_folder, current_music=None):
    """Joue une musique aléatoire et configure l'événement de fin."""
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
        set_music_popup(music_file)  # Afficher le nom de la musique dans la popup
        return music_file  # Retourner la nouvelle musique pour mise à jour
    else:
        logger.debug("Aucune musique trouvée dans /RGSX/assets/music")
        return current_music

def set_music_popup(music_name):
    """Définit le nom de la musique à afficher dans la popup."""
    global current_music_name, music_popup_start_time
    current_music_name = f"♬ {os.path.splitext(music_name)[0]}"  # Utilise l'emoji ♬ directement
    music_popup_start_time = pygame.time.get_ticks() / 1000  # Temps actuel en secondes

def load_api_key_1fichier():
    """Charge la clé API 1fichier depuis le dossier de sauvegarde, crée le fichier si absent."""
    api_path = os.path.join(SAVE_FOLDER, "1fichierAPI.txt")
    try:
        # Vérifie si le fichier existe déjà 
        if not os.path.exists(api_path):
            # Crée le fichier vide si absent
            with open(api_path, "w") as f:
                f.write("")
            logger.info(f"Fichier de clé API créé : {api_path}")
    except OSError as e:
        logger.error(f"Erreur lors de la création du fichier de clé API : {e}")
        return ""
    # Lit la clé API depuis le fichier
    try:
        with open(api_path, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
        logger.debug(f"Clé API 1fichier chargée : {api_key}")
        if not api_key:
            logger.warning("Clé API 1fichier vide, veuillez la renseigner dans le fichier pour pouvoir utiliser les fonctionnalités de téléchargement sur 1fichier.")
        return api_key
    except OSError as e:
        logger.error(f"Erreur lors de la lecture de la clé API : {e}")
        return ""
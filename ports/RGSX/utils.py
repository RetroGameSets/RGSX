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
from config import JSON_EXTENSIONS, SAVE_FOLDER
from history import save_history
from language import _  # Import de la fonction de traduction
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
    
    is_non_pc = arch not in ["x86_64", "amd64", "AMD64"]
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
            dest_dir = os.path.join(config.ROMS_FOLDER, platform_dict.get("folder"))
            break
    
    if not dest_dir:
        logger.warning(f"Aucun dossier 'folder' trouvé pour la plateforme {platform}")
        dest_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), platform)
    
    dest_folder_name = os.path.basename(dest_dir)
    for i, system in enumerate(extensions_data):
        if system["folder"] == dest_folder_name:
            result = extension in system["extensions"]
            return result
    
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
            lock = threading.Lock()
            # Lister les ISO avant extraction
            iso_before = set()
            for root, dirs, files in os.walk(dest_dir):
                for file in files:
                    if file.lower().endswith('.iso'):
                        iso_before.add(os.path.abspath(os.path.join(root, file)))

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
                                if isinstance(config.history, list):
                                    for entry in config.history:
                                        if "status" in entry and entry["status"] in ["Téléchargement", "Extracting", "downloading"]:
                                            if "url" in entry and entry["url"] == url:
                                                progress_percent = int(extracted_size / total_size * 100) if total_size > 0 else 0
                                                progress_percent = max(0, min(100, progress_percent))
                                                entry["status"] = "Extracting"
                                                entry["progress"] = progress_percent
                                                entry["message"] = "Extraction en cours"
                                                if current_time - last_save_time >= save_interval:
                                                    save_history(config.history)
                                                    last_save_time = current_time
                                                config.needs_redraw = True
                                                break
                    os.chmod(file_path, 0o644)
            # Vérifier si c'est un dossier xbox et le traiter si nécessaire
            xbox_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), "xbox")
            if dest_dir == xbox_dir:
                # Lister les ISO après extraction
                iso_after = set()
                for root, dirs, files in os.walk(dest_dir):
                    for file in files:
                        if file.lower().endswith('.iso'):
                            iso_after.add(os.path.abspath(os.path.join(root, file)))
                new_isos = list(iso_after - iso_before)
                if new_isos:
                    success, error_msg = handle_xbox(dest_dir, new_isos)
                    if not success:
                        return False, error_msg
                else:
                    logger.warning("Aucun nouvel ISO détecté après extraction pour conversion Xbox.")
                    # On ne retourne pas d'erreur fatale ici, on continue

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
    """Extrait le contenu du fichier RAR dans le dossier cible."""
    try:
        lock = threading.Lock()
        os.makedirs(dest_dir, exist_ok=True)

        system_type = platform.system()
        if system_type == "Windows":
            # Sur Windows, utiliser directement config.UNRAR_EXE
            unrar_exe = config.UNRAR_EXE
            if not os.path.exists(unrar_exe):
                logger.warning("unrar.exe absent, téléchargement en cours...")
                try:
                    import urllib.request
                    os.makedirs(os.path.dirname(unrar_exe), exist_ok=True)
                    urllib.request.urlretrieve(config.unrar_download_exe, unrar_exe)
                    logger.info(f"unrar.exe téléchargé dans {unrar_exe}")
                except Exception as e:
                    logger.error(f"Impossible de télécharger unrar.exe: {str(e)}")
                    return False, _("utils_unrar_unavailable")
            unrar_cmd = [unrar_exe]
        else:
            # Linux/Batocera: utiliser 'unrar' du système
            unrar_cmd = ["unrar"]

        # Reste du code pour la vérification de unrar
        result = subprocess.run(unrar_cmd, capture_output=True, text=True)
        if result.returncode not in [0, 1]:
            logger.error("Commande unrar non disponible")
            return False, _("utils_unrar_unavailable")

        result = subprocess.run(unrar_cmd + ['l', '-v', rar_path], capture_output=True, text=True)
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
        process = subprocess.Popen(unrar_cmd + ['x', '-y', escaped_rar_path, escaped_dest_dir],
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
       
        # Vérifier si c'est un dossier PS3 et le traiter si nécessaire
        ps3_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), "ps3")
        if dest_dir == ps3_dir:
            success, error_msg = handle_ps3(dest_dir)
            if not success:
                return False, error_msg

        for root, dirs, files in os.walk(dest_dir):
            for dir_name in dirs:
                os.chmod(os.path.join(root, dir_name), 0o755)

        os.remove(rar_path)
        logger.info(f"Fichier RAR {rar_path} extrait dans {dest_dir} et supprimé")
        return True, "RAR extrait avec succès"
        
    except Exception as e:
        logger.error(f"Erreur lors de l'extraction de {rar_path}: {str(e)}")
        return False, f"Erreur lors de l'extraction: {str(e)}"
    finally:
        if os.path.exists(rar_path):
            try:
                os.remove(rar_path)
                logger.info(f"Fichier RAR {rar_path} supprimé après échec de l'extraction")
            except Exception as e:
                logger.error(f"Erreur lors de la suppression de {rar_path}: {str(e)}")

def handle_ps3(dest_dir):
    """Gère le renommage spécifique des dossiers PS3 extraits."""
    logger.debug(f"Traitement spécifique PS3 dans: {dest_dir}")
    
    # Attendre un peu que tous les processus d'extraction se terminent
    time.sleep(2)
    
    # Rechercher le dossier extrait directement dans dest_dir
    extracted_dirs = [d for d in os.listdir(dest_dir) if os.path.isdir(os.path.join(dest_dir, d))]
    logger.debug(f"Dossiers trouvés dans {dest_dir}: {extracted_dirs}")
    
    # Filtrer pour ne garder que les dossiers nouvellement extraits
    ps3_dirs = [d for d in extracted_dirs if not d.endswith('.ps3')]
    logger.debug(f"Dossiers PS3 à renommer: {ps3_dirs}")
    
    if len(ps3_dirs) == 1:
        old_path = os.path.join(dest_dir, ps3_dirs[0])
        new_path = os.path.join(dest_dir, f"{ps3_dirs[0]}.ps3")
        logger.debug(f"Tentative de renommage PS3: {old_path} -> {new_path}")
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                # Fermer les handles potentiellement ouverts
                for root, dirs, files in os.walk(old_path):
                    for f in files:
                        try:
                            os.chmod(os.path.join(root, f), 0o644)
                        except (OSError, PermissionError):
                            pass
                    for d in dirs:
                        try:
                            os.chmod(os.path.join(root, d), 0o755)
                        except (OSError, PermissionError):
                            pass

                if os.path.exists(new_path):
                    shutil.rmtree(new_path, ignore_errors=True)
                    time.sleep(1)

                os.rename(old_path, new_path)
                logger.info(f"Dossier renommé avec succès: {old_path} -> {new_path}")
                return True, None
                
            except Exception as e:
                logger.warning(f"Tentative {attempt + 1}/{max_retries} échouée: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    error_msg = f"Erreur lors du renommage de {old_path} en {new_path}: {str(e)}"
                    logger.error(error_msg)
                    return False, error_msg
                    
    elif len(ps3_dirs) > 1:
        logger.warning(f"Plusieurs dossiers PS3 détectés: {ps3_dirs}")
        return True, None
    else:
        logger.warning("Aucun dossier PS3 à renommer trouvé")
        return True, None


def handle_xbox(dest_dir, iso_files):
    """Gère la conversion des fichiers Xbox extraits."""
    logger.debug(f"Traitement spécifique Xbox dans: {dest_dir}")
    
    # Attendre un peu que tous les processus d'extraction se terminent
    time.sleep(2)
    system_type = platform.system()
    if system_type == "Windows":
        # Sur Windows; telecharger le fichier exe
        XDVDFS_EXE = config.XDVDFS_EXE
        if not os.path.exists(XDVDFS_EXE):
            logger.warning("xdvdfs.exe absent, téléchargement en cours...")
            try:
                import urllib.request
                os.makedirs(os.path.dirname(XDVDFS_EXE), exist_ok=True)
                urllib.request.urlretrieve(config.xdvdfs_download_exe, XDVDFS_EXE)
                logger.info(f"xdvdfs.exe téléchargé dans {XDVDFS_EXE}")
            except Exception as e:
                logger.error(f"Impossible de télécharger xdvdfs.exe: {str(e)}")
                return False, _("utils_xdvdfs_unavailable")
        xdvdfs_cmd = [XDVDFS_EXE, "pack"]  # Liste avec 2 éléments

    else:
        # Linux/Batocera : télécharger le fichier xdvdfs  
        XDVDFS_LINUX = config.XDVDFS_LINUX
        if not os.path.exists(XDVDFS_LINUX):
            logger.warning("xdvdfs non trouvé, téléchargement en cours...")
            try:
                import urllib.request
                os.makedirs(os.path.dirname(XDVDFS_LINUX), exist_ok=True)
                urllib.request.urlretrieve(config.xdvdfs_download_linux, XDVDFS_LINUX)
                os.chmod(XDVDFS_LINUX, 0o755)  # Rendre exécutable
                logger.info(f"xdvdfs téléchargé dans {XDVDFS_LINUX}")
            except Exception as e:
                logger.error(f"Impossible de télécharger xdvdfs: {str(e)}")
                return False, _("utils_xdvdfs_unavailable")    # Vérifier les permissions après le téléchargement
        try:
            stat_info = os.stat(XDVDFS_LINUX)
            mode = stat_info.st_mode
            logger.debug(f"Permissions de {XDVDFS_LINUX}: {oct(mode)}")
            logger.debug(f"Propriétaire: {stat_info.st_uid}, Groupe: {stat_info.st_gid}")
            
            # Vérifier si le fichier est exécutable
            if not os.access(XDVDFS_LINUX, os.X_OK):
                logger.error(f"Le fichier {XDVDFS_LINUX} n'est pas exécutable")
                try:
                    os.chmod(XDVDFS_LINUX, 0o755)
                    logger.info(f"Permissions corrigées pour {XDVDFS_LINUX}")
                except Exception as e:
                    logger.error(f"Impossible de modifier les permissions: {str(e)}")
                    return False, "Erreur de permissions sur xdvdfs"
        except Exception as e:
            logger.error(f"Erreur lors de la vérification des permissions: {str(e)}")
    
        xdvdfs_cmd = [XDVDFS_LINUX, "pack"]  # Liste avec 2 éléments

    try:
        # Chercher les fichiers ISO à convertir
        iso_files = []
        for root, dirs, files in os.walk(dest_dir):
            for file in files:
                if file.lower().endswith('.iso'):
                    iso_files.append(os.path.join(root, file))

        if not iso_files:
            logger.warning("Aucun fichier ISO xbox trouvé")
            return True, None

        for iso_xbox_source in iso_files:
            logger.debug(f"Traitement de l'ISO Xbox: {iso_xbox_source}")
            xiso_dest = os.path.splitext(iso_xbox_source)[0] + "_xbox.iso"

            # Construction de la commande avec des arguments distincts
            cmd = xdvdfs_cmd + [iso_xbox_source, xiso_dest]
            logger.debug(f"Exécution de la commande: {' '.join(cmd)}")
            
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            if process.returncode != 0:
                logger.error(f"Erreur lors de la conversion de l'ISO: {process.stderr}")
                return False, f"Erreur lors de la conversion de l'ISO: {process.stderr}"

            # Vérifier que l'ISO converti a été créé
            if os.path.exists(xiso_dest):
                logger.info(f"ISO converti avec succès: {xiso_dest}")
                # Remplacer l'ISO original par l'ISO converti
                os.remove(iso_xbox_source)
                os.rename(xiso_dest, iso_xbox_source)
                logger.debug(f"ISO original remplacé par la version convertie")
            else:
                logger.error(f"L'ISO converti n'a pas été créé: {xiso_dest}")
                return False, "Échec de la conversion de l'ISO"

        return True, "Conversion Xbox terminée avec succès"

    except Exception as e:
        logger.error(f"Erreur lors de la conversion Xbox: {str(e)}")
        return False, f"Erreur lors de la conversion: {str(e)}"



def play_random_music(music_files, music_folder, current_music=None):
    if not getattr(config, "music_enabled", True):
        pygame.mixer.music.stop()
        return current_music
    if music_files:
        # Éviter de rejouer la même musique consécutivement
        available_music = [f for f in music_files if f != current_music]
        if not available_music:  # Si une seule musique, on la reprend
            available_music = music_files
        music_file = random.choice(available_music)
        music_path = os.path.join(music_folder, music_file)
        logger.debug(f"Lecture de la musique : {music_path}")
        
        def load_and_play_music():
            try:
                pygame.mixer.music.load(music_path)
                pygame.mixer.music.set_volume(0.5)
                pygame.mixer.music.play(loops=0)  # Jouer une seule fois
                pygame.mixer.music.set_endevent(pygame.USEREVENT + 1)  # Événement de fin
                set_music_popup(music_file)  # Afficher le nom de la musique dans la popup
            except Exception as e:
                logger.error(f"Erreur lors du chargement de la musique {music_path}: {str(e)}")
        
        # Charger et jouer la musique dans un thread séparé pour éviter le blocage
        music_thread = threading.Thread(target=load_and_play_music, daemon=True)
        music_thread.start()
        
        return music_file  # Retourner la nouvelle musique pour mise à jour
    else:
        logger.debug("Aucune musique trouvée dans /RGSX/assets/music")
        return current_music

def set_music_popup(music_name):
    """Définit le nom de la musique à afficher dans la popup."""
    config.current_music_name = f"♬ {os.path.splitext(music_name)[0]}"  # Utilise l'emoji ♬ directement
    config.music_popup_start_time = pygame.time.get_ticks() / 1000  # Temps actuel en secondes
    config.needs_redraw = True  # Forcer le redraw pour afficher le nom de la musique

def load_api_key_1fichier():
    """Charge la clé API 1fichier depuis le dossier de sauvegarde, crée le fichier si absent."""
    api_path = os.path.join(SAVE_FOLDER, "1fichierAPI.txt")
    logger.debug(f"Tentative de chargement de la clé API depuis: {api_path}")
    try:
        # Vérifie si le fichier existe déjà 
        if not os.path.exists(api_path):
            # Crée le dossier parent si nécessaire
            os.makedirs(SAVE_FOLDER, exist_ok=True)
            # Crée le fichier vide si absent
            with open(api_path, "w") as f:
                f.write("")
            logger.info(f"Fichier de clé API créé : {api_path}")
            return ""
    except OSError as e:
        logger.error(f"Erreur lors de la création du fichier de clé API : {e}")
        return ""
    # Lit la clé API depuis le fichier
    try:
        with open(api_path, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
        logger.debug(f"Clé API 1fichier lue: '{api_key}' (longueur: {len(api_key)})")
        if not api_key:
            logger.warning("Clé API 1fichier vide, veuillez la renseigner dans le fichier pour pouvoir utiliser les fonctionnalités de téléchargement sur 1fichier.")
        config.API_KEY_1FICHIER = api_key
        return api_key
    except OSError as e:
        logger.error(f"Erreur lors de la lecture de la clé API : {e}")
        return ""

def load_music_config():
    """Charge la configuration musique depuis music_config.json."""
    path = config.MUSIC_CONFIG_PATH
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config.music_enabled = data.get("music_enabled", True)
                return config.music_enabled
    except Exception as e:
        logger.error(f"Erreur lors du chargement de music_config.json: {str(e)}")
    config.music_enabled = True
    return True

def save_music_config():
    """Sauvegarde la configuration musique dans music_config.json."""
    path = config.MUSIC_CONFIG_PATH
    try:
        os.makedirs(config.SAVE_FOLDER, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"music_enabled": config.music_enabled}, f, indent=2)
        logger.debug(f"Configuration musique sauvegardée: {config.music_enabled}")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de music_config.json: {str(e)}")


def normalize_platform_name(platform):
    """Normalise un nom de plateforme en supprimant espaces et convertissant en minuscules."""
    return platform.lower().replace(" ", "")

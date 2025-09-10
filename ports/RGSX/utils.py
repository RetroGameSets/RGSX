import shutil
import re
import json
import os
import logging
import platform
import subprocess
import config
from config import HEADLESS
try:
    if not HEADLESS:
        import pygame  # type: ignore
    else:
        pygame = None  # type: ignore
except Exception:
    pygame = None  # type: ignore
import glob
import threading
from rgsx_settings import load_rgsx_settings, save_rgsx_settings
import zipfile
import time
import random
import config
from history import save_history
from language import _ 
from datetime import datetime
import sys


logger = logging.getLogger(__name__)
# Désactiver les logs DEBUG de urllib3 e requests pour supprimer les messages de connexion HTTP
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)

# Liste globale pour stocker les systèmes avec une erreur 404
unavailable_systems = []

# Cache/process flags for extensions generation/loading

 
def restart_application(delay_ms: int = 2000):
    """Schedule a restart with a visible popup; actual restart happens in the main loop.

    - Sets popup_restarting and schedules config.pending_restart_at = now + delay_ms.
    - Main loop (__main__) detects pending_restart_at and calls restart_application(0) to perform the execl.
    """
    try:
        # Show popup and schedule
        if hasattr(config, 'popup_message'):
            try:
                config.popup_message = _("popup_restarting")
            except Exception:
                config.popup_message = "Restarting..."
            config.popup_timer = max(config.popup_timer, int(delay_ms)) if hasattr(config, 'popup_timer') else int(delay_ms)
            config.menu_state = getattr(config, 'menu_state', 'restart_popup') or 'restart_popup'
            config.needs_redraw = True
        # Schedule actual restart in main loop
        now = pygame.time.get_ticks() if hasattr(pygame, 'time') else 0
        config.pending_restart_at = now + max(0, int(delay_ms))
        logger.debug(f"Redémarrage planifié dans {delay_ms} ms (pending_restart_at={getattr(config, 'pending_restart_at', 0)})")

        # If delay_ms is 0, perform immediately here
        if int(delay_ms) <= 0:
            try:
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                try:
                    pygame.quit()
                except Exception:
                    pass
                exe = sys.executable or "python"
                os.execl(exe, exe, *sys.argv)
            except Exception as e:
                logger.exception(f"Failed to restart immediately: {e}")
    except Exception as e:
        logger.exception(f"Failed to schedule restart: {e}")
_extensions_cache = None  # type: ignore
_extensions_json_regenerated = False


# Fonction pour charger le fichier JSON des extensions supportées
def load_extensions_json():
    """Charge le JSON des extensions supportées.
    - Régénère une seule fois par exécution (au premier appel ou si le fichier est absent).
    - Met en cache le résultat pour éviter les relectures et logs répétés.
    """
    global _extensions_cache, _extensions_json_regenerated
    try:
        # Retour immédiat si déjà en cache
        if _extensions_cache is not None:
            return _extensions_cache

        os.makedirs(os.path.dirname(config.JSON_EXTENSIONS), exist_ok=True)

        # Régénération unique au premier appel (ou si le fichier est manquant)
        if not _extensions_json_regenerated or not os.path.exists(config.JSON_EXTENSIONS):
            try:
                generated = generate_extensions_json_from_es_systems()
                if generated:
                    with open(config.JSON_EXTENSIONS, 'w', encoding='utf-8') as wf:
                        json.dump(generated, wf, ensure_ascii=False, indent=2)
                    logger.info(f"rom_extensions régénéré ({len(generated)} systèmes): {config.JSON_EXTENSIONS}")
                else:
                    logger.warning("Aucune donnée générée depuis es_systems.cfg; on conserve l'existant si présent")
                _extensions_json_regenerated = True
            except Exception as ge:
                logger.error(f"Échec lors de la régénération de {config.JSON_EXTENSIONS} depuis es_systems.cfg: {ge}")

        # Lecture du fichier (nouveau ou existant)
        if os.path.exists(config.JSON_EXTENSIONS):
            with open(config.JSON_EXTENSIONS, 'r', encoding='utf-8') as f:
                _extensions_cache = json.load(f)
                return _extensions_cache
        _extensions_cache = []
        return _extensions_cache
    except Exception as e:
        logger.error(f"Erreur lors de la lecture de {config.JSON_EXTENSIONS}: {e}")
        _extensions_cache = []
        return _extensions_cache

def _detect_es_systems_cfg_paths():
    """Retourne une liste de chemins possibles pour es_systems.cfg selon l'OS.
    - RetroBat (Windows): {config.RETROBAT_DATA_FOLDER}\\system\\templates\\emulationstation\\es_systems.cfg
    - Batocera (Linux): /usr/share/emulationstation/es_systems.cfg
      Ajoute aussi les fichiers customs: /userdata/system/configs/emulationstation/es_systems_*.cfg
    """
    candidates = []
    try:
        if platform.system() == 'Windows':
            base = getattr(config, 'RETROBAT_DATA_FOLDER', None)
            if base:
                candidates.append(os.path.join(base, 'system', 'templates', 'emulationstation', 'es_systems.cfg'))
        else:
            # Batocera / Linux classiques
            candidates.append('/usr/share/emulationstation/es_systems.cfg')
            candidates.append('/etc/emulationstation/es_systems.cfg')
            # Batocera customs
            custom_dir = '/userdata/system/configs/emulationstation'
            try:
                for p in glob.glob(os.path.join(custom_dir, 'es_systems_*.cfg')):
                    candidates.append(p)
                direct_cfg = os.path.join(custom_dir, 'es_systems.cfg')
                if os.path.exists(direct_cfg):
                    candidates.append(direct_cfg)
            except Exception:
                pass
    except Exception:
        pass
    existing = [p for p in candidates if p and os.path.exists(p)]
    # Logs réduits: on ne conserve que les résumés plus loin
    return existing

def _parse_es_systems_cfg(cfg_path):
    """Parse un es_systems.cfg minimalement pour extraire (folder, extensions).
    Retourne une liste de dicts: { 'folder': <str>, 'extensions': [..] }
    - folder: dérivé de la balise <path> en prenant la partie après 'roms/' (ou '\\roms\\' sous Windows)
    - extensions: liste normalisée de .ext (point + minuscule)
    """
    try:
        # Lire tel quel (pas besoin d'un parseur XML strict, mais ElementTree suffit)
        import xml.etree.ElementTree as ET
    # Log détaillé supprimé pour alléger les traces
        tree = ET.parse(cfg_path)
        root = tree.getroot()
        out = []
        for sys_elem in root.findall('system'):
            path_text = (sys_elem.findtext('path') or '').strip()
            ext_text = (sys_elem.findtext('extension') or '').strip()
            if not path_text:
                continue
            # Extraire le dossier après 'roms'
            folder = None
            norm = path_text.replace('\\', '/').lower()
            marker = '/roms/'
            if marker in norm:
                after = norm.split(marker, 1)[1]
                folder = after.strip().strip('/\\')
            if not folder:
                # fallback: si le chemin finit par .../roms/<folder>
                parts = norm.strip('/').split('/')
                if len(parts) >= 2 and parts[-2] == 'roms':
                    folder = parts[-1]
            if not folder:
                continue

            # Extensions: split par espaces, normaliser en .ext
            exts = []
            for tok in ext_text.split():
                tok = tok.strip().lower()
                if not tok:
                    continue
                if not tok.startswith('.'):
                    # Certaines entrées peuvent omettre le point
                    tok = '.' + tok
                exts.append(tok)
            # Dédupliquer tout en conservant l'ordre
            seen = set()
            norm_exts = []
            for e in exts:
                if e not in seen:
                    seen.add(e)
                    norm_exts.append(e)
            out.append({'folder': folder, 'extensions': norm_exts})
    # Résumé final affiché ailleurs
        return out
    except Exception as e:
        logger.error(f"Erreur parsing es_systems.cfg ({cfg_path}): {e}")
        return []

def generate_extensions_json_from_es_systems():
    """Essaie de construire la liste des extensions à partir des es_systems.cfg disponibles.
    Priorité: RetroBat si présent, sinon Batocera. Fusionne si plusieurs trouvés, en préférant RetroBat.
    """
    combined = {}
    paths = _detect_es_systems_cfg_paths()
    if not paths:
        logger.warning("Aucun chemin es_systems.cfg détecté (RetroBat/Batocera)")
        return []
    # Prioriser RetroBat en tête si présent
    def score(p):
        return 0 if 'templates' in p.replace('\\', '/').lower() else 1
    for cfg in sorted(paths, key=score):
        if not os.path.exists(cfg):
            continue
        items = _parse_es_systems_cfg(cfg)
        for itm in items:
            folder = itm['folder']
            exts = itm['extensions']
            if folder in combined:
                # Fusionner: ajouter extensions manquantes
                present = set(combined[folder])
                for e in exts:
                    if e not in present:
                        combined[folder].append(e)
                        present.add(e)
            else:
                combined[folder] = list(exts)
    # Convertir en liste triée par dossier
    result = [{'folder': k, 'extensions': v} for k, v in sorted(combined.items(), key=lambda x: x[0])]
    logger.info(f"Extensions combinées totales: {len(result)} systèmes")
    return result
    
def check_extension_before_download(url, platform, game_name):
    """Vérifie l'extension avant de lancer le téléchargement et retourne un tuple de 4 éléments."""
    try:
        sanitized_name = sanitize_filename(game_name)
        extensions_data = load_extensions_json()
        # Si le cache des extensions est vide/introuvable, ne bloquez pas: traitez comme "inconnu"
        # afin d'afficher l'avertissement d'extension au lieu d'une erreur fatale.
        if not extensions_data:
            logger.warning(f"Fichier {config.JSON_EXTENSIONS} vide ou introuvable; poursuite avec extensions inconnues")
            extensions_data = []

        is_supported = is_extension_supported(sanitized_name, platform, extensions_data)
        extension = os.path.splitext(sanitized_name)[1].lower()
        is_archive = extension in (".zip", ".rar")

        # Déterminer si le système (dossier) est connu dans extensions_data
        dest_folder_name = _get_dest_folder_name(platform)
        system_known = any(s.get("folder") == dest_folder_name for s in extensions_data)

        # Traitement spécifique BIOS: forcer extraction des archives même si le système n'est pas connu
        try:
            bios_like = {"BIOS", "- BIOS by TMCTV -", "- BIOS"}
            if (dest_folder_name == "bios" or platform in bios_like) and is_archive:
                logger.debug(f"Plateforme BIOS détectée pour {sanitized_name}, extraction auto forcée pour {extension}")
                return (url, platform, game_name, True)
        except Exception:
            pass

        if is_supported:
            logger.debug(f"L'extension de {sanitized_name} est supportée pour {platform}")
            return (url, platform, game_name, False)
        elif is_archive:
            # Même si le système n'est pas connu ou que l'extension n'est pas listée,
            # on force l'extraction des archives (ZIP/RAR) à la fin du téléchargement
            # puis suppression du fichier.
            logger.debug(f"Archive {extension.upper()} détectée pour {sanitized_name}, extraction automatique prévue (extension non listée)")
            return (url, platform, game_name, True)
        else:
            # Autoriser si l'utilisateur a choisi d'autoriser les extensions inconnues
            allow_unknown = False
            try:
                from rgsx_settings import get_allow_unknown_extensions
                allow_unknown = get_allow_unknown_extensions()
            except Exception:
                allow_unknown = False
            if allow_unknown:
                logger.debug(f"Extension non supportée ({extension}) mais autorisée par l'utilisateur pour {sanitized_name}")
                return (url, platform, game_name, False)
            logger.debug(f"Extension non supportée ({extension}) pour {sanitized_name}, avertissement affiché")
            return (url, platform, game_name, False)
    except Exception as e:
        logger.error(f"Erreur vérification extension {url}: {str(e)}")
        return None

# Fonction pour vérifier si l'extension est supportée pour une plateforme donnée
def is_extension_supported(filename, platform_key, extensions_data):
    """Vérifie si l'extension du fichier est supportée pour la plateforme donnée.
    platform_key correspond maintenant à l'identifiant utilisé dans config.platforms (platform_name)."""
    extension = os.path.splitext(filename)[1].lower()

    dest_dir = None
    for platform_dict in config.platform_dicts:
        # Nouveau schéma: platform_name
        if platform_dict.get("platform_name") == platform_key:
            dest_dir = os.path.join(config.ROMS_FOLDER, platform_dict.get("folder"))
            break

    if not dest_dir:
        logger.warning(f"Aucun dossier 'folder' trouvé pour la plateforme {platform_key}")
        dest_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), platform_key)
    
    dest_folder_name = os.path.basename(dest_dir)
    for i, system in enumerate(extensions_data):
        if system["folder"] == dest_folder_name:
            result = extension in system["extensions"]
            return result
    
    logger.warning(f"Aucun système trouvé pour le dossier {dest_dir}")
    return False


def _get_dest_folder_name(platform_key: str) -> str:
    """Retourne le nom du dossier de destination pour une plateforme (basename du dossier)."""
    dest_dir = None
    for platform_dict in config.platform_dicts:
        if platform_dict.get("platform_name") == platform_key:
            folder = platform_dict.get("folder")
            if folder:
                dest_dir = os.path.join(config.ROMS_FOLDER, folder)
            break
    if not dest_dir:
        dest_dir = os.path.join(os.path.dirname(os.path.dirname(config.APP_FOLDER)), platform_key)
    return os.path.basename(dest_dir)




# Fonction pour charger sources.json
def load_sources():
    try:
        # Détection legacy: si sources.json (ancien format) existe encore, déclencher redownload automatique
        legacy_path = os.path.join(config.SAVE_FOLDER, "sources.json")
        if os.path.exists(legacy_path):
            logger.warning("Ancien fichier sources.json détecté: déclenchement redownload cache jeux")
            try:
                # Supprimer ancien cache et forcer redémarrage logique comme dans l'option de menu
                if os.path.exists(config.SOURCES_FILE):
                    try:
                        os.remove(config.SOURCES_FILE)
                    except Exception:
                        pass
                if os.path.exists(config.GAMES_FOLDER):
                    shutil.rmtree(config.GAMES_FOLDER, ignore_errors=True)
                if os.path.exists(config.IMAGES_FOLDER):
                    shutil.rmtree(config.IMAGES_FOLDER, ignore_errors=True)
                # Renommer legacy pour éviter boucle
                try:
                    os.replace(legacy_path, legacy_path + ".bak")
                except Exception:
                    pass
                # Préparer popup redémarrage si contexte graphique chargé
                config.popup_message = _("popup_redownload_success") if hasattr(config, 'popup_message') else "Cache jeux réinitialisé"
                config.popup_timer = 5000 if hasattr(config, 'popup_timer') else 0
                config.menu_state = "restart_popup" if hasattr(config, 'menu_state') else getattr(config, 'menu_state', 'platform')
                config.needs_redraw = True
                logger.info("Redownload cache déclenché automatiquement (legacy sources.json)")
                return []  # On sort pour laisser le processus de redémarrage gérer le rechargement
            except Exception as e:
                logger.error(f"Échec redownload automatique depuis legacy sources.json: {e}")
        sources = []
        if os.path.exists(config.SOURCES_FILE):
            with open(config.SOURCES_FILE, 'r', encoding='utf-8') as f:
                sources = json.load(f)
            if not isinstance(sources, list):
                logger.error("systems_list.json n'est pas une liste JSON valide")
                sources = []
        else:
            logger.warning(f"Fichier systems_list absent: {config.SOURCES_FILE}")

        # S'assurer que chaque entrée possède la clé platform_image (vide si absente)
        for s in sources:
            if "platform_image" not in s:
                # Supporter ancienne clé system_image -> platform_image si présente
                legacy = s.pop("system_image", "") if isinstance(s, dict) else ""
                s["platform_image"] = legacy or ""
            # Normaliser clé dossier -> folder si besoin (legacy francophone)
            if isinstance(s, dict) and "folder" not in s:
                legacy_folder = s.get("dossier") or s.get("folder_name")
                if legacy_folder:
                    s["folder"] = legacy_folder

        existing_names = {s.get("platform_name", "") for s in sources}
        added = []
        if os.path.isdir(config.GAMES_FOLDER):
            for fname in sorted(os.listdir(config.GAMES_FOLDER)):
                if not fname.lower().endswith('.json'):
                    continue
                pname = os.path.splitext(fname)[0]
                if not pname or pname in existing_names:
                    continue
                new_entry = {"platform_name": pname, "folder": pname, "platform_image": ""}
                sources.append(new_entry)
                added.append(pname)
                existing_names.add(pname)

        # Déterminer les plateformes orphelines (fichier manquant)
        existing_files = set()
        if os.path.isdir(config.GAMES_FOLDER):
            existing_files = {os.path.splitext(f)[0] for f in os.listdir(config.GAMES_FOLDER) if f.lower().endswith('.json')}
        removed = []
        filtered_sources = []
        for entry in sources:
            pname = entry.get("platform_name", "")
            # Garder seulement si un fichier existe
            if pname in existing_files:
                filtered_sources.append(entry)
            else:
                # Ne retirer que si ce n'est pas un nom vide
                if pname:
                    removed.append(pname)
        sources = filtered_sources

        if added:
            logger.info(f"Plateformes ajoutées automatiquement: {', '.join(added)}")
        if removed:
            logger.info(f"Plateformes supprimées (fichiers absents): {', '.join(removed)}")

        # Persister si modifications (ajouts ou suppressions)
        if added or removed:
            try:
                # Pas de tri avant persistance: conserver ordre d'origine + ajouts fins
                os.makedirs(os.path.dirname(config.SOURCES_FILE), exist_ok=True)
                with open(config.SOURCES_FILE, 'w', encoding='utf-8') as f:
                    json.dump(sources, f, ensure_ascii=False, indent=2)
                logger.info("systems_list.json mis à jour (ajouts/suppressions, ordre conservé)")
            except Exception as e:
                logger.error(f"Échec écriture systems_list.json après maj auto: {e}")

        # Pour l'affichage on veut un tri alphabétique sans toucher l'ordre de persistance
        sorted_for_display = sorted(sources, key=lambda x: x.get("platform_name", "").lower())

        # Construire structures config: platform_dicts = ordre fichier, platforms = tri (avec filtre masqués)
        config.platform_dicts = sources  # ordre brut fichier
        settings = load_rgsx_settings()
        hidden = set(settings.get("hidden_platforms", [])) if isinstance(settings, dict) else set()
        all_sorted_names = [s.get("platform_name", "") for s in sorted_for_display]
        visible_names = [n for n in all_sorted_names if n and n not in hidden]

        # Masquer automatiquement les systèmes dont le dossier ROM n'existe pas (selon le toggle)
        unsupported = []
        try:
            from rgsx_settings import get_show_unsupported_platforms
            show_unsupported = get_show_unsupported_platforms(settings)
            sources_by_name = {s.get("platform_name", ""): s for s in sources if isinstance(s, dict)}
            for name in list(visible_names):
                entry = sources_by_name.get(name) or {}
                folder = entry.get("folder")
                # Conserver BIOS même sans dossier, et ignorer entrées sans folder
                bios_name = name.strip()
                if not folder or bios_name == "- BIOS by TMCTV -" or bios_name == "- BIOS":
                    continue
                expected_dir = os.path.join(config.ROMS_FOLDER, folder)
                if not os.path.isdir(expected_dir):
                    unsupported.append(name)
            if show_unsupported:
                config.unsupported_platforms = unsupported
            else:
                if unsupported:
                    # Filtrer la liste visible
                    visible_names = [n for n in visible_names if n not in set(unsupported)]
                    config.unsupported_platforms = unsupported
                    # Log concis + détaillé en DEBUG uniquement
                    logger.info(f"Plateformes masquées (dossier rom absent): {len(unsupported)}")
                    logger.debug("Détails plateformes masquées: " + ", ".join(unsupported))
                else:
                    config.unsupported_platforms = []
        except Exception as e:
            logger.error(f"Erreur détection plateformes non supportées (dossiers manquants): {e}")
            config.unsupported_platforms = []

        config.platforms = visible_names
        config.platform_names = {p: p for p in config.platforms}
        # Nouveau mapping par nom pour éviter décalages index après tri d'affichage
        try:
            config.platform_dict_by_name = {d.get("platform_name", ""): d for d in config.platform_dicts}
        except Exception:
            config.platform_dict_by_name = {}
        config.games_count = {}
        for platform_name in config.platforms:
            games = load_games(platform_name)
            config.games_count[platform_name] = len(games)
        return sources
    except Exception as e:
        logger.error(f"Erreur fusion systèmes + détection jeux: {e}")
        return []

def load_games(platform_id):
    try:
        # Retrouver l'objet plateforme pour accéder éventuellement à 'folder'
        platform_dict = None
        for pd in config.platform_dicts:
            if pd.get("platform_name") == platform_id or pd.get("platform") == platform_id:
                platform_dict = pd
                break

        candidates = []
        # 1. Nom exact
        candidates.append(os.path.join(config.GAMES_FOLDER, f"{platform_id}.json"))
        # 2. Nom normalisé
        norm = normalize_platform_name(platform_id)
        if norm and norm != platform_id:
            candidates.append(os.path.join(config.GAMES_FOLDER, f"{norm}.json"))
        # 3. Folder déclaré
        if platform_dict:
            folder_name = platform_dict.get("folder")
            if folder_name:
                candidates.append(os.path.join(config.GAMES_FOLDER, f"{folder_name}.json"))

        game_file = None
        for c in candidates:
            if os.path.exists(c):
                game_file = c
                break
        if not game_file:
            logger.warning(f"Aucun fichier de jeux trouvé pour {platform_id} (candidats: {candidates})")
            return []

        with open(game_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Si dict avec clé 'games'
        if isinstance(data, dict) and 'games' in data:
            data = data['games']

        normalized = []  # (name, url, size)

        def extract_from_dict(d):
            name = d.get('game_name') or d.get('name') or d.get('title') or d.get('game')
            url = d.get('url') or d.get('download') or d.get('link') or d.get('href')
            size = d.get('size') or d.get('filesize') or d.get('length')
            if name:
                normalized.append((str(name), url if isinstance(url, str) and url.strip() else None, str(size) if size else None))

        if isinstance(data, list):
            for item in data:
                if isinstance(item, (list, tuple)):
                    if len(item) == 0:
                        continue
                    name = str(item[0])
                    url = item[1] if len(item) > 1 and isinstance(item[1], str) and item[1].strip() else None
                    size = item[2] if len(item) > 2 and isinstance(item[2], str) and item[2].strip() else None
                    normalized.append((name, url, size))
                elif isinstance(item, dict):
                    extract_from_dict(item)
                elif isinstance(item, str):
                    normalized.append((item, None, None))
                else:
                    normalized.append((str(item), None, None))
        elif isinstance(data, dict):  # dict sans 'games'
            extract_from_dict(data)
        else:
            logger.warning(f"Format de fichier jeux inattendu pour {platform_id}: {type(data)}")

        logger.debug(f"{os.path.basename(game_file)}: {len(normalized)} jeux")
        return normalized
    except Exception as e:
        logger.error(f"Erreur lors du chargement des jeux pour {platform_id}: {e}")
        return []

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
    """Charge une image système avec la priorité suivante:
    1. platform_image explicite s'il est défini
    2. <platform_name>.png
    3. <folder>.png si disponible
    4. Recherche fallback dans le dossier images de l'app (APP_FOLDER/images) avec le même ordre
    5. default.png (dans SAVE_FOLDER/images), sinon default.png de l'app

    Cela évite d'échouer lorsque le nom affiché ne correspond pas au fichier image
    et respecte un mapping explicite fourni par systems_list.json."""
    platform_name = platform_dict.get("platform_name", "unknown")
    folder_name = platform_dict.get("folder") or ""

    # Dossiers d'images
    save_images = config.IMAGES_FOLDER
    app_images = os.path.join(config.APP_FOLDER, "images")

    # Candidats, par ordre de priorité
    candidates = []
    platform_image_field = (platform_dict.get("platform_image") or "").strip()
    if platform_image_field:
        candidates.append(os.path.join(save_images, platform_image_field))
    candidates.append(os.path.join(save_images, f"{platform_name}.png"))
    if folder_name:
        candidates.append(os.path.join(save_images, f"{folder_name}.png"))

    # Fallback: images packagées avec l'app
    if platform_image_field:
        candidates.append(os.path.join(app_images, platform_image_field))
    candidates.append(os.path.join(app_images, f"{platform_name}.png"))
    if folder_name:
        candidates.append(os.path.join(app_images, f"{folder_name}.png"))

    # Charger le premier fichier existant
    try:
        for path in candidates:
            if path and os.path.exists(path):
                return pygame.image.load(path).convert_alpha()

        # default.png (save d'abord, sinon app)
        default_save = os.path.join(save_images, "default.png")
        if os.path.exists(default_save):
            return pygame.image.load(default_save).convert_alpha()
        default_app = os.path.join(app_images, "default.png")
        if os.path.exists(default_app):
            return pygame.image.load(default_app).convert_alpha()

        logger.error(
            f"Aucune image trouvée pour {platform_name}. Candidats: "
            + ", ".join(candidates)
            + f"; default cherchés: {default_save}, {default_app}"
        )
        return None
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
                    success, error_msg = handle_xbox(dest_dir, new_isos, url)
                    if not success:
                        return False, error_msg
                else:
                    logger.warning("Aucun nouvel ISO détecté après extraction pour conversion Xbox.")
                    # On ne retourne pas d'erreur fatale ici, on continue

        try:
            os.remove(zip_path)
            logger.info(f"Fichier ZIP {zip_path} extrait dans {dest_dir} et supprimé")
            
            # Mettre à jour le statut final dans l'historique (couvre "Extracting" et "Converting")
            try:
                if isinstance(config.history, list):
                    for entry in config.history:
                        if entry.get("url") == url and entry.get("status") in ("Extracting", "Converting"):
                            entry["status"] = "Download_OK"
                            entry["progress"] = 100
                            message_text = _("utils_extracted").format(os.path.basename(zip_path))
                            entry["message"] = message_text
                            save_history(config.history)
                            config.needs_redraw = True
                            break
                # Mettre à jour l'état de progression à 100%
                if url in getattr(config, 'download_progress', {}):
                    try:
                        config.download_progress[url]["status"] = "Download_OK"
                        config.download_progress[url]["progress_percent"] = 100
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"MAJ statut final après conversion: ignorée ({e})")
            
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


def handle_xbox(dest_dir, iso_files, url=None):
    """Gère la conversion des fichiers Xbox extraits et met à jour l'UI (Converting)."""
    logger.debug(f"Traitement spécifique Xbox dans: {dest_dir}")
    
    # Attendre un peu que tous les processus d'extraction se terminent
    time.sleep(2)
    system_type = platform.system()
    if system_type == "Windows":
        # Sur Windows; telecharger le fichier exe
        XDVDFS_EXE = config.XDVDFS_EXE
        xdvdfs_cmd = [XDVDFS_EXE, "pack"]  # Liste avec 2 éléments

    else:
        # Linux/Batocera : télécharger le fichier xdvdfs  
        XDVDFS_LINUX = config.XDVDFS_LINUX
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
        # Chercher les fichiers ISO à convertir (rafraîchir la liste)
        iso_files = []
        for root, dirs, files in os.walk(dest_dir):
            for file in files:
                if file.lower().endswith('.iso'):
                    iso_files.append(os.path.join(root, file))

        if not iso_files:
            logger.warning("Aucun fichier ISO xbox trouvé")
            return True, None

        total = len(iso_files)
        # Marquer l'état comme Conversion en cours (0%)
        try:
            if url:
                # Progress dict (pour l'écran en cours)
                if url not in config.download_progress:
                    config.download_progress[url] = {}
                config.download_progress[url]["status"] = "Converting"
                config.download_progress[url]["progress_percent"] = 0
                config.needs_redraw = True
                # Historique
                if isinstance(config.history, list):
                    for entry in config.history:
                        if entry.get("url") == url and entry.get("status") in ["Extracting", "Téléchargement", "downloading"]:
                            entry["status"] = "Converting"
                            entry["progress"] = 0
                            entry["message"] = "Xbox conversion in progress"
                            save_history(config.history)
                            break
        except Exception as e:
            logger.debug(f"MAJ statut conversion ignorée: {e}")

        logger.info(f"Démarrage conversion Xbox: {total} ISO(s)")
        for idx, iso_xbox_source in enumerate(iso_files, start=1):
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
                # Mise à jour progression de conversion (coarse-grain)
                try:
                    percent = int(idx / total * 100) if total > 0 else 100
                    if url:
                        if url not in config.download_progress:
                            config.download_progress[url] = {}
                        config.download_progress[url]["status"] = "Converting"
                        config.download_progress[url]["progress_percent"] = percent
                        config.needs_redraw = True
                        if isinstance(config.history, list):
                            for entry in config.history:
                                if entry.get("url") == url and entry.get("status") == "Converting":
                                    entry["progress"] = percent
                                    save_history(config.history)
                                    break
                except Exception:
                    pass
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
    API_KEY_1FICHIER = os.path.join(config.SAVE_FOLDER, "1FichierAPI.txt")
    logger.debug(f"Chemin du fichier de clé API: {API_KEY_1FICHIER}")
    logger.debug(f"Tentative de chargement de la clé API depuis: {API_KEY_1FICHIER}")
    try:
        # Vérifie si le fichier existe déjà 
        if not os.path.exists(API_KEY_1FICHIER):
            logger.info(f"Fichier de clé API non trouvé")
            # Crée le dossier parent si nécessaire
            os.makedirs(config.SAVE_FOLDER, exist_ok=True)
            # Crée le fichier vide si absent
            with open(API_KEY_1FICHIER, "w") as f:
                f.write("")
            logger.info(f"Fichier de clé API créé : {API_KEY_1FICHIER}")
            return ""
    except OSError as e:
        logger.error(f"Erreur lors de la création du fichier de clé API : {e}")
        return ""
    # Lit la clé API depuis le fichier
    try:
        with open(API_KEY_1FICHIER, "r", encoding="utf-8") as f:
            api_key = f.read().strip()
        logger.debug(f"Clé API 1fichier lue: '{api_key}' (longueur: {len(api_key)})")
        if not api_key:
            logger.warning("Clé API 1fichier vide, veuillez la renseigner dans le fichier pour pouvoir utiliser les fonctionnalités de téléchargement sur 1fichier.")
        API_KEY_1FICHIER = api_key
        config.API_KEY_1FICHIER = api_key
        logger.debug(f"Clé API 1fichier chargée dans la configuration : '{config.API_KEY_1FICHIER}'")
        return api_key
    except OSError as e:
        logger.error(f"Erreur lors de la lecture de la clé API : {e}")
        return ""

def load_music_config():
    """Charge la configuration musique depuis rgsx_settings.json."""
    try:
        settings = load_rgsx_settings()
        config.music_enabled = settings.get("music_enabled", True)
        return config.music_enabled
    except Exception as e:
        logger.error(f"Erreur lors du chargement de la configuration musique: {str(e)}")
    config.music_enabled = True
    return True

def save_music_config():
    """Sauvegarde la configuration musique dans rgsx_settings.json."""
    try:
        settings = load_rgsx_settings()
        settings["music_enabled"] = config.music_enabled
        save_rgsx_settings(settings)
        logger.debug(f"Configuration musique sauvegardée: {config.music_enabled}")
    except Exception as e:
        logger.error(f"Erreur lors de la sauvegarde de la configuration musique: {str(e)}")


def normalize_platform_name(platform):
    """Normalise un nom de plateforme en supprimant espaces et convertissant en minuscules."""
    return platform.lower().replace(" ", "")

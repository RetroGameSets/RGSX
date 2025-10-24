#!/usr/bin/env python3
import json
import os
import logging
import config

logger = logging.getLogger(__name__)



#Fonction pour supprimer les anciens fichiers de paramètres non utilisés
def delete_old_files():
    old_files_saves = [
        "accessibility.json",
        "language.json",
        "music_config.json",
        "symlink_settings.json",
        "sources.json"
    ]
    old_files_app = [
        "rom_extensions.json",
        "es_input_parser.py",
        "sources.json"
    ]


    for filename in old_files_saves:
        file_path = os.path.join(config.SAVE_FOLDER, filename)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Ancien fichier supprimé : {file_path}")
                logger.info(f"Ancien fichier supprimé : {file_path}")
        except Exception as e:
            print(f"Erreur lors de la suppression de {file_path} : {str(e)}")
            logger.error(f"Erreur lors de la suppression de {file_path} : {str(e)}")
    for filename in old_files_app:
        file_path = os.path.join(config.APP_FOLDER, filename)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Ancien fichier supprimé : {file_path}")
                logger.info(f"Ancien fichier supprimé : {file_path}")
        except Exception as e:
            print(f"Erreur lors de la suppression de {file_path} : {str(e)}")
            logger.error(f"Erreur lors de la suppression de {file_path} : {str(e)}")

def load_rgsx_settings():
    """Charge tous les paramètres depuis rgsx_settings.json."""
    from config import RGSX_SETTINGS_PATH
    
    default_settings = {
        "language": "en",
        "music_enabled": True,
        "accessibility": {
            "font_scale": 1.0
        },
        "display": {
            "grid": "3x4",
            "font_family": "pixel"
        },
        "symlink": {
            "enabled": False,
            "target_directory": ""
        },
        "sources": {  
            "mode": "rgsx",       
            "custom_url": ""      
    },
    "show_unsupported_platforms": False,
    "allow_unknown_extensions": False,
    "roms_folder": "",
    "web_service_at_boot": False
    }
    
    try:
        if os.path.exists(RGSX_SETTINGS_PATH):
            with open(RGSX_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                # Fusionner avec les valeurs par défaut pour assurer la compatibilité
                for key, value in default_settings.items():
                    if key not in settings:
                        settings[key] = value
                return settings
    except Exception as e:
        print(f"Erreur lors du chargement de rgsx_settings.json: {str(e)}")
    
    return default_settings


def save_rgsx_settings(settings):
    """Sauvegarde tous les paramètres dans rgsx_settings.json."""
    from config import RGSX_SETTINGS_PATH, SAVE_FOLDER
    
    try:
        os.makedirs(SAVE_FOLDER, exist_ok=True)
        with open(RGSX_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Erreur lors de la sauvegarde de rgsx_settings.json: {str(e)}")



def load_symlink_settings():
    """Load symlink settings from rgsx_settings.json."""
    try:
        settings = load_rgsx_settings()
        symlink_settings = settings.get("symlink", {"enabled": False, "target_directory": ""})
        
        # Convertir l'ancien format si nécessaire
        if not isinstance(symlink_settings, dict):
            symlink_settings = {"enabled": False, "target_directory": ""}
        
        # Compatibilité avec l'ancien nom "use_symlink_path"
        if "use_symlink_path" in symlink_settings:
            symlink_settings["enabled"] = symlink_settings.pop("use_symlink_path")
        
        return {"use_symlink_path": symlink_settings.get("enabled", False)}
    except Exception as e:
        logger.error(f"Error loading symlink settings: {str(e)}")
    
    # Return default settings (disabled)
    return {"use_symlink_path": False}

def save_symlink_settings(settings_to_save):
    """Save symlink settings to rgsx_settings.json."""
    try:
        settings = load_rgsx_settings()
        
        # Convertir le format pour le nouveau système
        settings["symlink"] = {
            "enabled": settings_to_save.get("use_symlink_path", False),
            "target_directory": settings_to_save.get("target_directory", "")
        }
        
        save_rgsx_settings(settings)
        logger.debug(f"Symlink settings saved: {settings_to_save}")
        return True
    except Exception as e:
        logger.error(f"Error saving symlink settings: {str(e)}")
        return False

def set_symlink_option(enabled):
    """Enable or disable the symlink option."""
    settings = load_symlink_settings()
    settings["use_symlink_path"] = enabled
    
    if save_symlink_settings(settings):
        return True, "symlink_settings_saved_successfully"
    else:
        return False, "symlink_settings_save_error"

def get_symlink_option():
    """Get current symlink option status."""
    settings = load_symlink_settings()
    return settings.get("use_symlink_path", False)

def apply_symlink_path(base_path, platform_folder):
    """Apply symlink path modification if enabled."""
    if get_symlink_option():
        # Append the platform folder name to create symlink path
        return os.path.join(base_path, platform_folder, platform_folder)
    else:
        # Return original path
        return os.path.join(base_path, platform_folder)

# ----------------------- Sources (RGSX / Custom) ----------------------- #

def get_sources_mode(settings=None):
    """Retourne le mode des sources: 'rgsx' (par défaut) ou 'custom'."""
    if settings is None:
        settings = load_rgsx_settings()
    return settings.get("sources", {}).get("mode", "rgsx")

def set_sources_mode(mode):
    """Définit le mode des sources et sauvegarde le fichier."""
    if mode not in ("rgsx", "custom"):
        mode = "rgsx"
    settings = load_rgsx_settings()
    sources = settings.setdefault("sources", {})
    sources["mode"] = mode
    save_rgsx_settings(settings)
    return mode

def get_custom_sources_url(settings=None):
    """Retourne l'URL personnalisée configurée (ou chaîne vide)."""
    if settings is None:
        settings = load_rgsx_settings()
    return settings.get("sources", {}).get("custom_url", "").strip()

def get_sources_zip_url(fallback_url):
    """Retourne l'URL ZIP à utiliser selon le mode. Fallback sur l'URL standard si custom invalide."""
    settings = load_rgsx_settings()
    if get_sources_mode(settings) == "custom":
        custom = get_custom_sources_url(settings)
        if custom.startswith("http://") or custom.startswith("https://"):
            return custom
        # Pas de fallback : retourner None pour signaler une source vide
        return None
    return fallback_url

def find_local_custom_sources_zip():
    """Recherche un fichier ZIP local à la racine de SAVE_FOLDER pour le mode custom.

    Priorité sur quelques noms courants afin d'éviter toute ambiguïté.
    Retourne le chemin absolu du ZIP si trouvé, sinon None.
    """
    try:
        from config import SAVE_FOLDER
        candidates = [
            "games.zip",
            "custom_sources.zip",
            "rgsx_custom_sources.zip",
            "data.zip",
        ]
        if not os.path.isdir(SAVE_FOLDER):
            return None
        for name in candidates:
            p = os.path.join(SAVE_FOLDER, name)
            if os.path.isfile(p):
                return p
        # Option avancée: prendre le plus récent *.zip si aucun nom connu trouvé
        try:
            zips = [os.path.join(SAVE_FOLDER, f) for f in os.listdir(SAVE_FOLDER) if f.lower().endswith('.zip')]
            zips = [z for z in zips if os.path.isfile(z)]
            if zips:
                newest = max(zips, key=lambda z: os.path.getmtime(z))
                return newest
        except Exception:
            pass
        return None
    except Exception as e:
        logger.debug(f"find_local_custom_sources_zip error: {e}")
        return None

# ----------------------- Unsupported platforms toggle ----------------------- #

def get_show_unsupported_platforms(settings=None):
    """Retourne True si l'affichage des systèmes non supportés est activé."""
    if settings is None:
        settings = load_rgsx_settings()
    return bool(settings.get("show_unsupported_platforms", False))


def set_show_unsupported_platforms(enabled: bool):
    """Active/désactive l'affichage des systèmes non supportés et sauvegarde."""
    settings = load_rgsx_settings()
    settings["show_unsupported_platforms"] = bool(enabled)
    save_rgsx_settings(settings)
    return settings["show_unsupported_platforms"]

# ----------------------- Unknown extensions toggle ----------------------- #

def get_allow_unknown_extensions(settings=None) -> bool:
    """Retourne True si le téléchargement des extensions inconnues est autorisé."""
    if settings is None:
        settings = load_rgsx_settings()
    return bool(settings.get("allow_unknown_extensions", False))


def set_allow_unknown_extensions(enabled: bool) -> bool:
    """Active/désactive le téléchargement des extensions inconnues et sauvegarde."""
    settings = load_rgsx_settings()
    settings["allow_unknown_extensions"] = bool(enabled)
    save_rgsx_settings(settings)
    return settings["allow_unknown_extensions"]

# ----------------------- Hide premium systems toggle ----------------------- #

def get_hide_premium_systems(settings=None) -> bool:
    """Retourne True si le masquage des systèmes premium est activé."""
    if settings is None:
        settings = load_rgsx_settings()
    return bool(settings.get("hide_premium_systems", False))


def set_hide_premium_systems(enabled: bool) -> bool:
    """Active/désactive le masquage des systèmes premium et sauvegarde."""
    settings = load_rgsx_settings()
    settings["hide_premium_systems"] = bool(enabled)
    save_rgsx_settings(settings)
    return settings["hide_premium_systems"]

# ----------------------- Display layout (grid) ----------------------- #

def get_display_grid(settings=None):
    """Retourne (cols, rows) pour la grille d'affichage, par défaut (3,4)."""
    if settings is None:
        settings = load_rgsx_settings()
    disp = settings.get("display", {})
    grid = disp.get("grid", "3x4")
    try:
        cols, rows = map(int, grid.lower().split("x"))
        return cols, rows
    except Exception:
        return 3, 4

def set_display_grid(cols: int, rows: int):
    """Définit et sauvegarde la grille d'affichage (cols x rows) parmi options autorisées."""
    allowed = {(3,3), (3,4), (4,3), (4,4)}
    if (cols, rows) not in allowed:
        cols, rows = 3, 4
    settings = load_rgsx_settings()
    disp = settings.setdefault("display", {})
    disp["grid"] = f"{cols}x{rows}"
    save_rgsx_settings(settings)
    return cols, rows

def get_font_family(settings=None):
    if settings is None:
        settings = load_rgsx_settings()
    return settings.get("display", {}).get("font_family", "pixel")

def set_font_family(family: str):
    settings = load_rgsx_settings()
    disp = settings.setdefault("display", {})
    disp["font_family"] = family
    save_rgsx_settings(settings)
    return family

# ----------------------- ROMs folder (custom path) ----------------------- #

def get_roms_folder(settings=None):
    """Retourne le chemin du dossier ROMs personnalisé (ou chaîne vide si par défaut)."""
    if settings is None:
        settings = load_rgsx_settings()
    return settings.get("roms_folder", "").strip()

def set_roms_folder(path: str):
    """Définit le chemin du dossier ROMs personnalisé et sauvegarde."""
    settings = load_rgsx_settings()
    settings["roms_folder"] = path.strip()
    save_rgsx_settings(settings)
    return path.strip()

def get_language(settings=None):
    """Retourne la langue configurée (par défaut 'en')."""
    if settings is None:
        settings = load_rgsx_settings()
    return settings.get("language", "en")

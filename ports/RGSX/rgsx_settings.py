#!/usr/bin/env python3
"""
Module de gestion des paramètres RGSX
Gère le fichier unifié rgsx_settings.json qui remplace les anciens fichiers :
- accessibility.json
- language.json 
- music_config.json
- symlink_settings.json
"""

import json
import os
import logging

logger = logging.getLogger(__name__)


def load_rgsx_settings():
    """Charge tous les paramètres depuis rgsx_settings.json."""
    from config import RGSX_SETTINGS_PATH
    
    default_settings = {
        "language": "fr",
        "music_enabled": True,
        "accessibility": {
            "font_scale": 1.0
        },
        "symlink": {
            "enabled": False,
            "target_directory": ""
        },
        "sources": {  
            "mode": "rgsx",       
            "custom_url": ""      
        }
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

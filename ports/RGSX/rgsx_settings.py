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
        else:
            # Tenter de migrer depuis les anciens fichiers
            migrated_settings = migrate_old_settings()
            if migrated_settings:
                save_rgsx_settings(migrated_settings)
                return migrated_settings
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


def migrate_old_settings():
    """Migre les anciens fichiers de configuration vers le nouveau format."""
    from config import LANGUAGE_CONFIG_PATH, MUSIC_CONFIG_PATH, ACCESSIBILITY_FOLDER, SYMLINK_SETTINGS_PATH
    
    migrated_settings = {
        "language": "en",
        "music_enabled": True,
        "accessibility": {
            "font_scale": 1.0
        },
        "symlink": {
            "enabled": False,
            "target_directory": ""
        }
    }
    
    files_to_remove = []  # Liste des fichiers à supprimer après migration réussie
    
    # Migrer language.json
    if os.path.exists(LANGUAGE_CONFIG_PATH):
        try:
            with open(LANGUAGE_CONFIG_PATH, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # Gérer le cas où le fichier contient juste une chaîne (pas de JSON)
                if content.startswith('"') and content.endswith('"'):
                    migrated_settings["language"] = content.strip('"')
                elif not content.startswith('{'):
                    # Fichier texte simple sans guillemets
                    migrated_settings["language"] = content
                else:
                    # Fichier JSON normal
                    lang_data = json.loads(content)
                    migrated_settings["language"] = lang_data.get("language", "en")
            files_to_remove.append(LANGUAGE_CONFIG_PATH)
        except:
            pass
    
    # Migrer music_config.json
    if os.path.exists(MUSIC_CONFIG_PATH):
        try:
            with open(MUSIC_CONFIG_PATH, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                # Gérer le cas où le fichier contient juste un booléen
                if content.lower() in ['true', 'false']:
                    migrated_settings["music_enabled"] = content.lower() == 'true'
                else:
                    # Fichier JSON normal
                    music_data = json.loads(content)
                    migrated_settings["music_enabled"] = music_data.get("music_enabled", True)
            files_to_remove.append(MUSIC_CONFIG_PATH)
        except:
            pass
    
    # Migrer accessibility.json
    if os.path.exists(ACCESSIBILITY_FOLDER):
        try:
            with open(ACCESSIBILITY_FOLDER, 'r', encoding='utf-8') as f:
                acc_data = json.load(f)
                migrated_settings["accessibility"] = {
                    "font_scale": acc_data.get("font_scale", 1.0)
                }
            files_to_remove.append(ACCESSIBILITY_FOLDER)
        except:
            pass
    
    # Migrer symlink_settings.json
    if os.path.exists(SYMLINK_SETTINGS_PATH):
        try:
            with open(SYMLINK_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                symlink_data = json.load(f)
                migrated_settings["symlink"] = {
                    "enabled": symlink_data.get("use_symlink_path", False),
                    "target_directory": symlink_data.get("target_directory", "")
                }
            files_to_remove.append(SYMLINK_SETTINGS_PATH)
        except:
            pass
    
    # Supprimer les anciens fichiers après migration réussie
    if files_to_remove:
        print(f"Migration réussie. Suppression des anciens fichiers de configuration...")
        for file_path in files_to_remove:
            try:
                os.remove(file_path)
                print(f"  - Supprimé: {os.path.basename(file_path)}")
            except Exception as e:
                print(f"  - Erreur lors de la suppression de {os.path.basename(file_path)}: {e}")
    
    return migrated_settings


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

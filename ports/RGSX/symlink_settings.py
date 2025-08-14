import os
import json
import logging
import config
from language import _

logger = logging.getLogger(__name__)

# Path for symlink settings
SYMLINK_SETTINGS_PATH = os.path.join(config.SAVE_FOLDER, "symlink_settings.json")

def load_symlink_settings():
    """Load symlink settings from file."""
    try:
        if os.path.exists(SYMLINK_SETTINGS_PATH):
            with open(SYMLINK_SETTINGS_PATH, 'r', encoding='utf-8') as f:
                settings = json.load(f)
                if not isinstance(settings, dict):
                    settings = {}
                if "use_symlink_path" not in settings:
                    settings["use_symlink_path"] = False
                return settings
    except Exception as e:
        logger.error(f"Error loading symlink settings: {str(e)}")
    
    # Return default settings (disabled)
    return {"use_symlink_path": False}

def save_symlink_settings(settings):
    """Save symlink settings to file."""
    try:
        os.makedirs(config.SAVE_FOLDER, exist_ok=True)
        with open(SYMLINK_SETTINGS_PATH, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        logger.debug(f"Symlink settings saved: {settings}")
        return True
    except Exception as e:
        logger.error(f"Error saving symlink settings: {str(e)}")
        return False

def set_symlink_option(enabled):
    """Enable or disable the symlink option."""
    settings = load_symlink_settings()
    settings["use_symlink_path"] = enabled
    
    if save_symlink_settings(settings):
        return True, _("symlink_settings_saved_successfully")
    else:
        return False, _("symlink_settings_save_error")

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

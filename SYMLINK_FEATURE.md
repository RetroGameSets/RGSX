# Symlink Option Feature

## Overview

This feature adds a simple toggle option to append the platform folder name to the download path, creating a symlink-friendly structure for external storage.

## How It Works

When the symlink option is **disabled** (default):
- Super Nintendo ROMs download to: `../roms/snes/`
- PlayStation 2 ROMs download to: `../roms/ps2/`

When the symlink option is **enabled**:
- Super Nintendo ROMs download to: `../roms/snes/snes/`
- PlayStation 2 ROMs download to: `../roms/ps2/ps2/`

This allows users to create symlinks from the platform folder to external storage locations.

## Usage

1. Open the pause menu (P key or Start button)
2. Navigate to "Symlink Option" (second to last option, before Quit)
3. Press Enter to toggle the option on/off
4. The menu will show the current status: "Symlink option enabled" or "Symlink option disabled"

## Implementation Details

### Files Added
- `symlink_settings.py` - Core functionality for managing the symlink option

### Files Modified
- `display.py` - Added symlink option to pause menu with dynamic status display
- `controls.py` - Added handling for symlink option toggle
- `network.py` - Modified download functions to use symlink paths when enabled
- Language files - Added translation strings for all supported languages

### Configuration

The symlink setting is stored in `symlink_settings.json` in the save folder:

```json
{
  "use_symlink_path": false
}
```

### API Functions

- `get_symlink_option()` - Get current symlink option status
- `set_symlink_option(enabled)` - Enable/disable the symlink option
- `apply_symlink_path(base_path, platform_folder)` - Apply symlink path modification

## Example Use Case

1. Enable the symlink option
2. **Optional**: Create a symlink: `ln -s /external/storage/snes ../roms/snes/snes`
   - If you don't create the symlink, the nested directories will be created automatically when you download ROMs
3. Download ROMs - the nested directories (like `../roms/snes/snes/`) will be created automatically if they don't exist
4. Now Super Nintendo ROMs will download to the external storage via the symlink (if created) or to the local nested directory

## Features

- **Simple Toggle**: Easy on/off switch in the pause menu
- **Persistent Settings**: Option is remembered between sessions
- **Multi-language Support**: Full internationalization
- **Backward Compatible**: Disabled by default, doesn't affect existing setups
- **Platform Agnostic**: Works with all platforms automatically
- **Automatic Directory Creation**: Nested directories are created automatically if they don't exist

## Technical Notes

- The option is disabled by default
- Settings are stored in JSON format
- Path modification is applied at download time
- Works with both regular downloads and 1fichier downloads
- No impact on existing ROMs or folder structure
- Missing directories are automatically created using `os.makedirs(dest_dir, exist_ok=True)`

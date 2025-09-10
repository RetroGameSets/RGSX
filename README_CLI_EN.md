# RGSX CLI — Usage Guide

This guide covers all available CLI commands with copy-ready Windows PowerShell examples.

## Prerequisites
- Python installed and on PATH (the app runs in headless mode; no window will open).
- Run commands from the folder that contains `rgsx_cli.py`.

## General syntax
Global options can be placed before or after the subcommand.

- Form 1:
  ```powershell
  python rgsx_cli.py [--verbose] [--force-update|-force-update] <command> [options]
  ```
- Form 2:
  ```powershell
  python rgsx_cli.py <command> [options] [--verbose] [--force-update|-force-update]
  ```

- `--verbose` enables detailed logs (DEBUG) on stderr.
- `--force-update` (or `-force-update`) purges local data and re-downloads the data pack (systems_list, games/*.json, images).

When source data is missing, the CLI will automatically download and extract the data pack (with progress).

## Commands

### 1) platforms — list platforms
- Options:
  - `--json`: JSON output (objects `{ name, folder }`).

Examples:
```powershell
python rgsx_cli.py platforms
python rgsx_cli.py platforms --json
python rgsx_cli.py --verbose platforms
python rgsx_cli.py platforms --verbose
```

Text output: one line per platform, formatted as `Name<TAB>Folder`.

### 2) games — list games for a platform
- Options:
  - `--platform <name_or_folder>` (e.g., `n64` or "Nintendo 64").
  - `--search <text>`: filter by substring in game title.

Examples:
```powershell
python rgsx_cli.py games --platform n64
python rgsx_cli.py games --platform "Nintendo 64" --search zelda
python rgsx_cli.py games --platform n64 --verbose
```

Notes:
- The platform is resolved by display name (platform_name) or folder, case-insensitively.

### 3) download — download a game
- Options:
  - `--platform <name_or_folder>`
  - `--game "<exact or partial title>"`
  - `--force`: ignore unsupported-extension warning for the platform.

Examples:
```powershell
# Exact title
python rgsx_cli.py download --platform n64 --game "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Partial match
# If no exact title is found, the CLI no longer auto-selects; it displays suggestions.
python rgsx_cli.py download --platform n64 --game "Ocarina of Time (Beta)"
# ➜ The CLI shows a list of candidates (then run again with the exact title).

Interactive mode by default:
- If no exact title is found and you are in an interactive terminal (TTY), a numbered list is shown automatically so you can pick and start the download.

# Force if the file extension seems unsupported (e.g., .rar)
python rgsx_cli.py download --platform snes --game "pack_roms.rar" --force

# Verbose placed after the subcommand
python rgsx_cli.py download --platform n64 --game "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip" --verbose
```

During download, progress %, size (MB) and speed (MB/s) are shown. The final result is also written to history.

Notes:
- ROMs are saved into the corresponding platform directory (e.g., `R:\roms\n64`).
- If the file is an archive (zip/rar) and the platform doesn’t support that extension, a warning is shown (you can use `--force`).

### 4) history — show history
- Options:
  - `--tail <N>`: last N entries (default: 50)
  - `--json`: JSON output

Examples:
```powershell
python rgsx_cli.py history
python rgsx_cli.py history --tail 20
python rgsx_cli.py history --json
```

### 5) clear-history — clear history
Example:
```powershell
python rgsx_cli.py clear-history
```

### Global option: --force-update — purge + re-download data
- Removes `systems_list.json`, the `games/` and `images/` folders, then downloads/extracts the data pack again.

Examples:
```powershell
# Without subcommand: purge + re-download then exit
python rgsx_cli.py --force-update

# Placed after a subcommand (also accepted)
python rgsx_cli.py platforms --force-update
```

## Behavior and tips
- Platform resolution: by display name or folder, case-insensitive. For `games` and `download`, if no exact match is found a search-like suggestion list is shown.
- `--verbose` logs: most useful during downloads/extraction; printed at DEBUG level.
- Missing data download: automatic, with consistent progress (download then extraction).
- Exit codes (indicative):
  - `0`: success
  - `1`: download failure/generic error
  - `2`: platform not found
  - `3`: game not found
  - `4`: unsupported extension (without `--force`)

## Quick examples (copy/paste)
```powershell
# List platforms (text)
python rgsx_cli.py platforms

# List platforms (JSON)
python rgsx_cli.py platforms --json

# List N64 games with filter
python rgsx_cli.py games --platform n64 --search zelda

# Download an N64 game (exact title)
python rgsx_cli.py download --platform n64 --game "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Download with approximate title (suggestions + interactive pick)
python rgsx_cli.py download --platform n64 --game "Ocarina of Time"

# View last 20 history entries
python rgsx_cli.py history --tail 20

# Purge and refresh data pack
python rgsx_cli.py --force-update
```

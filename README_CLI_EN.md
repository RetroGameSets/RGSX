# RGSX CLI — Usage Guide

This guide covers all available CLI commands with copy-ready Windows PowerShell examples.

## Prerequisites
- Python installed and on PATH (the app runs in headless mode; no window will open).
- Run commands from the folder that contains `rgsx_cli.py`.

## Quick interactive mode (new)
You can now start an interactive shell once and issue multiple commands without retyping `python rgsx_cli.py` each time:

```powershell
python rgsx_cli.py
```
You will see a prompt like:
```
RGSX CLI interactive mode. Type 'help' for commands, 'exit' to quit.
rgsx>
```
Inside this shell type subcommands exactly as you would after `python rgsx_cli.py`:
```
rgsx> platforms
rgsx> games --platform snes --search mario
rgsx> download --platform snes --game "Super Mario World (USA).zip"
rgsx> history --tail 10
rgsx> exit
```
Extras:
- `help` or `?` prints the global help.
- `exit` or `quit` leaves the shell.
- `--verbose` once sets persistent verbose logging for the rest of the session.

## Formatted table output (platforms)
The `platforms` command now renders a fixed-width ASCII table (unless `--json` is used):
```
+--------------------------------+-----------------+
| Platform Name                  | Folder          |
+--------------------------------+-----------------+
| Nintendo Entertainment System  | nes             |
| Super Nintendo Entertainment.. | snes            |
| Sega Mega Drive                | megadrive       |
+--------------------------------+-----------------+
```
Columns: 30 chars for name, 15 for folder (values longer are truncated with `...`).

## Aliases & option synonyms (updated)
Subcommand aliases:
- `platforms` → `p`
- `games` → `g`
- `download` → `dl`
- `clear-history` → `clear`

Option aliases (all shown forms are accepted; they are equivalent):
- Platform: `--platform`, `--p`, `-p`
- Game: `--game`, `--g`, `-g`
- Search: `--search`, `--s`, `-s`
- Force (download): `--force`, `-f`
- Interactive (download): `--interactive`, `-i`

Examples with aliases:
```powershell
python rgsx_cli.py dl -p snes -g "Super Mario World (USA).zip"
python rgsx_cli.py g --p snes --s mario
python rgsx_cli.py p --json
python rgsx_cli.py clear
```

## Ambiguous download selection (new table)
When you attempt a download with a non-exact title and interactive mode is active (TTY or `--interactive`), matches are displayed in a table:
```
No exact result found for this game: mario super  yoshi
Select a match to download:
+------+--------------------------------------------------------------+------------+
| #    | Title                                                        | Size       |
+------+--------------------------------------------------------------+------------+
| 1    | Super Mario - Yoshi Island (Japan).zip                       | 3.2M       |
| 2    | Super Mario - Yoshi Island (Japan) (Rev 1).zip               | 3.2M       |
| 3    | Super Mario - Yoshi Island (Japan) (Rev 2).zip               | 3.2M       |
| 4    | Super Mario World 2 - Yoshi's Island (USA).zip               | 3.3M       |
| 5    | Super Mario - Yoshi Island (Japan) (Beta) (1995-07-10).zip   | 3.1M       |
+------+--------------------------------------------------------------+------------+
Enter number (or press Enter to cancel):
```
If you cancel or are not in interactive mode, a similar table is still shown (without the prompt) followed by a tip.

## Improved fuzzy search for games (multi-token)
The `--search` / `--s` / `-s` option now uses the same multi-strategy ranking as the download suggestion logic:
1. Substring match (position-based) — highest priority
2. Ordered non-contiguous token sequence (smallest gap wins)
3. All tokens present in any order (smaller token set size wins)

Duplicate titles are deduplicated by keeping the best scoring strategy. This means queries like:
```powershell
python rgsx_cli.py games --p snes --s "super mario yoshi"
```
will surface all relevant "Super Mario World 2 - Yoshi's Island" variants even if the word order differs.

Example output:
```
+--------------------------------------------------------------+------------+
| Game Title                                                   | Size       |
+--------------------------------------------------------------+------------+
| Super Mario World 2 - Yoshi's Island (USA).zip               | 3.3M       |
| Super Mario World 2 - Yoshi's Island (Europe) (En,Fr,De).zip | 3.3M       |
| Super Mario - Yoshi Island (Japan).zip                       | 3.2M       |
| Super Mario - Yoshi Island (Japan) (Rev 1).zip               | 3.2M       |
| Super Mario - Yoshi Island (Japan) (Rev 2).zip               | 3.2M       |
+--------------------------------------------------------------+------------+
```
If no results are found the table displays only headers followed by a message.

## General syntax (non-interactive)
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

### 1) platforms (`platforms` / `p`) — list platforms
- Options:
  - `--json`: JSON output (objects `{ name, folder }`).

Examples:
```powershell
python rgsx_cli.py platforms
python rgsx_cli.py p --json
python rgsx_cli.py --verbose p
python rgsx_cli.py p --verbose
```

Text output: one line per platform, formatted as `Name<TAB>Folder`.

### 2) games (`games` / `g`) — list games for a platform
- Options:
  - `--platform | --p | -p <name_or_folder>` (e.g., `n64` or "Nintendo 64").
  - `--search | --s | -s <text>`: filter by substring in game title.

Examples:
```powershell
python rgsx_cli.py games --platform n64
python rgsx_cli.py g --p "Nintendo 64" --s zelda
python rgsx_cli.py g -p n64 --verbose
```

Notes:
- The platform is resolved by display name (platform_name) or folder, case-insensitively.

### 3) download (`download` / `dl`) — download a game
- Options:
  - `--platform | --p | -p <name_or_folder>`
  - `--game | --g | -g "<exact or partial title>"`
  - `--force | -f`: ignore unsupported-extension warning for the platform.
  - `--interactive | -i`: prompt to choose from matches when no exact title is found.

Examples:
```powershell
# Exact title
python rgsx_cli.py dl --p n64 --g "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Partial match (interactive numbered selection if no exact match)
python rgsx_cli.py dl -p n64 -g "Ocarina of Time (Beta)"

# Forced despite extension
python rgsx_cli.py dl -p snes -g "pack_roms.rar" -f

# Verbose after subcommand
python rgsx_cli.py dl -p n64 -g "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip" --verbose
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

### 5) clear-history (`clear-history` / `clear`) — clear history
Example:
```powershell
python rgsx_cli.py clear
```

### Global option: --force-update — purge + re-download data
- Removes `systems_list.json`, the `games/` and `images/` folders, then downloads/extracts the data pack again.

Examples:
```powershell
# Without subcommand: purge + re-download then exit
python rgsx_cli.py --force-update

# Placed after a subcommand (also accepted)
python rgsx_cli.py p --force-update
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
# Start interactive shell
python rgsx_cli.py

# List platforms (text)
python rgsx_cli.py p

# List platforms (JSON)
python rgsx_cli.py p --json

# List N64 games with filter (using alias synonyms)
python rgsx_cli.py g --p n64 --s zelda

# Download an N64 game (exact title) using aliases
python rgsx_cli.py dl --p n64 --g "Legend of Zelda, The - Ocarina of Time (USA) (Beta).zip"

# Download with approximate title (suggestions + interactive pick)
python rgsx_cli.py dl -p n64 -g "Ocarina of Time"

# View last 20 history entries
python rgsx_cli.py history --tail 20

# Purge and refresh data pack
python rgsx_cli.py --force-update
```

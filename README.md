# 🎮 Retro Game Sets Xtra (RGSX)

## SUPPORT / HELP: https://discord.gg/Vph9jwg3VV

RGSX is a Python application using Pygame for its graphical interface, created by and for the RetroGameSets community. It is completely free.

The application currently supports multiple download sources such as myrient and 1fichier (with optional unlocking / fallback via AllDebrid and Real-Debrid). Sources can be updated frequently.

---

## ✨ Features

- **Game downloads**: Supports ZIP files and handles unsupported raw archives automatically based on allowed extensions defined in EmulationStation's `es_systems.cfg` (and custom `es_systems_*.cfg` on Batocera). RGSX reads the per‑system allowed extensions and extracts archives automatically if the target system does not support zipped files.
  - Most downloads require no account or authentication.
  - Systems tagged with `(1fichier)` in their name require a valid API key (1Fichier, AllDebrid or Real-Debrid) for premium links.

---
> ## IMPORTANT (1Fichier / AllDebrid / Real-Debrid)
> To download from 1Fichier links you may use one of: your 1Fichier API key, an AllDebrid API key (automatic fallback), or a Real-Debrid API key (fallback if others missing / limited).
>
> Where to paste your API key (file must contain ONLY the key):
> - `/saves/ports/rgsx/1FichierAPI.txt` (1Fichier API key)
> - `/saves/ports/rgsx/AllDebridAPI.txt` (AllDebrid API key – optional fallback)
> - `/saves/ports/rgsx/RealDebridAPI.txt` (Real-Debrid API key – optional fallback)
>
> Do NOT create these files manually. Launch RGSX once: it will auto‑create the empty files if they are missing. Then open the relevant file and paste your key.
---

**🧰 Command Line (CLI) Usage**

RGSX also provides a headless command‑line interface to list platforms/games and download ROMs:

- French CLI guide: https://github.com/RetroGameSets/RGSX/blob/main/README_CLI.md
- English CLI guide: https://github.com/RetroGameSets/RGSX/blob/main/README_CLI_EN.md

- **Download history**: View all current and past downloads.
- **Multi‑selection downloads**: Mark several games using the key mapped to Clear History (default X) to prepare a batch, then Confirm to launch sequential downloads.
- **Control customization**: Remap keyboard / controller buttons; many popular pads are auto‑configured on first launch.
- **Platform grid layouts**: Switch between 3x3, 3x4, 4x3, 4x4.
- **Hide unsupported systems**: Automatically hides systems whose ROM folder is missing (toggle in Display menu).
- **Change font & size**: Accessibility & readability adjustments directly in the menu.
- **Search / filter mode**: Quickly filter games by name; includes on‑screen virtual keyboard for controllers.
- **Multi‑language interface**: Switch language any time in the menu.
- **Adaptive interface**: Scales cleanly from 800x600 up to 1080p (higher resolutions untested but should work).
- **Auto update & restart**: The application restarts itself after applying an update.
- **System & extension discovery**: On first run, RGSX parses `es_systems.cfg` (Batocera / RetroBat) and generates `/saves/ports/rgsx/rom_extensions.json` plus the supported systems list.

---

## 🖥️ Requirements

### Operating System
- Batocera / Knulli or RetroBat

### Hardware
- PC, Raspberry Pi, handheld console...
- Controller (recommended) or keyboard
- Active internet connection

### Disk Space
- ~100 MB for the application (additional space for downloaded games)

---

## 🚀 Installation

### Automatic Method (Batocera / Knulli)

On the target system:
- On Batocera PC: open an xTERM (F1 > Applications > xTERM), or
- From another machine: connect via SSH (root / linux) using PuTTY, PowerShell, etc.

Run:
`curl -L bit.ly/rgsx-install | sh`

Wait for the script to finish (log file and on‑screen output). Then update the game list via:
`Menu > Game Settings > Update game list`

You will find RGSX under the "PORTS" or "Homebrew and ports" system. Physical paths created: `/roms/ports/RGSX` (and `/roms/windows/RGSX` on RetroBat environments as needed).

### Manual Method (RetroBat / Batocera)

1. Download ZIP: https://github.com/RetroGameSets/RGSX/archive/refs/heads/main.zip
2. Extract into your ROMS folder:
   - Batocera: only extract the `ports` folder contents
   - RetroBat: extract both `ports` and `windows`
3. Ensure you now have: `/roms/ports/RGSX` and (RetroBat) `/roms/windows/RGSX`
4. Update the game list: `Menu > Game Settings > Update game list`

---

## 🏁 First Launch

- RGSX appears in the "WINDOWS" system on RetroBat, and in "PORTS" / "Homebrew and ports" on Batocera/Knulli.
- On first launch, if your controller matches a predefined profile in `/roms/ports/RGSX/assets/controls`, mapping is auto‑imported.
- The app then downloads required data (system images, game lists, etc.).
- If controls act strangely or are corrupt, delete `/saves/ports/rgsx/controls.json` and restart (it will be regenerated).

INFO (RetroBat only): On the first run, Python (~50 MB) is downloaded into `/system/tools/python`. The screen may appear frozen on the loading splash for several seconds—this is normal. Installation output is logged in `/roms/ports/RGSX-INSTALL.log` (share this if you need support).

---

## 🕹️ Usage

### Menu Navigation

- Use D‑Pad / Arrow keys to move between platforms, games, and options.
- Press the Start key (default: `P` or controller Start) for the pause menu with all configuration options.
- From the pause menu you can regenerate cached system/game/image lists to pull latest updates.

### Display Menu

- Layout: switch platform grid (3x3, 3x4, 4x3, 4x4)
- Font size: adjust text scale (accessibility)
- Show unsupported systems: toggle systems whose ROM directory is missing
- Filter systems: persistently include/exclude systems by name

### Downloading Games

1. Select a platform then a game
2. Press the Confirm key (default: Enter / A) to start downloading
3. (Optional) Press the Clear History key (default: X) on multiple games to toggle multi‑selection ([X] marker), then Confirm to launch a sequential batch
4. Track progress in the HISTORY menu

### Control Customization

- Open pause menu → Reconfigure controls
- Hold each desired key/button for ~3 seconds when prompted
- Button labels adapt to your pad (A/B/X/Y, LB/RB/LT/RT, etc.)
- Delete `/saves/ports/rgsx/controls.json` if mapping breaks; restart to regenerate

### History

- Access from pause menu or press the History key (default: H)
- Select an entry to re‑download (e.g. after an error or cancellation)
- CLEAR button empties the list only (does not delete installed games)
- BACK cancels an active download

### Logs

Logs are stored at: `/roms/ports/RGSX/logs/RGSX.log` (provide this for troubleshooting).

---

## 🔄 Changelog
See Discord or GitHub commits for the latest changes.

---

## 🌐 Custom Game Sources
Switch the game source in the pause menu (Game Source: RGSX / Custom).

Custom mode expects an HTTP/HTTPS ZIP URL pointing to a sources archive mirroring the default structure. Configure in:
`{rgsx_settings path}` → key: `sources.custom_url`

Behavior:
- If custom mode is selected and URL is empty/invalid → empty list + popup (no fallback)
- Fix the URL then choose "Update games list" (restart if prompted)

Example `rgsx_settings.json` snippet:
```json
"sources": {
  "mode": "custom",
  "custom_url": "https://example.com/my-sources.zip"
}
```
Switch back to RGSX mode any time via the pause menu.

---

## 📁 Project Structure
```
/roms/windows/RGSX
│
├── RGSX Retrobat.bat          # Windows/RetroBat launcher (not needed on Batocera/Knulli)

/roms/ports/
├── RGSX-INSTALL.log           # Install log (first scripted install)
└── RGSX/
    ├── __main__.py            # Main entry point
    ├── controls.py            # Input handling & menu navigation events
    ├── controls_mapper.py     # Interactive control remapping & auto button naming
    ├── display.py             # Pygame rendering layer
    ├── config.py              # Global paths / parameters
    ├── rgsx_settings.py       # Unified settings manager
    ├── network.py             # Download logic (multi-provider, fallback)
    ├── history.py             # Download history store & UI logic
    ├── language.py            # Localization manager
    ├── accessibility.py       # Accessibility options (fonts, layout)
    ├── utils.py               # Helper utilities (text wrapping, truncation, etc.)
    ├── update_gamelist.py     # Game list updater (Batocera/Knulli)
    ├── update_gamelist_windows.py # RetroBat gamelist auto-update on launch
    ├── assets/                # Fonts, binaries, music, predefined control maps
    ├── languages/             # Translation files
    └── logs/
        └── RGSX.log           # Runtime log

/saves/ports/RGSX/
├── systems_list.json          # Discovered systems / folders / images
├── games/                     # Platform game link repositories
├── images/                    # Downloaded platform images
├── rgsx_settings.json         # Unified config (settings, language, music, symlinks, sources)
├── controls.json              # Generated control mapping
├── history.json               # Download history database
├── rom_extensions.json        # Allowed ROM extensions cache from es_systems.cfg
├── 1FichierAPI.txt            # 1Fichier API key (empty until you paste key)
├── AllDebridAPI.txt           # AllDebrid API key (optional fallback)
└── RealDebridAPI.txt          # Real-Debrid API key (optional fallback)
```

---

## 🤝 Contributing

### Report a Bug
1. Review `/roms/ports/RGSX/logs/RGSX.log`.
2. Open a GitHub issue with a clear description + relevant log excerpt OR share it on Discord.

### Propose a Feature
- Open an issue (or discuss on Discord first) describing the feature and its integration.

### Contribute Code
1. Fork the repository & create a feature branch:
```bash
git checkout -b feature/your-feature-name
```
2. Test on Batocera / RetroBat.
3. Open a Pull Request with a detailed summary.

---

## ⚠️ Known Issues
- (None currently listed)

---

## 📝 License
This project is free software. You are free to use, modify, and distribute it under the terms of the included license.

Developed with ❤️ for retro gaming enthusiasts.
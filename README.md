# 🎮 Retro Game Sets Xtra (RGSX)

## SUPPORT / HELP : https://discord.gg/Vph9jwg3VV
## LISEZ-MOI EN FRANCAIS : https://github.com/RetroGameSets/RGSX/blob/main/README_FR.md

RGSX is a Python application developed using Pygame for graphics, created for the community by RetroGameSets. It is completely free.

The application supports multiple sources like myrient and 1fichier. These sources can be updated frequently.

---

## ✨ Features

- **Game downloads** : Support for ZIP files and handling of unsupported extensions thanks to the `info.txt` file in each folder (batocera), which automatically extracts if the system doesn't support archives.
  - Downloads require no authentication or account for most sources.
  - Systems marked `(1fichier)` in the name will only be accessible if you provide your 1fichier API key (see below).
- **Download history** : View and re-download previous files.
- **Multi-select downloads** : Mark multiple games in the game list with the key mapped to Clear History (default X) to enqueue several downloads in one batch. Press Confirm to start batch.
- **Control customization** : Remap keyboard or controller keys to your preference with automatic button name detection from EmulationStation (beta).
- **Font size adjustment** : If you find the text too small/too large, you can change it in the menu.
- **Search mode** : Filter games by name for quick navigation with virtual keyboard on controller.
- **Multilingual support** : Interface available in multiple languages. You can choose the language in the menu.
- **Error handling** with informative messages and LOG file.
- **Adaptive interface** : The interface adapts to all resolutions from 800x600 to 4K (not tested beyond 1920x1080).
- **Automatic updates** : the application must be restarted after an update.

---

## 🖥️ Requirements

### Operating System
- Batocera / Knulli or Retrobat

### Hardware
- PC, Raspberry Pi, handheld console...
- Controller (optional, but recommended for optimal experience) or Keyboard.
- Active internet connection

### Disk Space
- 100 MB for the application.

---

## 🚀 Installation

### Method 1: Automatic command line installation for Batocera/Knulli

- On batocera x86 PC access F1>Applications>xTERM or
- From another PC on the network with Putty, powershell SSH or other application

Enter the command:
## `curl -L bit.ly/rgsx-install | sh`
  
Wait and watch the return on screen or on the command (to be improved).  
Update the game list via: `Menu > Game Settings > Update game list`.  
You will find RGSX in the "PORTS" system or "Homebrew and ports" and in `/roms/ports/RGSX`

---

### Method 2: Manual copy (Mandatory method on retrobat)

- Download the repository content as zip: https://github.com/RetroGameSets/RGSX/archive/refs/heads/main.zip
- Extract the zip file into the ROMS folder (for Batocera, only the PORTS folder will be used, for Retrobat you will need to extract PORTS and WINDOWS)
- Update the game list via the menu:  
  `Game Settings > Update list`.


## 🏁 First startup
---
> ## IMPORTANT
> If you have a 1Fichier API key, you must enter it in  
> `/saves/ports/rgsx/1FichierAPI.txt`  
> if you want to download from 1Fichier links.
---

- Launch RGSX from ports on batocera, from Windows on Retrobat.
- On first launch, the application will automatically import the control configuration from EmulationStation if available.
- Configure controls if necessary. They can be reconfigured via the pause menu later.
- Delete the `/saves/ports/rgsx/controls.json` file in case of problems then restart the application.
- The application will then automatically download all necessary data.

INFO: for retrobat on first launch, the application will download Python in the /system/tools/python folder which is necessary to run the application. The file is about 50MB and downloads quite quickly but there is no visual feedback on screen, which will remain frozen on the RGSX loading for a few seconds.
---

## 🕹️ Usage

### Menu navigation

- Use the directional keys (D-Pad, keyboard arrows) to navigate between platforms, games and options.
- Press the key configured as start (default, **P** or Start button on controller) to open the pause menu.
- From the pause menu, access history, control help (control display changes depending on which menu you're in) or reconfiguration of keys, languages, font size.
- You can also, from the menu, regenerate the cache of the systems/games/images list to be sure to have the latest updates.

---

### Download

- Select a platform, then a game.
- Press the confirm key (default, **Enter** or **A** button) to start the download.
- Optional: Press the key mapped to Clear History (default **X**) on several games to toggle multi-selection ([X] marker). Then press Confirm to launch a sequential batch download.
- Follow the progress in the `HISTORY` menu.

---

### Control customization

- In the pause menu, select **Reconfigure controls**.
- Follow the on-screen instructions to map each action by holding the key or button for 3 seconds.
- Button names are automatically displayed according to your controller (A, B, X, Y, LB, RB, LT, RT, etc.).
- The configuration is compatible with all controllers supported by EmulationStation.

---

### History

- Access download history via the pause menu or by pressing the history key (default, **H**).
- Select a game to re-download it if necessary in case of error or cancellation.
- Clear all history via the **CLEAR** button in the history menu. Games are not deleted, only the list.
- Cancel a download with the **BACK** button.

---

### Logs

Logs are saved in `roms/ports/RGSX/logs/RGSX.log` on batocera and on Retrobat to diagnose problems and should be shared for any support.

---

## 📁 Project structure
```
/roms/windows/RGSX
│
├── RGSX Retrobat.bat    # Shortcut to launch RGSX application for retrobat only, not necessary for batocera/knulli

/roms/ports/
RGSX-INSTALL.log         # Installation LOG only for a first command line installation.
RGSX/
│
├── __main__.py          # Main entry point of the application.
├── controls.py          # Keyboard/controller/mouse event handling and menu navigation.
├── controls_mapper.py   # Control configuration with automatic button name detection.
├── es_input_parser.py   # EmulationStation configuration parser for automatic control import.
├── display.py           # Pygame graphics interface rendering.
├── config.py            # Global configuration (paths, parameters, etc.).
├── rgsx_settings.py     # Unified application settings management.
├── network.py           # Game download management.
├── history.py           # Download history management.
├── language.py          # Multilingual support management.
├── accessibility.py     # Accessibility settings management.
├── utils.py             # Utility functions (text wrap, truncation etc.).
├── update_gamelist.py   # Game list update.
├── assets/              # Application resources (fonts, executables, music).
├── games/               # Game system configuration files.
├── images/              # System images.
├── languages/           # Translation files.
└── logs/
    └── RGSX.log         # Log file.

/saves/ports/RGSX/
│
├── rgsx_settings.json   # Unified configuration file (settings, accessibility, language, music, symlinks).
├── controls.json        # Control mapping file (generated after first startup).
├── history.json         # Download history database (generated after first download).
└── 1FichierAPI.txt      # 1fichier API key (premium account and + only) (empty by default).
```





---

## 🤝 Contributing

### Report a bug

1. Check the logs in `/roms/ports/RGSX/logs/RGSX.log`.
2. Open an issue on GitHub with a detailed description and relevant logs.

### Propose a feature

- Submit an issue with a clear description of the proposed feature.
- Explain how it integrates into the application.

### Contribute to the code

1. Fork the repository and create a branch for your feature or fix:
```bash
git checkout -b feature/your-feature-name
```
2. Test your changes on Batocera.
3. Submit a pull request with a detailed description.

---

## ⚠️ Known issues / To implement

- (None currently listed)

---

## 📝 License

This project is free. You are free to use, modify and distribute it under the terms of this license.

Developed with ❤️ for retro gaming enthusiasts.

# 🎮 Retro Game Sets Xtra (RGSX)

**[Discord Support](https://discord.gg/XPK8YG8XYC)** • **[Installation](#-installation)** • **[French Documentation](https://github.com/RetroGameSets/RGSX/blob/main/README_FR.md)** • **[Turkish Documentation](https://github.com/RetroGameSets/RGSX/blob/main/README_TR.md)** • **[Troubleshoot / Common Errors](https://github.com/RetroGameSets/RGSX#%EF%B8%8F-troubleshooting)** •

A free, user-friendly ROM downloader for Batocera, Knulli, and RetroBat with multi-source support.

<p align="center">
  <img width="49%" alt="RGSX Web platform list" src="screenshots/platforms-web.png" />
  <img width="49%" alt="RGSX application platform grid" src="screenshots/platforms-app.png" />
</p>
<p align="center">
  <img width="49%" alt="RGSX global game search" src="screenshots/global-search.png" />
  <img width="49%" alt="RGSX controller controls help" src="screenshots/controls-help.png" />
</p>
<p align="center">
  <img width="49%" alt="RGSX grid layout settings" src="screenshots/grid-layout.png" />
  <img width="49%" alt="RGSX ROM folder browser" src="screenshots/folder-browser.png" />
</p>
<p align="center">
  <img width="49%" alt="RGSX download history" src="screenshots/downloads-history.png" />
  <img width="49%" alt="RGSX Web settings" src="screenshots/settings-web.png" />
</p>


---

## 🚀 Installation

### Quick Install (Batocera / Knulli / dArkOS)

**SSH or Terminal access required:**
```bash
curl -L bit.ly/rgsx-install | sh
```

After installation:
1. Update game lists: `Menu > Game Settings > Update game list`
2. Find RGSX under **PORTS** or **Homebrew and ports**

On dArkOS, the same command runs the dArkOS installer and EmulationStation restarts by itself: see [dArkOS](#darkos--darkosre--darkosen-r36s-and-clones) below.

### Manual Install (All Systems)
1. **Download**: [RGSX_full_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)
2. **Extract**:
   - **Batocera/Knulli**: Extract `ports` folder to `/roms/`
   - **RetroBat**: Extract both `ports` and `windows` folders to `/roms/`
3. **Refresh**: `Menu > Game Settings > Update game list`

### dArkOS / dArkOSRE / dArkOSen (R36S and clones)
**Install script (recommended):** [tools/install_darkos.sh](tools/install_darkos.sh) downloads the latest release, installs RGSX in `/roms/ports` (or `/roms2/ports` with a second SD card), adds RGSX to `gamelist.xml` without touching your other ports (a backup is saved as `gamelist.xml.rgsx-backup`), then restarts EmulationStation. Run it the same way to update.
- Over SSH (`ssh ark@IPADDRESS`, password `ark`; enable SSH with `Options > Enable Remote Services`):
  ```bash
  curl -L bit.ly/rgsx-install | sh
  ```
  Without curl: `wget -qO- bit.ly/rgsx-install | sh`
- From the menu: copy `install_darkos.sh` to `/roms/tools/`, then start it from `Options` in EmulationStation.
- A local zip or folder also works: `bash install_darkos.sh /path/to/RGSX_full_latest.zip`

**Manual install:** copy `ports/RGSX` from [RGSX_full_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip) to `/roms/ports/`, and `RGSX.png` / `RGSX.mp4` into `/roms/ports/images/` and `/roms/ports/videos/`. Merge the folders, never replace them: they also hold your other ports. Do not copy a `gamelist.xml` over yours. dArkOS only lists launchers placed directly in `ports/`, so also create `/roms/ports/RGSX.sh`:
```bash
printf '#!/bin/bash\nexec "$(dirname "$0")/RGSX/RGSX.sh" "$@"\n' > /roms/ports/RGSX.sh
```
Then restart EmulationStation.

Notes:
- The R36S has no built-in WiFi. Plug a USB WiFi dongle into the OTG port and connect from `Options > Wifi`. RGSX shows a warning at startup when no adapter or no connection is found.
- pygame and requests are not part of dArkOS. They are bundled in `ports/RGSX/vendor_darkos` (built with `tools/build_darkos_vendor.sh` from Debian trixie packages, linked against the system SDL2).
- Settings and the local database are stored in `/home/ark/.config/rgsx` (ext4), not on the exFAT ROM card. Media Manager covers can take a lot of space, so they go to the ROM card: `/roms/rgsx/media` (or `/roms2/rgsx/media`).
- When games were added during the session, EmulationStation restarts automatically after you quit RGSX so they show up.
- The A/B button swap (EmulationStation's "SWITCH A/B BUTTONS IN EMULATIONSTATION" option, or the dArkOSen Button Mapper) is applied automatically when RGSX starts.
- Torrent downloads are not available on ARM devices yet.

### Manual Update (if automatic update failed)
Download and extract the latest release: [RGSX_full_latest.zip](https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip)

**Installed paths:**
- `/roms/ports/RGSX` (all systems)
- `/roms/windows/RGSX` (RetroBat only)

---

## 🎮 Usage

### First Launch

- Syncs the systems and games catalog into a local SQLite database
- Downloads the images needed by the interface
- Auto-configures controls if your controller is recognized
- **Controls broken?** Delete `/saves/ports/rgsx/controls.json` and restart

**Retrobat / first Windows launch**

- It is recommended to launch `RGSX Retrobat.bat` manually once, outside the Retrobat interface, to verify that everything is working.
- Allow Windows firewall prompts when they appear, especially for qBittorrent on first launch.
- Retrobat hides some system windows by default, so a first manual launch helps avoid missing an important prompt.
- The launcher then configures a local rule for the embedded qBittorrent binary and for the TCP `18572` WebUI.

**Keyboard Mode**: When no controller is detected, controls display as `[Key]` instead of icons.

### Pause Menu Structure

**Root menu** — Games, Language, Controls, Display, Scrap, Settings, Support, Reset Default Settings, and Quit.

- **Games**: refresh the catalog, scan locally owned ROMs, open download history, show/hide unsupported systems, and choose visible platforms.
- **Controls**: view the currently mapped actions or remap keyboard/controller inputs.
- **Display**: choose from eight grids (3×3, 3×4, 4×3, 4×4, 5×4, 6×4, 6×6, or 8×6), adjust UI and footer font sizes separately, choose a font (Pixel, Bell Centennial, or DejaVu Sans), background theme, and Light Mode. Monitor selection appears only when multiple displays are detected; window/fullscreen mode is Windows-only. You can also hide unknown-extension warnings.
- **Scrap**: edit ScreenScraper credentials and open the Media Manager.
- **Settings**: background music, symlink behavior, automatic extraction, ROM folder, maximum simultaneous downloads, API-key status, and connection status. Web service at boot and Custom DNS are available on Linux/Batocera.
- **Support**: diagnostic tools and support archive generation.
- **Quit**: quit or restart RGSX. Language selection is directly in the root menu.

### ScreenScraper and Media Manager

In the game list, leaving a game selected for two seconds retrieves its cover for the local media cache and displays its ScreenScraper synopsis in the preview panel. If no information is available, the panel shows an unavailable placeholder. The preferred ScreenScraper system ID is stored per platform in the online RGSX catalog and can be edited in RGSX Sources Manager. If no ID is configured, RGSX falls back to the periodically refreshed ScreenScraper system list cached in SQLite, then to built-in aliases. A two-second hold on **Confirm** opens the ScreenScraper details page with the cover, screenshot, and synopsis. In **Pause > Scrap**, the ScreenScraper username and password can be edited together; a virtual keyboard is shown only when a controller is detected, otherwise type directly and use Tab to switch fields. The account is stored in the dedicated `screenscraper_account.json` file and can also be edited from the web interface.

The Media Manager downloads media in bulk. Its **History** control shortcut starts, resumes, or cancels the current job without navigating back to the first row.

### Local Database and Migration

The systems/games catalog, download history, locally detected owned games, and related persistent state are stored in `/saves/ports/rgsx/rgsx.sqlite3`. The initial catalog sync downloads a full snapshot; later syncs apply changes incrementally. When a source or platform is hidden or re-enabled, RGSX reconciles the visible platform list and transfers game data only for newly visible platforms. **Games > Refresh Game Catalog** runs synchronization again. General preferences remain in `rgsx_settings.json`, and custom controls remain in `controls.json`.

On the first launch after upgrading from the former JSON-based storage, RGSX imports the download history, owned-game records, and torrent cache when present. Any discovered legacy cache/data files are moved to `/saves/ports/rgsx/backup_old_rgsx/<date>/`. Do not delete the SQLite database while RGSX is running: it contains the catalog and persistent user data. SQLite may create temporary `-wal` and `-shm` files alongside the database.

---

## ✨ Features

- 🎯 **Smart System Detection** – Auto-discovers supported systems from `es_systems.cfg`
- 📦 **Intelligent Archive Handling** – Auto-extracts archives when systems don't support ZIP files
- 🔑 **Premium Unlocking** – 1Fichier API + AllDebrid/Debrid-Link/Real-Debrid/TorBox fallback for unlimited downloads
- 🎨 **Fully Customizable** – Eight layouts up to 8×6, Pixel/Bell Centennial/DejaVu Sans fonts, font sizes (UI + footer), languages (EN/FR/DE/ES/IT/PT/TR)
- 🎮 **Controller-First Design** – Auto-mapping for popular controllers + custom remapping support
- 🔍 **Advanced Filtering** – Search by name, hide/show unsupported systems, filter platforms
- 📊 **Download Management** – Queue system, history tracking, progress notifications
- 🖼️ **ScreenScraper Media** – Delayed cover downloads, game details, screenshots, and bulk media management
- ♿ **Accessibility** – Separate font scaling for UI and footer, keyboard-only mode support

> ### 🔑 API Keys Setup
> For unlimited 1Fichier downloads, add your API key(s) to `/saves/ports/rgsx/`:
> - `1FichierAPI.txt` – 1Fichier API key (recommended)
> - `AllDebridAPI.txt` – AllDebrid fallback (optional)
> - `DebridLinkAPI.txt` – Debrid-Link fallback (optional)
> - `RealDebridAPI.txt` – Real-Debrid fallback (optional)
> - `TorBoxAPI.txt` – TorBox fallback (optional)
> 
> **Each file must contain ONLY the key, no extra text.**

### Downloading Games

1. Browse platforms → Select game
2. **Direct Download**: Press `Confirm`
3. **Queue Download**: Press `X` (West button)
4. Track progress in **History** menu or via popup notifications

## Embedded qBittorrent torrent backend

Torrent downloads now run through an embedded qBittorrent binary on both Windows and Linux/Batocera.

- LAN debug WebUI: `http://YOUR_DEVICE_IP:18572`
- Default credentials: `admin` / `RGSXqbt`
- The RGSX web interface now includes a `qBittorrent` button that opens this WebUI directly.

Useful notes:
- This WebUI is intended for debugging and advanced torrent monitoring from a phone or another PC on the same local network.
- If LAN access to the WebUI does not work, first check the local Windows firewall.
- Do not expose port `18572` directly to the Internet: it is the WebUI admin port, not the BitTorrent performance port.
- If torrent connectivity is poor, prefer UPnP or forwarding the actual BitTorrent listening port configured inside qBittorrent.

## 🌐 Web Interface (Batocera/Knulli Only)

RGSX includes a web interface that launched automatically when using RGSX for remote browsing and downloading games from any device on your network.

### Accessing the Web Interface

1. **Find your Batocera IP address**:
   - Check Batocera menu: `Network Settings`
   - Or from terminal: `ip addr show`

2. **Open in browser**: `http://[BATOCERA_IP]:5000` or `http://BATOCERA:5000`
   - Example: `http://192.168.1.100:5000`

3. **Available from any device**: Phone, tablet, PC on the same network

### Web Interface Features

- 📱 **Mobile-Friendly** – Responsive design works on all screen sizes
- 🔍 **Browse All Systems** – View all platforms and games
- ⬇️ **Remote Downloads** – Queue downloads directly to your Batocera
- 📊 **Real-Time Status** – See active downloads and history
- 🎮 **Same Game Lists** – Uses identical sources as the main app


### Enable/Disable Web Service at Boot, without the need to launch RGSX

**From RGSX Menu**
1. Open **Pause Menu** (Start/ALTGr)
2. Navigate to **Settings > Web Service**
3. Toggle **Enable at Boot**
4. Restart your device


**Port Configuration**: The web service runs on port `5000` by default. Ensure this port is not blocked by firewall rules.

---

## 📁 File Structure

```
/roms/
├── ports/
│   ├── RGSX/
│   │   ├── __main__.py                # Entry point
│   │   ├── config.py                  # Application paths and configuration
│   │   ├── database.py                # Local SQLite storage
│   │   ├── catalog_sync.py            # Online catalog synchronization
│   │   ├── controls.py                # Navigation, input, and actions
│   │   ├── controls_mapper.py         # Control profiles and remapping
│   │   ├── display.py                 # Pygame interface and menus
│   │   ├── game_info.py               # ScreenScraper details retrieval
│   │   ├── media_manager.py           # Bulk media downloads
│   │   ├── network.py                 # Downloads
│   │   ├── preview.py                 # Game-list cover preview and delayed fetch
│   │   ├── rgsx_settings.py           # User preferences
│   │   ├── screenscraper.py           # ScreenScraper proxy client
│   │   ├── rgsx_web.py                # Web interface and server
│   │   ├── assets/                    # Profiles, images, fonts, music, and tools
│   │   ├── languages/                 # Translations (EN/FR/DE/ES/IT/PT/TR)
│   │   ├── static/                    # Web interface CSS and JavaScript
│   │   └── logs/                      # RGSX.log and rgsx_web.log
│   ├── gamelist.xml
│   ├── images/
│   └── videos/
└── windows/
    ├── RGSX Retrobat.bat              # Launcher for Windows only (can be used without retrobat too)
    ├── gamelist.xml
    ├── images/
    └── videos/

/saves/ports/rgsx/
├── rgsx_settings.json        # User preferences
├── controls.json             # Control mapping
├── rgsx.sqlite3              # Catalog, history, and persistent user state
├── images/                   # System images
├── media/                    # Cached game covers, screenshots, and logos
├── screenscraper_account.json # Optional ScreenScraper account
├── backup_old_rgsx/          # Legacy files archived during migration, if present
├── 1FichierAPI.txt           # 1Fichier API key
├── AllDebridAPI.txt          # AllDebrid API key
├── DebridLinkAPI.txt         # Debrid-Link API key
├── RealDebridAPI.txt         # Real-Debrid API key
└── TorBoxAPI.txt              # TorBox API key
```

The `-wal` and `-shm` files that may appear beside `rgsx.sqlite3` are temporary SQLite files used while the application is running.

---

## 🛠️ Troubleshooting

| Issue | Solution |
|-------|----------|
| Controls not working | Delete `/saves/ports/rgsx/controls.json` + restart app, you can try delete /roms/ports/RGSX/assets/controls/xx.json too |
| No games or empty catalog? | Open **Games > Refresh Game Catalog**, then check **Games > Filter Platforms** and the unsupported-systems visibility option. In **Settings**, confirm the configured ROM folder is correct. Check Connection Status if synchronization fails. |
| Missing systems on the list? | RGSX discovers systems from the emulator configuration. Enable unsupported-system visibility under **Games** and check the platform filter. |
| Catalog sync or database write failure | Check available disk space and write permissions in `/saves/ports/rgsx/`, then inspect the logs. Do not delete `rgsx.sqlite3` without a backup: it also contains history and owned-game records. |
| App crashes | Check `/roms/ports/RGSX/logs/RGSX.log` (and `rgsx_web.log` for the web server). |
| Layout change not applied | Restart RGSX after changing layout |
| ScreenScraper details or covers are missing | Check the Internet connection and ensure the updated ScreenScraper proxy is deployed. An account is optional; valid account credentials can increase available quotas. |
| Problem downloading some Games ? | Open Pause Menu > Settings > Connection Status. If one or more required sites are red, enable Custom DNS in Settings and reboot. Also check ISP/router protections (especially ASUS web threat blocking). |

**Need help?** Share logs from `/roms/ports/RGSX/logs/` on [Discord](https://discord.gg/XPK8YG8XYC).

---

## 🤝 Contributing

- **Bug Reports**: Open GitHub issue with logs or post on Discord
- **Feature Requests**: Discuss on Discord first, then open issue
- **Code Contributions**: 
  ```bash
  git checkout -b feature/your-feature
  # Test on Batocera/RetroBat
  # Submit Pull Request
  ```

---

## 📝 License

Free and open-source software. Use, modify, and distribute freely.

## Thanks to all contributors, and followers of this app

**If you want to support my project you can buy me a beer :  https://bit.ly/donate-to-rgsx**
<a href="https://github.com/RetroGameSets/RGSX/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=RetroGameSets/RGSX" />
</a>
[![Stargazers over time](https://starchart.cc/RetroGameSets/RGSX.svg?variant=adaptive)](https://starchart.cc/RetroGameSets/RGSX)

**Developed with ❤️ for the retro gaming community.**

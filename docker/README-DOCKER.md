# 🐳 RGSX Docker - Headless Web Server

Run RGSX as a web-only service without the Pygame UI. Perfect for homelab/server setups.

## Quick Start

```bash
# Using docker-compose (recommended)
docker-compose up -d

# Or build and run manually
docker build -f docker/Dockerfile -t rgsx .
docker run -d \
  --name rgsx \
  -p 5000:5000 \
  -v ./config:/config \
  -v ./data:/data \
  rgsx

# Access the web interface
open http://localhost:5000
```

## What This Does

- Runs RGSX web server in headless mode (no Pygame UI)
- Web interface accessible from any browser
- Config persists in `/config` volume (settings, metadata, history)
- ROMs download to `/data/roms/{platform}/` and extract there
- Environment variables pre-configured (no manual setup needed)

## Environment Variables

**Pre-configured in the container (no need to set these):**
- `RGSX_HEADLESS=1` - Runs in headless mode
- `RGSX_CONFIG_DIR=/config` - Config location
- `RGSX_DATA_DIR=/data` - Data location

**Optional (only if needed):**
- `PUID` - User ID for file ownership (default: root)
- `PGID` - Group ID for file ownership (default: root)

## Configuration

### Docker Compose

See `docker-compose.example.yml` for a complete example configuration.

### User Permissions (Important!)

**For SMB mounts (Unraid, Windows shares):**
- Don't set PUID/PGID
- The container runs as root, and the SMB server maps files to your authenticated user

**For NFS/local storage:**
- Set PUID and PGID to match your host user (files will be owned by that user)
- Find your user ID: `id -u` and `id -g`

### Volumes

Two volumes are used:

**`/config`** - Configuration and metadata
- `rgsx_settings.json` - Settings
- `games/` - Platform game database files (JSON)
- `images/` - Game cover art
- `history.json` - Download history
- `logs/` - Application logs
- `*.txt` - API keys

**`/data`** - ROM storage
- `roms/` - ROMs by platform (snes/, nes/, psx/, etc.) - downloads extract here

### API Keys

Add your download service API keys to `./config/`:

```bash
# Add your API key (just the key, no extra text)
echo "YOUR_KEY_HERE" > ./config/1FichierAPI.txt

# Optional: AllDebrid/RealDebrid
echo "YOUR_KEY" > ./config/AllDebridAPI.txt
echo "YOUR_KEY" > ./config/RealDebridAPI.txt

# Restart to apply
docker restart rgsx
```

## Commands

```bash
# Start
docker start rgsx

# View logs
docker logs -f rgsx

# Stop
docker stop rgsx

# Update (after git pull)
docker build --no-cache -t rgsx .
docker stop rgsx && docker rm rgsx
# Then re-run the docker run command
```

## Directory Structure

**On Host:**
```
./
├── config/              # Config volume (created on first run)
│   ├── rgsx_settings.json
│   ├── games/          # Platform game database (JSON)
│   ├── images/         # Platform images
│   ├── logs/           # Application logs
│   └── *.txt           # API keys (1FichierAPI.txt, etc.)
└── data/
    └── roms/           # ROMs by platform
        ├── snes/
        ├── n64/
        └── ...
```

**In Container:**
```
/app/RGSX/              # Application code
/config/                # Mapped to ./config on host
└── games/, images/, logs/, etc.
/data/                  # Mapped to ./data on host
└── roms/               # ROM downloads go here
```

## How It Works

RGSX already has a headless mode (`RGSX_HEADLESS=1`) and the web server (`rgsx_web.py`) works standalone - this was designed for the Batocera web service. The Docker setup just runs it in a container with proper volume mappings.

## Troubleshooting

**Permission denied errors / Can't delete files:**

The container creates files with the UID/GID specified by PUID/PGID environment variables:

```bash
# Set correct PUID/PGID for your environment
docker run -e PUID=1000 -e PGID=1000 ...
```

**Changed PUID/PGID and permission errors:**

Fix ownership of your volumes:

```bash
# Fix ownership to match new PUID/PGID
sudo chown -R 1000:1000 ./config ./data
```

**Port already in use:**
```bash
docker run -p 8080:5000 ...  # Use port 8080 instead
```

**Container won't start:**
```bash
docker logs rgsx
```

## vs Traditional Install

| Feature | Docker | Batocera/RetroBat |
|---------|--------|-------------------|
| Interface | Web only | Pygame UI + Web |
| Install | `docker run` | Manual setup |
| Updates | `docker build` | git pull |
| Access | Any device on network | Device only |
| Use Case | Server/homelab | Gaming device |

## Support

- RGSX Issues: https://github.com/RetroGameSets/RGSX/issues
- Discord: https://discord.gg/Vph9jwg3VV

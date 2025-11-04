# 🐳 RGSX Docker - Headless Web Server

Run RGSX as a web-only service without the Pygame UI. Perfect for homelab/server setups.

## Quick Start

```bash
# Build the image
docker build -t rgsx .

# Run with docker
docker run -d \
  --name rgsx \
  -p 5000:5000 \
  -e PUID=99 \
  -e PGID=100 \
  -e RGSX_HEADLESS=1 \
  -v ./data/saves:/userdata/saves/ports/rgsx \
  -v ./data/roms:/userdata/roms/ports \
  -v ./data/logs:/userdata/roms/ports/RGSX/logs \
  rgsx

# Access the web interface
open http://localhost:5000
```

## What This Does

- Runs RGSX web server in headless mode (no Pygame UI)
- Web interface accessible from any browser
- ROMs and settings persist in `./data/` volumes
- Container restarts automatically

## Configuration

### User Permissions (Important!)

**For SMB mounts (Unraid, Windows shares):**

Don't set PUID/PGID. The container runs as root, and the SMB server maps files to your authenticated user.

```bash
docker run \
  -e RGSX_HEADLESS=1 \
  ...
```

**For NFS/local storage:**

Set PUID and PGID to match your host user. Files will be owned by that user.

```bash
docker run \
  -e PUID=1000 \
  -e PGID=1000 \
  -e RGSX_HEADLESS=1 \
  ...
```

**Find your user ID:**
```bash
id -u  # Your UID
id -g  # Your GID
```

### Change Port

```bash
docker run -p 8080:5000 ...  # Access on port 8080
```

### Custom ROM Location

Map to your existing ROM collection:
```bash
docker run -v /your/existing/roms:/userdata/roms/ports ...
```

### API Keys

Add your download service API keys to `./data/saves/`:

```bash
# Add your API key (just the key, no extra text)
echo "YOUR_KEY_HERE" > ./data/saves/1FichierAPI.txt

# Optional: AllDebrid/RealDebrid fallbacks
echo "YOUR_KEY" > ./data/saves/AllDebridAPI.txt
echo "YOUR_KEY" > ./data/saves/RealDebridAPI.txt

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

```
RGSX/
├── data/                 # Created on first run
│   ├── saves/           # Settings, history, API keys
│   ├── roms/            # Downloaded ROMs
│   └── logs/            # Application logs
├── Dockerfile
└── docker-compose.yml
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

**Changed PUID/PGID and container won't start:**

When you change PUID/PGID, old files with different ownership will cause rsync to fail. You MUST fix ownership on the storage server:

```bash
# On your NAS/Unraid (via SSH), either:

# Option 1: Delete old files (easiest)
rm -rf /mnt/user/roms/rgsx/roms/ports/RGSX/*

# Option 2: Change ownership to new PUID/PGID
chown -R 1000:1000 /mnt/user/roms/rgsx/roms/ports/RGSX/
```

Then restart the container.

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

# 🐳 RGSX Docker - Headless Web Server

Run RGSX as a web-only service without the Pygame UI. Perfect for homelab/server setups.

## Quick Start

```bash
# Clone and start
git clone https://github.com/RetroGameSets/RGSX.git
cd RGSX
docker-compose up -d

# Access the web interface
open http://localhost:5000
```

## What This Does

- Runs RGSX web server in headless mode (no Pygame UI)
- Web interface accessible from any browser
- ROMs and settings persist in `./data/` volumes
- Container restarts automatically

## Configuration

### Change Port

Edit `docker-compose.yml`:
```yaml
ports:
  - "8080:5000"  # Host port : Container port
```

### Custom ROM Location

Map to your existing ROM collection:
```yaml
volumes:
  - ./data/saves:/userdata/saves/ports/rgsx
  - /your/existing/roms:/userdata/roms  # Change this
  - ./data/logs:/app/RGSX/logs
```

### API Keys

Add your download service API keys to `./data/saves/`:

```bash
# Start container once to create directories
docker-compose up -d

# Add your API key (just the key, no extra text)
echo "YOUR_KEY_HERE" > ./data/saves/1FichierAPI.txt

# Optional: AllDebrid/RealDebrid fallbacks
echo "YOUR_KEY" > ./data/saves/AllDebridAPI.txt
echo "YOUR_KEY" > ./data/saves/RealDebridAPI.txt

# Restart to apply
docker-compose restart
```

## Commands

```bash
# Start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Update (after git pull)
docker-compose build --no-cache
docker-compose up -d
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

**Port already in use:**
```bash
# Use different port
sed -i '' 's/5000:5000/8080:5000/' docker-compose.yml
```

**Permission errors:**
```bash
sudo chown -R $USER:$USER ./data
```

**Container won't start:**
```bash
docker-compose logs
```

## vs Traditional Install

| Feature | Docker | Batocera/RetroBat |
|---------|--------|-------------------|
| Interface | Web only | Pygame UI + Web |
| Install | `docker-compose up` | Manual setup |
| Updates | `docker-compose build` | git pull |
| Access | Any device on network | Device only |
| Use Case | Server/homelab | Gaming device |

## Support

- RGSX Issues: https://github.com/RetroGameSets/RGSX/issues
- Discord: https://discord.gg/Vph9jwg3VV

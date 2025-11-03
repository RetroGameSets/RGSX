#!/bin/bash
set -e

# Always sync RGSX app code to the mounted volume (for updates)
echo "Syncing RGSX app code to /userdata/roms/ports/RGSX..."
mkdir -p /userdata/roms/ports/RGSX
cp -rf /app/RGSX/* /userdata/roms/ports/RGSX/
echo "RGSX app code synced!"

# Create Batocera folder structure only if folders don't exist
[ ! -d "/userdata/saves/ports/rgsx/images" ] && mkdir -p /userdata/saves/ports/rgsx/images
[ ! -d "/userdata/saves/ports/rgsx/games" ] && mkdir -p /userdata/saves/ports/rgsx/games
[ ! -d "/userdata/roms/ports/RGSX/logs" ] && mkdir -p /userdata/roms/ports/RGSX/logs

# Create default settings with show_unsupported_platforms enabled if config doesn't exist
SETTINGS_FILE="/userdata/saves/ports/rgsx/rgsx_settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "Creating default settings with all platforms visible..."
    cat > "$SETTINGS_FILE" << 'EOF'
{
    "show_unsupported_platforms": true
}
EOF
    echo "Default settings created!"
fi

# Run the command
cd /userdata/roms/ports/RGSX
exec "$@"

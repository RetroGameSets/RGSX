#!/bin/bash
set -e

# Copy RGSX app code to the mounted volume if it doesn't exist yet
if [ ! -f "/userdata/roms/ports/RGSX/rgsx_web.py" ]; then
    echo "Initializing RGSX in /userdata/roms/ports/RGSX..."
    mkdir -p /userdata/roms/ports
    cp -r /app/RGSX /userdata/roms/ports/
    echo "RGSX app code initialized!"
fi

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

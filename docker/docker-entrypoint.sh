#!/bin/bash
set -e

# If PUID/PGID are set, create user and run as that user
# If not set, run as root (works for SMB mounts)
if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    echo "=== Creating user with PUID=$PUID, PGID=$PGID ==="

    # Create group if it doesn't exist
    if ! getent group $PGID >/dev/null 2>&1; then
        groupadd -g $PGID rgsx
    fi

    # Create user if it doesn't exist
    if ! getent passwd $PUID >/dev/null 2>&1; then
        useradd -u $PUID -g $PGID -m -s /bin/bash rgsx
    fi

    # Fix ownership of app files
    chown -R $PUID:$PGID /app /userdata 2>/dev/null || true

    echo "=== Running as user $(id -un $PUID) (UID=$PUID, GID=$PGID) ==="
    RUN_USER="gosu rgsx"
else
    echo "=== Running as root (no PUID/PGID set) - for SMB mounts ==="
    RUN_USER=""
fi

# Always sync RGSX app code to the mounted volume (for updates)
echo "Syncing RGSX app code to /userdata/roms/ports/RGSX..."
$RUN_USER mkdir -p /userdata/roms/ports/RGSX

# Try rsync
if ! $RUN_USER rsync -av --delete /app/RGSX/ /userdata/roms/ports/RGSX/ 2>&1; then
    echo ""
    echo "=========================================="
    echo "WARNING: rsync partially failed!"
    echo "=========================================="
    echo "Some files may not have synced. Container will continue for debugging."
    echo ""
    if [ -n "$PUID" ] && [ -n "$PGID" ]; then
        echo "If using SMB, try removing PUID/PGID to run as root"
    fi
    echo ""
fi

echo "RGSX app code sync attempted."

# Create Batocera folder structure only if folders don't exist
$RUN_USER mkdir -p /userdata/saves/ports/rgsx/images
$RUN_USER mkdir -p /userdata/saves/ports/rgsx/games
$RUN_USER mkdir -p /userdata/roms/ports/RGSX/logs

# Create default settings with show_unsupported_platforms enabled if config doesn't exist
SETTINGS_FILE="/userdata/saves/ports/rgsx/rgsx_settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "Creating default settings with all platforms visible..."
    $RUN_USER bash -c "cat > '$SETTINGS_FILE' << 'EOF'
{
    \"show_unsupported_platforms\": true
}
EOF"
    echo "Default settings created!"
fi

# Run the command
cd /userdata/roms/ports/RGSX
if [ -z "$RUN_USER" ]; then
    exec "$@"
else
    exec $RUN_USER "$@"
fi

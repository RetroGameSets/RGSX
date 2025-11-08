#!/bin/bash
set -e

echo "=== RGSX Docker Container Startup ==="

# If PUID/PGID are set, create user and run as that user
# If not set, run as root (works for SMB mounts)
if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    echo "Creating user with PUID=$PUID, PGID=$PGID..."

    # Create group if it doesn't exist
    if ! getent group $PGID >/dev/null 2>&1; then
        groupadd -g $PGID rgsx
    fi

    # Create user if it doesn't exist
    if ! getent passwd $PUID >/dev/null 2>&1; then
        useradd -u $PUID -g $PGID -m -s /bin/bash rgsx
    fi

    echo "Running as user $(id -un $PUID) (UID=$PUID, GID=$PGID)"
    RUN_USER="gosu rgsx"
else
    echo "Running as root (no PUID/PGID set) - suitable for SMB mounts"
    RUN_USER=""
fi

# Create necessary directories
# /config needs logs directory, app will create others (like images/, games/) as needed
# /data needs roms directory
echo "Setting up directories..."
$RUN_USER mkdir -p /config/logs
$RUN_USER mkdir -p /data/roms

# Fix ownership of volumes if PUID/PGID are set
if [ -n "$PUID" ] && [ -n "$PGID" ]; then
    echo "Setting ownership on volumes..."
    chown -R $PUID:$PGID /config /data 2>/dev/null || true
fi

# Create default settings with show_unsupported_platforms enabled if config doesn't exist
SETTINGS_FILE="/config/rgsx_settings.json"
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "Creating default settings with all platforms visible..."
    $RUN_USER bash -c "cat > '$SETTINGS_FILE' << 'EOF'
{
    \"show_unsupported_platforms\": true
}
EOF"
    echo "Default settings created at $SETTINGS_FILE"
fi

echo "=== Starting RGSX Web Server ==="
echo "Config directory: /config"
echo "ROMs directory: /data/roms"
echo "======================================"

# Run the command from the working directory (/app/RGSX set in Dockerfile)
if [ -z "$RUN_USER" ]; then
    exec "$@"
else
    exec $RUN_USER "$@"
fi

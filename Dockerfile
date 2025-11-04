FROM python:3.11-slim

# Install system dependencies for ROM extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    unrar-free \
    curl \
    rsync \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create required directories
RUN mkdir -p /userdata/saves/ports/rgsx \
    && mkdir -p /userdata/roms/ports \
    && mkdir -p /app

# Copy RGSX application files to /app (will be copied to volume at runtime)
COPY ports/RGSX/ /app/RGSX/

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Install Python dependencies
# pygame is imported in some modules even in headless mode, so we include it
RUN pip install --no-cache-dir requests pygame

# Set environment to headless mode
ENV RGSX_HEADLESS=1

# Expose web interface port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# Entrypoint copies app to volume, then runs command
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "rgsx_web.py", "--host", "0.0.0.0", "--port", "5000"]

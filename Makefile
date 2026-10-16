# Run RGSX on a development machine without copying it to a device.
# RGSX_CONFIG_DIR / RGSX_DATA_DIR switch config.py to its "Docker mode" paths:
# settings, SQLite catalog, media cache and logs stay isolated under RGSX_DEV_DIR.

RGSX_DEV_DIR ?= $(HOME)/rgsx-dev

.PHONY: run-test-env clean-test-env

run-test-env:
	@mkdir -p "$(RGSX_DEV_DIR)/config" "$(RGSX_DEV_DIR)/data/roms"
	@[ -f "$(RGSX_DEV_DIR)/config/rgsx_settings.json" ] || \
		echo '{"language":"en","music_enabled":false,"display":{"fullscreen":false}}' > "$(RGSX_DEV_DIR)/config/rgsx_settings.json"
	@echo "Log: $(RGSX_DEV_DIR)/config/logs/RGSX.log"
	cd ports/RGSX && RGSX_CONFIG_DIR="$(RGSX_DEV_DIR)/config" RGSX_DATA_DIR="$(RGSX_DEV_DIR)/data" \
		uv run --no-project --with pygame --with requests python __main__.py

clean-test-env:
	rm -rf "$(RGSX_DEV_DIR)"

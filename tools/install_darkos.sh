#!/bin/bash
# Install or update RGSX on dArkOS (dArkOSRE, dArkOSen) for R36S and clones.
#
# Run it on the device, either:
#   - over SSH:        curl -L https://raw.githubusercontent.com/RetroGameSets/RGSX/main/tools/install_darkos.sh | bash
#                      (or: bash install_darkos.sh [SOURCE])
#   - from the menu:   copy it to /roms/tools/ and start it from EmulationStation > Options
#
# SOURCE (optional): release zip URL (default: latest RGSX_full_latest.zip), a local .zip file,
# or a folder that contains ports/RGSX (for example a copy of the repository).
#
# Only RGSX files are replaced: other ports, their images/videos and their gamelist.xml entries stay.
set -euo pipefail

SOURCE="${1:-https://github.com/RetroGameSets/RGSX/releases/latest/download/RGSX_full_latest.zip}"
LOG_FILE="/tmp/rgsx_install.log"

show() {
	echo "$1" | tee -a "${LOG_FILE}"
}

finish() {
	show "$1"
	# msgbox is the dArkOS on-screen dialog used by the Options tools; it waits for a button
	# press on the device, so skip it over SSH where the terminal already shows the result.
	if [[ -z "${SSH_CONNECTION:-}" ]] && command -v msgbox >/dev/null 2>&1; then
		msgbox "$1" || true
	fi
}

fail() {
	finish "RGSX install failed: $1 (log: ${LOG_FILE})"
	exit 1
}

# Everything runs from main(), called on the last line: with "curl ... | bash",
# a truncated download then runs nothing instead of half of the install.
main() {

: >"${LOG_FILE}"

if [[ ! -f /etc/darkos_version ]] && ! grep -qi darkos /usr/share/plymouth/themes/text.plymouth 2>/dev/null; then
	fail "this script is only for dArkOS"
fi

# Same rule as PortMaster: ports live on the second SD card when /roms2 is in fstab
ROMS_ROOT="/roms"
if grep -q roms2 /etc/fstab 2>/dev/null && [[ -d /roms2/ports ]]; then
	ROMS_ROOT="/roms2"
fi
PORTS_DIR="${ROMS_ROOT}/ports"
[[ -d "${PORTS_DIR}" ]] || fail "${PORTS_DIR} not found"

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

# 1. Get the files
if [[ -d "${SOURCE}" ]]; then
	SRC_ROOT="${SOURCE}"
else
	ZIP_FILE="${WORK_DIR}/rgsx.zip"
	if [[ -f "${SOURCE}" ]]; then
		cp "${SOURCE}" "${ZIP_FILE}"
	elif [[ "${SOURCE}" != http://* && "${SOURCE}" != https://* ]]; then
		# A mistyped local path must not turn into a download
		fail "${SOURCE} not found"
	else
		show "Downloading ${SOURCE}"
		if command -v wget >/dev/null 2>&1; then
			wget -q -O "${ZIP_FILE}" "${SOURCE}" >>"${LOG_FILE}" 2>&1 || fail "download failed (is WiFi connected?)"
		else
			curl -fsSL -o "${ZIP_FILE}" "${SOURCE}" >>"${LOG_FILE}" 2>&1 || fail "download failed (is WiFi connected?)"
		fi
	fi
	unzip -tq "${ZIP_FILE}" >>"${LOG_FILE}" 2>&1 || fail "zip file is corrupted"
	unzip -q "${ZIP_FILE}" -d "${WORK_DIR}/src" >>"${LOG_FILE}" 2>&1 || fail "extraction failed"
	SRC_ROOT="${WORK_DIR}/src"
fi

# Accept both <root>/ports/RGSX and <root>/RGSX layouts
if [[ -d "${SRC_ROOT}/ports/RGSX" ]]; then
	SRC_PORTS="${SRC_ROOT}/ports"
elif [[ -d "${SRC_ROOT}/RGSX" ]]; then
	SRC_PORTS="${SRC_ROOT}"
else
	fail "ports/RGSX not found in ${SOURCE}"
fi
[[ -f "${SRC_PORTS}/RGSX/RGSX.sh" ]] || fail "RGSX.sh not found in ${SOURCE}"
[[ -d "${SRC_PORTS}/RGSX/vendor_darkos" ]] || fail "this RGSX version has no dArkOS support (vendor_darkos missing)"
# The next step deletes the installed folder: never let it be the source itself
[[ "$(cd "${SRC_PORTS}/RGSX" && pwd -P)" != "$(cd "${PORTS_DIR}" && pwd -P)/RGSX" ]] \
	|| fail "the source is the installed folder itself; copy it somewhere else first (for example /roms/rgsx_test)"

# 2. Replace the app folder only (settings live in ~/.config/rgsx and are kept)
show "Installing RGSX to ${PORTS_DIR}/RGSX"
rm -rf "${PORTS_DIR}/RGSX"
# exFAT cannot keep owners or permissions: plain recursive copy
cp -r "${SRC_PORTS}/RGSX" "${PORTS_DIR}/RGSX"
rm -rf "${PORTS_DIR}/RGSX/logs" "${PORTS_DIR}/RGSX/__pycache__"

# 3. dArkOS EmulationStation only lists launchers at the top of ports/, not RGSX/RGSX.sh
cat >"${PORTS_DIR}/RGSX.sh" <<'LAUNCHER'
#!/bin/bash
exec "$(dirname "$0")/RGSX/RGSX.sh" "$@"
LAUNCHER
chmod +x "${PORTS_DIR}/RGSX.sh" 2>/dev/null || true

# 4. Add only RGSX media, never replace the image/video folders
for media in images/RGSX.png videos/RGSX.mp4; do
	if [[ -f "${SRC_PORTS}/${media}" ]]; then
		mkdir -p "${PORTS_DIR}/$(dirname "${media}")"
		cp "${SRC_PORTS}/${media}" "${PORTS_DIR}/${media}"
	fi
done

# 5. Add the RGSX entry to gamelist.xml with EmulationStation stopped: dArkOS sets
# SaveGamelistsMode="on exit", so a running ES would write its own list over ours when it quits.
# Started from the Options menu, this script is a child of ES and dies when ES stops,
# so this stage runs as a separate transient systemd unit.
FINISH_STAGE='
exec >>"$2" 2>&1
ports_dir="$1"
gamelist="${ports_dir}/gamelist.xml"
sudo -n systemctl stop emulationstation
# update_gamelist.py rebuilds an unreadable gamelist from scratch: keep the list ES just saved
if [ -s "${gamelist}" ]; then
	cp "${gamelist}" "${gamelist}.rgsx-backup" && echo "Backup: ${gamelist}.rgsx-backup"
fi
if (cd "${ports_dir}/RGSX" && PYTHONPATH="${ports_dir}/RGSX/vendor_darkos" RGSX_HEADLESS=1 python3 update_gamelist.py); then
	echo "gamelist.xml updated"
else
	echo "gamelist.xml update failed: RGSX still shows up, without image"
fi
# Always bring EmulationStation back
sudo -n systemctl start emulationstation
'

finish "RGSX installed in ${PORTS_DIR}/RGSX. EmulationStation will now restart."
sudo -n systemd-run --quiet --collect --unit="rgsx-install-finish-$$" --uid="$(id -un)" \
	bash -c "${FINISH_STAGE}" rgsx-install-finish "${PORTS_DIR}" "${LOG_FILE}" >>"${LOG_FILE}" 2>&1 \
	|| fail "could not restart EmulationStation; restart it from the Start menu"
}

main "$@"

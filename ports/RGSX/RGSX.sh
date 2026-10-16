#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}" || true
LOGFILE="${LOG_DIR}/launcher.log"
VENDOR_DIR="${SCRIPT_DIR}/vendor"
if [[ -d "${VENDOR_DIR}" ]]; then
	export PYTHONPATH="${VENDOR_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
	echo "[RGSX] Bundled Python modules enabled: ${VENDOR_DIR}" >>"${LOGFILE}"
fi

detect_platform() {
	if [[ -f /etc/rocknix-release || -f /etc/rocknix-os-release ]]; then
		echo rocknix
		return
	fi
	if [[ -r /proc/device-tree/model ]] && grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
		echo rpi
		return
	fi
	if [[ -f /etc/batocera-release ]] || command -v batocera-info >/dev/null 2>&1; then
		echo batocera
		return

	fi
	# dArkOS family (dArkOS, dArkOSRE, dArkOSen): same probe as PortMaster
	if [[ -f /etc/darkos_version ]] || grep -qi darkos /usr/share/plymouth/themes/text.plymouth 2>/dev/null; then
		echo darkos
		return
	fi
	echo generic
}

PLATFORM="$(detect_platform)"
echo "[RGSX] Platform detected: ${PLATFORM}" >>"${LOGFILE}"

case "${PLATFORM}" in
	rocknix)
		# Source system profile to get entware environment (PYTHONPATH, PATH)
		if [[ -f /etc/profile ]]; then
			# shellcheck source=/dev/null
			source /etc/profile 2>/dev/null || true
		fi
		# Add entware site-packages if present
		for sp in /storage/.opt/lib/python*/site-packages; do
			if [[ -d "${sp}" ]]; then
				export PYTHONPATH="${sp}${PYTHONPATH:+:${PYTHONPATH}}"
				echo "[RGSX] PYTHONPATH extended: ${sp}" >>"${LOGFILE}"
				break
			fi
		done

		# Verify required Python modules on Rocknix (pygame, requests, optional pymysql)
		if command -v python3 >/dev/null 2>&1; then
			missing=""
			modules=(pygame requests pymysql)
			for mod in "${modules[@]}"; do
				if ! python3 -c "import ${mod}" >/dev/null 2>&1; then
					missing+=" ${mod}"
				fi
			done

			if [[ -n "${missing// /}" ]]; then
				echo "[RGSX] Missing python modules:${missing}" >>"${LOGFILE}"
				# Try opkg for requests first (available in entware)
				if command -v opkg >/dev/null 2>&1; then
					if echo "${missing}" | grep -qw "requests"; then
						opkg update >/dev/null 2>&1 || true
						opkg install python3-requests >>"${LOGFILE}" 2>&1 || true
					fi
				fi

				# Install remaining via pip (prefer binary wheels)
				to_install=()
				for mod in ${missing}; do
					# recheck requests in case opkg installed it
					if [[ "${mod}" == "requests" ]]; then
						if python3 -c "import requests" >/dev/null 2>&1; then
							continue
						fi
					fi
					to_install+=("${mod}")
				done
				if [[ ${#to_install[@]} -gt 0 ]]; then
					echo "[RGSX] Installing python modules via pip: ${to_install[*]}" >>"${LOGFILE}"
					python3 -m pip install --disable-pip-version-check --upgrade pip setuptools wheel >>"${LOGFILE}" 2>&1 || true
					if ! python3 -m pip install --disable-pip-version-check --prefer-binary "${to_install[@]}" >>"${LOGFILE}" 2>&1; then
						python3 -m pip install --disable-pip-version-check --only-binary :all: "${to_install[@]}" >>"${LOGFILE}" 2>&1 || true
					fi
				fi
			fi
		fi
		;;
	rpi|batocera)
		# RPi/Batocera: assume system Python and system libs are present
		;;
	darkos)
		# pygame/requests are not shipped with dArkOS; tools/build_darkos_vendor.sh bundles them here
		DARKOS_VENDOR_DIR="${SCRIPT_DIR}/vendor_darkos"
		if [[ -d "${DARKOS_VENDOR_DIR}" ]]; then
			export PYTHONPATH="${DARKOS_VENDOR_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
			echo "[RGSX] dArkOS bundled Python modules enabled: ${DARKOS_VENDOR_DIR}" >>"${LOGFILE}"
		else
			echo "[RGSX] Missing ${DARKOS_VENDOR_DIR}: pygame/requests will not be found" >>"${LOGFILE}"
		fi
		;;
	generic)
		;; 
esac

# Run the app from the script directory and capture stdout/stderr to log
cd "${SCRIPT_DIR}"

if [[ "${PLATFORM}" == "darkos" ]]; then
	ROMS_ROOT="$(dirname "$(dirname "${SCRIPT_DIR}")")"
	STAMP_FILE="$(mktemp)"
	set +e
	python3 __main__.py >>"${LOGFILE}" 2>&1
	APP_STATUS=$?
	set -e
	# dArkOS EmulationStation has no reload API: restart it only when a ROM folder changed during the session.
	# rgsx/ holds the Media Manager covers, not ROMs
	if [[ -n "$(find "${ROMS_ROOT}" -mindepth 1 -maxdepth 1 -type d -not -name rgsx -newer "${STAMP_FILE}" -print -quit 2>/dev/null)" ]]; then
		echo "[RGSX] ROM folders changed, restarting EmulationStation" >>"${LOGFILE}"
		rm -f "${STAMP_FILE}"
		sudo systemctl restart emulationstation
	fi
	rm -f "${STAMP_FILE}"
	exit "${APP_STATUS}"
fi

exec python3 __main__.py >>"${LOGFILE}" 2>&1
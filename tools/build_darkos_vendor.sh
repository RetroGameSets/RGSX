#!/bin/bash
# Build ports/RGSX/vendor_darkos: pygame + requests for dArkOS (dArkOSRE, dArkOSen) on R36S.
#
# dArkOS (Debian trixie, Python 3.13, arm64) ships neither module. pygame is taken from the
# Debian package so it links against the system libSDL2, which dArkOS replaces with its own
# KMSDRM/Mali build. The .deb files are only unpacked, never installed.
#
# Usage: tools/build_darkos_vendor.sh   (needs Docker; runs natively on arm64 hosts)
set -euo pipefail

DEBIAN_SUITE="trixie"
PACKAGES=(python3-pygame python3-requests python3-urllib3 python3-idna python3-certifi python3-charset-normalizer)
MODULES=(pygame requests urllib3 idna certifi charset_normalizer)

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/ports/RGSX/vendor_darkos"

if [[ "${1:-}" != "--in-container" ]]; then
	rm -rf "${OUT_DIR}"
	mkdir -p "${OUT_DIR}"
	docker run --rm --platform linux/arm64 \
		-v "${REPO_ROOT}/tools:/tools:ro" -v "${OUT_DIR}:/out" \
		"debian:${DEBIAN_SUITE}" bash /tools/build_darkos_vendor.sh --in-container
	echo "Done: ${OUT_DIR} ($(du -sh "${OUT_DIR}" | cut -f1))"
	exit 0
fi

# --- inside debian:trixie arm64 ---
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq binutils >/dev/null
WORK="$(mktemp -d)"
cd "${WORK}"
apt-get download -qq "${PACKAGES[@]}"
for deb in ./*.deb; do
	dpkg-deb -x "${deb}" root
done

SITE="root/usr/lib/python3/dist-packages"
# The ROM card is exFAT, which cannot store symlinks: drop dangling ones, dereference the rest.
find "${SITE}" -xtype l -delete
for module in "${MODULES[@]}"; do
	cp -rL "${SITE}/${module}" /out/
done
rm -rf /out/pygame/tests /out/pygame/examples /out/pygame/docs
find /out -name "__pycache__" -type d -prune -exec rm -rf {} +

# Debian's freesansbold.ttf is a symlink into fonts-freefont-ttf; RGSX ships its own fonts.
dpkg-deb -f ./python3-pygame_*.deb Version > /out/PYGAME_DEBIAN_VERSION

echo "Shared libraries required on the device:"
find /out/pygame -name "*.so" -exec readelf -d {} + 2>/dev/null | awk '/NEEDED/ {print $5}' | tr -d '[]' | sort -u

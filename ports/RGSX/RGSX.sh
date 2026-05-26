#!/usr/bin/env bash

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAIN_SCRIPT="${SCRIPT_DIR}/__main__.py"
VENV_DIR="${SCRIPT_DIR}/.venv-linux"

log() {
	echo "[RGSX] $*"
}

warn() {
	echo "[RGSX][WARN] $*" >&2
}

fail() {
	echo "[RGSX][ERROR] $*" >&2
	exit 1
}

detect_linux_flavor() {
	if [[ -f /etc/batocera-release ]] || command -v batocera-info >/dev/null 2>&1; then
		echo "batocera"
		return
	fi

	local id=""
	local id_like=""
	if [[ -r /etc/os-release ]]; then
		# shellcheck source=/dev/null
		. /etc/os-release
		id="${ID:-}"
		id_like="${ID_LIKE:-}"
	fi

	local haystack
	haystack="${id} ${id_like}"
	haystack="${haystack,,}"
	if [[ "${haystack}" == *"bazzite"* ]]; then
		echo "bazzite"
		return
	fi

	echo "linux"
}

find_python() {
	local candidate
	if [[ -n "${RGSX_PYTHON:-}" ]] && command -v "${RGSX_PYTHON}" >/dev/null 2>&1; then
		command -v "${RGSX_PYTHON}"
		return 0
	fi

	for candidate in python3 python; do
		if command -v "${candidate}" >/dev/null 2>&1; then
			command -v "${candidate}"
			return 0
		fi
	done

	return 1
}

run_as_root_non_interactive() {
	if [[ "$(id -u)" -eq 0 ]]; then
		"$@"
		return $?
	fi

	if command -v sudo >/dev/null 2>&1; then
		sudo -n "$@"
		return $?
	fi

	return 1
}

try_install_python_for_bazzite() {
	log "Python absent: tentative d'installation sur Bazzite"

	if command -v dnf5 >/dev/null 2>&1; then
		run_as_root_non_interactive dnf5 -y install python3 python3-pip python3-virtualenv && return 0
	fi

	if command -v dnf >/dev/null 2>&1; then
		run_as_root_non_interactive dnf -y install python3 python3-pip python3-virtualenv && return 0
	fi

	if command -v rpm-ostree >/dev/null 2>&1; then
		if run_as_root_non_interactive rpm-ostree install python3 python3-pip python3-virtualenv; then
			warn "python3 ajoute via rpm-ostree. Un redemarrage est requis avant le premier lancement."
			return 2
		fi
	fi

	return 1
}

get_missing_imports() {
	local python_exec="$1"
	local mode="$2"

	if [[ "${mode}" == "required" ]]; then
		"${python_exec}" - <<'PY'
import importlib.util

required = ("requests", "pygame")
for name in required:
		if importlib.util.find_spec(name) is None:
				print(name)
PY
	else
		"${python_exec}" - <<'PY'
import importlib.util

optional = ("bs4", "PIL", "cairosvg")
for name in optional:
		if importlib.util.find_spec(name) is None:
				print(name)
PY
	fi
}

map_import_to_pip_package() {
	case "$1" in
		requests) echo "requests" ;;
		pygame) echo "pygame" ;;
		bs4) echo "beautifulsoup4" ;;
		PIL) echo "pillow" ;;
		cairosvg) echo "cairosvg" ;;
		*) echo "$1" ;;
	esac
}

ensure_pip_available() {
	local python_exec="$1"
	if "${python_exec}" -m pip --version >/dev/null 2>&1; then
		return 0
	fi

	"${python_exec}" -m ensurepip --upgrade >/dev/null 2>&1
}

ensure_python_modules() {
	local python_exec="$1"
	local missing_required=()
	local missing_optional=()
	local packages=()
	local module
	local package

	mapfile -t missing_required < <(get_missing_imports "${python_exec}" required)
	mapfile -t missing_optional < <(get_missing_imports "${python_exec}" optional)

	if [[ ${#missing_required[@]} -eq 0 && ${#missing_optional[@]} -eq 0 ]]; then
		return 0
	fi

	if ! ensure_pip_available "${python_exec}"; then
		warn "pip indisponible pour ${python_exec}"
		[[ ${#missing_required[@]} -eq 0 ]]
		return $?
	fi

	for module in "${missing_required[@]}"; do
		package="$(map_import_to_pip_package "${module}")"
		packages+=("${package}")
	done

	for module in "${missing_optional[@]}"; do
		package="$(map_import_to_pip_package "${module}")"
		packages+=("${package}")
	done

	if [[ ${#packages[@]} -gt 0 ]]; then
		log "Installation des modules Python manquants: ${packages[*]}"
		"${python_exec}" -m pip install --disable-pip-version-check --upgrade pip setuptools wheel >/dev/null 2>&1 || true
		"${python_exec}" -m pip install --disable-pip-version-check --upgrade "${packages[@]}"
	fi

	mapfile -t missing_required < <(get_missing_imports "${python_exec}" required)
	if [[ ${#missing_required[@]} -gt 0 ]]; then
		warn "Modules requis introuvables apres installation: ${missing_required[*]}"
		return 1
	fi

	mapfile -t missing_optional < <(get_missing_imports "${python_exec}" optional)
	if [[ ${#missing_optional[@]} -gt 0 ]]; then
		warn "Modules optionnels indisponibles (RGSX continuera): ${missing_optional[*]}"
	fi

	return 0
}

build_runtime_python() {
	local system_python="$1"

	if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
		if ! "${system_python}" -m venv "${VENV_DIR}" >/dev/null 2>&1; then
			warn "Impossible de creer le venv local (${VENV_DIR}), utilisation du Python systeme"
			echo "${system_python}"
			return
		fi
	fi

	echo "${VENV_DIR}/bin/python"
}

main() {
	local flavor
	local system_python
	local runtime_python
	local install_status

	if [[ ! -f "${MAIN_SCRIPT}" ]]; then
		fail "Fichier principal introuvable: ${MAIN_SCRIPT}"
	fi

	flavor="$(detect_linux_flavor)"
	log "OS detecte: ${flavor}"

	if ! system_python="$(find_python)"; then
		if [[ "${flavor}" == "bazzite" ]]; then
			if try_install_python_for_bazzite; then
				system_python="$(find_python || true)"
			else
				install_status=$?
				if [[ ${install_status} -eq 2 ]]; then
					fail "Python installe via rpm-ostree. Redemarrez Bazzite puis relancez RGSX."
				fi
				fail "Python introuvable et installation automatique impossible sur Bazzite."
			fi
		else
			fail "Python introuvable. Installez python3 puis relancez RGSX."
		fi
	fi

	runtime_python="$(build_runtime_python "${system_python}")"

	if ! ensure_python_modules "${runtime_python}"; then
		if [[ "${runtime_python}" != "${system_python}" ]]; then
			warn "Echec dans le venv, tentative avec le Python systeme"
			runtime_python="${system_python}"
			ensure_python_modules "${runtime_python}" || fail "Dependances Python manquantes (requests/pygame)."
		else
			fail "Dependances Python manquantes (requests/pygame)."
		fi
	fi

	export PYGAME_HIDE_SUPPORT_PROMPT=1
	export PYTHONWARNINGS="ignore::UserWarning:pygame.pkgdata"
	exec "${runtime_python}" "${MAIN_SCRIPT}"
}

main "$@"
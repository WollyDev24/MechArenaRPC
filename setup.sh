#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

echo "Needed dependencies for the Mech Arena RPC :3"

# 1. Identify distro using /etc/os-release
if [ ! -f /etc/os-release ]; then
    echo "[-] Cannot detect OS: /etc/os-release not found." >&2
    exit 1
fi

. /etc/os-release
DISTRO_ID="${ID:-}"
DISTRO_LIKE="${ID_LIKE:-}"

echo "[*] Detected distribution: ${PRETTY_NAME:-$DISTRO_ID}"

# 2. Install distribution-specific system packages
# Requires: python + venv, imagemagick (for import), xorg-xwininfo,
# libappindicator/ayatana + gobject-introspection for pystray appindicator backend
install_system_dependencies() {
    case "${DISTRO_ID}" in
        arch|manjaro|endeavouros|artix)
            echo "[*] Installing dependencies via pacman..."
            sudo pacman -S --needed --noconfirm \
                python \
                python-pip \
                python-gobject \
                libayatana-appindicator \
                libappindicator-gtk3 \
                imagemagick \
                xorg-xwininfo
            ;;
        fedora|nobara|rhel|centos)
            echo "[*] Installing dependencies via dnf..."
            sudo dnf install -y \
                python3 \
                python3-pip \
                python3-gobject \
                libayatana-appindicator-gtk3 \
                ImageMagick \
                xwininfo
            ;;
        ubuntu|debian|pop|linuxmint|elementary)
            echo "[*] Installing dependencies via apt..."
            sudo apt-get update
            sudo apt-get install -y \
                python3 \
                python3-pip \
                python3-venv \
                python3-gi \
                python3-gi-cairo \
                gir1.2-appindicator3-0.1 \
                libayatana-appindicator3-1 \
                imagemagick \
                x11-utils
            ;;
        opensuse*|suse)
            echo "[*] Installing dependencies via zypper..."
            sudo zypper install -y \
                python3 \
                python3-pip \
                python3-gobject \
                libayatana-appindicator3-1 \
                ImageMagick \
                xwininfo
            ;;
        *)
            # Fallback check for ID_LIKE
            if [[ "${DISTRO_LIKE}" =~ (arch) ]]; then
                sudo pacman -S --needed --noconfirm python python-pip python-gobject libayatana-appindicator libappindicator-gtk3 imagemagick xorg-xwininfo
            elif [[ "${DISTRO_LIKE}" =~ (rhel|fedora) ]]; then
                sudo dnf install -y python3 python3-pip python3-gobject libayatana-appindicator-gtk3 ImageMagick xwininfo
            elif [[ "${DISTRO_LIKE}" =~ (debian|ubuntu) ]]; then
                sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-venv python3-gi python3-gi-cairo gir1.2-appindicator3-0.1 libayatana-appindicator3-1 imagemagick x11-utils
            else
                echo "[-] Unsupported distribution family: ${DISTRO_ID} / ${DISTRO_LIKE}" >&2
                echo "[-] Please manually install: python3, python3-gobject, libayatana-appindicator, imagemagick, xwininfo" >&2
                exit 1
            fi
            ;;
    esac
}

install_system_dependencies

# 3. Create or update virtual environment with --system-site-packages
# Crucial so pystray can resolve system-provided 'gi' (PyGObject/AppIndicator)
echo "[*] Configuring Python virtual environment at ${VENV_DIR}..."
if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv --system-site-packages "${VENV_DIR}"
else
    # Update config file in place if the venv already exists
    CFG_FILE="${VENV_DIR}/pyvenv.cfg"
    if [ -f "${CFG_FILE}" ]; then
        if grep -q "include-system-site-packages" "${CFG_FILE}"; then
            sed -i 's/include-system-site-packages = false/include-system-site-packages = true/' "${CFG_FILE}"
        else
            echo "include-system-site-packages = true" >> "${CFG_FILE}"
        fi
    fi
fi

# 4. Install required Python packages inside the virtual environment
echo "[*] Installing Python requirements..."
"${VENV_DIR}/bin/pip" install --upgrade pip
"${VENV_DIR}/bin/pip" install --upgrade \
    pypresence \
    pillow \
    psutil \
    pystray

echo "[+] Setup finished successfully!"
echo "[*] Run the daemon using:"
echo "    ${VENV_DIR}/bin/python RPCA.py"
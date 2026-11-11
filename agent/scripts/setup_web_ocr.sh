#!/usr/bin/env bash
# Set up the web screenshot OCR tool (web_capture_ocr) on Ubuntu 24.04 without root.
#
# Installs the OCR Python packages into the project venv, the Playwright Chromium headless shell,
# the NSS/ATK system libraries Chromium needs (downloaded as .deb with apt-get and extracted, no
# dpkg install), and the Noto CJK fonts Chinese pages need to render. Safe to re-run.
#
#   bash agent/scripts/setup_web_ocr.sh            # libs in ~/.local/chromium-libs, fonts in ~/.local/share/fonts
#   WEB_OCR_HOME=/opt/ocr bash agent/scripts/setup_web_ocr.sh
#
# Then set the printed WEB_CAPTURE_LIBRARY_PATH (and OCR_ENABLE_MKLDNN=false) in the env file and
# check with: .venv/bin/python -m agent.scripts.check_web_ocr
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$PROJECT/.venv/bin/python}"
HOME_DIR="${WEB_OCR_HOME:-$HOME/.local/chromium-libs}"
FONT_DIR="${WEB_OCR_FONT_DIR:-$HOME/.local/share/fonts}"
# Chromium's runtime libraries missing from slim images, and the CJK fonts.
PACKAGES=(libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libatspi2.0-0t64 libxcomposite1 libxdamage1)
FONT_PACKAGE=fonts-noto-cjk

step() { echo "==> $*"; }

step "OCR Python packages"
"$PY" -m pip install --quiet playwright==1.64.1 paddleocr==3.7.0 paddlepaddle==3.3.1

step "Playwright Chromium headless shell"
"$PY" -m playwright install chromium-headless-shell

if [ "$(id -u)" = "0" ]; then
  step "running as root: installing system dependencies with apt"
  "$PY" -m playwright install-deps chromium
  apt-get install -y "$FONT_PACKAGE"
  echo "System libraries installed; WEB_CAPTURE_LIBRARY_PATH is not needed."
  exit 0
fi

step "downloading ${PACKAGES[*]} $FONT_PACKAGE (no root)"
mkdir -p "$HOME_DIR"/{lists/partial,cache/archives/partial,debs,root}
APT_OPTS=(-o "Dir::State::Lists=$HOME_DIR/lists" -o "Dir::Cache=$HOME_DIR/cache"
          -o "Dir::Cache::archives=$HOME_DIR/cache/archives" -o "Debug::NoLocking=1")
apt-get "${APT_OPTS[@]}" -qq update
(cd "$HOME_DIR/debs" && apt-get "${APT_OPTS[@]}" -qq download "${PACKAGES[@]}" "$FONT_PACKAGE")

step "extracting libraries into $HOME_DIR/root"
for deb in "$HOME_DIR"/debs/*.deb; do
  case "$deb" in
    *"$FONT_PACKAGE"*) dpkg-deb -x "$deb" "$HOME_DIR/fontroot" ;;
    *) dpkg-deb -x "$deb" "$HOME_DIR/root" ;;
  esac
done

step "installing CJK fonts into $FONT_DIR"
mkdir -p "$FONT_DIR/noto"
find "$HOME_DIR/fontroot" -name 'Noto*CJK-*.ttc' \( -name '*Regular*' -o -name '*Bold*' \) -exec cp -f {} "$FONT_DIR/noto/" \;
fc-cache -f "$FONT_DIR" >/dev/null 2>&1 || true

LIB_PATH="$HOME_DIR/root/usr/lib/x86_64-linux-gnu"
echo
echo "Done. Add to the env file (.env / .env.deepseek):"
echo "  WEB_CAPTURE_LIBRARY_PATH=$LIB_PATH"
echo "  OCR_ENABLE_MKLDNN=false"
echo "Then verify: WEB_CAPTURE_LIBRARY_PATH=$LIB_PATH $PY -m agent.scripts.check_web_ocr"

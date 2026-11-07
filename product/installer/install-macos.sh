#!/bin/zsh
set -eu
umask 077
RESOURCES="${0:A:h}"
INSTALL_ROOT="${VERITY_INSTALL_ROOT:-$HOME/Library/Application Support/Verity}"
BROWSER_HOME="${VERITY_BROWSER_HOME:-$HOME}"
HEADLESS=false
[[ "${1:-}" == "--headless" ]] && HEADLESS=true
STAGE=""
PHASE="Preparing installation"
OS_VERSION=$(/usr/bin/sw_vers -productVersion)

say() {
  if ! $HEADLESS; then
    /usr/bin/osascript - "$1" <<'APPLESCRIPT'
on run argv
  display notification (item 1 of argv) with title "Verity Installer"
end run
APPLESCRIPT
  fi
}

finish() {
  local outcome=$?
  if [[ -n "$STAGE" && -d "$STAGE" ]]; then
    /bin/rm -rf -- "$STAGE"
  fi
  if (( outcome != 0 )); then
    if ! $HEADLESS; then
      /usr/bin/osascript - "$PHASE" "$INSTALL_ROOT/installer.log" <<'APPLESCRIPT'
on run argv
  set answer to display dialog "Installation could not finish: " & (item 1 of argv) & ". Check your internet connection and run the installer again. Existing settings were preserved." with title "Verity Installer" buttons {"View log", "OK"} default button "OK"
  if button returned of answer is "View log" then
    do shell script "/usr/bin/open " & quoted form of (item 2 of argv)
  end if
end run
APPLESCRIPT
    fi
  fi
}
trap finish EXIT

if ! $HEADLESS; then
  if ! /usr/bin/osascript <<'APPLESCRIPT'
display dialog "Install Verity's local desktop companion? This downloads its runtime and browser components once. It runs locally, requires no administrator password, and does not install AI model weights or upload documents." with title "Verity Installer" buttons {"Cancel", "Install"} default button "Install"
APPLESCRIPT
  then
    trap - EXIT
    exit 0
  fi
fi

/bin/mkdir -p "$INSTALL_ROOT/versions"
exec > >(/usr/bin/tee -a "$INSTALL_ROOT/installer.log") 2>&1
if (( ${OS_VERSION%%.*} < 14 )); then
  PHASE="Checking macOS compatibility (macOS 14 or newer required)"
  print -u2 "This runtime requires macOS 14 or newer."
  exit 1
fi
STAGE=$(/usr/bin/mktemp -d "$INSTALL_ROOT/.install-XXXXXXXX")
source "$RESOURCES/runtime-pins.sh"
case "$(/usr/bin/uname -m)" in
  arm64) URL="$ARM64_URL"; EXPECTED="$ARM64_SHA256" ;;
  x86_64) URL="$X86_64_URL"; EXPECTED="$X86_64_SHA256" ;;
  *) print -u2 "This installer supports Apple Silicon and Intel Macs."; exit 1 ;;
esac

PHASE="Downloading the local runtime"
say "$PHASE. This can take a few minutes."
/usr/bin/curl --fail --location --proto '=https' --tlsv1.2 --connect-timeout 15 --max-time 300 --retry 2 --output "$STAGE/python.tar.gz" "$URL"
ACTUAL=$(/usr/bin/shasum -a 256 "$STAGE/python.tar.gz")
[[ "${ACTUAL%% *}" == "$EXPECTED" ]] || { print -u2 "Runtime integrity verification failed."; exit 1; }
/usr/bin/tar -xzf "$STAGE/python.tar.gz" -C "$STAGE"
/bin/rm -- "$STAGE/python.tar.gz"
/bin/cp -R "$RESOURCES/payload/." "$STAGE/"

PHASE="Installing local components"
say "$PHASE. No model weights are being downloaded."
"$STAGE/python/bin/python3" -I -m pip --isolated install --only-binary=:all: --disable-pip-version-check --index-url https://pypi.org/simple --cache-dir "$INSTALL_ROOT/download-cache" -r "$STAGE/runtime-requirements.txt"
PLAYWRIGHT_BROWSERS_PATH="$STAGE/browsers" "$STAGE/python/bin/python3" -I -m playwright install chromium --only-shell
"$STAGE/python/bin/python3" -I -c 'from docling_parse.pdf_parser import DoclingPdfParser; from playwright.async_api import async_playwright; print("Local components verified.")'

# Promote a new immutable release; never replace an active runtime or user settings.
RELEASE="$INSTALL_ROOT/versions/$(/bin/date +%Y%m%d%H%M%S)-${STAGE:t}"
/bin/mv "$STAGE" "$RELEASE"
STAGE=""
PHASE="Connecting your browsers"
"$RELEASE/python/bin/python3" -I "$RELEASE/provision_entry.py" --root "$RELEASE" --install-root "$INSTALL_ROOT" --browser-home "$BROWSER_HOME"

if ! $HEADLESS; then
  /usr/bin/open -R "$RELEASE/chrome-extension"
  /usr/bin/osascript <<'APPLESCRIPT'
display dialog "Verity is installed. Load the chrome-extension folder shown in Finder into Chrome or Edge. Once loaded, the extension connects, pairs, and starts its local companion automatically—no terminal or token setup. AI estimates remain unavailable until approved models are provisioned." with title "Verity Installer" buttons {"Done"} default button "Done"
APPLESCRIPT
fi
print "Verity desktop companion installation complete."

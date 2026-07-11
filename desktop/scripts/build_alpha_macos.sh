#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VERSION="${1:-alpha}"
ARCHIVE_DIR="$ROOT/release"
APP_PATH="$ROOT/dist/NeuroEdit.app"
ZIP_PATH="$ARCHIVE_DIR/NeuroEdit-${VERSION}-macOS-unsigned.zip"
DMG_PATH="$ARCHIVE_DIR/NeuroEdit-${VERSION}-macOS-unsigned.dmg"

if [[ ! -d ".venv" ]]; then
  python3 -m venv .venv
fi

source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -c requirements-release.txt -e ".[package]"

rm -rf build dist "$ARCHIVE_DIR"
mkdir -p "$ARCHIVE_DIR"

NEUROEDIT_VERSION="${VERSION#v}" pyinstaller --clean --noconfirm NeuroEdit.spec

if [[ ! -d "$APP_PATH" ]]; then
  echo "Build failed: $APP_PATH was not created." >&2
  exit 1
fi

# Re-copy the bundle into /tmp without Finder/resource-fork metadata before
# signing. Some cloud-backed/workspace paths reattach FinderInfo to framework
# directories, which breaks macOS launch checks. This is still not Developer ID
# signing and does not require an Apple Developer account; it is an ad-hoc
# signature required by macOS for bundled native libraries on Apple Silicon.
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT
CLEAN_APP="$TMP_ROOT/NeuroEdit.app"
ditto --norsrc --noextattr "$APP_PATH" "$CLEAN_APP"
codesign --force --deep --sign - "$CLEAN_APP"
codesign --verify --deep --strict --verbose=2 "$CLEAN_APP"

ditto -c -k --norsrc --noextattr --keepParent "$CLEAN_APP" "$ZIP_PATH"

if command -v hdiutil >/dev/null 2>&1; then
  TMP_DMG_DIR="$TMP_ROOT/dmg"
  rm -rf "$TMP_DMG_DIR"
  mkdir -p "$TMP_DMG_DIR"
  ditto --norsrc --noextattr "$CLEAN_APP" "$TMP_DMG_DIR/NeuroEdit.app"
  ln -s /Applications "$TMP_DMG_DIR/Applications"
  hdiutil create \
    -volname "NeuroEdit ${VERSION}" \
    -srcfolder "$TMP_DMG_DIR" \
    -ov \
    -format UDZO \
    "$DMG_PATH"
fi

cat <<EOF
Unsigned alpha build complete.

App: $APP_PATH
Zip: $ZIP_PATH
DMG: $DMG_PATH

Because this build is unsigned, testers may need to right-click NeuroEdit.app
and choose Open the first time they launch it.
EOF

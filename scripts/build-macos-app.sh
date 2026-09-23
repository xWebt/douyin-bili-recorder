#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"
export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.pyinstaller"
APP="$ROOT_DIR/dist/DouyinBiliRecorder.app"
ZIP="$ROOT_DIR/dist/DouyinBiliRecorder-macos-arm64.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "This build script must be run on macOS."
  exit 1
fi

UV_CACHE_DIR="$ROOT_DIR/.uv-cache" "$ROOT_DIR/.tools/bin/uv" pip install \
  --python "$ROOT_DIR/.venv/bin/python" "${ROOT_DIR}[build]"

rm -rf "$ROOT_DIR/build" "$APP" "$ZIP"

"$ROOT_DIR/.venv/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name "DouyinBiliRecorder" \
  --osx-bundle-identifier "com.webt.DouyinBiliRecorder" \
  --paths "$ROOT_DIR/src" \
  --add-data "$ROOT_DIR/src/douyin_bili_recorder/web:douyin_bili_recorder/web" \
  --add-binary "$ROOT_DIR/.tools/ffmpeg/ffmpeg:bin" \
  --add-binary "$ROOT_DIR/.tools/ffmpeg/ffprobe:bin" \
  --collect-all "biliup" \
  --collect-all "stream_gears" \
  --collect-submodules "uvicorn" \
  "$ROOT_DIR/packaging/launcher.py"

/usr/libexec/PlistBuddy -c 'Set :CFBundleShortVersionString 2.0.1' "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :CFBundleVersion string 2.0.1' "$APP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c 'Set :CFBundleVersion 2.0.1' "$APP/Contents/Info.plist"
xattr -dr com.apple.FinderInfo "$APP" 2>/dev/null || true
xattr -dr com.apple.provenance "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP"
ditto -c -k --norsrc --keepParent "$APP" "$ZIP"

print "$APP"
print "$ZIP"

#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

export PYINSTALLER_CONFIG_DIR="$ROOT_DIR/.pyinstaller"
export COPYFILE_DISABLE=1

APP_NAME="DouyinBiliRecorder"
DIST_APP="$ROOT_DIR/dist/$APP_NAME.app"
RUNTIME_DIR="$ROOT_DIR/dist/$APP_NAME"
ZIP="$ROOT_DIR/dist/${APP_NAME}-macos-arm64.zip"
VERSION="${APP_VERSION:-2.2.8}"
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/DouyinBiliRecorder-build.XXXXXX")"
APP="$BUILD_ROOT/$APP_NAME.app"

cleanup() {
  rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT

if [[ "$(uname -s)" != "Darwin" ]]; then
  print -u2 "This build script must be run on macOS."
  exit 1
fi

UV_CACHE_DIR="$ROOT_DIR/.uv-cache" "$ROOT_DIR/.tools/bin/uv" pip install \
  --python "$ROOT_DIR/.venv/bin/python" "${ROOT_DIR}[build]"

rm -rf "$ROOT_DIR/build" "$RUNTIME_DIR" "$DIST_APP" "$ZIP"

# Build a relocatable onedir runtime. A native launcher will place this
# runtime inside a standard macOS app bundle instead of using PyInstaller's
# fragile macOS BUNDLE wrapper.
"$ROOT_DIR/.venv/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --onedir \
  --console \
  --name "$APP_NAME" \
  --paths "$ROOT_DIR/src" \
  --add-data "$ROOT_DIR/src/douyin_bili_recorder/web:douyin_bili_recorder/web" \
  --add-data "$ROOT_DIR/src/douyin_bili_recorder/fonts:douyin_bili_recorder/fonts" \
  --add-data "$ROOT_DIR/src/douyin_bili_recorder/NotoEmoji-OFL.txt:douyin_bili_recorder" \
  --add-binary "$ROOT_DIR/.tools/ffmpeg/ffmpeg:bin" \
  --add-binary "$ROOT_DIR/.tools/ffmpeg/ffprobe:bin" \
  --collect-all "biliup" \
  --collect-all "stream_gears" \
  --collect-submodules "uvicorn" \
  "$ROOT_DIR/packaging/launcher.py"

if [[ ! -x "$RUNTIME_DIR/$APP_NAME" ]]; then
  print -u2 "PyInstaller runtime executable was not created: $RUNTIME_DIR/$APP_NAME"
  exit 1
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
clang -fobjc-arc -framework Foundation \
  -mmacosx-version-min=12.0 \
  "$ROOT_DIR/packaging/macos_launcher.m" \
  -o "$APP/Contents/MacOS/$APP_NAME"
chmod +x "$APP/Contents/MacOS/$APP_NAME"
cp "$ROOT_DIR/packaging/macos_Info.plist" "$APP/Contents/Info.plist"
printf 'APPL????' > "$APP/Contents/PkgInfo"
cp "$ROOT_DIR/packaging/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$APP/Contents/Info.plist"

cp -R "$RUNTIME_DIR" "$APP/Contents/Resources/runtime"

xattr -cr "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=2 "$APP"
ditto -c -k --norsrc --keepParent "$APP" "$ZIP"
rm -rf "$RUNTIME_DIR"

print "$ZIP"

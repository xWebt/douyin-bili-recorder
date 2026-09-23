#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
TOOLS_DIR="$ROOT_DIR/.tools"
UV_DIR="$TOOLS_DIR/bin"

mkdir -p "$UV_DIR"
if [[ ! -x "$UV_DIR/uv" ]]; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR="$UV_DIR" UV_NO_MODIFY_PATH=1 sh
fi

UV_CACHE_DIR="$ROOT_DIR/.uv-cache" UV_PYTHON_INSTALL_DIR="$ROOT_DIR/.uv-python" \
  "$UV_DIR/uv" venv --python 3.14 "$ROOT_DIR/.venv"

UV_CACHE_DIR="$ROOT_DIR/.uv-cache" "$UV_DIR/uv" pip install \
  --python "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR"

mkdir -p "$TOOLS_DIR/ffmpeg"
curl -fL https://ffmpeg.martin-riedl.de/redirect/latest/macos/arm64/release/ffmpeg.zip -o "$TOOLS_DIR/ffmpeg.zip"
unzip -q -o "$TOOLS_DIR/ffmpeg.zip" -d "$TOOLS_DIR/ffmpeg"
curl -fL https://ffmpeg.martin-riedl.de/download/macos/arm64/1789931890_9.0.2/ffprobe.zip -o "$TOOLS_DIR/ffprobe.zip"
unzip -q -o "$TOOLS_DIR/ffprobe.zip" -d "$TOOLS_DIR/ffmpeg"
chmod +x "$TOOLS_DIR/ffmpeg/ffmpeg" "$TOOLS_DIR/ffmpeg/ffprobe"

printf 'Install biliup with: uv tool install biliup\n'
printf 'Tools directory: %s\n' "$TOOLS_DIR"

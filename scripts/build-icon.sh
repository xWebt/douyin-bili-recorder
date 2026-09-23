#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SOURCE="$ROOT_DIR/packaging/AppIcon.svg"
ICONSET="$ROOT_DIR/build/AppIcon.iconset"
OUTPUT="$ROOT_DIR/packaging/AppIcon.icns"
PREVIEW="$ROOT_DIR/packaging/AppIcon.png"
MASTER="$ROOT_DIR/build/AppIcon-1024.png"

mkdir -p "$ROOT_DIR/build"

/opt/homebrew/bin/python3.12 -c \
  "import cairosvg; cairosvg.svg2png(url='$SOURCE', write_to='$MASTER', output_width=1024, output_height=1024)"

"$ROOT_DIR/.venv/bin/python" -c \
  "from PIL import Image; im=Image.open('$MASTER').convert('RGBA'); im.save('$OUTPUT', format='ICNS'); im.resize((512,512)).save('$PREVIEW', format='PNG')"

rm -f "$MASTER"
print "$OUTPUT"
print "$PREVIEW"

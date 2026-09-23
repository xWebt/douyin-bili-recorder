#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LIVE_URL="${1:?usage: run_local_poc.sh <live-url> [seconds]}"
DURATION_SECONDS="${2:-45}"
START_EPOCH="$(date +%s)"
START_ISO="$(date -r "$START_EPOCH" "+%Y-%m-%dT%H:%M:%S%z")"
OUTPUT_DIR="$ROOT_DIR/poc/session-$START_EPOCH"

mkdir -p "$OUTPUT_DIR"

printf '{\n  "url": "%s",\n  "start_epoch": %s,\n  "start_iso": "%s",\n  "duration_target_seconds": %s\n}\n' \
  "$LIVE_URL" "$START_EPOCH" "$START_ISO" "$DURATION_SECONDS" \
  > "$OUTPUT_DIR/session.json"

set +o pipefail
PATH="$ROOT_DIR/.tools/ffmpeg:$PATH" \
  "$ROOT_DIR/.venv/bin/streamlink" \
  --stdout \
  "$LIVE_URL" \
  best \
  | "$ROOT_DIR/.tools/ffmpeg/ffmpeg" \
      -hide_banner \
      -loglevel warning \
      -i pipe:0 \
      -t "$DURATION_SECONDS" \
      -map 0 \
      -c copy \
      -f mpegts \
      "$OUTPUT_DIR/part-000.ts"
set -o pipefail

if [[ ! -s "$OUTPUT_DIR/part-000.ts" ]]; then
  print -u2 "recording output is empty: $OUTPUT_DIR/part-000.ts"
  exit 1
fi

"$ROOT_DIR/.tools/ffmpeg/ffprobe" \
  -v error \
  -show_entries format=duration,size,bit_rate \
  -show_entries stream=index,codec_name,codec_type,width,height,r_frame_rate,sample_rate,channels \
  -of json \
  "$OUTPUT_DIR/part-000.ts" \
  > "$OUTPUT_DIR/probe.json"

"$ROOT_DIR/.tools/ffmpeg/ffmpeg" \
  -hide_banner \
  -loglevel warning \
  -y \
  -fflags +genpts+igndts \
  -i "$OUTPUT_DIR/part-000.ts" \
  -c copy \
  -bsf:a aac_adtstoasc \
  -movflags +faststart \
  -avoid_negative_ts make_zero \
  "$OUTPUT_DIR/part-000.mp4"

printf 'POC_OUTPUT=%s\n' "$OUTPUT_DIR"

#!/bin/zsh
# Daily morning job: render dashboard from Obsidian, send via OpenWA.
set -euo pipefail

ROOT="${0:A:h}"                 # repo location — works from launchd or a terminal
OPENWA="$ROOT/OpenWA"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

# Personal configuration lives in .env (never committed); see .env.example.
if [[ -f "$ROOT/.env" ]]; then
  set -a; source "$ROOT/.env"; set +a
fi

NODE="${OPENWA_NODE:-node}"
PY="${PYTHON_BIN:-python3}"

echo "=== $(date '+%F %T') start ==="

PNG="$("$PY" "$ROOT/generate_dashboard.py")"
echo "rendered $PNG"

SCRIPT_FILE="$ROOT/podcast/script-$(date '+%F').txt"
VOICE="$ROOT/podcast/voice-$(date '+%F').ogg"
if "$PY" "$ROOT/generate_podcast_script.py" >/dev/null 2>"$LOG_DIR/podcast.log"; then
  echo "script $SCRIPT_FILE"
else
  VOICE=""
  echo "podcast script generation failed, see $LOG_DIR/podcast.log (image will still be sent)"
fi
if [[ -n $VOICE ]]; then
  # Voice quality tiers: VoiceStudio (local, cloned voice) → Gemini TTS (cloud)
  # → macOS say (always works). Start VoiceStudio if it isn't up.
  if ! curl -sf http://127.0.0.1:3900/health >/dev/null; then
    echo "starting VoiceStudio"
    /usr/bin/open -a VoiceStudio
    for i in {1..60}; do
      curl -sf http://127.0.0.1:3900/health >/dev/null && break
      sleep 2
    done
  fi
  if "$PY" "$ROOT/tts_voicestudio.py" "$SCRIPT_FILE" "$VOICE"; then
    echo "voice $VOICE (VoiceStudio)"
  elif "$PY" "$ROOT/tts_gemini.py" "$SCRIPT_FILE" "$VOICE"; then
    echo "voice $VOICE (Gemini fallback)"
  elif "$PY" "$ROOT/text_to_voice.py" "$SCRIPT_FILE" "$VOICE"; then
    echo "voice $VOICE (say fallback)"
  else
    VOICE=""
    echo "voice note unavailable (image will still be sent)"
  fi
fi

API_PID=""
if ! curl -sf http://localhost:2785/api/health >/dev/null; then
  echo "starting OpenWA"
  cd "$OPENWA"
  NODE_ENV=development "$NODE" dist/main >> "$LOG_DIR/openwa.log" 2>&1 &
  API_PID=$!
  cd "$ROOT"
  for i in {1..60}; do
    curl -sf http://localhost:2785/api/health >/dev/null && break
    sleep 2
  done
fi

cleanup() {
  if [[ -n $API_PID ]]; then
    kill "$API_PID" 2>/dev/null && wait "$API_PID" 2>/dev/null || true
    echo "stopped OpenWA"
  fi
}
trap cleanup EXIT

"$PY" "$ROOT/send_whatsapp.py" "$PNG"
if [[ -n $VOICE && -f $VOICE ]]; then
  "$PY" "$ROOT/send_voice.py" "$VOICE" || echo "voice send failed (image was sent)"
fi
# keep two weeks of outputs
find "$ROOT/out" -name 'morning-dashboard-*.png' -mtime +14 -delete
find "$ROOT/podcast" \( -name 'script-*.txt' -o -name 'voice-*.ogg' \) -mtime +14 -delete
echo "=== $(date '+%F %T') done ==="

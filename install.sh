#!/usr/bin/env bash
# Grok Studio installer: clones (or updates) the repo and installs Python deps.
# usage: curl -fsSL https://raw.githubusercontent.com/smfworks/grok-studio/main/install.sh | bash
#    or: GROK_STUDIO_DIR=/somewhere bash install.sh
set -euo pipefail
REPO="${GROK_STUDIO_REPO:-https://github.com/smfworks/grok-studio.git}"
if [ -z "${GROK_STUDIO_DIR:-}" ]; then
  if [ -d /workspace ] && [ -w /workspace ]; then GROK_STUDIO_DIR=/workspace/grok-studio; else GROK_STUDIO_DIR="$HOME/grok-studio"; fi
fi
if [ -d "$GROK_STUDIO_DIR/.git" ]; then git -C "$GROK_STUDIO_DIR" pull --ff-only
else git clone --depth 1 "$REPO" "$GROK_STUDIO_DIR"; fi
python3 -m pip install --user --break-system-packages -r "$GROK_STUDIO_DIR/requirements.txt" 2>/dev/null \
  || python3 -m pip install --break-system-packages -r "$GROK_STUDIO_DIR/requirements.txt" \
  || python3 -m pip install -r "$GROK_STUDIO_DIR/requirements.txt"
missing=""
for b in ffmpeg ffprobe pdftotext fc-match; do command -v "$b" >/dev/null || missing="$missing $b"; done
if [ -n "$missing" ]; then
  echo "Missing system tools:$missing"
  echo "  Debian/Ubuntu: sudo apt-get install -y ffmpeg poppler-utils fontconfig fonts-dejavu"
  echo "  macOS:         brew install ffmpeg poppler fontconfig"
fi
[ -n "${XAI_API_KEY:-}" ] || echo "Note: set XAI_API_KEY (an xAI API key with credits) before generating."
echo "Grok Studio installed at $GROK_STUDIO_DIR"

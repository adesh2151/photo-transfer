#!/usr/bin/env bash
# Photo Transfer — Linux / macOS launcher.
# Tries to set up a small virtual environment for the optional QR library,
# but falls back to running directly if that isn't available. The app has NO
# required dependencies, so it always runs.
cd "$(dirname "$0")"

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python

RUNPY="$PY"

# Try a virtual environment (keeps things tidy). Harmless if it fails.
if [ ! -d .venv ]; then
  "$PY" -m venv .venv >/dev/null 2>&1 || true
fi
if [ -f .venv/bin/python ]; then
  RUNPY=".venv/bin/python"
fi

# Optional: install 'segno' for the on-screen QR image. Best-effort only.
if ! "$RUNPY" -c "import segno" >/dev/null 2>&1; then
  "$RUNPY" -m pip install -q --disable-pip-version-check segno >/dev/null 2>&1 \
    || "$RUNPY" -m pip install -q --user --disable-pip-version-check segno >/dev/null 2>&1 \
    || true
fi

exec "$RUNPY" app.py "$@"

#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PY=python3
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip wheel >/dev/null 2>&1
  pip install -r requirements.txt
  PY=".venv/bin/python"
fi
exec "$PY" gui.py

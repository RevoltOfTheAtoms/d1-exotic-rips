#!/usr/bin/env sh
# D1 Exotic Rips: run ./start.sh to open the window (Linux). Installs the Python packages it needs.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is not installed. Install Python 3.10 or newer, then run ./start.sh again."
  exit 1
fi
if ! python3 -c "import numpy, PIL" >/dev/null 2>&1; then
  echo "Installing the Python packages D1 Exotic Rips needs (numpy, pillow)..."
  python3 -m pip install --user -q -r requirements.txt || {
    echo "pip couldn't install them. On Ubuntu/Debian: sudo apt install python3-numpy python3-pil python3-tk"
    exit 1
  }
fi
if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "The window needs tkinter. On Ubuntu/Debian: sudo apt install python3-tk"
  echo "Or use the command line: python3 d1rip.py --help"
  exit 1
fi
exec python3 d1rip.py gui

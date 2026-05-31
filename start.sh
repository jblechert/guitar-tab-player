#!/usr/bin/env bash
# Guitar Tab Player – launcher for Linux / macOS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── Activate virtual environment if present ────────────────────────────────────
if   [ -d ".venv/bin" ];  then source .venv/bin/activate
elif [ -d "venv/bin" ];   then source venv/bin/activate
fi

# ── First-run: install dependencies ───────────────────────────────────────────
if ! python -c "import tabplayer" &>/dev/null; then
    echo "First run – installing dependencies …"
    pip install -q -r requirements.txt
fi

# ── FluidSynth hint ───────────────────────────────────────────────────────────
if ! command -v fluidsynth &>/dev/null; then
    echo "WARNING: FluidSynth not found – audio may be silent."
    echo "  Arch/Manjaro : sudo pacman -S fluidsynth soundfont-fluid"
    echo "  Ubuntu/Debian: sudo apt  install fluidsynth fluid-soundfont-gm"
    echo "  macOS        : brew install fluidsynth fluid-soundfont-gm"
fi

exec python -m tabplayer "$@"

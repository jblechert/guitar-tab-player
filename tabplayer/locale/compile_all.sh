#!/usr/bin/env bash
# Compile all .po files to .mo files.
# Run from the project root:  bash tabplayer/locale/compile_all.sh
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for po in "$SCRIPT_DIR"/*/LC_MESSAGES/tabplayer.po; do
    mo="${po%.po}.mo"
    echo "Compiling: $po → $mo"
    msgfmt -o "$mo" "$po"
done
echo "Done."

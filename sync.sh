#!/bin/zsh
# Copy the four runtime scripts from this repo into the runtime directory,
# overwriting existing copies. Usage: ./sync.sh [target_dir]
# Default target: ~/Pictures/pixiv_bookmarks
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-$HOME/Pictures/pixiv_bookmarks}"

if [[ ! -d "$TARGET" ]]; then
    echo "Target directory does not exist: $TARGET" >&2
    echo "Create it first, then re-run." >&2
    exit 1
fi

echo "Syncing: $REPO_DIR -> $TARGET"
for f in pixiv_core.py pixivdownload.py download_all.py pixivdownload_gui.py; do
    cp -v "$REPO_DIR/$f" "$TARGET/$f"
done
echo "Done."

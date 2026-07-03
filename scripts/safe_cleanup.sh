#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$HOME/Projects/Darial}"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_DIR="$HOME/Downloads/Darial_project_backups_$STAMP"

mkdir -p "$ARCHIVE_DIR"

cd "$PROJECT_DIR"

echo "Archiving patch backups to:"
echo "$ARCHIVE_DIR"

find . -maxdepth 1 -type d -name '.mvp_*_backup_*' -print0 |
while IFS= read -r -d '' directory; do
  mv "$directory" "$ARCHIVE_DIR/"
done

find . -type d -name '__pycache__' -prune -exec rm -rf {} +
find . -type f -name '*.pyc' -delete
find . -type f -name '.DS_Store' -delete

echo
echo "Removed generated cache files."
echo "Patch backups were moved, not deleted."
echo
echo "Remaining project status:"
git status --short 2>/dev/null || true

#!/bin/bash
# Two-way sync of one local folder with its Drive folder through rclone bisync, on a machine
# Google ships no Drive client for. See docs/drive-access.md, Sync on Linux.
set -uo pipefail
REMOTE="${DRIVE_SYNC_REMOTE:-drive:}"
STATE="${DRIVE_SYNC_STATE:-$HOME/.local/state/slopmeister/drive-sync}"
# 1.74.2 carries the last fix to the conflict flags. Older releases accept the flags and can
# rename the newer version away too.
MIN_RCLONE=1.74.2
# Percent of one side's files. A run that would delete more refuses and changes nothing.
MAX_DELETE=2

usage() {
  echo "usage: slopmeister-drive-sync <vault|documents> [--resync|--force]" >&2
  exit 2
}

[ $# -ge 1 ] && [ $# -le 2 ] || usage
case "$1" in
  vault) folder="${SLOPMEISTER_VAULT:-$HOME/.slopmeister/vault}"; remote="${REMOTE}obsidian" ;;
  documents) folder="${DRIVE_SYNC_DOCUMENTS:-$HOME/My Drive}"; remote="$REMOTE" ;;
  *) usage ;;
esac

version=$(rclone version 2>/dev/null | sed -n '1s/^rclone v//p')
oldest=$(printf '%s\n' "$MIN_RCLONE" "$version" | sort -V | head -1)
if [ -z "$version" ] || [ "$oldest" != "$MIN_RCLONE" ]; then
  echo "refused: rclone $MIN_RCLONE or newer is required, found ${version:-none}" >&2
  exit 2
fi

# No --recover: it restores the listings after a critical error and removes that halt.
# --resilient lets the run after a failed listing proceed, the failed run still exits nonzero.
args=(bisync "$folder" "$remote" --workdir "$STATE" --max-delete "$MAX_DELETE"
  --conflict-resolve newer --conflict-loser num
  --conflict-suffix "sync-conflict-linux,sync-conflict-drive" --suffix-keep-extension
  --create-empty-src-dirs --drive-skip-gdocs --drive-skip-shortcuts --resilient --max-lock 2m)
# The vault has its own run and its own deletion guard.
[ "$1" = documents ] && args+=(--filter "- /obsidian/**")
case "${2:-}" in
  "") ;;
  --force) args+=(--force) ;;
  --resync)
    # A resync over differing files lets the local one overwrite Drive's and keeps no copy.
    if [ -n "$(ls -A "$folder" 2>/dev/null)" ]; then
      echo "refused: --resync only fills an empty folder, move $folder aside first" >&2
      exit 2
    fi
    mkdir -p "$folder"
    # A first sync takes long. A file that changes on Drive meanwhile must win over the
    # older copy fetched here, which rclone's default would upload over it.
    args+=(--resync --resync-mode newer)
    ;;
  *) usage ;;
esac

# The listings name every private file, so the state folder is the owner's alone.
mkdir -p "$STATE" && chmod 700 "$STATE" || exit 1
exec rclone "${args[@]}"

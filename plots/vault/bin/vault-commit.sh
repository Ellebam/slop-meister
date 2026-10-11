#!/bin/bash
# Scheduled vault commit with a mass-deletion guard, a non-blocking lint report and a daily
# git bundle beside the synced vault so the history leaves the machine. See
# docs/vault-version-control.md.
set -uo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
V="${SLOPMEISTER_VAULT:-$HOME/.slopmeister/vault}"
# Git and the bundle location run after the lint step changes directory, so a relative
# override must not stay relative.
case "$V" in /*) ;; *) V="$PWD/$V" ;; esac
G="${VAULT_GIT_DIR:-$HOME/.vault-git/obsidian.git}"
LOG="${VAULT_LOG:-$HOME/.vault-git/vault-commit.log}"
LOCK="${VAULT_LOCK:-$HOME/.vault-git/bin/vault-lock.py}"
MAX_DEL_FILES=25
MAX_DEL_PCT=5

g() { git --git-dir="$G" --work-tree="$V" "$@"; }
log() { printf '%s %s\n' "$(date '+%F %T')" "$*" >> "$LOG"; }
notify() {
  [ "${VAULT_NOTIFY:-1}" = 0 ] && return 0
  osascript -e "display notification \"$1\" with title \"Vault commit\"" >/dev/null 2>&1 || true
}

# Launchd keeps no output of this job, so Git's own words and the lock helper's go to the log.
exec 2>>"$LOG"
[ -d "$G" ] || { log "no repository at $G"; exit 0; }
[ -x "$LOCK" ] || { log "no vault lock helper at $LOCK"; exit 0; }
if [ "${SLOPMEISTER_VAULT_LOCKED:-0}" != 1 ]; then
  exec "$LOCK" --git-dir "$G" --kind scheduled --timeout 0 -- "$0"
fi
# macOS TCC blocks background processes from synced cloud folders. Git then sees an
# unreadable tree and reports nothing to commit, a silent no-op, so refuse to continue blind.
if ! ls "$V/_system" >/dev/null 2>&1; then
  log "NO ACCESS to the vault, grant Full Disk Access to ~/.vault-git/VaultCommit.app, see docs/vault-version-control.md"
  notify "No access to the vault. Grant Full Disk Access to VaultCommit.app."
  exit 0
fi

if ! g add -A; then
  log "add failed, Git's message is above, see docs/vault-version-control.md"
  notify "Add failed, see vault-commit.log"; exit 0
fi
if g diff --cached --quiet; then
  log "nothing to commit"
else
  tracked=$(g ls-files | wc -l | tr -d ' ')
  deleted=$(g diff --cached --name-only --diff-filter=D | wc -l | tr -d ' ')
  [ "$tracked" -gt 0 ] || tracked=1
  pct=$(( deleted * 100 / tracked ))
  if [ "$deleted" -gt "$MAX_DEL_FILES" ] || [ "$pct" -gt "$MAX_DEL_PCT" ]; then
    g reset -q
    log "SKIPPED, $deleted deletions ($pct% of $tracked) exceed the guard, inspect with vaultgit status"
    notify "Skipped, $deleted deletions staged. Inspect the vault before committing."
    exit 0
  fi
  if g commit -q -m "Vault snapshot $(date '+%F %H:%M')"; then
    log "committed $(g rev-parse --short HEAD), $(g show --shortstat --format= HEAD | tail -1 | sed 's/^ *//')"
  else
    log "commit failed, Git's message is above, see docs/vault-version-control.md"
    notify "Commit failed, see vault-commit.log"; exit 0
  fi
fi

# Lint report only. A defect in a note must never cost the history that would let you fix it.
cd "$V" || exit 0
pipes=$(grep -rlE '^\|.*\[\[[^]]*[^\\]\|[^]]*\]\]' --include='*.md' . 2>/dev/null | wc -l | tr -d ' ')
bare=$(grep -rnoE --include='*.md' '\[\[(README|WORKLOG|_INDEX|CUSTOMER|contacts)(\|[^]]*)?(#[^]|]*)?\]\]' . 2>/dev/null | wc -l | tr -d ' ')
[ "$pipes$bare" = "00" ] || log "LINT alias-pipe-rows=$pipes bare-wikilinks=$bare"

# Daily bundle, written to a temp name and renamed so the sync never uploads a half-written
# file. It sits in the folder that holds the real vault, the link's own folder is not synced.
BUNDLE_DIR="$(cd -P "$V/.." && pwd)/Backups"
BUNDLE="$BUNDLE_DIR/vault-history.bundle"

# The bundle is the only copy of the history off this machine. A rebuilt repository must
# never replace it with a shorter one, so every head it holds has to be in a local ref.
# A bundle Git cannot read or that lists no head is kept too, nothing here can tell what it
# held.
holds_bundle_history() {
  local heads sha
  heads=$(g bundle list-heads "$BUNDLE") || return 1
  [ -n "$heads" ] || return 1
  for sha in $(printf '%s\n' "$heads" | cut -d' ' -f1); do
    [ -n "$(g for-each-ref --count=1 --contains "$sha" 2>/dev/null)" ] || return 1
  done
}

mkdir -p "$BUNDLE_DIR"
if [ -f "$BUNDLE" ] && [ -z "$(find "$BUNDLE" -mmin +1380 2>/dev/null)" ]; then
  exit 0
fi
if [ -f "$BUNDLE" ] && ! holds_bundle_history; then
  log "bundle kept, this repository does not hold the history in $BUNDLE, see docs/vault-version-control.md"
  notify "Bundle kept, the repository does not hold its history. See vault-commit.log."
  exit 0
fi
tmp="$BUNDLE_DIR/.vault-history.bundle.tmp"
if g bundle create "$tmp" --all >/dev/null && mv -f "$tmp" "$BUNDLE"; then
  log "bundle written, $(du -h "$BUNDLE" | cut -f1)"
else
  rm -f "$tmp"
  log "bundle failed, Git's message is above, see docs/vault-version-control.md"
  notify "Bundle failed, see vault-commit.log"
fi

#!/bin/sh
# Hook: UserPromptSubmit
# Tracks the active slash-command skill for the status line.
# Writes /tmp/claude-skill-<session_id> when a /command is submitted.
#
# We intentionally do NOT clear on plain (non-slash) prose because the user
# often sends follow-up messages inside a running skill (e.g. answers to
# clarifying questions). The sentinel persists until:
#   - the user submits another slash command (replaces it), or
#   - the session ends (sentinel is an orphan in /tmp; session_id is unique
#     per session so stale files never collide with a new session).
#
# Skill tool invocations by Claude itself are handled by a separate
# PreToolUse hook (skill-tracker-tool-hook.sh) which writes the same file.

input=$(cat)
session_id=$(printf '%s' "$input" | jq -r '.session_id // empty')
prompt=$(printf '%s' "$input" | jq -r '.prompt // empty')

[ -z "$session_id" ] && exit 0

sentinel="/tmp/claude-skill-${session_id}"

# Only act on slash commands — plain prose messages are ignored so the
# skill label persists throughout a multi-turn skill run.
if printf '%s' "$prompt" | grep -qE '^\s*/[a-zA-Z]'; then
  # Extract skill name: first word after the slash, strip leading slash,
  # lowercase, truncate to 15 chars.
  skill=$(printf '%s' "$prompt" | grep -oE '/[a-zA-Z][a-zA-Z0-9_-]*' | head -1 | sed 's|^/||' | tr '[:upper:]' '[:lower:]' | cut -c1-15)
  if [ -n "$skill" ]; then
    printf '%s' "$skill" > "$sentinel"
    # No global "most recent" mirror — that file leaked across unrelated parallel
    # sessions. Subagent inheritance is handled in the status line by deriving the
    # parent session_id from transcript_path, which scopes to actual lineage only.
  fi
fi

exit 0

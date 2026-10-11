#!/bin/sh
# Hook: PreToolUse (scoped to tool_name == "Skill")
# Tracks skills invoked by Claude itself (not via user slash commands) for the
# status line. Writes the same /tmp/claude-skill-<session_id> sentinel that
# the UserPromptSubmit hook writes, so both paths update the same file.
#
# The JSON envelope for PreToolUse hooks is:
#   { "session_id": "...", "tool_name": "...", "tool_input": { ... } }
# For the Skill tool, tool_input.skill holds the skill name (e.g. "investigate").

input=$(cat)
session_id=$(printf '%s' "$input" | jq -r '.session_id // empty')
skill_raw=$(printf '%s' "$input" | jq -r '.tool_input.skill // empty')

[ -z "$session_id" ] && exit 0
[ -z "$skill_raw" ] && exit 0

sentinel="/tmp/claude-skill-${session_id}"

# Normalise: strip any leading slash, lowercase, truncate to 15 chars —
# same treatment as the UserPromptSubmit hook.
skill=$(printf '%s' "$skill_raw" | sed 's|^/||' | tr '[:upper:]' '[:lower:]' | cut -c1-15)

if [ -n "$skill" ]; then
  printf '%s' "$skill" > "$sentinel"
  # No global "most recent" mirror — see statusline-command.sh: subagents inherit
  # via parent_session_id derived from transcript_path, scoped to real lineage.
fi

exit 0

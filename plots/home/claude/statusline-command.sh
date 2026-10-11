#!/bin/sh
# Claude Code status line.
# Format:
#   main checkout : "<dir> | <branch> | <skill> | ctx: N% | lim: N%"
#   worktree      : "<branch> | <skill> | ctx: N% | lim: N%"
# - Dir is suppressed inside a git linked worktree; the branch already names it.
# - Skill comes from /tmp/claude-skill-<session_id> (written by the slash-command
#   hook + the Skill-tool PreToolUse hook). For subagents (their own session_id,
#   no per-session sentinel) we derive the parent session_id from transcript_path
#   — subagent transcripts live at <projects>/<parent_id>/subagents/agent-*.jsonl.
#   This scopes skill inheritance to the actual parent→subagent lineage; we never
#   read a "global most recent" file, so unrelated parallel sessions can't leak.
# - Session name segment intentionally dropped: for subagents it's the auto-derived
#   Task description, which is misleading vs. the triggering skill.

input=$(cat)

cwd=$(printf '%s' "$input" | jq -r '.workspace.current_dir // .cwd')
session_id=$(printf '%s' "$input" | jq -r '.session_id // empty')
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
used=$(printf '%s' "$input" | jq -r '.context_window.used_percentage // empty')
limit_pct=$(printf '%s' "$input" | jq -r '.rate_limits.five_hour.used_percentage // empty')

branch=$(git -C "$cwd" branch --show-current 2>/dev/null || true)

# Linked-worktree detection: git-dir differs from git-common-dir.
git_dir=$(git -C "$cwd" rev-parse --git-dir 2>/dev/null || true)
git_common_dir=$(git -C "$cwd" rev-parse --git-common-dir 2>/dev/null || true)
in_worktree=0
if [ -n "$git_dir" ] && [ -n "$git_common_dir" ] && [ "$git_dir" != "$git_common_dir" ]; then
  in_worktree=1
fi

# Active skill — per-session sentinel first; for subagents, walk up to the parent
# session via transcript_path. No cross-session fallback: only this session's own
# lineage is considered, so an unrelated parallel session can never leak its skill.
skill=""
if [ -n "$session_id" ]; then
  sentinel="/tmp/claude-skill-${session_id}"
  [ -f "$sentinel" ] && skill=$(cat "$sentinel" 2>/dev/null || true)
fi
if [ -z "$skill" ] && [ -n "$transcript_path" ]; then
  # Subagent transcripts live at <projects>/<parent_session_id>/subagents/agent-*.jsonl
  # (and may be nested for sub-subagents). Strip from the FIRST /subagents/ onward
  # and basename what remains — that's always the topmost ancestor session id.
  case "$transcript_path" in
    */subagents/*)
      parent_dir=$(printf '%s' "$transcript_path" | sed 's|/subagents/.*||')
      parent_session_id=$(basename "$parent_dir")
      if [ -n "$parent_session_id" ] && [ "$parent_session_id" != "$session_id" ]; then
        parent_sentinel="/tmp/claude-skill-${parent_session_id}"
        [ -f "$parent_sentinel" ] && skill=$(cat "$parent_sentinel" 2>/dev/null || true)
      fi
      ;;
  esac
fi

# Path segment: "<dir> | <branch>" in main checkout, "<branch>" in a worktree.
# Branch is separated by "|" rather than " on " to save horizontal space.
if [ "$in_worktree" -eq 0 ]; then
  dir=$(printf '%s' "$cwd" | sed "s|^$HOME|~|")
  output="$dir"
  [ -n "$branch" ] && output="${output} | ${branch}"
else
  output=""
  [ -n "$branch" ] && output="${branch}"
fi

[ -n "$skill" ] && output="${output} | ${skill}"
[ -n "$used" ] && output="${output} | ctx: $(printf '%.0f' "$used")%"
if [ -n "$limit_pct" ]; then
  output="${output} | lim: $(printf '%.0f' "$limit_pct")%"
else
  output="${output} | lim: --"
fi

printf '%s' "$output"

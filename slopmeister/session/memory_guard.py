"""Refuse a Codex `apply_patch` that touches a client's private memory folder.

The home `PreToolUse` hook runs it with the folders from src/permissions.toml as arguments. Codex
on Linux runs without a sandbox, so this refusal is the only one before the file lands. It reads
the hook event on stdin and prints a deny for a patch that adds, changes, deletes or moves a file
inside a listed folder. Codex also applies a patch from a shell command that names `apply_patch`,
which reaches the hook as `Bash`, so such a command's patch headers are checked the same way. Any
other shell write stays uncovered. An event it cannot read is denied too. The `slopmeister-prompt`
launcher turns any failure of this module into a blocking exit, so a broken guard never allows the
write.
"""

import fnmatch
import glob
import json
import os
from pathlib import Path
import sys

# Codex's parser accepts leading whitespace before a hunk header, so this match does too.
TOOLS = ("apply_patch", "Bash")
# Codex applies a patch from a shell command only through one of these program names.
PATCH_PROGRAMS = ("apply_patch", "applypatch")
HEADERS = ("*** Add File:", "*** Update File:", "*** Delete File:", "*** Move to:")
REASON = (
    "Slopmeister refuses writes into a client's private memory folder. The vault is the only "
    "memory, see the global instructions."
)


def _patch_paths(patch: str) -> list[str]:
    paths = []
    for line in patch.splitlines():
        stripped = line.strip()
        for header in HEADERS:
            if stripped.startswith(header):
                paths.append(stripped.removeprefix(header).strip())
    return paths


def _folders(patterns: list[str], home: str) -> list[tuple[str, ...]]:
    """Each folder as path parts, once as written and once with its fixed part's links resolved."""
    folders = []
    for pattern in patterns:
        written = Path(home + pattern.removeprefix("~") if pattern.startswith("~/") else pattern)
        parts = written.parts
        fixed = next((i for i, part in enumerate(parts) if any(c in part for c in "*?[")), None)
        fixed = len(parts) if fixed is None else fixed
        resolved = Path(os.path.realpath(Path(*parts[:fixed]))).parts + parts[fixed:]
        # A matching folder that is itself a link is also guarded at the place it points to.
        linked = [Path(os.path.realpath(match)).parts for match in glob.glob(str(written))]
        folders.extend(dict.fromkeys((parts, resolved, *linked)))
    return folders


def _inside(target: tuple[str, ...], folder: tuple[str, ...]) -> bool:
    # macOS folders ignore case by default, so a differently cased path is the same folder there.
    return len(target) > len(folder) and all(
        fnmatch.fnmatchcase(part.casefold(), pattern.casefold())
        for part, pattern in zip(target, folder, strict=False)
    )


def _denied(event: object, patterns: list[str], home: str) -> bool:
    if not isinstance(event, dict):
        return True
    tool, tool_input, cwd = event.get("tool_name"), event.get("tool_input"), event.get("cwd")
    patch = tool_input.get("command") if isinstance(tool_input, dict) else None
    plain_shell = tool == "Bash" and isinstance(patch, str)
    if tool not in TOOLS or (plain_shell and not any(name in patch for name in PATCH_PROGRAMS)):
        return False
    if not isinstance(patch, str) or not isinstance(cwd, str) or not os.path.isabs(cwd):
        return True
    folders = _folders(patterns, home)
    absolute = [os.path.normpath(os.path.join(cwd, path)) for path in _patch_paths(patch)]
    targets = [Path(p).parts for p in absolute] + [
        Path(os.path.realpath(p)).parts for p in absolute
    ]
    return any(_inside(target, folder) for target in targets for folder in folders)


def main(patterns: list[str]) -> None:
    home = os.environ.get("HOME", "")
    if not patterns or not os.path.isabs(home):
        raise SystemExit("memory guard needs its folders and an absolute HOME")
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = None
    if _denied(event, patterns, home):
        decision = {"permissionDecision": "deny", "permissionDecisionReason": REASON}
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **decision}}))


if __name__ == "__main__":
    main(sys.argv[1:])

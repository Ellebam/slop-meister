# Recover or abandon

Before replacing a worker, ask it to save its state and restart commands, and confirm it has. After a crash only what's on disk survives.
```bash
task plot-session -- <repo> <plot> <name> --redispatch --tool claude < kickoff.md
task plot-session -- <plot> <name> --directory --redispatch --tool codex < kickoff.md
task plot-session -- <repo> <plot> <name> --abandon --handoff <absolute-notes> --tool <tool>
```

Redispatch stops the old worker and its descendants, verifies they are gone and starts a fresh conversation in the same workspace, keeping its saved configuration, notes and slot. When it refuses, fix what it names and retry the same name. When no process appears, it prints no runnable line, so look at the terminal before retrying rather than risk a second session. A slot is recovered the same way, never with `task slot:up`. Abandon needs a saved nonempty handoff, closes only that worker, removes its claim and leaves the issue open and the workspace intact.

For operator-requested removal of a retired or orphaned workspace, follow `docs/workspace-removal.md` in the invoking Slopmeister checkout. Use its `task --dir <invoking-Slopmeister> workspace:remove -- <absolute-workspace>` command on the machine that owns the workspace.

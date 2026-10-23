# Harvest report and removal

Continue here only after the earlier harvest steps succeed. Retain the selected route and all compatibility restrictions.

## 6. The report

If step 3 retains the workspace, retain its notes too, deliver the report and skip step 7. Do not prepare claim hand-back while retaining an active worker.

For a slot worktree with `tmp/`, copy its contents before the report with `umask 077 && cp -Rn "<worktree>/tmp/." "<proof>/"`. Use the launcher's state directory, `PLOT_SESSION_STATE_DIR` or `<saved-absolute-Slopmeister>/tmp/plot-session`, with `<SLOT_NAME>-proof` appended. Require private destination directories. Refuse symlinks and nonregular entries in either tree and symlinked destination ancestors before copying. Never overwrite saved proof. Copy failure stops release. The guard verifies matching bytes before shutdown and removal. Missing, unreadable, changed or symlinked files keep the refusal.

Deliver the [task summary](../execute-plan/task-summary.md) closing shape once, with the merge, CI, tracker and vault results now known and cleanup reported as pending. Keep unanswered questions verbatim, name every unresolved recovery or housekeeping item and the documents changed or why none changed. When the worth-changing line names a concrete tooling defect, put the existing issue number or a one-line proposed title in the report, and file nothing. Cite evidence that survives cleanup.

Before deleting notes, retain the test guide and named proof needed to verify the result, plus otherwise-lost recovery records outside the worktree: unanswered questions, spill paths and each live process's exact start command, working directory, environment and port, with secrets redacted. Then delete `<TASK-ID>-NOTES.md` and the other root notes carrying this task's identifier, and leave other files alone. The recorded scratch handoff stays for hand-back. Older sessions without owned scratch retain their workspace unless another contained handoff has explicit ownership.

## 7. Remove yourself

The report is delivered first. When the state requires retaining the workspace, do not remove it. A non-slot worktree then runs, as its last action, `cd <main-checkout> && <saved-absolute-Slopmeister>/bin/slopmeister workspace-remove --self -- <absolute-worktree>` outside the tool's sandbox, with paths quoted for the shell. The final `--` keeps later arguments from enabling force. The command verifies the sole calling worker, stops it and its descendants, completes a recorded claim hand-back, checks ownership again and removes the worktree. Its private result log lands under `<saved-absolute-Slopmeister>/tmp/plot-session/`, which the report names. A starting line is not completed cleanup.

A slot worktree, one carrying `.slot.env`, runs `<saved-absolute-Slopmeister>/bin/slopmeister slots down <main-checkout> <SLOT_TARGET> <SLOT_NAME> --self` instead, from the main checkout and outside the sandbox, with both values from `.slot.env`. It stops this session, releases the slot and removes the worktree. Its result lands in `<saved-absolute-Slopmeister>/tmp/slots/<SLOT_NAME>.down.log`.

Both commands refuse unsaved or unknown work. Add `--force` only when the operator explicitly accepted losing what the refusal names. Both keep the local branch. A refusal before shutdown leaves the session running. A later refusal can leave the worker stopped and the workspace retained; the surviving caller reads the result log before choosing a retry.

A directory session cannot remove itself. End with the report and name `task workspace:remove -- <absolute session directory>` for the dispatcher.


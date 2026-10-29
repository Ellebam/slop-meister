# Testing environments

[Check selection and execution](testing.md)

## Workstation and CI boundaries

| Where | Layers | Requirements |
|---|---|---|
| Hosted Ubuntu CI | `task lint`, `task quality`, `task test:portable`, and the four `host:*` checks | Python 3.14, Task, portable system tools, optional host dependencies, Chromium and Docker, no native login or model inference |
| Workstation `task check` | The core catalogue plus `tests/native` and `bin/slopmeister workstation drift`, which reports home-install differences as notices in linked task worktrees, fails on them in the main checkout, and fails on changed delivered configuration in a launcher-prepared worktree. `task home:diff` reports allow-rule status | [Workstation setup](../README.md#quick-start), standalone Codex and native process inspection |
| Real-session smoke | `task test:live` | Normal subscription login for both clients, the operator's consent |

The four CI check jobs use GitHub-hosted Ubuntu runners, pinned setup actions and read-only tokens. Core jobs retain failed reports and logs as artifacts. Host tasks keep their output in the Actions log. No client login, shared workstation state or model inference is required. The separate [release job](releases.md) can write only after every check job passes. Run host tasks separately from workstation `task check`.

CI and the workstation share the catalogue. Real host requirements stay native, never skipped to obtain green. Portability needs minimal-environment execution or fixture ownership of relevant dependencies. CI does not prove macOS launch, discovery, Orca or real-session behavior.

Focused directory-session fixtures must live outside a Git checkout. When the calling session exports workspace scratch as TMPDIR, use an owned external temporary root for those fixtures; do not weaken the directory guard. The complete gate already assigns external job roots.

Routine checks own their fixtures and usually need no peer coordination. Worktrees do not isolate shared ancestors. A concurrent Codex sandbox can create `/tmp/.codex` and correctly trigger installer refusal below it. Native tool calls are the observed local workaround, not a general platform fix. Preserve the ancestor guard and other sessions' files. Home-install differences are notices only in linked task worktrees. The main checkout, doctor and prepared-delivery comparison remain strict.

Explicit operator coordination is reserved for installed machine configuration changes, non-test vault writes, driving or closing operator terminal sessions and probing an operator-designated live environment. These operations affect shared operator state. Prefer disposable fixtures for testing their mechanisms.

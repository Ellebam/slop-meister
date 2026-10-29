# Testing Slopmeister

Select tests by [Test purpose](../src/skills/implement/SKILL.md#test-purpose). Use the smallest check that observes the behavior. Apply [behavior proof](../src/skills/local-qa/SKILL.md#3-the-break-it-pass) to distinct changes and boundaries. Absence claims need subject activity and a control when capture can hide execution. Run the complete local gate after exact restoration. Deterministic checks make no paid requests. Real sessions prove decisions those checks cannot establish. [Architecture](architecture.md) owns layers, [CONTRIBUTING.md](../CONTRIBUTING.md) owns placement.

Test paths name their layer and subsystem. Names describe stable behavior and the failure prevented. Follow [contributor setup](../CONTRIBUTING.md#set-up), including the Node or Orca runtime requirement for portable browser tests.

## Which command

| Need | Command | What runs |
|---|---|---|
| The developer tools | `task tools` | Exact `.venv` from committed `uv.lock`; undeclared packages are removed |
| One subsystem while editing | `.venv/bin/python -m pytest tests/unit/<subsystem> tests/integration/<subsystem> -q` | Those tests, in one process |
| Lint | `task lint` | ruff, ruff format, shellcheck at warning severity |
| Quality | `task quality` | [Size budgets](architecture.md#budgets), import rules and bounded exceptions, [private identifier patterns](context-layer.md#private-identifier-patterns) and plot style outside the allowlist, `render --check`, docs paths |
| The portable layers | `task test:portable` | `tests/unit` and `tests/integration`, the CI test job |
| Core workstation gate | `task check` | the core catalogue with bounded concurrency, native layer and installed drift included |
| Optional Linux host layer | `task host:lint`, `task host:syntax`, `task host:test`, `task host:ha:check` | Ansible lint/syntax, synthetic role tests, Chromium panel tests and pinned-image HA configuration validation |
| The command inventory | `bin/slopmeister check --list` | every check with its layer, kind and phase, no execution |
| The real-session smoke | `task test:live` | one `sow` session per tool, only with the operator's consent, see [session testing](testing-sessions.md#run-real-session-qa) |
| Real Jira and Confluence acceptance | `task sandbox:up`, then `task sandbox:live` | the delivered Atlassian reads and writes against local Data Center servers, opt-in and never in a gate, see [Atlassian sandbox](atlassian-sandbox.md) |

`--jobs` controls process concurrency. `task check -- --jobs 2` reduces machine load, `--jobs 1` serialises for diagnosis. `task check -- --report <report-path>` in the Git-ignored scratch directory in the task worktree keeps the JSON report and logs as evidence.

uv owns Python dependencies. `task tools` runs `uv sync --locked`, which creates `.venv` but refuses stale project metadata instead of rewriting `uv.lock`. Developer dependencies live in `[dependency-groups].dev`. Change a pin there, refresh only that package with `uv lock --upgrade-package <name>`, review the lock diff, and run `uv lock --check`. Install or update uv through the [workstation procedure](../src/skills/workstation/SKILL.md).

The development environment and product runtime are separate. Both require Python 3.14 or newer. Checks use `.venv/bin/python` and `.venv/bin/ruff` exclusively. `bin/slopmeister` runs the uninstalled checkout with system `python3`; uv does not package the runtime. The workstation installer copies the self-contained vault modules behind an absolute platform-specific Python 3.14 launcher.

The [catalogue](../slopmeister/check/catalogue.py) declares every core check once with a layer, `portable` or `native`, and a kind, `lint`, `quality` or `tests`. Lint and quality run first, the three pytest layers run concurrently where safe, and installed drift runs last. Ordinary workstation invocations wait on one blocking file lock. CI, listing and cleanup bypass it. A failed command, a missing check or an interruption fails the complete gate, and a later pass never hides an earlier failure. The gate judges each check by its exit status alone. A dead pytest worker fails its layer, at the latest at the check's time limit.

`bin/slopmeister quality --inventory` reports runtime `oversized_400` and each exception's metric, ceiling, target and owner. Generated output, test data and binary fixtures are excluded. The [budgets](architecture.md#budgets) include word limits for repository docs and skills.

Each reviewer and interrupted or failed check retains its original leader as an unreaped ownership anchor until every non-zombie member of that process group is gone, then reaps the leader. Repeated bounded group signalling therefore reaches same-group descendants created during teardown without exposing a reused group ID. A child that calls `setsid()` or moves to another process group is outside this guarantee and is stopped through its run folder instead. Once the leader has already been reaped, cleanup never falls back to unchecked group signalling.

Every process a job starts inherits `SLOPMEISTER_TEST_ROOT`, its run folder. Nested gates append their folder with `:`. At job end, the runner stops its process group, then this user's processes whose exact `SLOPMEISTER_TEST_ROOT` or `TMPDIR` names that folder. Codex children can retain only `TMPDIR`. The runner checks birth identity before SIGTERM and SIGKILL. It reads environments through `sysctl KERN_PROCARGS2` on macOS and `/proc/<pid>/environ` on Linux. It never reads mixed arguments and variables from `ps` text. If processes cannot stop or contents cannot be deleted, the folder and its `owner.json` stay. The log records `cleanup failed`. A passing job becomes failed. An already failed job keeps its exit code. Evidence stays in the log beside the report.

Every `task check` first clears leftovers of ended runs, and `bin/slopmeister check --clean` does only that and prints one count line. A run has ended when the gate recorded in its folder's `owner.json` has exited, judged by that process's birth identity. The cleanup stops this user's processes whose named run folders have all ended, then removes each `/tmp/htr.*` entry that is a real directory owned by this user, holds a regular `owner.json` owned by this user, has ended and is named by no remaining process. It never follows a link, never touches a folder without `owner.json`, a folder whose gate is alive or `/tmp/cfd.*`, and it is safe beside another worker's running gate, including one on older code, whose `owner.json` names its live gate. A hard-killed gate cannot finish its own cleanup, and the next gate start covers it. There is no background cleanup process.

Plot declaration and claim tests run in portable layers. Native dispatch needs the platform sleep guard and fixed Python, curl, OpenSSL and 1Password runtime. Native install needs installed clients or host services. Native slots need process and socket inspection. Native vault drive-sync needs real rclone. Launcher changes use `.venv/bin/python -m pytest -q tests/unit/launch tests/integration/launch`, and live delivery stays a real session test.

Vault changes use `.venv/bin/python -m pytest -q tests/unit/vault tests/integration/vault`. Portable fixtures use disposable subject trees and external bare repositories; the optional Obsidian adapter has its own fake-command tests. The scheduled-script overrides select its vault, Git directory, log and notification suppression, and its bundle follows the vault. Production defaults remain the installed paths.

Host checks stay outside the core catalogue and run in their own CI job. Install the optional `host` Python group and pinned browser dependencies through the [host guide](../host/README.md#check-without-deployment). Run executable fixtures inside an isolated container on a shared machine. The separate HA checker controls Docker without mounting its socket into that container. These checks apply no playbook and prove no live account or service.

## Workstation and CI boundaries

The [environment guide](testing-environments.md) names CI, workstation and real-session prerequisites, installed drift behavior and temporary-fixture boundaries.

## The independent tester and readable handoff

See [session testing](testing-sessions.md#the-independent-tester-and-readable-handoff).

## Test files and cleanup

See [session testing](testing-sessions.md#test-files-and-cleanup).

## Run real session QA

See [session testing](testing-sessions.md#run-real-session-qa).

## Evidence and diagnosis

The console shows each job's result and duration, then the complete gate result. Interactive failures retain a private report and logs at the printed path. Non-terminal failures also print the last 100 lines of each failed check, capped at 32 KiB, with every displayed line neutralized against GitHub workflow-command parsing. The unchanged complete log remains authoritative.

Successful default runs remove their temporary logs. Failed runs retain their report and logs. Each core CI check job selects an explicit report path and, only when that check step fails, uploads the report and complete logs as its own artifact for seven days. Setup failures do not attempt an evidence upload. Repository tests prove the declared workflow configuration, not GitHub's provider-side execution; a real failed run is required for that proof. For task evidence, select a unique report path in the Git-ignored scratch directory in the task worktree:

```bash
task check -- --jobs 8 --report tmp/task-check-01.json
```

The JSON report records run ownership, UTC execution intervals, requested concurrency, completion, return codes, job durations and log paths. Existing explicit report or log destinations are refused before jobs start. Measure the outer `task check` invocation as well when claiming an end-to-end speed improvement. Runner timing alone excludes work done before the runner starts.

Keep evidence for the current task until acceptance, then preserve named proof through harvest and clean up only disposable evidence except unresolved recovery records and immutable producer reports. There is no automatic historical results ledger or retention service. Save compact findings and measured results in the task's completion report. Missing native usage data stays unknown, and wall-time/session limits are not a subscription token quota.

See [the working agreement](../AGENTS.md) for proof and review gates, and [the session walkthrough](session-walkthrough.md) for the surrounding workflow.

## Automatic post-plan workflow checks

Run focused regressions for candidate freezing, the four commit/shipping permission combinations, native-prompted denied delivery, repeatable tester runs, final review replay and stateless reassessment before the complete gate:

```bash
.venv/bin/python -m pytest tests/unit/plots tests/unit/review tests/integration/review tests/unit/spine tests/integration/spine tests/integration/session -q
.venv/bin/python -m pytest tests/integration/render -q
task check -- --report tmp/task-check-01.json
```

Use a new report path for each gate attempt. Deterministic fixtures demonstrate failure and recovery logic, not native acceptance, which comes from real tasks running the path. See [the procedure](../src/skills/execute-plan/SKILL.md).

## Issue claim fixtures

Run `.venv/bin/python -m pytest tests/unit/claims tests/integration/claims -q -p no:cacheprovider` for classification, launcher, recovery, inventory and worktree receipts. These fixtures use disposable fake GitHub and native records, with no model inference or live tracker writes. CI prints PASS rows for the launcher, recovery, inventory and worktree suites from the saved pytest log. This proves control flow, not provider availability or an installed agent following instructions.

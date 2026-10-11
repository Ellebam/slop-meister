# Testing Slopmeister

Select tests by [Test purpose](../src/skills/implement/SKILL.md#test-purpose). Use the smallest check that observes the behavior. Apply [behavior proof](../src/skills/local-qa/SKILL.md#3-the-break-it-pass) to distinct changes and boundaries. Absence claims need subject activity and a control when capture can hide execution. Run the complete local gate after exact restoration. Deterministic checks make no paid requests. Real sessions prove decisions those checks cannot establish. [Architecture](architecture.md) owns layers, [CONTRIBUTING.md](../CONTRIBUTING.md) owns placement.

Test paths name their layer and subsystem. Names describe stable behavior and the failure prevented.

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
| The real-session smoke | `task test:live` | one `sow` session per tool, only with the operator's consent, see below |
| Real Jira and Confluence acceptance | `task sandbox:up`, then `task sandbox:live` | the delivered Atlassian reads and writes against local Data Center servers, opt-in and never in a gate, see [Atlassian sandbox](atlassian-sandbox.md) |

`--jobs` controls process concurrency. `task check -- --jobs 2` reduces machine load, `--jobs 1` serialises for diagnosis. `task check -- --report <report-path>` in the Git-ignored scratch directory in the task worktree keeps the JSON report and logs as evidence.

uv owns Python dependencies. `task tools` runs `uv sync --locked`, which creates `.venv` but refuses stale project metadata instead of rewriting `uv.lock`. Developer dependencies live in `[dependency-groups].dev`. Change a pin there, refresh only that package with `uv lock --upgrade-package <name>`, review the lock diff, and run `uv lock --check`. Install or update uv through the [workstation procedure](../src/skills/workstation/SKILL.md).

The development environment and product runtime are separate. Both require Python 3.14 or newer. Checks use `.venv/bin/python` and `.venv/bin/ruff` exclusively. `bin/slopmeister` runs the uninstalled checkout with system `python3`; uv does not package the runtime. The workstation installer copies the self-contained vault modules behind an absolute platform-specific Python 3.14 launcher.

The [catalogue](../slopmeister/check/catalogue.py) declares every core check once with a layer, `portable` or `native`, and a kind, `lint`, `quality` or `tests`. Lint and quality run first, the three pytest layers run concurrently where safe, and installed drift runs last. Another invocation may run at the same time. A failed command, a missing check or an interruption fails the complete gate, and a later pass never hides an earlier failure. The gate judges each check by its exit status alone. A dead pytest worker fails its layer, at the latest at the check's time limit.

`bin/slopmeister quality --inventory` reports runtime `oversized_400` and each exception's metric, ceiling, target and owner. Generated output, test data and binary fixtures are excluded. The [budgets](architecture.md#budgets) include word limits for repository docs and skills.

Each reviewer and interrupted or failed check retains its original leader as an unreaped ownership anchor until every non-zombie member of that process group is gone, then reaps the leader. Repeated bounded group signalling therefore reaches same-group descendants created during teardown without exposing a reused group ID. A child that calls `setsid()` or moves to another process group is outside this guarantee and is stopped through its run folder instead. Once the leader has already been reaped, cleanup never falls back to unchecked group signalling.

Every process a job starts inherits `SLOPMEISTER_TEST_ROOT`, its run folder. Nested gates append their folder with `:`. At job end, the runner stops its process group, then this user's processes whose exact `SLOPMEISTER_TEST_ROOT` or `TMPDIR` names that folder. Codex children can retain only `TMPDIR`. The runner checks birth identity before SIGTERM and SIGKILL. It reads environments through `sysctl KERN_PROCARGS2` on macOS and `/proc/<pid>/environ` on Linux. It never reads mixed arguments and variables from `ps` text. If processes cannot stop or contents cannot be deleted, the folder and its `owner.json` stay. The log records `cleanup failed`. A passing job becomes failed. An already failed job keeps its exit code. Evidence stays in the log beside the report.

Every `task check` first clears leftovers of ended runs, and `bin/slopmeister check --clean` does only that and prints one count line. A run has ended when the gate recorded in its folder's `owner.json` has exited, judged by that process's birth identity. The cleanup stops this user's processes whose named run folders have all ended, then removes each `/tmp/htr.*` entry that is a real directory owned by this user, holds a regular `owner.json` owned by this user, has ended and is named by no remaining process. It never follows a link, never touches a folder without `owner.json`, a folder whose gate is alive or `/tmp/cfd.*`, and it is safe beside another worker's running gate, including one on older code, whose `owner.json` names its live gate. A hard-killed gate cannot finish its own cleanup, and the next gate start covers it. There is no background cleanup process.

Plot declaration and claim tests run in portable layers. Native dispatch needs the platform sleep guard and fixed Python, curl, OpenSSL and 1Password runtime. Native install needs installed clients or host services. Native slots need process and socket inspection. Native vault drive-sync needs real rclone. Launcher changes use `.venv/bin/python -m pytest -q tests/unit/launch tests/integration/launch`, and live delivery stays a real session test.

Vault changes use `.venv/bin/python -m pytest -q tests/unit/vault tests/integration/vault`. Portable fixtures use disposable subject trees and external bare repositories; the optional Obsidian adapter has its own fake-command tests. The scheduled-script overrides select its vault, Git directory, log and notification suppression, and its bundle follows the vault. Production defaults remain the installed paths.

Host checks stay outside the core catalogue and run in their own CI job. Install the optional `host` Python group and pinned browser dependencies through the [host guide](../host/README.md#check-without-deployment). Run executable fixtures inside an isolated container on a shared machine. The separate HA checker controls Docker without mounting its socket into that container. These checks apply no playbook and prove no live account or service.

## Workstation and CI boundaries

| Where | Layers | Requirements |
|---|---|---|
| Hosted Ubuntu CI | `task lint`, `task quality`, `task test:portable`, and the four `host:*` checks | Python 3.14, Task, portable system tools, optional host dependencies, Chromium and Docker, no native login or model inference |
| Workstation `task check` | The core catalogue plus `tests/native` and `bin/slopmeister workstation drift`, which reports home-install differences as notices in linked task worktrees, fails on them in the main checkout, and fails on changed delivered configuration in a launcher-prepared worktree. `task home:diff` reports allow-rule status | [Workstation setup](../README.md#quick-start), standalone Codex and native process inspection |
| Real-session smoke | `task test:live` | Normal subscription login for both clients, the operator's consent |

The four CI check jobs use GitHub-hosted Ubuntu runners, pinned setup actions and read-only tokens. Core jobs retain failed reports and logs as artifacts. Host tasks keep their output in the Actions log. No client login, shared workstation state or model inference is required. The separate [release job](releases.md) can write only after every check job passes. Run host tasks separately from workstation `task check`.

CI and the workstation share the catalogue. Real host requirements stay native, never skipped to obtain green. Portability needs minimal-environment execution or fixture ownership of relevant dependencies. CI does not prove macOS launch, discovery, Orca or real-session behavior.

Routine checks own their fixtures and usually need no peer coordination. Worktrees do not isolate shared ancestors. A concurrent Codex sandbox can create `/tmp/.codex` and correctly trigger installer refusal below it. Native tool calls are the observed local workaround, not a general platform fix. Preserve the ancestor guard and other sessions' files. Home-install differences are notices only in linked task worktrees. The main checkout, doctor and prepared-delivery comparison remain strict.

Explicit operator coordination is reserved for installed machine configuration changes, non-test vault writes, driving or closing operator terminal sessions and probing an operator-designated live environment. These operations affect shared operator state. Prefer disposable fixtures for testing their mechanisms.

## The independent tester and readable handoff

Follow [operator proof](1password-access.md#prove-the-route) for real approvals, dialogs and reboot. Run `.venv/bin/python -m pytest -q tests/unit/session tests/integration/session/test_secret_run.py tests/integration/workstation/test_op_setup.py tests/native/install/test_permission_op.py tests/integration/render/test_permission_contract.py` for the session's `op` against a stand-in real `op` and a stand-in Home Assistant, the setup step and the native rules.

For the shared [task summary](../src/skills/execute-plan/task-summary.md), run `.venv/bin/python -m pytest -q tests/integration/spine/test_rendered.py tests/integration/render/test_procedures.py`. These checks cover caller references, tool parity and stateless reassessment. There is deliberately no report-shape or milestone parser. Readability and session compliance need a fresh small spine task in each tool and the operator's acceptance.

For selected service actions, run `.venv/bin/python -m pytest -q tests/unit/session/service_actions tests/integration/install/test_service_actions_*.py tests/native/install/test_service_action*.py tests/unit/plots`. Portable tests cover provider behavior, shared operations, profile admission, workspace delivery, snapshots, cancellation and diagnostics. Native tests drive the fixed curl on each system against disposable PAT-only and PKCS#12 HTTPS servers and check exact entry-command approval-rule precedence. Only the disposable certificate generator runs through system Python with its installed `cryptography`. The delivered session and pytest environment remain standard-library-only. The suites use no real 1Password or provider credentials. `tests/integration/install/test_service_actions_server_ca.py` covers profile pins and `tests/native/install/test_service_actions_server_ca.py` drives their TLS enforcement and `tests/unit/sandbox` keeps sandbox secrets out of process arguments, while real server acceptance runs only in the opt-in [Atlassian sandbox](atlassian-sandbox.md). Native approval behavior and real ticket retrieval require the separately authorized [service-action proof](service-actions.md#verify).

The independent tester starts from a fresh clone without `.venv` or worker scratch. Guides own setup and dependencies. It executes required scenarios itself, worker evidence cannot substitute. Changed HEAD or tested files block the run. Use the task checkout's `bin/slopmeister` when present. Only required scenarios decide the verdict. Triage failures, setup/guide faults and additional candidates through [prune](../src/skills/prune/SKILL.md). Never regrade saved results or repeat unchanged checks for another receipt. Save output under `evidence/` and quote exact substrings, including whitespace and escapes. Only evidence files other than `draft.json` are valid citations. Batch independent checks. Each launch owns a fresh run directory. Commit-backed runs retain `--cwd --commit`; candidates use pathless `--candidate`, preserve missing-commit errors and record the tree.

The tester checks its draft before submission with the fixed producer command supplied in its prompt: `<python> <slopmeister>/bin/slopmeister tester validate --run <absolute run> --draft <absolute run>/evidence/draft.json`. The command reads the saved required scenarios and evidence without changing the run. `VALID DRAFT (outcome: fail; not test proof)` means valid citations for a failing test, not a passing subject. Invalid drafts exit nonzero with `INVALID DRAFT` and citation positions where applicable. Correct citation mistakes from saved files without rerunning the subject, then submit the checked draft unchanged. Final supervisor validation, native identity and containment checks still apply.

The tester validates every original citation before masking report text. When masking changes a quote or its path, the report and saved verdict cite a separate masked excerpt whose source label identifies the original file with sensitive text masked and escapes preserved. Unchanged citations keep their original paths. Validation runs on the raw quotes and again on the masked report and its excerpts. Original evidence and completed run records remain untouched. Chat summarizes the sanitized report while preserving its exact verdict, blockers and proof limits. The existing `verbatim-verdict` scenario assertion means the exact verdict or gate, not a full report pasted into chat.

Masking has limits. Reports mask recognized credential formats, known sensitive environment assignments and explicit token, secret, password or API-key labels followed by `=` or `:`. Token length alone does not trigger masking, so an unknown, unlabelled secret can stay visible. If masking breaks an evidence reference, the run becomes blocked and keeps its raw evidence for diagnosis. Run control files are trusted local state, not protected from a hostile tester running as the same unsandboxed user.

A failed preparation is still collectable as a blocked report. If supervisor startup is unconfirmed, collect that exact run while diagnosing it. Collection replays a result without regrading and never writes one. It answers pending while the supervisor runs and blocked once it is gone. A timeout report records whether the tester's owned process group stopped, keeps partial evidence and names any unverified group.

After saving a pass, fail or blocked result, the supervisor removes only that run's `checkout/`, including read-only caches. Reports, run records and evidence remain. If stopping the tester is unverified, or deletion fails, the checkout remains and `result.json` records `checkout_cleanup_error` without changing the outcome. Failures during launch preparation retain their checkout. Existing runs are not cleaned up.

Empty or whitespace-only quotes also block validation. For expected empty output, the guide must check command success and the saved output before emitting a nonempty assertion marker, as [test-guide](../src/skills/test-guide/SKILL.md) requires. A dirty checkout or command error must not print success. Preserve existing blocked verdicts, even when their scenario results passed.

OpenCode checks use a fake `opencode` from `tests/support/opencode_fake.py` and never call a provider. Run `.venv/bin/python -m pytest tests/integration/opencode tests/integration/launch/test_opencode.py tests/unit/threads/test_opencode_occupants.py -q -p no:cacheprovider` for native evidence, the launch line, argument refusal, occupancy, tester outcomes and provider-value scrubbing. A live OpenCode proof needs the operator's provider reachable and its variable in `~/.zshenv`, see [OpenCode](opencode.md).

Task notes are ordinary untracked Markdown and can be corrected or selectively updated without a recovery command. Producer results are different. Collect the exact tester run recorded in the notes and replay the review's protected task-and-mode result. A candidate-bound result validates the current tree identity before replay and refuses substitution without launching. Shipping keeps no result file, Git and the PR show what shipped, and a rerun of ship never repeats a confirmed write. A permission error or a failed or blocked producer does not authorize another external session, result replacement or alternate state namespace.

## Test files and cleanup

The runner and process-sensitive suites create short private `/private/tmp/htr.<random>/` roots. `owner.json` names the folder and the gate's PID and kernel start identity. Gate jobs receive separate `TMPDIR` values. Fixture homes, sockets, repositories and reproducer files stay beneath owned roots. Normal HOME remains available for binary discovery and installed-drift checks. Native listener fixtures bind port 0 and keep the assigned socket open.

Native close-out proof runs create one run folder `slopmeister-<task>-<tool>/` and one retro note `slopmeister-<task>-<tool>-retro.md` per fresh session in the vault's `_system/test-fixtures/`, planted and driven from the task's test guide. The fresh session maintains the run folder before its handback, and close-out verifies it. Derive any index expectation from the actual file shape and permitted paths, never an assumed README table row. After acceptance and authorized cleanup, remove only exact recorded test files whose bytes match the expected final state, preserving unrelated or changed files. Use `slopmeister-vault commit` for the named vault paths. Whole-vault manifests taken before and after every turn show changes outside the scenario's paths. The [test-guide examples](../src/skills/test-guide/SKILL.md) cover scoped first-turn instructions, attributable operator answers and owned-file cleanup.

No automated test writes into the real vault, vault tests run against disposable subject trees under their own temporary directory. A leftover note in the vault's `_system/test-fixtures/` is removed only by exact path with operator approval, and only while `vaultgit ls-files --error-unmatch -- <path>` succeeds and `vaultgit status --porcelain -- <path>` prints nothing, both checked immediately before the delete, so history can restore it. Commit the removals by name with `slopmeister-vault commit`. A prefix, marker or age alone never authorizes a removal.

Cleanup and debloat sessions use `bin/slopmeister check --clean` for `/private/tmp/htr.*` run folders instead of deleting them by hand, because it applies the ownership and liveness rules above. A prefix, PID alone or age is never deletion authority. There is no shared scheduler, whole-gate lock or background cleanup service.


## Run real session QA

Use the cheapest layer that observes behavior. Registry tests check required entries independently of generic translation tests. `tests/native/install/test_discovery.py` checks delivered configuration loading. `tests/native/install/test_permissions.py` drives both clients through `tests/support/standin.py`, a loopback model with scripted calls. It requires every contract deny's direct bare and argument forms to be refused and records the `env` difference. Marker stubs and unrefused controls prove execution safely. `tests/native/install/test_permission_intent.py` checks cleanup prompt precedence over inherited allows in Codex's policy engine and the unlisted direct-PID kill control. Deterministic checks do not prove real approval-model judgment. Live scenarios use harmless stubs and record decisions. Start and stop a disposable child within one client shell command so PID namespaces cannot invalidate the control.

`task test:live` runs one `sow` session per tool, with operator consent. Neither may change tracked files, and each must send the one message, plain summary first, both options under Your call, within both limits. Each session has 300 seconds, no retries or grading model. The live layer runs only when named explicitly. See the [plot's trigger rule](../plots/slopmeister/local-qa-gates.md).

The smoke uses the operator's normal login and home, so native session history lands there and the installed global instructions are the ones it reads. Missing login or rate limits are a blocked result, not a failure. Each session's command, output and errors stay under pytest's temporary directory. Read them before recording a pass or fail.

Documentation scenarios use the current task's guide and separate operator consent, keeping the smoke unchanged. Bind native write grants and vault, history and spill routes to disposable fixtures before a write-capable session. Record remote calls, verify containment and stop if isolation is unproven. Finalize refusal is checked before any remote command.

The full spine needs no harness. Every real task runs it, including a real opposite-tool tester. The scoped close-out contract is proven by fresh Slopmeister directory sessions that the tester drives from the task's test guide, and link and containment behavior is deterministic under `tests/integration/vault/`.

The launcher accepts individual Codex `mcp_servers.<name>.enabled=false` overrides for disabling inherited connections. Enabling, replacing or bundling connection settings remains refused. These invocation options leave the normal account configuration unchanged.

## Evidence and diagnosis

The console shows each job's result and duration, then the complete gate result. Interactive failures retain a private report and logs at the printed path. Non-terminal failures also print the last 100 lines of each failed check, capped at 32 KiB, with every displayed line neutralized against GitHub workflow-command parsing. The unchanged complete log remains authoritative.

Successful default runs remove their temporary logs. Failed runs retain their report and logs. Each core CI check job selects an explicit report path and, only when that check step fails, uploads the report and complete logs as its own artifact for seven days. Setup failures do not attempt an evidence upload. Repository tests prove the declared workflow configuration, not GitHub's provider-side execution; a real failed run is required for that proof. For task evidence, select a unique report path in the Git-ignored scratch directory in the task worktree:

```bash
task check -- --jobs 8 --report tmp/task-check-01.json
```

The JSON report records run ownership, UTC execution intervals, requested concurrency, completion, return codes, job durations and log paths. Existing explicit report or log destinations are refused before jobs start. Measure the outer `task check` invocation as well when claiming an end-to-end speed improvement. Runner timing alone excludes work done before the runner starts.

Keep evidence for the current task until acceptance, then clean it up during close-out except unresolved recovery records and immutable producer reports. There is no automatic historical results ledger or retention service. Save compact findings and measured results in the task's completion report. Missing native usage data stays unknown, and wall-time/session limits are not a subscription token quota.

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

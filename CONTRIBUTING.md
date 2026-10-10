# Contributing

Slopmeister is a Python product. This page is the short form of [the architecture](docs/architecture.md) for someone about to change it.

## Set up

Follow the [workstation skill](src/skills/workstation/SKILL.md) for macOS or Ubuntu prerequisites, including uv. Then sync the committed environment:

```bash
task tools          # uv sync --locked creates the exact .venv from uv.lock
task check          # the complete deterministic gate on a workstation
```

Python 3.14 is the development and runtime floor. The checkout runs through `bin/slopmeister`. The self-contained vault runtime is the narrow exception: the workstation installer copies its reviewed bytes behind `~/.vault-git/bin/slopmeister-vault` so repository and directory sessions use the same command without a checkout. Repository checks use only `.venv`; `task tools` also removes packages that are not in the lock.

Core developer tools belong in `[dependency-groups].dev` in `pyproject.toml`. Ansible and host validation tools belong in the optional `host` group. `uv sync --locked --group host` selects that group. The [host guide](host/README.md#check-without-deployment) owns browser setup and the separate `host:*` checks. After changing a pin, run `uv lock --upgrade-package <name>`, review `uv.lock`, and confirm `uv lock --check`. Normal setup never updates the lock.

## Where things go

| You are adding | It goes in | It is run by |
|---|---|---|
| A command | one module with `main(argv)` under the owning subpackage, registered in `slopmeister/cli.py` | `bin/slopmeister <command>` and a Task target in `taskfiles/` |
| Code a session runs on its own | `slopmeister/session/`, standard library only | the installer's snapshot |
| Vault code every workspace can run | `slopmeister/vault/runtime/`, standard library only | `bin/slopmeister vault` in this checkout, installed `slopmeister-vault` elsewhere |
| Linux service deployment or its static tests | `host/`, with explicit tasks in `taskfiles/host.yml` | the optional [host checks](host/README.md#check-without-deployment) |
| A test with no subprocess | `tests/unit/<subsystem>/` | every push |
| A test driving the product through subprocesses with fakes | `tests/integration/<subsystem>/` | every push |
| A test needing the real machine, Orca, the real Codex binary, launchd or systemd | `tests/native/<subsystem>/` | the workstation gate |
| A test that runs real sessions | `tests/live/` | only when the operator invokes it |
| Test inputs | `tests/data/` | never executed |
| A shared test builder | `tests/support/` once two files need it | |
| A check | one `Check` in `slopmeister/check/catalogue.py` with its layer and kind | `task check`, `task lint`, `task quality`, `task test:portable` |
| A procedure every session should have | `src/skills/<name>/` | delivered to every plot |
| A procedure only one plot should have, or a change to a shared one | `plots/<target>/skills/<name>/`, with `SKILL.md` to own it or without to patch it | delivered to that plot |

## Rules the gate enforces

- Follow [size budgets and exceptions](docs/architecture.md#budgets) for code, executable instructions and repository documentation.
- `slopmeister` never imports `tests` or `scripts`. `slopmeister/session/` and `slopmeister/vault/runtime/` each import only themselves and the standard library. No cycles. No launching a repository script by path, no `runpy`, no `sys.path` patching inside the package.
- Ruff for formatting, import order, unused imports and complexity. Shellcheck at warning severity for the bash that remains.
- Field identifiers and plot style findings cannot be waived through an exception.

Run `bin/slopmeister quality` and `task lint` before every commit. When the gate fails, read the whole error, fix the cause, and never edit a passing test to make a failure go away.

## Writing tests

Use the shared [test-purpose rule](src/skills/implement/SKILL.md#test-purpose). Name the caller or input, observable consequence and coverage gap before adding a permanent test. Extend existing coverage first. A negative test must reach its intended guard and observe its diagnostic or preserved state. New behavior gets a valid failing reproducer first where possible. Apply [behavior proof](src/skills/local-qa/SKILL.md#3-the-break-it-pass) to distinct changed behaviors and boundaries, not to every parameter row or wording assertion.

A test that binds a socket or drives a process tree declares `@pytest.mark.xdist_group("<group>")`. The gate uses `--dist loadgroup`, so tests in one group never overlap. Other groups and layers still run beside it. Raise the 60-second timeout only with a marked reason.

Scratch repositories use `tests/support/repos.py`, which isolates Git identity and configuration. Instruction tests check each safety rule once in source with a short stable token. Render tests keep parity, structure and delivery checks. Avoid assertions that only forbid retired names.

## Hand-port maintenance

Port changes by hand into the owning modules, tests and documents. Preserve established interfaces and trust boundaries, select only the required files, and remove environment-specific values before admission. Do not add a synchronization generator or copy generated output. Regenerate `dist/` from the reviewed sources and rerun the affected checks.

## Bias toward less code

When new code makes old code dead, delete the old. When an abstraction has one caller, inline it. Extract after the third duplication. Comment the why of a non-obvious decision, never the history.

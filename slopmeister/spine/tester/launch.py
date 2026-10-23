"""Admit one tester for a task and commit, prepare its isolated checkout, start its supervisor."""

import argparse
from dataclasses import dataclass, field
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib

from slopmeister.install.trust import TrustRequest, trust
from slopmeister.opencode import tester as opencode_tester
from slopmeister.review.config import DEFAULT_CONFIG_PATH as DEFAULTS
from slopmeister.review.redact import redact
from slopmeister.review.run import project_child_env
from slopmeister.slots import tester as slot_tester
from slopmeister.spine import candidate as repository_candidate
from slopmeister.spine.tester import runs
from slopmeister.spine.tester.command import build_command as build_command
from slopmeister.spine.tester.validate import SCENARIO, VERDICT_SCHEMA, scenario_ids
from slopmeister.vault import subject as directory_subject

INPUT_LIMIT = 256_000
ACCEPTANCE_SECONDS = 10
TASK = re.compile(r"[A-Za-z0-9._-]{1,64}")


@dataclass
class Launch:
    args: argparse.Namespace
    cwd: Path
    commit: str = ""
    guide: str = ""
    validation: str = ""
    required: list[str] = field(default_factory=list)
    inputs: dict[str, str] = field(default_factory=dict)
    subject: directory_subject.DirectorySubject | None = None
    candidate: repository_candidate.RepositoryCandidate | None = None


def evidence_home(cwd: Path, *, create: bool = True) -> Path:
    home = Path(os.environ.get("XDG_STATE_HOME", ""))
    if not home.is_absolute():
        home = Path.home() / ".local/state"
    home = (home / "slopmeister/spine-tests").resolve()
    if home.is_relative_to(cwd):
        raise ValueError("tester evidence must live outside the worker checkout")
    if create:
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
    return home


def launch(args: argparse.Namespace) -> Path:
    target = _resolve_target(args)
    subject = target if isinstance(target, directory_subject.DirectorySubject) else None
    frozen = target if isinstance(target, repository_candidate.RepositoryCandidate) else None
    cwd = Path(getattr(args, "cwd", None) or ".").resolve(strict=True)
    cwd = subject.root if subject else frozen.workspace if frozen else cwd
    request = Launch(args, cwd, subject=subject, candidate=frozen)
    _read_subject(request)
    root, run = _new_run(request, _tester(args))
    return _prepare(root, run, request)


def _new_run(request: Launch, tester: dict) -> tuple[Path, dict]:
    if not TASK.fullmatch(request.args.task):
        raise ValueError(
            "tester task must be 1 to 64 letters, digits, dots, underscores or hyphens"
        )
    root = Path(tempfile.mkdtemp(prefix="run-", dir=evidence_home(request.cwd)))
    run = {
        "task": request.args.task,
        "worker_tool": request.args.worker_tool,
        **tester,
        "cwd": str(request.cwd),
        "commit": request.commit,
        "checkout": str(root / "checkout"),
        "required": request.required,
        "input_hashes": request.inputs,
        "started_at": time.time(),
        "status": "preparing",
    }
    if request.subject:
        run.update(
            subject_manifest=str(request.subject.manifest),
            subject_identity=request.subject.identity,
        )
    if request.candidate:
        run.update(candidate_base=request.candidate.base, candidate_tree=request.candidate.tree)
    runs.save(root / "run.json", run)
    return root, run


def _tester(args: argparse.Namespace) -> dict:
    tool = getattr(args, "tester_tool", None) or (
        "claude" if args.worker_tool == "codex" else "codex"
    )
    if tool == args.worker_tool:
        raise ValueError(f"same-tool testing refused: the worker and the tester are both {tool}")
    if tool == "opencode":
        return opencode_tester.settings(args)
    if getattr(args, "tester_model", None):
        raise ValueError("--tester-model applies to the opencode tester only")
    config = tomllib.loads(DEFAULTS.read_text())[tool]
    if set(config) != {"model", "effort"} or not all(
        isinstance(v, str) and v for v in config.values()
    ):
        raise ValueError("invalid tester defaults")
    return dict(tool=tool, **config)


def _read_subject(request: Launch) -> None:
    args = request.args
    if request.candidate:
        request.commit = "candidate:" + request.candidate.tree
    elif request.subject:
        request.commit = "directory:" + request.subject.identity
    else:
        request.commit = runs.git(request.cwd, "rev-parse", "--verify", f"{args.commit}^{{commit}}")
    guide = Path(args.guide).read_text()
    notes = Path(args.validation).read_text()
    validation = notes.partition("\n## Validation\n")[2].split("\n## ", 1)[0]
    if not validation.strip() or len(guide) + len(validation) > INPUT_LIMIT:
        raise ValueError("missing Validation section or tester input exceeds 256000 characters")
    required = scenario_ids(guide)
    request.required = sorted(set(required) | set(SCENARIO.findall(validation)))
    request.guide, request.validation = guide, validation
    request.inputs = {
        name: hashlib.sha256(text.encode()).hexdigest()
        for name, text in (("guide.md", guide), ("validation.md", validation))
    }
    if request.subject:
        request.inputs.update(
            subject_manifest=request.subject.manifest_sha256,
            subject_tree=request.subject.tree_sha256,
        )


def _resolve_target(args: argparse.Namespace):
    cwd, commit = getattr(args, "cwd", None), getattr(args, "commit", None)
    manifest = getattr(args, "subject_manifest", None)
    if getattr(args, "candidate", False):
        if not cwd or commit or manifest:
            raise ValueError(
                "candidate testing requires --cwd without --commit or --subject-manifest"
            )
        workspace = Path(cwd).resolve(strict=True)
        return repository_candidate.load_for_session(workspace, args.task, args.worker_tool)
    if bool(cwd) != bool(commit):
        raise ValueError("repository testing requires both --cwd and --commit")
    if (bool(cwd) or bool(commit)) == bool(manifest):
        raise ValueError("choose repository --cwd/--commit or --subject-manifest")
    return directory_subject.load(manifest) if manifest else None


def _prepare(root: Path, run: dict, request: Launch) -> Path:
    started = time.monotonic()
    try:
        _checkout(root, run, request)
        if run["tool"] == "claude":
            trust(TrustRequest("write", Path.home() / ".claude.json", run["checkout"]), "claude")
        with slot_tester.prepared(root, run, getattr(request.args, "slot_target", None)):
            _start_supervisor(root, run)
    except (Exception, SystemExit) as error:
        (root / "report.md").write_text(
            f"Tester BLOCKED during preparation: {redact(str(error))}\nEvidence: {root}\n"
        )
        run.update(
            status="blocked",
            exit_code=1,
            elapsed_seconds=time.monotonic() - started,
            completed_at=time.time(),
        )
        runs.save(root / "result.json", run)
        print(f"tester evidence: {root}", file=sys.stderr)
        raise
    try:
        return _await_acceptance(root)
    except Exception:
        print(f"tester evidence: {root}", file=sys.stderr)
        raise


def _checkout(root: Path, run: dict, request: Launch) -> None:
    checkout = run["checkout"]
    if request.candidate:
        repository_candidate.materialize(request.candidate, Path(checkout))
    elif request.subject:
        directory_subject.load(request.subject.manifest)
        directory_subject.copy_inputs(request.subject, Path(checkout))
        directory_subject.load(request.subject.manifest)
        run["checkout_tree_sha256"] = directory_subject.tree_digest(Path(checkout))
    else:
        runs.git(
            root, "clone", "--local", "--no-hardlinks", "--no-checkout", str(request.cwd), checkout
        )
        runs.git(Path(checkout), "checkout", "--detach", request.commit)
    (root / "guide.md").write_text(request.guide)
    (root / "validation.md").write_text(request.validation)
    (root / "evidence").mkdir(mode=0o700)
    runs.save(root / "schema.json", VERDICT_SCHEMA)
    run["command"] = build_command(run, root)
    run["status"] = "prepared"
    runs.save(root / "run.json", run)


def _start_supervisor(root: Path, run: dict) -> None:
    with (root / "supervisor.log").open("w") as log:
        subprocess.Popen(
            runs.command(str(runs.ENTRY), "_supervise", "--run", str(root)),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            pass_fds=slot_tester.descriptors(run),
            env=opencode_tester.supervisor_env(run)
            if run["tool"] == "opencode"
            else project_child_env(),
        )


def _await_acceptance(root: Path) -> Path:
    deadline = time.monotonic() + ACCEPTANCE_SECONDS
    while time.monotonic() < deadline:
        if (root / "accepted.json").exists():
            return root
        if (root / "result.json").exists():
            raise ValueError(f"tester failed during startup; collect {root}")
        time.sleep(0.05)
    raise ValueError(f"supervisor admission unconfirmed; collect {root}, do not relaunch")

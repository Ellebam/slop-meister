"""The detached supervisor: run the tester once, verify its identity and evidence, save a result."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid

from slopmeister.opencode import native
from slopmeister.opencode import tester as opencode_tester
from slopmeister.removal import remove_tree
from slopmeister.review.redact import redact
from slopmeister.spine import candidate as repository_candidate
from slopmeister.spine.tester import runs
from slopmeister.spine.tester.process import run_tester
from slopmeister.spine.tester.validate import native_identity, render_report, validate_verdict
from slopmeister.vault import subject as directory_subject

BLOCKING = (OSError, ValueError, KeyError, TypeError, StopIteration, subprocess.SubprocessError)
PROMPT = (
    "You are the independent tester for the operator-approved spine task. Test it the way you "
    "would test a colleague's pull request. Run every guide scenario and the worker "
    "falsification cases, then try additional counterexamples. Decide each required scenario by "
    "its written steps and expected results alone. Add no scenario of your own. Report each "
    "additional counterexample that holds as a regression candidate named for the escaping bug, "
    "it never changes a scenario's verdict. Run any command, but never "
    "change the subject's code or files. Your checkout is a fresh copy without development "
    "tools; when one is missing, run the development setup its README or CONTRIBUTING names "
    "before calling a scenario blocked. Preserve the worker checkout and all unrelated sessions. "
    "Do not launch reviews or additional agents. Save command stdout/stderr directly to files in "
    "the evidence directory. Copy any quoted checkout file into evidence/ before citing it. "
    "The checkout is deleted after the run. Populate evidence quote fields from exact substrings "
    "read from those files, preserving whitespace and escapes. Do not reconstruct command output "
    "or paraphrase quotes. Never cite an empty or whitespace-only quote. When success means empty "
    "output, verify the command succeeded and its saved output is empty, then save and quote a "
    "nonempty assertion marker. Never print success unconditionally. Batch independent checks "
    "and reuse saved results unless a changed input or unresolved failure requires a rerun. A "
    "failed or unavailable scenario is fail or blocked, never pass. Return the requested JSON, "
    "every required scenario ID and regression candidates named for the escaping bug. Before "
    "submission, save your draft to evidence/draft.json under the run root and run this check. "
    "Draft check command: {draft}\n"
    "Correct citation mistakes from saved evidence, preserving actual scenario outcomes, then "
    "check again. A valid draft is not test proof. After successful validation return the checked "
    "draft unchanged. Read {guide} and {validation}. Evidence root: {root}. "
    "Work only in {checkout}. Required IDs: {required}."
)


def prompt(root: Path, run: dict) -> str:
    draft = runs.command(
        str(runs.ENTRY),
        "validate",
        "--run",
        str(root),
        "--draft",
        str(root / "evidence/draft.json"),
    )
    # OpenCode has no output-schema flag, its final message carries the JSON instead.
    schema = (
        f"\nYour final message is only that JSON, matching {root / 'schema.json'}."
        if run["tool"] == "opencode"
        else ""
    )
    text = PROMPT.format(
        draft=shlex.join(draft),
        guide=root / "guide.md",
        validation=root / "validation.md",
        root=root,
        checkout=run["checkout"],
        required=", ".join(run["required"]),
    )
    return text + schema


def supervise(root: Path) -> int:
    run = json.loads((root / "run.json").read_text())
    # Exclusive admission survives a duplicate supervisor call without launching again.
    claim = os.open(root / "supervisor.claim", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(claim)
    runs.save(root / "accepted.json", {"supervisor_pid": os.getpid(), "started_at": time.time()})
    text = prompt(root, run)
    started = time.monotonic()
    try:
        status = _test(root, run, text)
        code = 0 if status == "pass" else 1
    except BLOCKING as error:
        status, code = "blocked", 1
        if isinstance(error, native.Blocked):
            run["blocked_reason"] = error.reason
        (root / "report.md").write_text(f"Tester BLOCKED: {redact(str(error))}\nEvidence: {root}\n")
    run.update(
        status=status,
        exit_code=code,
        elapsed_seconds=time.monotonic() - started,
        completed_at=time.time(),
    )
    runs.save(root / "result.json", run)
    if error := _cleanup_checkout(root / "checkout", run):
        run["checkout_cleanup_error"] = error
        runs.save(root / "result.json", run)
    return code


def _cleanup_checkout(checkout: Path, run: dict) -> str | None:
    if run.get("process_stopped") is False:
        return "tester process stop unverified, checkout not removed"
    if checkout.is_symlink():
        return "checkout is a symlink, not removed"
    try:
        remove_tree(checkout)
    except FileNotFoundError:
        pass
    except OSError as error:
        return redact(str(error))
    return None


def _test(root: Path, run: dict, text: str) -> str:
    for name in ("guide.md", "validation.md"):
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != run["input_hashes"][name]:
            raise ValueError(f"tester input changed after preparation: {name}")
    run["process_stopped"] = False
    run_tester(root, run, text)
    if run["tool"] == "opencode":
        _, verdict = opencode_tester.outcome(root, run, text)
    else:
        verdict = _native(root, run)
    _verify_subject(run)
    validate_verdict(verdict, run["required"], root)
    _mask(root, verdict)
    status = validate_verdict(verdict, run["required"], root)
    runs.save(root / "verdict.json", verdict)
    (root / "report.md").write_text(render_report(verdict, run["required"]))
    return status


def _native(root: Path, run: dict) -> dict:
    session, verdict, natives = _outcome(root, run)
    if len(natives) != 1:
        raise ValueError("tester native session record is missing or ambiguous")
    shutil.copyfile(natives[0], root / "native.jsonl")
    observed = native_identity(root / "native.jsonl", run["tool"])
    if observed != (run["model"], run["effort"]):
        raise ValueError(f"native model/effort mismatch: {observed}")
    run.update(
        session_id=session,
        native_source=str(natives[0]),
        observed_model=observed[0],
        observed_effort=observed[1],
    )
    return verdict


def _verify_subject(run: dict) -> None:
    checkout = Path(run["checkout"])
    if run.get("subject_manifest"):
        directory_subject.load(run["subject_manifest"])
        if directory_subject.tree_digest(checkout) != run.get("checkout_tree_sha256"):
            raise ValueError("tester changed the directory subject copy")
        return
    base = run.get("candidate_base") or run["commit"]
    tree = run.get("candidate_tree") or runs.git(checkout, "rev-parse", base + "^{tree}")
    # New paths are the tester's own output; candidate-new files are untracked yet tested.
    if runs.git(checkout, "rev-parse", "HEAD") != base or not repository_candidate.unchanged(
        checkout, tree
    ):
        raise ValueError("tester changed the tested commit or files")


def _outcome(root: Path, run: dict) -> tuple[str, dict, list[Path]]:
    """The native session, the returned verdict and the native records naming that session."""
    lines = (root / "events.jsonl").read_bytes().split(b"\n")
    events = [json.loads(line) for line in lines if line.strip()]
    if run["tool"] == "claude":
        initial = next(
            e for e in events if e.get("type") == "system" and e.get("subtype") == "init"
        )
        session = str(uuid.UUID(initial["session_id"]))
        terminal = next(e for e in reversed(events) if e.get("type") == "result")
        if terminal.get("is_error"):
            raise ValueError("tester returned an error result")
        natives = list((Path.home() / ".claude/projects").glob(f"*/{session}.jsonl"))
        run["cost_usd_client_estimate"] = terminal.get("total_cost_usd")
        run["usage"] = terminal.get("usage")
        return session, terminal["structured_output"], natives
    thread = next(e["thread_id"] for e in events if e.get("type") == "thread.started")
    session = str(uuid.UUID(thread))
    verdict = json.loads((root / "verdict.raw.json").read_text())
    natives = list((Path.home() / ".codex/sessions").glob(f"*/*/*/*{session}.jsonl"))
    completed = (e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed")
    run["usage"] = next(completed, None)
    return session, verdict, natives


def _mask(root: Path, verdict: dict) -> None:
    for row in verdict["scenarios"]:
        row["id"] = redact(row["id"])
        for item in row["evidence"]:
            _mask_citation(root, item)
    for candidate in verdict["regressions"]:
        candidate.update({key: redact(value) for key, value in candidate.items()})


def _mask_citation(root: Path, item: dict) -> None:
    masked = {key: redact(value) for key, value in item.items()}
    if masked != item:
        # Raw validation proves the quote. The excerpt keeps its masked citation usable.
        fd, excerpt = tempfile.mkstemp(
            dir=root / "evidence", prefix="report-evidence-", suffix=".txt"
        )
        with os.fdopen(fd, "w") as stream:
            stream.write("Source: " + json.dumps(masked["path"]) + "\n\n" + masked["quote"] + "\n")
        masked["path"] = "evidence/" + Path(excerpt).name
    item.update(masked)

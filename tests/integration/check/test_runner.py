"""Keep concurrent checks from hiding failures or dropping required coverage."""

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

import pytest

from slopmeister.check import jobs, ownership, scheduler

SCHEDULER_PROGRAM = """
import fcntl, json, time
from pathlib import Path
def record(event):
    with open('events.jsonl', 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stream.write(json.dumps([NAME, event]) + '\\n')
record('start')
peer = {'a': 'b', 'b': 'a', 'c': 'd', 'd': 'c'}.get(NAME)
if peer:
    Path(NAME + '.ready').touch()
    deadline = time.monotonic() + 5
    while not Path(peer + '.ready').exists():
        if time.monotonic() >= deadline:
            raise SystemExit('second parallel check never started')
        time.sleep(.01)
else:
    time.sleep(.03)
record('end')
"""

OVERLAP_PROGRAM = """
import json, os, tempfile, time
from pathlib import Path
p = Path(tempfile.gettempdir()) / 'same-fixture-name'
p.write_text(NAME)
Path(NAME + '.ready').touch()
deadline = time.monotonic() + 5
while not Path(PEER + '.ready').exists():
    assert time.monotonic() < deadline, 'peer gate never overlapped'
    time.sleep(.01)
assert p.read_text() == NAME, 'another invocation changed my fixture'
print(json.dumps({'tmp': str(p.parent), 'run': os.environ.get('SLOPMEISTER_TEST_ROOT')}))
"""


def check(name, code, **options):
    return jobs.Check(name, (sys.executable, "-c", code), **options)


def run(tmp_path, checks, jobs_count=2, logs_name="logs"):
    settings = scheduler.Settings(jobs_count, tmp_path, tmp_path / logs_name)
    return scheduler.run_checks(checks, settings)


def assert_schedule(events):
    active = set()
    maximum = 0
    for name, event in events:
        if event == "start":
            if name in {"before", "after"}:
                assert not active
            assert not active.intersection({"before", "after"})
            active.add(name)
            maximum = max(maximum, len(active))
        else:
            active.remove(name)
    assert not active and maximum == 2


def test_failing_group_cannot_be_hidden_by_a_later_success(tmp_path):
    checks = [check("broken", "raise SystemExit(7)"), check("good", "print('ok')")]
    result = run(tmp_path, checks)
    codes = {row["id"]: row["returncode"] for row in result["results"]}
    assert not result["passed"]
    assert result["complete"]
    assert codes == {"broken": 7, "good": 0}


def test_missing_executable_is_a_failed_check_not_a_dropped_result(tmp_path):
    result = run(tmp_path, [jobs.Check("missing", (str(tmp_path / "absent"),))])
    assert not result["passed"]
    assert result["results"][0]["returncode"] != 0
    assert result["results"][0]["id"] == "missing"


def test_serial_and_parallel_record_the_same_checks(tmp_path):
    """Escaping bug: one concurrency setting dropped a check's result and still passed."""
    checks = [check(name, "print('ok')") for name in ("one", "two", "three")]
    serial = run(tmp_path, checks, jobs_count=1)
    parallel = run(tmp_path, checks, jobs_count=3, logs_name="parallel")
    assert serial["passed"] and parallel["passed"]
    ran = [sorted(row["id"] for row in result["results"]) for result in (serial, parallel)]
    assert ran == [["one", "three", "two"]] * 2


def test_exclusive_check_never_overlaps_a_parallel_child(tmp_path):
    code = (
        "from pathlib import Path; import time; p=Path('running'); "
        "p.touch(); time.sleep(.1); p.unlink()"
    )
    exclusive = "from pathlib import Path; assert not Path('running').exists()"
    checks = [check("parallel", code), check("exclusive", exclusive, phase="last")]
    assert run(tmp_path, checks)["passed"]


def test_scheduler_enforces_process_limit_and_exclusive_phases(tmp_path):
    phases = (
        ("before", "first"),
        ("a", "parallel"),
        ("b", "parallel"),
        ("c", "parallel"),
        ("d", "parallel"),
        ("after", "last"),
    )
    checks = [
        check(name, f"NAME={name!r}\n{SCHEDULER_PROGRAM}", phase=phase) for name, phase in phases
    ]
    assert run(tmp_path, checks, jobs_count=2)["passed"]
    events = map(json.loads, (tmp_path / "events.jsonl").read_text().splitlines())
    assert_schedule(events)


def test_duplicate_check_identity_is_rejected_before_execution(tmp_path):
    checks = [check("same", "raise SystemExit(0)"), check("same", "raise SystemExit(0)")]
    with pytest.raises(ValueError, match="duplicate"):
        run(tmp_path, checks)


def test_empty_selection_cannot_report_a_successful_gate(tmp_path):
    with pytest.raises(ValueError, match="no checks"):
        run(tmp_path, [])


def test_two_gates_overlap_without_sharing_job_temporary_state(tmp_path, monkeypatch):
    """A predictable fixture filename in one check must not overwrite a peer's file."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    pairs = (("a", "b"), ("b", "a"))
    with ThreadPoolExecutor(2) as pool:
        futures = [
            pool.submit(
                run,
                tmp_path,
                [check(name, f"NAME={name!r}\nPEER={peer!r}\n{OVERLAP_PROGRAM}")],
                8,
                name,
            )
            for name, peer in pairs
        ]
        results = [future.result() for future in futures]
    owners = [json.loads(Path(row["results"][0]["log"]).read_text()) for row in results]
    assert all(result["passed"] for result in results)
    assert owners[0]["tmp"] != owners[1]["tmp"]
    assert owners[0]["run"] and owners[0]["run"] != owners[1]["run"]


def test_existing_logs_refuse_a_second_runner_without_changing_evidence(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    sentinel = logs / "owned.log"
    sentinel.write_text("foreign evidence")
    with pytest.raises(FileExistsError):
        run(tmp_path, [check("owned", "raise SystemExit('must not run')")])
    assert sentinel.read_text() == "foreign evidence"


@pytest.mark.parametrize("outcome", [0, 7])
def test_readonly_fixture_cleanup_preserves_the_check_result(tmp_path, run_root, outcome):
    """Bug: locked fixture directories crash cleanup and discard the completed check result."""
    code = (
        "from pathlib import Path; import tempfile; "
        "root=Path(tempfile.gettempdir())/'workspace/.claude/service-actions'; "
        "root.mkdir(parents=True); (root/'entry.py').write_text('fixture'); "
        f"root.chmod(0o555); raise SystemExit({outcome})"
    )
    result = run(tmp_path, [check("readonly", code)])
    row = result["results"][0]
    assert result["complete"] and result["passed"] == (outcome == 0)
    assert row["returncode"] == outcome and not Path(row["owner"]["root"]).exists()


@pytest.mark.parametrize("outcome", [0, 7])
def test_unreadable_fixture_cleanup_reports_failure_without_losing_the_result(
    tmp_path, run_root, outcome
):
    """Bug: a fixture without read permission discards the completed job and its output."""
    code = (
        "from pathlib import Path; import tempfile; "
        "root=Path(tempfile.gettempdir())/'locked'; root.mkdir(); "
        f"root.chmod(0o000); print('finished'); raise SystemExit({outcome})"
    )
    try:
        result = run(tmp_path, [check("unreadable", code)])
        row = result["results"][0]
        log = Path(row["log"]).read_text()
        assert result["complete"] and not result["passed"]
        assert row["returncode"] == (outcome or 1)
        assert "finished" in log and "cleanup failed:" in log
        assert (Path(row["owner"]["root"]) / "owner.json").exists()
    finally:
        for folder in run_root.glob("htr.*"):
            (folder / "locked").chmod(0o700)
            ownership.remove(folder)

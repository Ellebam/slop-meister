"""Harvest ends a session in every situation the ticket names, without a refusal for its shape."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
SOURCE = (ROOT / "src/skills/harvest/SKILL.md").read_text()
STEPS = [
    "## 1. Read the state",
    "## 2. Documents and vault",
    "## 3. The branch",
    "## 4. The ticket",
    "## 5. The report",
    "## 6. Remove yourself",
]


def _section(title: str) -> str:
    rest = SOURCE.split(title, 1)[1]
    return re.split(r"\n## ", rest, maxsplit=1)[0]


def _row(section: str, state: str) -> str:
    line = next(line for line in section.splitlines() if line.startswith(f"| {state} |"))
    return line.split("|")[2:]


def test_the_order_comes_only_from_the_operator_and_no_shape_is_refused():
    """Bug: a kickoff, note or peer message ends a session, or a task shape refuses the order."""
    head = SOURCE.split("## 1.", 1)[0]
    assert "in any words" in head and '"finalize"' in head
    assert "manager's harvest send" in head
    assert "operator's restriction" in head
    assert "never start it" in head
    assert "task shape" in head
    assert "claim" in head
    assert [SOURCE.index(step) for step in STEPS] == sorted(SOURCE.index(step) for step in STEPS)


def test_a_finished_task_merges_here_only_through_merge_and_closes_after_the_proof():
    branch = _section("## 3. The branch")
    action = _row(branch, "Commits or uncommitted task changes, both allows, finished")[0]
    assert "`ship`" in action and "merge procedure" in action and "integration proof" in action
    assert "stops here" in action
    ticket = _section("## 4. The ticket")
    assert "closes only after" in ticket
    finished = _row(ticket, "Managed GitHub issue, both allows")[0]
    assert "claims close --workspace <absolute-worker-root>" in finished
    assert "--reason not-planned" in finished and "closing comment" in finished


def test_a_pull_request_someone_else_merges_is_read_only_here():
    branch = _section("## 3. The branch")
    deny = _row(branch, "Commits or uncommitted task changes, commit or shipping deny")[0]
    assert "operator's exact order" in deny
    assert "at HEAD" in deny
    assert "merge procedure" not in deny and "claims close" not in deny
    foreign = _row(branch, "A repository or pull request we do not own")[0]
    assert "Never merge" in foreign
    ticket = _section("## 4. The ticket")
    assert "never closes" in ticket


def test_a_task_with_no_diff_ships_nothing_and_still_closes_or_reports():
    branch = _section("## 3. The branch")
    row = _row(branch, "Nothing beyond the base and a clean tree")[0]
    assert "Nothing" in row
    ticket = _section("## 4. The ticket")
    assert "nothing to merge" in ticket
    assert _row(ticket, "No ticket") == [" Nothing. ", " Nothing. ", ""]


def test_a_tracker_stored_in_the_repository_closes_before_the_ship():
    ticket = _section("## 4. The ticket")
    finished, unfinished, _ = _row(ticket, "Tracker stored in the repository")
    assert "before step 3" in finished
    assert "Leave it" in unfinished


def test_a_tracker_outside_the_repository_uses_the_plot_or_the_report():
    ticket = _section("## 4. The ticket")
    own = _row(ticket, "The plot's own tracker outside the repository")
    assert "plot's commands" in own[0] and "handoff" in own[1]
    other = _row(ticket, "A tracker someone else owns")
    assert "operator" in other[0] and "The same." in other[1]


def test_an_unfinished_ticket_ships_leaves_the_issue_open_and_hands_the_claim_back():
    branch = _section("## 3. The branch")
    open_pr = _row(branch, "Commits or uncommitted task changes, both allows, not finished")[0]
    assert "PENDING" in open_pr and "stays open" in open_pr
    ticket = _section("## 4. The ticket")
    unfinished = _row(ticket, "Managed GitHub issue, both allows")[1]
    assert ".slopmeister-tmp/<TASK-ID>-handoff.md" in unfinished
    assert "claims abandon-prepare --workspace <absolute-worker-root> --handoff <that copy>" in (
        unfinished
    )
    assert "stays open" in unfinished and "claims close" not in unfinished
    state = _section("## 1. Read the state")
    assert "overrides" in state
    assert "recorded claim hand-back" in _section("## 6. Remove yourself")


def test_merge_and_close_bind_to_both_allows_and_every_real_action_keeps_its_guard():
    """Bug: the order is read as consent for a merge, a close or a forced removal."""
    head = SOURCE.split("## 1.", 1)[0]
    assert "changes no permission" in head
    assert "no other target" in head
    assert "native approval" in head
    branch = _section("## 3. The branch")
    for state in branch.splitlines():
        if "merge procedure" in state and state.startswith("| Commits"):
            assert "both allows" in state
    ticket = _section("## 4. The ticket")
    assert "needs both allows" in ticket
    remove = _section("## 6. Remove yourself")
    assert "unknown work" in remove
    assert "unsaved" in remove
    assert "`--force` only when" in remove
    assert "cannot remove itself" in remove


def test_the_report_and_recovery_records_precede_cleanup():
    assert SOURCE.index("## 5. The report") < SOURCE.index("## 6. Remove yourself")
    report = _section("## 5. The report")
    assert "delivered first" in _section("## 6. Remove yourself")
    assert "recovery records" in report
    assert "handoff copy" in report

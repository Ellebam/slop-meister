"""Historical decisions keep unknown and protected states out of redispatch."""

from datetime import UTC, datetime

import pytest

from slopmeister.threads.census import policy
from slopmeister.threads.census.records import Compaction, Interval, Request, Session

AT = datetime(2026, 10, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "override",
    [
        {"wait": {"kind": "permission"}},
        {"wait": "unevaluated"},
        {"state": "working"},
        {"question_open": True},
        {"protected_window": True},
        {"compactions": None},
        {"compactions": True},
    ],
)
def test_protected_or_unknown_state_cannot_redispatch(override):
    state = {
        "client": "codex",
        "state": "done",
        "wait": None,
        "context": 500_000,
        "compactions": 3,
        "notes_bytes": 70_000,
        **override,
    }
    assert ("recommend-redispatch", "manager-or-dispatcher") not in policy.decide(
        state, policy.DEFAULT_THRESHOLDS
    )


def test_evaluated_null_wait_is_required():
    state = {"client": "codex", "state": "done", "compactions": 3}
    assert policy.decide(state, policy.DEFAULT_THRESHOLDS) == []
    state["wait"] = None
    assert policy.decide(state, policy.DEFAULT_THRESHOLDS) == [
        ("recommend-redispatch", "manager-or-dispatcher")
    ]


def test_replay_cost_and_unknown_ratio():
    session = Session("claude", requests=[Request(AT, 300_000, 1, "claude-sample")])
    result = policy.replay([session], 0.1, 200_000)
    assert result["gross_saved"] == 270_000
    assert result["compaction_cost"] == 300_000
    assert result["net_saved"] == -30_000
    assert policy.replay([session], None, 200_000) is None
    session.requests.append(Request(AT, None, 1, "claude-sample"))
    assert policy.replay([session], 0.1, 200_000) is None


def test_decisions_report_unknown_final_context():
    session = Session("claude", requests=[Request(AT, None, 1, "claude-sample")])
    result = policy.decisions([session], policy.DEFAULT_THRESHOLDS)
    assert result["recorded_states"] == 1
    assert result["context_unknown"] == 1
    assert result["counts"] == {}
    session.requests[-1].context = 250_000
    result = policy.decisions([session], policy.DEFAULT_THRESHOLDS)
    assert result["context_unknown"] == 0
    assert result["counts"] == {"native-compaction/client": 1}


def test_ratios_exclude_out_of_window_compactions():
    session = Session(
        "codex",
        compactions=[
            Compaction(AT, 100, 10),
            Compaction(datetime(2026, 9, 1, tzinfo=UTC), 100, 90),
        ],
    )
    interval = Interval(datetime(2026, 10, 3, tzinfo=UTC), datetime(2026, 11, 8, tzinfo=UTC))
    assert policy.ratios([session], interval) == {"claude": None, "codex": 0.1}

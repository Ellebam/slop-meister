"""Compaction comparisons count reads and notes without keeping their targets."""

from datetime import UTC, datetime, timedelta
import json

from slopmeister.threads.census import after_compaction, readers
from slopmeister.threads.census.records import Interval

START = datetime(2026, 10, 5, tzinfo=UTC)


def call(index, target, name="Read"):
    return {
        "type": "assistant",
        "timestamp": (START + timedelta(minutes=index)).isoformat(),
        "message": {
            "id": f"request-{index}",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"tool-{index}",
                    "name": name,
                    "input": {"command" if name == "Bash" else "file_path": target},
                }
            ],
        },
    }


def test_full_windows_and_notes_used_outside_the_last_thirty_calls(tmp_path):
    targets = ["/scratch/sample-NOTES.md"] + [f"/scratch/file-{i}" for i in range(1, 40)]
    rows = [call(i, target) for i, target in enumerate(targets)]
    rows.append(
        {
            "type": "system",
            "subtype": "compact_boundary",
            "timestamp": (START + timedelta(minutes=40)).isoformat(),
        }
    )
    rows.extend(call(i + 41, targets[i]) for i in range(30))
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    session = readers.claude(path)
    interval = Interval(START, START + timedelta(hours=2))
    result = after_compaction.summarize([session], interval)
    assert result["compactions_with_full_windows"] == 1
    assert result["compactions_with_prior_notes"] == 1
    assert result["notes_reopened_in_first_10_calls"] == 1
    assert result["repeat_before_mean"] == 0
    assert result["repeat_after_mean"] == 30
    assert result["reread_after_mean"] == 30
    assert (
        after_compaction.summarize([session], Interval(START, START + timedelta(hours=1)))[
            "compactions_with_full_windows"
        ]
        == 0
    )
    assert all(target not in repr(session.tools) for target in targets)


def test_command_arguments_are_data_and_streamed_calls_count_once(tmp_path):
    forbidden = tmp_path / "must-not-exist"
    record = call(0, f"touch {forbidden}", "Bash")
    seen = set()
    first = after_compaction.extract(record, seen)
    assert len(first) == 1
    assert after_compaction.extract(record, seen) == []
    assert str(forbidden) not in repr(first)
    assert not forbidden.exists()


def test_missing_read_target_makes_comparison_unknown(tmp_path):
    rows = [call(i, "/scratch/example") for i in range(30)]
    rows.append(
        {
            "type": "system",
            "subtype": "compact_boundary",
            "timestamp": (START + timedelta(minutes=30)).isoformat(),
        }
    )
    rows.extend(call(i + 31, None if i == 0 else "/scratch/example") for i in range(30))
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = after_compaction.summarize(
        [readers.claude(path)], Interval(START, START + timedelta(hours=2))
    )
    assert result["reread_after_mean"] is None
    assert result["status"] == "unknown"
    assert result["unknown_target_calls"] == 1

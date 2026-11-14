"""Native usage shapes, mirrors and absent fields have distinct meanings."""

import json

from slopmeister.threads.census import readers, report
from slopmeister.threads.census.records import Interval, stamp


def log(tmp_path, rows):
    path = tmp_path / "rollout-example.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def assistant(usage, **fields):
    return {
        "type": "assistant",
        "timestamp": "2026-10-05T00:00:00Z",
        "message": {"id": "one", "model": "claude-sample", "usage": usage},
        **fields,
    }


def token(input_tokens, cumulative, timestamp="2026-10-05T00:00:00Z"):
    last = {"output_tokens": 3, "total_tokens": 13}
    if input_tokens is not None:
        last["input_tokens"] = input_tokens
    return {
        "type": "event_msg",
        "timestamp": timestamp,
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": last,
                "total_token_usage": {"input_tokens": cumulative, "output_tokens": 3},
            },
        },
    }


def test_claude_streaming_and_missing_usage(tmp_path):
    usage = {
        "input_tokens": 10,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 0,
        "output_tokens": 1,
    }
    rows = [
        assistant(usage),
        assistant({**usage, "output_tokens": 8}),
        assistant({"input_tokens": 1}, uuid="different"),
    ]
    rows[-1]["message"]["id"] = "two"
    session = readers.claude(log(tmp_path, rows))
    assert len(session.requests) == 2
    assert (session.requests[0].context, session.requests[0].output) == (30, 8)
    assert session.requests[1].context is None
    assert session.requests[1].output is None


def test_codex_mirror_zero_and_unknown_are_not_the_same(tmp_path):
    rows = [
        {"type": "session_meta", "payload": {"cwd": "/scratch/sample-task"}},
        {"type": "turn_context", "payload": {"model": "gpt-sample"}},
        token(10, 10),
        token(10, 10),
        {"type": "compacted", "timestamp": "2026-10-05T01:00:00Z", "payload": {}},
        token(0, 20),
        token(None, 30),
        token(15, 45),
    ]
    session = readers.codex(log(tmp_path, rows))
    assert [request.context for request in session.requests] == [10, None, 15]
    assert session.requests[-1].model == "gpt-sample"
    assert session.compactions[0].before == 10


def test_event_only_weeks_and_limit_timestamps_are_clipped(tmp_path):
    hit = token(10, 10, "2026-09-30T00:00:00Z")
    hit["payload"]["rate_limits"] = {"primary": {"used_percent": 100}}
    boundary = {"type": "compacted", "timestamp": "2026-10-11T00:00:00Z"}
    session = readers.codex(log(tmp_path, [hit, token(20, 30), boundary]))
    interval = Interval(stamp("2026-10-03T00:00:00Z"), stamp("2026-11-08T00:00:00Z"))
    cells = report.cells([session], interval, "local", set())
    assert sum(cell["limit_hits"] for cell in cells) == 0
    event_cell = next(cell for cell in cells if cell["week"] == "W2")
    assert event_cell["compactions"] == 1
    assert event_cell["mean_context"] is None


def test_untrusted_shapes_and_boolean_counts_stay_unknown(tmp_path):
    rows = [assistant(["unsupported"]), assistant({"input_tokens": True})]
    rows[-1]["message"]["id"] = "two"
    session = readers.claude(log(tmp_path, rows))
    assert all(request.context is None for request in session.requests)


def test_declared_manager_and_native_auxiliary_roles(tmp_path):
    workspace = tmp_path / "sample-job"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text(report.DELIVERED_MARK + "\n" + report.MANAGER_MARK)
    usage = {
        "input_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 1,
    }
    session = readers.claude(log(tmp_path, [assistant(usage, cwd=str(workspace))]))
    assert report.classification(session, {"sample"}) == ("sample", "manager")
    session = readers.codex(
        log(
            tmp_path,
            [
                {
                    "type": "session_meta",
                    "payload": {
                        "cwd": str(workspace),
                        "source": {"subagent": {"other": "guardian"}},
                    },
                },
                {
                    "type": "session_meta",
                    "payload": {"cwd": "/scratch/copied-parent", "source": "exec"},
                },
                token(10, 10),
            ],
        )
    )
    assert report.classification(session, {"sample"}) == ("sample", "review")


def test_unreadable_source_roots_are_not_reported_as_missing(tmp_path, monkeypatch):
    from slopmeister.threads.census import cli

    def denied(root, *, onerror):
        onerror(PermissionError("PRIVATE_PATH_SENTINEL"))
        return iter(())

    monkeypatch.setattr(cli.os, "walk", denied)
    sessions, coverage = cli._scan(tmp_path)
    assert sessions == []
    assert coverage["source_roots"] == {"claude": "unreadable", "codex": "unreadable"}
    assert coverage["unreadable_roots"] == 2
    assert "PRIVATE_PATH_SENTINEL" not in repr(coverage)

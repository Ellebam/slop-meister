"""The census is reached through the registered command and emits no transcript text."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def test_tracer(tmp_path):
    log = tmp_path / ".claude/projects/example/session.jsonl"
    log.parent.mkdir(parents=True)
    record = {
        "type": "assistant",
        "timestamp": "2026-10-05T12:00:00Z",
        "cwd": "/private/workspaces/sample-job",
        "message": {
            "id": "request-one",
            "model": "claude-sample",
            "content": "TRANSCRIPT_SENTINEL",
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 70,
                "cache_creation_input_tokens": 20,
                "output_tokens": 5,
            },
        },
    }
    log.write_text(json.dumps(record) + "\n")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "slopmeister",
            "context-census",
            "--since",
            "2026-10-03",
            "--until",
            "2026-11-08",
            "--home",
            str(tmp_path),
            "--plots",
            "sample",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    cell = json.loads(result.stdout)["cells"][0]
    assert (cell["requests"], cell["input"], cell["output"]) == (1, 100, 5)
    assert (cell["peak_context"], cell["mean_context"]) == (100, 100)
    assert (cell["plot"], cell["role"], cell["week"]) == ("sample", "launched", "W1")
    assert "TRANSCRIPT_SENTINEL" not in result.stdout + result.stderr
    assert record["cwd"] not in result.stdout + result.stderr


def invoke(home, *options):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "slopmeister",
            "context-census",
            "--since",
            "2026-10-03",
            "--until",
            "2026-11-08",
            "--home",
            str(home),
            "--plots",
            "sample",
            *options,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_codex_mirrors_and_missing_input_through_the_command(tmp_path):
    path = tmp_path / ".codex/sessions/rollout-example.jsonl"
    path.parent.mkdir(parents=True)
    event = {
        "type": "event_msg",
        "timestamp": "2026-10-05T00:00:00Z",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {"input_tokens": 100, "output_tokens": 8},
                "total_token_usage": {"input_tokens": 100, "output_tokens": 8},
            },
        },
    }
    unknown = {
        "type": "event_msg",
        "timestamp": "2026-10-06T00:00:00Z",
        "payload": {
            "type": "token_count",
            "info": {
                "last_token_usage": {"output_tokens": 8},
                "total_token_usage": {"input_tokens": 200, "output_tokens": 16},
            },
        },
    }
    rows = [
        {"type": "session_meta", "payload": {"cwd": "/scratch/sample-work"}},
        {"type": "turn_context", "payload": {"model": "gpt-sample"}},
        event,
        event,
        unknown,
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    cell = data["cells"][0]
    assert cell["client"] == "codex"
    assert cell["requests"] == 2
    assert cell["input"] is None
    assert cell["output"] == 16
    assert data["coverage"]["unknown_input_records"] == 1
    assert data["replay"]["codex"] == [None, None, None]
    assert data["decisions"]["policy"] == "historical-recommendation"
    assert "/scratch/sample-work" not in result.stdout + result.stderr


def test_threshold_override_is_validated_and_extra_text_is_not_echoed(tmp_path):
    thresholds = {
        "debloat_bytes": 100,
        "compact_tokens": {"claude": 200, "codex": 300},
        "redispatch_compactions": 4,
        "content": "PRIVATE_SENTINEL",
    }
    result = invoke(tmp_path, "--thresholds", json.dumps(thresholds))
    assert result.returncode == 0, result.stderr
    assert "PRIVATE_SENTINEL" not in result.stdout + result.stderr
    assert json.loads(result.stdout)["decisions"]["thresholds"]["redispatch_compactions"] == 4
    result = invoke(tmp_path, "--thresholds", '{"compact_tokens": []}')
    assert result.returncode == 1
    assert "cannot read inputs or unsupported argument data" in result.stderr


def test_unknown_native_identity_and_undated_usage_are_visible(tmp_path):
    path = tmp_path / ".claude/projects/example/session.jsonl"
    path.parent.mkdir(parents=True)
    usage = {
        "input_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 2,
    }
    rows = [
        {
            "type": "assistant",
            "timestamp": "2026-10-05T00:00:00Z",
            "message": {"model": "claude-sample", "usage": usage},
        },
        {"type": "assistant", "message": {"id": "undated", "usage": usage}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["cells"][0]["requests"] is None
    assert data["cells"][0]["input"] is None
    assert data["coverage"]["unknown_request_identity_records"] == 1
    assert data["coverage"]["undated_usage_records"] == 1


def test_exact_end_boundary_and_outside_limit_events_are_excluded(tmp_path):
    path = tmp_path / ".claude/projects/example/session.jsonl"
    path.parent.mkdir(parents=True)
    usage = {
        "input_tokens": 100,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 8,
    }
    rows = [
        {
            "type": "assistant",
            "timestamp": "2026-10-05T00:00:00Z",
            "message": {"id": "inside", "model": "claude-sample", "usage": usage},
        },
        {
            "type": "assistant",
            "timestamp": "2026-11-08T00:00:00Z",
            "error": "rate_limit",
            "message": {"id": "outside", "usage": usage},
        },
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert sum(cell["requests"] for cell in data["cells"]) == 1
    assert sum(cell["limit_hits"] for cell in data["cells"]) == 0
    assert data["coverage"]["out_of_window_limit_hits_in_active_sessions"] == 1


def test_unsupported_usage_shape_is_reported(tmp_path):
    path = tmp_path / ".claude/projects/example/session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "future-response",
                "usage": {"tokens": 100},
                "timestamp": "2026-10-05T00:00:00Z",
            }
        )
        + "\n"
    )
    result = invoke(tmp_path)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["coverage"].get("unsupported_usage_records", 0) == 1
    assert data["cells"] == []

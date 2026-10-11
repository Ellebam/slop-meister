"""Only a complete model record in the session's own transcript counts as observed evidence."""

import json

import pytest

from slopmeister.launch import model as launch_model
from slopmeister.launch import report
from slopmeister.launch.model import Delivery, Launch, Stop

KINDS = {"claude": ("assistant", "message"), "codex": ("turn_context", "payload")}
CONTROL = "observed\x1b[2J\n\x85"


def _record(tool: str, model) -> str:
    kind, field = KINDS[tool]
    return json.dumps({"type": kind, field: {"model": model}}) + "\n"


def _malformed(tool: str) -> str:
    """Wrong record types, the other tool's shape and non-name values, all complete lines."""
    kind, field = KINDS[tool]
    other = next(name for name in KINDS if name != tool)
    rows = [json.dumps({"type": "user", "message": {"model": "wrong"}}) + "\n", "{broken}\n"]
    rows += ["null\n", "[]\n", json.dumps({"type": kind, field: []}) + "\n", _record(other, "x")]
    return "".join(rows + [_record(tool, value) for value in (None, "", 7, {}, [], "   ")])


def _cases(tool: str):
    """Each case: the chunks written before each poll, and (model, comparison, line) or None."""
    requested = _record(tool, "requested")
    half = len(requested) // 2
    rows = {
        "same": ([requested], ("requested", "same", 1)),
        "different": ([_record(tool, "other") + requested], ("other", "different", 1)),
        "delayed": (
            ["", "{broken}\n[]\n" + requested[:half], requested[half:]],
            ("requested", "same", 3),
        ),
        "unterminated": ([requested.rstrip("\n")], None),
        "control": ([_record(tool, CONTROL)], (CONTROL, "different", 1)),
        "malformed": ([_malformed(tool)], None),
    }
    if tool == "claude":
        rows["synthetic"] = ([_record(tool, "<synthetic>")], None)
    return [pytest.param(tool, row, id=f"{tool}-{name}") for name, row in rows.items()]


@pytest.mark.parametrize(("tool", "case"), _cases("claude") + _cases("codex"))
def test_observed_model(tmp_path, monkeypatch, capsys, tool, case):
    """Bug: a partial, malformed, synthetic or unrelated record passes as the observed model."""
    chunks, observed = case
    evidence = tmp_path / "transcript.jsonl"
    evidence.write_text(chunks[0])
    polls = []

    def sleep(seconds):
        polls.append(seconds)
        with evidence.open("a") as stream:
            stream.write(chunks[len(polls)] if len(polls) < len(chunks) else "")

    monkeypatch.setattr(launch_model, "pause", sleep)
    launch = Launch(
        "example-client", "example-client-worker", "", tool=tool, model="requested", model_set=True
    )
    if observed is None:
        with pytest.raises(Stop, match="model unconfirmed after 60s"):
            report.observe_model(launch, Delivery(1, str(evidence)))
        assert "model observed" not in capsys.readouterr().out
        assert 0 < len(polls) <= 60
        return
    report.observe_model(launch, Delivery(1, str(evidence)))
    model, comparison, line = observed
    kind = KINDS[tool][0]
    assert capsys.readouterr().out == (
        f'  model requested: "requested"\n  model observed: {json.dumps(model)}\n'
        f"  model comparison: {comparison}\n  model evidence: {evidence}:{line} ({kind})\n"
    )
    assert len(polls) == len(chunks) - 1

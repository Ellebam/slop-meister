"""Directory tester preparation copies frozen inputs without manufacturing a repository."""

from argparse import Namespace

import pytest

from slopmeister.spine.tester.launch import Launch, _checkout, _read_subject, _resolve_target
from slopmeister.spine.tester.supervise import _verify_subject
from slopmeister.vault import subject


def _fixture(tmp_path):
    candidate, evidence = tmp_path / "candidate", tmp_path / "evidence"
    candidate.mkdir()
    (candidate / "visible.md").write_text("visible\n")
    (candidate / "hidden.md").write_text("hidden\n")
    frozen = subject.freeze(candidate, [{"path": "visible.md"}], evidence / "subject.json")
    guide = tmp_path / "guide.md"
    guide.write_text("### Scenario t-1: inspect\nRun `true`. Expect exit 0.\n")
    validation = tmp_path / "notes.md"
    validation.write_text("Notes\n\n## Validation\nScenario t-1 is required.\n")
    args = Namespace(
        cwd=None,
        commit=None,
        subject_manifest=str(frozen.manifest),
        guide=str(guide),
        validation=str(validation),
    )
    resolved = _resolve_target(args)
    request = Launch(args, resolved.root, subject=resolved)
    _read_subject(request)
    root = tmp_path / "tester"
    root.mkdir()
    checkout = root / "checkout"
    run = dict(checkout=str(checkout), tool="claude", model="claude-opus-5", effort="high")
    _checkout(root, run, request)
    return frozen, request, checkout, run


def test_directory_tester_snapshot_contains_only_frozen_candidate_inputs(tmp_path):
    frozen, request, checkout, run = _fixture(tmp_path)
    assert [path.name for path in checkout.iterdir()] == ["visible.md"]
    assert request.commit.startswith("directory:")
    assert request.inputs["subject_tree"] == frozen.tree_sha256
    run["subject_manifest"] = str(frozen.manifest)
    _verify_subject(run)
    (checkout / "visible.md").write_text("changed\n")
    with pytest.raises(ValueError, match="changed the directory subject copy"):
        _verify_subject(run)

"""Directory subjects freeze exact inputs and the entire surrounding tree."""

import json

import pytest

from slopmeister.vault import subject


def test_subject_copy_contains_only_declared_inputs_and_detects_undeclared_change(tmp_path):
    root, evidence = tmp_path / "candidate", tmp_path / "evidence"
    root.mkdir()
    (root / "kept.md").write_text("one\ntwo\n")
    (root / "undeclared.md").write_text("context\n")
    frozen = subject.freeze(
        root,
        [{"path": "kept.md", "ranges": [[1, 2]]}],
        evidence / "subject.json",
    )
    copied = tmp_path / "copied"
    subject.copy_inputs(frozen, copied)
    assert [path.name for path in copied.iterdir()] == ["kept.md"]
    assert subject.scope_lines(frozen) == ("kept.md lines 1-2",)

    (root / "undeclared.md").write_text("changed\n")
    with pytest.raises(ValueError, match="changed after it was frozen"):
        subject.load(frozen.manifest)


def test_subject_identity_does_not_change_when_the_same_manifest_is_relocated(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "note.md").write_text("content\n")
    first = subject.freeze(root, [{"path": "note.md"}], tmp_path / "one/subject.json")
    second_path = tmp_path / "two/subject.json"
    second_path.parent.mkdir()
    second_path.write_bytes(first.manifest.read_bytes())
    second = subject.load(second_path)
    assert first.identity == second.identity


def test_subject_refuses_symlinked_manifest_and_root_paths(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    (root / "note.md").write_text("content\n")
    frozen = subject.freeze(root, [{"path": "note.md"}], tmp_path / "subject.json")
    manifest_link = tmp_path / "manifest-link.json"
    manifest_link.symlink_to(frozen.manifest)
    with pytest.raises(ValueError, match="manifest must not use a symlink"):
        subject.load(manifest_link)
    root_link = tmp_path / "root-link"
    root_link.symlink_to(root, target_is_directory=True)
    payload = json.loads(frozen.manifest.read_text())
    payload["root"] = str(root_link)
    linked_root_manifest = tmp_path / "linked-root.json"
    linked_root_manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="root must not use a symlink"):
        subject.load(linked_root_manifest)


@pytest.mark.parametrize(
    "files,match",
    [
        ([{"path": "../outside.md"}], "escapes"),
        ([{"path": "/absolute.md"}], "escapes"),
        ([{"path": "note.md", "ranges": [[2, 3], [3, 4]]}], "non-overlapping"),
    ],
)
def test_subject_refuses_traversal_absolute_paths_and_overlapping_ranges(tmp_path, files, match):
    root, manifest = tmp_path / "candidate", tmp_path / "subject.json"
    root.mkdir()
    (root / "note.md").write_text("one\ntwo\nthree\nfour\n")
    payload = {
        "version": 1,
        "root": str(root),
        "files": files,
        "tree_sha256": subject.tree_digest(root),
    }
    manifest.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=match):
        subject.load(manifest)


def test_declared_symlink_is_never_copied_into_a_reviewer_or_tester_root(tmp_path):
    root, manifest = tmp_path / "candidate", tmp_path / "subject.json"
    root.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("private\n")
    (root / "link.md").symlink_to(outside)
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "root": str(root),
                "files": [{"path": "link.md"}],
                "tree_sha256": subject.tree_digest(root),
            }
        )
    )
    with pytest.raises(ValueError, match="must not use a symlink"):
        subject.load(manifest)

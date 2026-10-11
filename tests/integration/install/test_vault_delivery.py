"""Every session receives every shared skill, and a target folder overrides one by name."""

import csv
from pathlib import Path
import shutil

import pytest

from slopmeister.install.payload import PayloadContext, payload
from slopmeister.plots import load_all

ROOT = Path(__file__).resolve().parents[3]
TARGETS = [name for name, value in load_all(ROOT / "plots").items() if "target" in value]


with (ROOT / "dist/manifest.tsv").open() as _stream:
    ROWS = list(csv.DictReader(_stream, delimiter="\t"))
SHARED = sorted(row["name"] for row in ROWS if row["kind"] == "skill")


def _varied(target: str) -> set[str]:
    return {
        row["name"].removeprefix(target + "/")
        for row in ROWS
        if row["kind"] == "target-skill" and row["plot"] == target
    }


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("directory", (False, True))
def test_every_target_receives_every_shared_skill(target, directory):
    """Delivery is additive, so target skills cannot hide unrelated shared skills."""
    varied = _varied(target)
    files, _ = payload(PayloadContext(ROOT, target, "allow", directory))
    for tool, destination in (("codex", ".agents"), ("claude", ".claude")):
        for skill in SHARED:
            if skill in varied:
                continue
            source = ROOT / "dist" / tool / "skills" / skill
            _assert_tree_delivered(files, f"{destination}/skills/{skill}", source)


def _assert_tree_delivered(files: dict, prefix: str, source: Path) -> None:
    for path in source.rglob("*"):
        if path.is_file():
            delivered = f"{prefix}/{path.relative_to(source)}"
            assert files[delivered][0] == path.read_bytes(), delivered


@pytest.mark.parametrize("target", TARGETS)
@pytest.mark.parametrize("directory", (False, True))
def test_a_target_folder_wins_over_the_shared_skill_of_that_name(target, directory):
    """The target tree is what a plot varies. Delivering the shared copy instead would drop the
    target's own procedure and its payload without any error."""
    files, _ = payload(PayloadContext(ROOT, target, "allow", directory))
    for tool, destination in (("codex", ".agents"), ("claude", ".claude")):
        for skill in sorted(_varied(target)):
            expected = ROOT / "dist" / tool / "targets" / target / "skills" / skill / "SKILL.md"
            assert files[f"{destination}/skills/{skill}/SKILL.md"][0] == expected.read_bytes()


def test_a_target_folder_overrides_a_vault_skill_by_name(tmp_path):
    """Replaced test_target_manifest_cannot_replace_shared_vault_capability. Under the replacing
    manifest a target could lose vault capability by forgetting it, so vault skills were carved
    out. Additive delivery makes that unreachable, and an override now requires deliberately
    creating a folder of that name, so the carve-out is gone and the override is the property."""
    shutil.copytree(ROOT / "dist", tmp_path / "dist")
    (tmp_path / "plots/fixture/skills/vault-todos").mkdir(parents=True)
    with (tmp_path / "dist/manifest.tsv").open("a") as stream:
        stream.write("target-skill\tfixture/vault-todos\tfixture\tfalse\tfalse\n")
    for tool in ("codex", "claude"):
        (tmp_path / "dist" / tool / "plots/fixture.md").write_text("Fixture plot\n")
        shadow = tmp_path / "dist" / tool / "targets/fixture/skills/vault-todos/SKILL.md"
        shadow.parent.mkdir(parents=True)
        shadow.write_text("Target-local shadow\n")
    files, _ = payload(PayloadContext(tmp_path, "fixture", "allow", False))
    for destination in (".agents", ".claude"):
        assert files[f"{destination}/skills/vault-todos/SKILL.md"][0] == b"Target-local shadow\n"

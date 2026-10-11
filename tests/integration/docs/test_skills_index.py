"""The skills index names every shared skill exactly once."""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
ROW = re.compile(r"^\| \[([a-z-]+)\]\(\.\./src/skills/([a-z-]+)/SKILL\.md\) \|", re.M)


def test_skills_index_names_every_shared_skill_once():
    """Bug: a skill is added or removed and docs/skills.md goes stale without failing."""
    rows = ROW.findall((ROOT / "docs/skills.md").read_text())
    names = [name for name, _ in rows]
    skills = sorted(path.name for path in (ROOT / "src/skills").iterdir() if path.is_dir())
    assert [name for name, target in rows if name != target] == []
    assert sorted(names) == skills
    assert len(names) == len(set(names))

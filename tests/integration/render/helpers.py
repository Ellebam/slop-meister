"""Scratch renderer installations, merge-gate fixtures and deterministic tree digests."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.support.repos import GIT_ENV

ROOT = Path(__file__).resolve().parents[3]


def scaffold(tmp_path: Path, fixture: str | None = None) -> Path:
    root = tmp_path / "slopmeister"
    shutil.copytree(ROOT / "slopmeister", root / "slopmeister")
    (root / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin/slopmeister", root / "bin/slopmeister")
    (root / "src/skills").mkdir(parents=True)
    if fixture:
        shutil.copytree(
            ROOT / "tests/data" / fixture,
            root / ("plots" if fixture == "plot-fixtures" else "src/skills"),
            dirs_exist_ok=True,
        )
    return root


def run_render(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "bin/slopmeister", "render", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def digest(path: Path) -> str:
    result = hashlib.sha256()
    for file in sorted(item for item in path.rglob("*") if item.is_file()):
        result.update(str(file.relative_to(path)).encode())
        result.update(b"\0")
        result.update(file.read_bytes())
    return result.hexdigest()


HEAD = "a" * 40
QUERY = (
    "([.state, .baseRefName, .headRefOid, (.isCrossRepository | tostring), .mergeable] "
    '| join(" ")) + "\\n" + .body'
)
FIELDS = "state,baseRefName,headRefOid,isCrossRepository,mergeable,body"
PR = dict(
    state="OPEN", baseRefName="main", headRefOid=HEAD, isCrossRepository=False,
    mergeable="MERGEABLE", body="Summary\n\nIndependent review: PASS - external review satisfied",
)  # fmt: skip
FAKE_GH = r"""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
calls_file = Path("calls.json")
calls = json.loads(calls_file.read_text()) if calls_file.exists() else []
calls_file.write_text(json.dumps([*calls, args]))
fixture = json.loads(Path("github.json").read_text())
failure = fixture.get("failure")
if args[:2] == ["pr", "view"]:
    assert args[2:] == ["7", "--repo", "github.com/" + fixture["repository"], "--json",
                       fixture["fields"], "--jq", fixture["query"]], args
    if failure == "view":
        sys.exit("fixture PR read failed")
    reads = sum(call[:2] == ["pr", "view"] for call in calls)
    pr = fixture["snapshots"][min(reads, len(fixture["snapshots"]) - 1)]
    fields = [pr[key] for key in ("state", "baseRefName", "headRefOid")]
    fields += [str(pr["isCrossRepository"]).lower(), pr["mergeable"]]
    print(" ".join(fields) + "\n" + pr["body"])
elif args[0] == "api":
    assert args[1:] == ["--hostname", "github.com",
                       "repos/" + fixture["repository"] + "/compare/main..."
                        + fixture["snapshots"][0]["headRefOid"], "--jq", ".status"], args
    if failure == "compare":
        sys.exit("fixture comparison failed")
    print(fixture["comparison"])
elif args[:2] == ["pr", "merge"]:
    assert args[2:] == ["7", "--repo", "github.com/" + fixture["repository"], "--merge",
                       "--match-head-commit", fixture["snapshots"][0]["headRefOid"]], args
    if failure == "merge":
        sys.exit("fixture pinned merge refused")
    Path("merged").write_text(fixture["snapshots"][0]["headRefOid"])
else:
    sys.exit("unexpected command: " + repr(args))
"""


@pytest.fixture(params=("bash", "zsh"))
def gate(request, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, text in (
        ("gh", f"#!{sys.executable}\n" + FAKE_GH),
        ("sleep", "#!/bin/sh\nexit 0\n"),
    ):
        path = bin_dir / name
        path.write_text(text)
        path.chmod(0o700)
    (bin_dir / "python3").symlink_to(sys.executable)
    env = dict(
        PATH=f"{bin_dir}:/usr/bin:/bin", HOME=str(tmp_path), GH_CONFIG_DIR=str(tmp_path / "gh"),
        merge_repository="owner/subject", merge_number="7", merge_base="main", merge_head=HEAD,
        merge_proof="ci", GIT_ALLOW_PROTOCOL="file", **GIT_ENV,
    )  # fmt: skip
    if request.param == "zsh" and shutil.which("zsh", path=env["PATH"]) is None:
        pytest.skip("Zsh is not on the test command PATH.")
    skill = (ROOT / "dist/codex/skills/merge/SKILL.md").read_text()
    command = skill.split("```bash\n", 1)[1].split("\n```", 1)[0]
    plot = (ROOT / "dist/codex/plots/slopmeister.md").read_text().split("## Merge-tree proof", 1)[1]
    project = plot.split("```bash\n", 1)[1].split("\n```", 1)[0]
    return dict(root=tmp_path, env=env, shell=request.param, command=command, project=project)


def run_gate(gate, **changes):
    fixture = dict(snapshots=[dict(PR, headRefOid=gate["env"].get("merge_head", HEAD))],
                   comparison="diverged", query=QUERY, fields=FIELDS,
                   repository=gate["env"].get("merge_repository", "owner/subject"))  # fmt: skip
    fixture.update(changes)
    (gate["root"] / "github.json").write_text(json.dumps(fixture))
    result = subprocess.run(
        [gate["shell"], "-fc", gate["command"]], cwd=gate["root"], env=gate["env"],
        text=True, capture_output=True, timeout=30,
    )  # fmt: skip
    path = gate["root"] / "calls.json"
    return result, json.loads(path.read_text()) if path.exists() else []


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                            check=True, timeout=30, env={**os.environ, **GIT_ENV})  # fmt: skip
    return result.stdout.strip()


def merge_subject(gate, words, stale):
    root = gate["root"]
    git(ROOT, "clone", "--depth=1", "--quiet", ROOT.as_uri(), str(root / "subject"))
    root = gate["root"] = root / "subject"
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    document = root / "docs/merge-budget.md"
    document.write_text("start\n" + "word " * words + "\nend\n")
    git(root, "add", str(document))
    git(root, "commit", "-qm", "Add a budget fixture")
    common = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-qB", "main")
    document.write_text(document.read_text() + "base " * 10 + "\n")
    git(root, "commit", "-qam", "Extend the base")
    git(root, "checkout", "--detach", common)
    document.write_text("head " * 10 + "\n" + document.read_text())
    if stale:
        skill = root / "src/skills/merge/SKILL.md"
        skill.write_text(skill.read_text() + "\nRefuse a stale render.\n")
    git(root, "commit", "-qam", "Extend the head")
    return root


def merge_environment(gate):
    root = gate["root"]
    scratch = root.parent / "scratch"
    scratch.mkdir()
    gate["command"] = gate["project"] + " &&\n" + gate["command"]
    gate["env"].update(
        merge_repository="Ellebam/slop-meister",
        merge_head=git(root, "rev-parse", "HEAD"),
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0=f"url.file://{root}.insteadOf",
        GIT_CONFIG_VALUE_0="https://github.com/Ellebam/slop-meister.git",
        TMPDIR=str(scratch),
    )

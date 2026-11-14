"""One launched task consumes its initial and later repository worktrees together."""

import json
from pathlib import Path
import shlex
import subprocess

import pytest

from slopmeister import repositories
from slopmeister.session import repositories as saved
from slopmeister.spine import candidate
from tests.integration.launch.helpers import CLI, declare, launch, machine, target
from tests.support.repos import git


@pytest.fixture
def prepared_primary(tmp_path, monkeypatch):
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    app = target(tmp_path / "app")
    launch(world, str(app), "example-app", "example-app-attach")
    for key, value in world.env.items():
        monkeypatch.setenv(key, value)
    return world, app / ".worktrees/example-app-attach"


@pytest.fixture(params=[False, True], ids=["before-prepare", "after-prepare"])
def interrupted_install(monkeypatch, prepared_primary, changed, request):
    _, primary = prepared_primary
    original = repositories.prepare
    destination = primary / ".slopmeister-repos/service"
    after_prepare = request.param

    def fail(request):
        if request.action == "--prepare":
            if after_prepare:
                original(request)
            if changed == "file":
                (destination / "new-work.txt").write_text("preserve this\n")
            if changed == "commit":
                git(destination, "commit", "--allow-empty", "-qm", "Preserve new commit")
            raise ValueError("fixture install refused")
        return original(request)

    monkeypatch.setattr(repositories, "prepare", fail)
    return original, primary


def test_launch_and_late_addition_run_one_path_across_three_repositories(tmp_path):
    world = machine(tmp_path)
    declare(tmp_path / "plots", "example-app", "committed")
    sources = [target(tmp_path / name) for name in ("entry", "processor", "storage")]
    for repo, value in zip(sources, ("entry", "process", "store"), strict=True):
        (repo / "value.txt").write_text(value)
        git(repo, "add", "value.txt")
        git(repo, "commit", "-qm", "Seed input")
    launch(
        world,
        str(sources[0]),
        "example-app",
        "example-app-path",
        "--repository",
        str(sources[1]),
        kickoff="Mode: spine\n\nRead the complete path across the repositories.",
    )
    primary = sources[0] / ".worktrees/example-app-path"
    command_before = (world.state / "example-app-path.command").read_bytes()
    added = subprocess.run(
        [str(CLI), "repository", "add", "--workspace", str(primary), "--repo", str(sources[2])],
        env=world.env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert added.returncode == 0, added.stdout + added.stderr
    assert (world.state / "example-app-path.command").read_bytes() == command_before
    members = [primary, *(primary / ".slopmeister-repos" / p.name for p in sources[1:])]
    for member in members:
        assert git(member, "branch", "--show-current").strip() == "example-app-path"
        (member / "value.txt").write_text((member / "value.txt").read_text().upper())
    consumer = (
        "from pathlib import Path; import sys; "
        "print(' -> '.join((Path(p)/'value.txt').read_text() for p in sys.argv[1:]))"
    )
    result = subprocess.run(
        ["python3", "-c", consumer, *map(str, members)],
        env=world.env,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    assert result.stdout.strip() == "ENTRY -> PROCESS -> STORE"
    metadata = Path(git(primary, "rev-parse", "--absolute-git-dir").strip())
    state = json.loads((metadata / "slopmeister-config/state.json").read_text())
    assert [row["worktree"] for row in state["repositories"]] == list(map(str, members))
    assert all(
        row["plot"] == "example-app" and row["commit"] == "allow" for row in state["repositories"]
    )
    assert git(primary, "status", "--porcelain", "--untracked-files=all").splitlines() == [
        " M value.txt"
    ]
    for repo, value in zip(sources, ("entry", "process", "store"), strict=True):
        assert (repo / "value.txt").read_text() == value


@pytest.mark.parametrize("changed", ["clean", "file", "commit"])
@pytest.mark.parametrize("empty", [False, True], ids=["committed", "unborn"])
def test_failed_add_restores_membership_unless_new_work_appeared(
    tmp_path, monkeypatch, interrupted_install, changed, empty
):
    original, primary = interrupted_install
    repo = tmp_path / "service"
    if empty:
        repo.mkdir()
        git(repo, "init", "-qb", "main")
    else:
        target(repo)
    destination = primary / ".slopmeister-repos/service"
    with pytest.raises(ValueError, match="fixture install refused"):
        repositories.add(primary, repo)
    state = saved.read(primary)
    if changed != "clean":
        assert state["repositories"][-1]["status"] == "pending"
        assert destination.is_dir()
        if changed == "file":
            assert (destination / "new-work.txt").read_text() == "preserve this\n"
        else:
            assert git(destination, "log", "-1", "--format=%s").strip() == "Preserve new commit"
    else:
        assert not destination.exists() and len(saved.members(primary)) == 1
        assert not git(repo, "for-each-ref", f"refs/heads/{primary.name}").strip()
        monkeypatch.setattr(repositories, "prepare", original)
        repositories.add(primary, repo)
        assert len(saved.members(primary)) == 2


def test_add_starts_from_fetched_default_without_moving_local_checkout(tmp_path, prepared_primary):
    world, primary = prepared_primary
    upstream = target(tmp_path / "upstream")
    origin, repo = tmp_path / "origin.git", tmp_path / "service"
    git(upstream, "clone", "--bare", ".", str(origin))
    git(upstream, "clone", str(origin), str(repo))
    git(repo, "checkout", "-qb", "local-feature")
    (repo / "local.txt").write_text("local feature\n")
    git(repo, "add", "local.txt")
    git(repo, "commit", "-qm", "Keep local feature")
    local = git(repo, "rev-parse", "HEAD").strip()
    (upstream / "value.txt").write_text("fresh default\n")
    git(upstream, "add", "value.txt")
    git(upstream, "commit", "-qm", "Advance default")
    git(upstream, "push", str(origin), "main")
    expected = git(upstream, "rev-parse", "HEAD").strip()
    added = subprocess.run(
        [str(CLI), "repository", "add", "--workspace", str(primary), "--repo", str(repo)],
        env=world.env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert added.returncode == 0, added.stdout + added.stderr
    member = primary / ".slopmeister-repos/service"
    assert git(member, "rev-parse", "HEAD").strip() == expected
    assert (member / "value.txt").read_text() == "fresh default\n"
    assert not (member / "local.txt").exists()
    assert git(repo, "rev-parse", "HEAD").strip() == local
    assert git(repo, "branch", "--show-current").strip() == "local-feature"
    assert len(saved.members(primary)) == 2


@pytest.mark.parametrize("remote", [False, True], ids=["local", "empty-origin"])
def test_empty_add_can_freeze_before_first_product_commit(tmp_path, prepared_primary, remote):
    _, primary = prepared_primary
    repo = tmp_path / "empty"
    if remote:
        origin = tmp_path / "origin.git"
        git(tmp_path, "init", "--bare", "-qb", "main", str(origin))
        git(tmp_path, "clone", str(origin), str(repo))
    else:
        repo.mkdir()
        git(repo, "init", "-qb", "main")
    row = repositories.add(primary, repo)
    member = Path(row["worktree"])
    assert git(member, "branch", "--show-current").strip() == primary.name
    assert not git(repo, "for-each-ref").strip()
    assert len(saved.members(primary)) == 2
    (member / "product.txt").write_text("first product\n")
    frozen = candidate.freeze(primary, primary.name)
    copied = candidate.materialize(frozen, tmp_path / "review")
    assert (copied / ".slopmeister-repos/empty/product.txt").read_text() == "first product\n"
    assert not git(repo, "for-each-ref").strip()
    git(member, "add", "product.txt")
    git(member, "commit", "-qm", "Create product")
    assert candidate.verify_commit(frozen, "HEAD") == git(primary, "rev-parse", "HEAD").strip()
    assert git(member, "rev-list", "--count", "HEAD").strip() == "1"


@pytest.mark.parametrize("legacy", [False, True], ids=["source-path", "legacy-state"])
def test_changed_delivery_prints_quoted_retry_without_creating_member(
    tmp_path, prepared_primary, legacy
):
    _, primary = prepared_primary
    repo = target(tmp_path / "service with spaces;$(false)")
    state = saved.read(primary)
    state["source_identity"] = "older source"
    if legacy:
        state.pop("source_root", None)
    saved.save(saved.state_path(primary), state)
    with pytest.raises(ValueError, match="session delivery differs") as refused:
        repositories.add(primary, repo)
    lines = str(refused.value).splitlines()
    command = shlex.split(
        next(line.removeprefix("Retry: ") for line in lines if line.startswith("Retry: "))
    )
    assert command[1:] == ["repository", "add", "--workspace", str(primary), "--repo", str(repo)]
    assert command[0].endswith("bin/slopmeister")
    assert "unchanged" in str(refused.value)
    assert not (primary / ".slopmeister-repos" / repo.name).exists()
    assert len(saved.members(primary)) == 1
    assert not git(repo, "for-each-ref", f"refs/heads/{primary.name}").strip()


@pytest.mark.parametrize("problem", ["missing-default", "unreachable"])
def test_remote_start_refusal_names_source_and_restores_membership(
    tmp_path, prepared_primary, problem
):
    _, primary = prepared_primary
    repo, origin = [target(tmp_path / name) for name in ("service", "origin")]
    git(repo, "remote", "add", "origin", str(origin))
    if problem == "missing-default":
        git(origin, "symbolic-ref", "HEAD", "refs/heads/missing")
    else:
        git(repo, "remote", "set-url", "origin", str(tmp_path / "absent"))
    with pytest.raises(ValueError, match=f"cannot select companion start in {repo}"):
        repositories.add(primary, repo)
    assert len(saved.members(primary)) == 1
    assert not (primary / ".slopmeister-repos/service").exists()
    assert not git(repo, "for-each-ref", f"refs/heads/{primary.name}").strip()


@pytest.mark.parametrize("changed", ["clean"])
def test_failed_remote_add_removes_its_unchanged_branch_ahead_of_local_head(
    tmp_path, interrupted_install
):
    _, primary = interrupted_install
    repo, origin = [target(tmp_path / name) for name in ("service", "origin")]
    (origin / "fresh.txt").write_text("fresh default\n")
    git(origin, "add", "fresh.txt")
    git(origin, "commit", "-qm", "Advance default")
    git(repo, "remote", "add", "origin", str(origin))
    local = git(repo, "rev-parse", "HEAD").strip()
    with pytest.raises(ValueError, match="fixture install refused"):
        repositories.add(primary, repo)
    assert len(saved.members(primary)) == 1
    assert not (primary / ".slopmeister-repos/service").exists()
    assert not git(repo, "for-each-ref", f"refs/heads/{primary.name}").strip()
    assert git(repo, "rev-parse", "HEAD").strip() == local

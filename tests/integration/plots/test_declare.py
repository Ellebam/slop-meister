"""Declaration writes require exact authority and preserve existing sources."""

import os
from pathlib import Path
import subprocess
import tomllib

import pytest

from tests.support.fakes import fake_binary
from tests.support.trees import write

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def plots(tmp_path, monkeypatch):
    directory = tmp_path / "plots"
    directory.mkdir()
    binary = fake_binary(tmp_path / "bin", "git", "exit 98")
    monkeypatch.setenv("PLOT_DECLARATIONS", str(directory))
    monkeypatch.setenv("PATH", f"{binary.parent}{os.pathsep}{os.environ['PATH']}")
    return directory


def run(*args, answers=""):
    return subprocess.run(
        [str(ROOT / "bin/slopmeister"), "plots", *args],
        input=answers,
        text=True,
        capture_output=True,
        timeout=10,
    )


@pytest.mark.parametrize("permission", ["allow", "deny"])
def test_preview_matches_permission_and_duplicate_does_not_rewrite(plots, permission):
    result = run("--declare", "example", answers=f"github\nyes\n{permission}\nyes\n")
    assert result.returncode == 0, result.stderr
    path = plots / "example/plot.toml"
    original = path.read_bytes()
    assert path.read_text() in result.stdout
    assert tomllib.loads(path.read_text())["target"]["repository"]["commit"] == permission
    assert run("example").stdout.strip() == "inject"
    assert run("--commit", "example").stdout.strip() == permission
    assert run("--shipping", "example").stdout.strip() == "deny"
    assert run("--tasks", "example").stdout.strip() == "github"
    assert run("--slots", "example").stdout.strip() == "none\t-\t-"
    assert run("--declare", "example").returncode == 0
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "answers",
    [
        "",
        "github\n",
        "github\nno\n",
        "github\nno\n\n",
        "github\nyes\nallow\ny\n",
        "github\nno\nYES\n",
        "github\nno\n yes\n",
        "github\nno\nno\n",
    ],
)
def test_incomplete_or_inexact_confirmation_never_writes_a_directory(plots, answers):
    result = run("--declare", "refused", answers=answers)
    assert result.returncode != 0
    assert not (plots / "refused").exists()


@pytest.mark.parametrize("name", ["Bad Name", "../escape", "-bad", "bad\n"])
def test_unsafe_name_cannot_escape_the_declaration_root(plots, name):
    result = run("--declare", name, answers="vault\nno\nyes\n")
    assert result.returncode != 0
    assert list(plots.iterdir()) == []
    assert not (plots.parent / "escape").exists()


def test_declaration_cannot_convert_an_existing_base(plots):
    base = write(plots, "base/plot.md", "# Existing base\n")
    result = run("--declare", "base", answers="manual\nno\nyes\n")
    assert result.returncode != 0 and "plot.md" in result.stderr
    assert base.read_bytes() == b"# Existing base\n"
    assert not base.with_suffix(".toml").exists()


def test_symlink_destination_cannot_write_into_another_directory(plots):
    destination = plots.parent / "outside"
    destination.mkdir()
    (plots / "redirect").symlink_to(destination, target_is_directory=True)
    result = run("--declare", "redirect", answers="vault\nno\nyes\n")
    assert result.returncode != 0
    assert list(destination.iterdir()) == []
    assert (plots / "redirect").is_symlink()


@pytest.mark.parametrize("args", [("--list",), ("good",), ("--tasks", "good")])
def test_invalid_neighbor_refuses_lookup_without_partial_output(plots, args):
    write(plots, "good/plot.toml", '[plot]\nbase="freeform"\n[target]\ntasks="vault"\n')
    write(plots, "bad/plot.toml", '[plot]\nbase="code"\ntypo=true\n')
    result = run(*args)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "bad/plot.toml: plot.typo: unknown key" in result.stderr


def test_directory_and_template_never_gain_repository_authority(plots):
    result = run("--declare", "directory", answers="vault\nno\nyes\n")
    assert result.returncode == 0, result.stderr
    assert "repository" not in tomllib.loads((plots / "directory/plot.toml").read_text())["target"]
    assert run("directory").stdout.strip() == "-"
    assert run("--commit", "directory").stdout.strip() == "-"
    assert run("--slots", "directory").returncode != 0
    template = write(plots, "template/plot.toml", '[plot]\nbase="code"\nopen-points=["target"]\n')
    original = template.read_bytes()
    assert run("template").returncode != 0
    assert run("--declare", "template").returncode == 0
    assert template.read_bytes() == original
    assert run("--list").stdout.splitlines() == [
        "directory\t-\tvault\t-",
        "template\ttemplate\t-\t-",
    ]


def test_list_includes_bases_and_bootstrap_directories_without_launch_authority(plots):
    write(plots, "base/plot.md", "# Base\n")
    write(plots, "home/global.md", "Global rules.\n")
    write(plots, "vault/bin/helper", "fixture\n")
    assert run("--list").stdout.splitlines() == [
        "base\ttemplate\t-\t-",
        "home\ttemplate\t-\t-",
        "vault\ttemplate\t-\t-",
    ]
    for name in ("base", "home", "vault"):
        for option in ((), ("--commit",), ("--slots",)):
            assert run(*option, name).returncode != 0


def test_list_is_sorted_and_source_history_cannot_change_delivery(plots):
    for name in ("z-last", "a-first"):
        assert run("--declare", name, answers="github\nyes\ndeny\nyes\n").returncode == 0
    path = plots / "z-last/plot.toml"
    path.write_text(path.read_text().replace("[plot]\n", "[plot]\nseed=true\n"))
    assert run("z-last").stdout.strip() == "inject"
    assert run("--list").stdout.splitlines() == [
        "a-first\tinject\tgithub\tdeny",
        "z-last\tinject\tgithub\tdeny",
    ]


def test_extra_repository_argument_cannot_start_declaration(plots):
    result = run("--declare", "new", "/repo", answers="vault\nno\nyes\n")
    assert result.returncode != 0 and list(plots.iterdir()) == []

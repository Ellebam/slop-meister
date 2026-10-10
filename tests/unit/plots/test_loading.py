"""Plot declaration files are loaded safely and without coercion."""

import os
from pathlib import Path

import pytest

from slopmeister.plots import load_all, load_file, slot_rows
from tests.support.trees import write


@pytest.mark.parametrize(
    "content", [b"\xff", b"[plot", b"[plot]\nbase='code'\nbase='code'", b"[[plot]]\nbase='code'"]
)
def test_invalid_document_has_a_safe_located_error(tmp_path, content):
    path = tmp_path / "example" / "plot.toml"
    path.parent.mkdir()
    path.write_bytes(content)
    with pytest.raises(ValueError) as error:
        load_file(path)
    assert str(path) in str(error.value) and ": " in str(error.value)


def test_dotted_and_inline_toml_have_the_same_meaning(tmp_path):
    path = write(
        tmp_path,
        "example/plot.toml",
        'plot.base="code"\ntarget={tasks="github", repository={commit="deny"}}\nslots.none=true\n',
    )
    assert load_file(path)["target"]["repository"]["commit"] == "deny"


def test_whole_tree_refuses_bad_neighbor_and_symlink_sources(tmp_path):
    good = tmp_path / "good"
    write(tmp_path, "good/plot.toml", '[plot]\nbase="code"\n')
    assert list(load_all(tmp_path)) == ["good"]
    bad = tmp_path / "bad"
    write(tmp_path, "bad/plot.toml", '[plot]\nbase="../code"\n')
    with pytest.raises(ValueError, match="bad/plot.toml"):
        load_all(tmp_path)
    (bad / "plot.toml").unlink()
    bad.rmdir()
    bad.symlink_to(good, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        load_all(tmp_path)


def test_control_characters_in_keys_and_paths_cannot_inject_diagnostics():
    data = {"plot": {"base": "code"}, "target": {"bad\x1b\nkey": True}}
    with pytest.raises(ValueError) as error:
        from slopmeister.plots import validate

        validate(data, Path("plots/bad\x1b\n/plot.toml"))
    assert not any(ord(char) < 32 or ord(char) == 127 for char in str(error.value))


def test_slot_row_order_and_values_match_old_normalizer():
    data = {
        "slots": {
            "ports": {"PG_PORT": 45432, "API_PORT": 48000},
            "compose": "docker/stack.yml",
            "max": 3,
        }
    }
    assert slot_rows(data) == [
        "port\tPG_PORT\t45432",
        "port\tAPI_PORT\t48000",
        "compose\t-\tdocker/stack.yml",
        "slots\tmax\t3",
    ]
    assert slot_rows({"slots": {"none": True}}) == ["none\t-\t-"]


SAMPLES = {
    "with-ports": (
        "[slots]\nmax=3\n[slots.ports]\nPG_PORT=45432\nAPI_PORT=43100\n",
        ["port\tPG_PORT\t45432", "port\tAPI_PORT\t43100", "slots\tmax\t3"],
    ),
    "scratch": (
        "[slots]\nmax=3\n[slots.ports]\nPG_PORT=45432\nAPI_PORT=43100\n",
        ["port\tPG_PORT\t45432", "port\tAPI_PORT\t43100", "slots\tmax\t3"],
    ),
    "composed": (
        "[slots]\ncompose='docker/compose.yml'\n[slots.ports]\nWEB_PORT=45080\n",
        ["port\tWEB_PORT\t45080", "compose\t-\tdocker/compose.yml", "slots\tmax\t6"],
    ),
    "without-ports": ("[slots]\nnone=true\n", ["none\t-\t-"]),
}


@pytest.mark.parametrize("name,expected", [(name, value[1]) for name, value in SAMPLES.items()])
def test_each_migrated_sample_preserves_its_old_slot_rows(tmp_path, name, expected):
    prefix = "[plot]\nbase='code'\n[target]\ntasks='github'\n[target.repository]\ncommit='deny'\n"
    path = write(tmp_path, f"{name}/plot.toml", prefix + SAMPLES[name][0])
    assert slot_rows(load_file(path)) == expected


@pytest.mark.parametrize("kind", ["symlink", "directory", "fifo"])
def test_nonregular_declaration_is_refused_before_read(tmp_path, kind):
    path = tmp_path / "example" / "plot.toml"
    path.parent.mkdir()
    if kind == "symlink":
        destination = write(tmp_path, "outside", '[plot]\nbase="code"\n')
        path.symlink_to(destination)
    elif kind == "directory":
        path.mkdir()
    else:
        os.mkfifo(path)
    with pytest.raises(ValueError, match="symlink|regular"):
        load_all(tmp_path)

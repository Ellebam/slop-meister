"""Malformed plot and skill sources fail without replacing prior renders."""

from pathlib import Path

import pytest

from tests.integration.render.helpers import run_render, scaffold
from tests.support.trees import write

PLOT_CASES = (
    (
        "missing-base",
        "plots/overlay/plot.toml",
        "write",
        '[plot]\nbase="nope"\n',
        "plots/nope/plot.md",
    ),
    ("unfilled-marker", "plots/overlay/tail.md", "unlink", "", "overlay/tail.md"),
    ("rogue-fragment", "plots/overlay/rogue.md", "write", "text\n", "rogue.md"),
    ("unknown-token", "plots/base/plot.md", "append", "\n{{WAT}}\n", "unsanctioned"),
    ("inline-marker", "plots/base/plot.md", "append", "\nprose {{FILL:intro}}\n", "unsanctioned"),
    (
        "duplicate-marker",
        "plots/base/plot.md",
        "append",
        "\n{{FILL:intro}}\n",
        "duplicate insertion",
    ),
    ("fragment-h1", "plots/overlay/intro.md", "write", "# second\n", "base owns"),
    ("base-is-plot", "plots/base/plot.toml", "write", '[plot]\nbase="overlay"\n', "both plot.md"),
    ("marker-fragment", "plots/overlay/intro.md", "write", "{{FILL:conventions}}\n", "intro.md"),
    ("second-h1", "plots/base/plot.md", "append", "\n# second\n", "exactly one H1"),
    ("traversal", "plots/overlay/plot.toml", "write", '[plot]\nbase="../evil"\n', "required name"),
    ("indented-h1", "plots/overlay/intro.md", "write", "   # second\n", "base owns"),
    ("crlf-fragment", "plots/overlay/intro.md", "bytes", b"line\r\n", "convert to LF"),
    (
        "invalid-toml",
        "plots/overlay/plot.toml",
        "write",
        '[plot]\nbase="base"\nbase="base"\n',
        "invalid TOML",
    ),
)
PARAMS = tuple((case[0], case[1:4], case[4]) for case in PLOT_CASES)


def _mutate(root: Path, spec: tuple[str, object]) -> None:
    relative, mode, payload = spec
    path = root / relative
    if mode == "unlink":
        path.unlink()
    elif mode == "append":
        path.write_text(path.read_text() + payload)
    elif mode == "bytes":
        path.write_bytes(payload)
    else:
        write(root, relative, payload)


@pytest.mark.parametrize("label,spec,expected", PARAMS, ids=[case[0] for case in PLOT_CASES])
def test_check_plot_failure_modes(tmp_path, label, spec, expected):
    root = scaffold(tmp_path, "plot-fixtures")
    _mutate(root, spec)
    result = run_render(root)
    assert result.returncode != 0, label
    assert expected in result.stderr, result.stderr[-500:]


def test_symlinked_plot_fragment_is_refused(tmp_path):
    root = scaffold(tmp_path, "plot-fixtures")
    outside = write(root, "outside.md", "outside\n")
    fragment = root / "plots/overlay/intro.md"
    fragment.unlink()
    fragment.symlink_to(outside)
    result = run_render(root)
    assert result.returncode != 0 and "symlink" in result.stderr

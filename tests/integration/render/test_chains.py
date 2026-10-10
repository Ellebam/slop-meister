"""Composed plot chains stop at one open middle layer."""

import pytest

from tests.integration.render.helpers import run_render, scaffold
from tests.support.trees import write


def test_check_plot_chain(tmp_path):
    root = scaffold(tmp_path, "plot-fixtures")
    result = run_render(root)
    assert result.returncode == 0, result.stderr
    leaf = (root / "dist/claude/plots/leaf.md").read_text()
    assert "This middle plot sits on the fixture base" in leaf
    assert "The leaf names its target here." in leaf
    assert not (root / "dist/claude/plots/middle.md").exists()
    assert "\tmiddle\t" not in (root / "dist/manifest.tsv").read_text()


CHAIN_CASES = (
    ("closed", "plots/leaf/plot.toml", '[plot]\nbase="overlay"\n', "leaves no points open"),
    ("missing", "plots/middle/intro.md", "No marker\n", "leave nothing open"),
    ("extra", "plots/middle/tail.md", "{{FILL:extra}}\n", "target extra"),
    ("leaf-marker", "plots/leaf/target.md", "{{FILL:target}}\n", "leaf/target.md"),
    (
        "bad-meta",
        "plots/middle/plot.toml",
        '[plot]\nbase="base"\nopen-point=["target"]\n',
        "open-point",
    ),
)


@pytest.mark.parametrize(
    "label,relative,text,expected", CHAIN_CASES, ids=[case[0] for case in CHAIN_CASES]
)
def test_plot_chain_failure_modes(tmp_path, label, relative, text, expected):
    root = scaffold(tmp_path, "plot-fixtures")
    write(root, relative, text)
    result = run_render(root)
    assert result.returncode != 0, label
    assert expected in result.stderr

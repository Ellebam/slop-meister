"""Migrated cross-tool review regressions."""

from __future__ import annotations

from pathlib import Path

import pytest

from slopmeister.review.command import (
    build_review_command,
)
import slopmeister.review.config as config_module
from slopmeister.review.config import ReviewerConfig, load_config
from slopmeister.review.prompt import ReviewTarget
from slopmeister.review.schema import (
    CrossToolReviewError,
    ReviewDirection,
)
from tests.support.review_helpers import (
    DEFAULTS,
    REPO_DIR,
    canned_cli,
)


def test_config_file_values_reach_reviewer_argv(tmp_path: Path):
    """Escaping bug: a model bump in the data file is silently ignored and the old model reviews."""
    config_path = tmp_path / "defaults.toml"
    config_path.write_text(
        '[codex]\nmodel = "codex-bumped"\neffort = "xhigh"\n\n'
        '[claude]\nmodel = "claude-bumped"\neffort = "medium"\n',
        encoding="utf-8",
    )
    config = load_config(config_path)
    target = ReviewTarget(prompt="Review.")
    codex_argv = build_review_command(ReviewDirection.CLAUDE_TO_CODEX, target, config=config)
    claude_argv = build_review_command(ReviewDirection.CODEX_TO_CLAUDE, target, config=config)
    Path(codex_argv[codex_argv.index("--output-schema") + 1]).unlink(missing_ok=True)

    assert codex_argv[codex_argv.index("--model") + 1] == "codex-bumped"
    assert codex_argv[codex_argv.index("--config") + 1] == "model_reasoning_effort='xhigh'"
    assert claude_argv[claude_argv.index("--model") + 1] == "claude-bumped"
    assert claude_argv[claude_argv.index("--effort") + 1] == "medium"


def test_committed_config_carries_both_reviewers():
    """Escaping bug: the committed defaults file loses a key and every review is blocked."""
    config = load_config()
    assert config == ReviewerConfig(
        codex_model=DEFAULTS["codex"]["model"],
        codex_effort=DEFAULTS["codex"]["effort"],
        claude_model=DEFAULTS["claude"]["model"],
        claude_effort=DEFAULTS["claude"]["effort"],
    )


@pytest.mark.parametrize(
    "toml_text, match",
    [
        ("", r"lacks \[codex\]\.model"),
        (
            '[codex]\nmodel = "m"\neffort = "high"\n[claude]\neffort = "high"\n',
            r"lacks \[claude\]\.model",
        ),
        ('[codex]\nmodel = ""\neffort = "high"\n', r"lacks \[codex\]\.model"),
        ('[codex]\nmodel = 3\neffort = "high"\n', r"lacks \[codex\]\.model"),
        ("not toml [", "not valid TOML"),
    ],
)
def test_load_config_fails_closed_naming_the_missing_key(
    tmp_path: Path, toml_text: str, match: str
):
    path = tmp_path / "c.toml"
    path.write_text(toml_text, encoding="utf-8")
    with pytest.raises(CrossToolReviewError, match=match) as raised:
        load_config(path)
    assert raised.value.category.value == "START_PRECONDITION"


def test_load_config_missing_file_fails_closed(tmp_path: Path):
    with pytest.raises(CrossToolReviewError, match="could not be read") as raised:
        load_config(tmp_path / "absent.toml")
    assert raised.value.category.value == "START_PRECONDITION"


def test_default_config_path_is_anchored_beside_the_cli(tmp_path: Path, monkeypatch, capsys):
    """Escaping bug: an absolute invocation from another checkout cannot find its defaults."""
    assert (
        config_module.DEFAULT_CONFIG_PATH == REPO_DIR / "slopmeister" / "review" / "defaults.toml"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CROSS_TOOL_REVIEW_TIMEOUT_SECONDS", raising=False)
    module = canned_cli(monkeypatch, tmp_path)
    assert (
        module.main(
            [
                "review",
                "--direction",
                "codex-to-claude",
                "--mode",
                "plan",
                "--prompt",
                "Review.",
            ]
        )
        == 0
    )
    err = capsys.readouterr().err
    assert f"model={DEFAULTS['claude']['model']} effort={DEFAULTS['claude']['effort']}" in err

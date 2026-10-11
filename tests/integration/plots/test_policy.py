"""Valid-looking declaration edits must not widen the operator's deny permissions."""

from pathlib import Path
import tomllib

import pytest

from tests.integration.plots.test_declare import run

ROOT = Path(__file__).resolve().parents[3]
DENY_PLOTS = ("example-client", "example-notes")


@pytest.mark.parametrize("name", DENY_PLOTS)
def test_deny_plot_cannot_gain_commit_or_shipping_permission(name):
    declaration = tomllib.loads((ROOT / "plots" / name / "plot.toml").read_text())
    repository = declaration["target"]["repository"]
    assert repository["commit"] == "deny"
    assert repository.get("shipping", "deny") == "deny"


def test_example_client_declares_only_the_documented_service_actions():
    declaration = tomllib.loads((ROOT / "plots/example-client/plot.toml").read_text())
    assert set(declaration["target"]["service_actions"]) == {
        "jira-read",
        "jira-write",
        "confluence-read",
        "confluence-write",
    }


def test_real_plot_readback_keeps_its_tracker_and_permission_roster(monkeypatch):
    """Bug: a valid-looking tracker swap silently changes where a real plot gets its tasks."""
    monkeypatch.setenv("PLOT_DECLARATIONS", str(ROOT / "plots"))
    result = run("--list")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "code\ttemplate\t-\t-",
        "example-app\tinject\tmanual\tallow",
        "example-client\tinject\tmanual\tdeny",
        "example-notes\tinject\tvault\tdeny",
        "freeform\ttemplate\t-\t-",
        "home\ttemplate\t-\t-",
        "inject\ttemplate\t-\t-",
        "slopmeister\tinject\tgithub\tallow",
        "vault\ttemplate\t-\t-",
    ]

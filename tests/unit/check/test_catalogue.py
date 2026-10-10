"""The catalogue selects each declared check in the correct execution layer."""

from pathlib import Path

from slopmeister.check import catalogue
from tests.support.trees import write

PORTABLE_IDS = "render ruff format shellcheck quality pytest-unit pytest-integration"
PORTABLE = set(PORTABLE_IDS.split())


def test_ci_catalogue_contains_portable_additions_without_native_or_live_jobs():
    checks = catalogue.catalogue(catalogue.Selection(layer="portable"))
    argv = "\n".join(" ".join(item.argv) for item in checks if item.id != "shellcheck")
    assert {item.id for item in checks} == PORTABLE
    for layer in ("tests/unit", "tests/integration"):
        assert layer in argv


def test_legacy_vault_argument_only_reaches_drift():
    checks = catalogue.catalogue(catalogue.Selection(vault="/tmp/vault with spaces"))
    routed = [item for item in checks if "/tmp/vault with spaces" in item.argv]
    assert len(routed) == 1
    assert routed[0].id == "drift"


def test_catalogue_never_falls_back_from_the_locked_environment(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(catalogue, "ROOT", tmp_path)
    checks = catalogue.first_phase() + catalogue.layered_pytest()
    by_id = {item.id: item for item in checks}
    python = str(tmp_path / ".venv/bin/python")
    ruff = str(tmp_path / ".venv/bin/ruff")
    assert by_id["ruff"].argv[0] == ruff
    assert by_id["format"].argv[0] == ruff
    assert by_id["pytest-unit"].argv[0] == python
    assert by_id["pytest-integration"].argv[0] == python
    assert by_id["pytest-native"].argv[0] == python


def test_every_pytest_layer_keeps_grouped_tests_on_one_worker():
    """Escaping bug: a layer on plain load ran grouped process-tree tests beside each other."""
    for item in catalogue.layered_pytest():
        position = item.argv.index("--dist")
        assert item.argv[position + 1] == "loadgroup", item.id


def test_shellcheck_uses_all_inventory_bash_paths_and_excludes_non_bash(tmp_path, monkeypatch):
    bash = (
        "plots/vault/bin/slopmeister-vault",
        "plots/vault/bin/vaultgit",
        "plots/home/bin/op",
        "plots/home/drive/drive-sync.sh",
        "scripts/check.sh",
        "src/skills/example/scripts/check.sh",
    )
    excluded = (
        "plots/vault/bin/vault-lock.py",
        "dist/claude/check.sh",
        "tests/data/check.sh",
        "plots/example-app/skills/example/fixtures/check.sh",
    )
    for path in (*bash, *excluded):
        write(tmp_path, path, "")
    monkeypatch.setattr(catalogue, "ROOT", tmp_path)
    check = next(check for check in catalogue.first_phase() if check.id == "shellcheck")
    assert check.argv == ("shellcheck", "--severity=warning", *sorted(bash))

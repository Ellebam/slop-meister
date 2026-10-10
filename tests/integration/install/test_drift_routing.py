"""Drift delegates to the product installer in check mode."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_drift_uses_the_product_installer_in_check_mode():
    source = (ROOT / "slopmeister/workstation/drift.py").read_text()
    assert "install_cli.main" in source and '"--check"' in source

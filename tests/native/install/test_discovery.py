"""Native clients discover only the installed session configuration."""

import pytest

from tests.native.install.discovery_claude import verify_claude
from tests.native.install.discovery_codex import verify_codex
from tests.native.install.discovery_fixture import prepare


@pytest.mark.xdist_group("native-standin")
def test_installed_configuration_excludes_competing_native_discovery(tmp_path):
    root = tmp_path / "discovery"
    root.mkdir()
    verify_claude(prepare(root), verify_codex)

"""Installer integration fixtures."""

import pytest

from tests.integration.install.installer_helpers import prepared


@pytest.fixture
def installed(tmp_path):
    return prepared(tmp_path)

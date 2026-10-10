"""A private stand-in for /tmp keeps the machine's real run folders out of reach."""

from pathlib import Path
import shutil
import tempfile

import pytest

from slopmeister.check import ownership


@pytest.fixture
def run_root(monkeypatch):
    root = Path(tempfile.mkdtemp(prefix="rr.", dir="/tmp")).resolve()
    monkeypatch.setattr(ownership, "RUN_ROOT", root)
    yield root
    shutil.rmtree(root, ignore_errors=True)

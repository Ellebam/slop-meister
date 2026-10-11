"""Native claims fixture with isolated process and socket state."""

from pathlib import Path
import tempfile

import pytest

from tests.support.claims_world import ClaimWorld


@pytest.fixture
def world():
    # A short root keeps the daemon socket path under the Unix socket limit. Resolved, because
    # /tmp is a link on the Mac and a real folder on Linux.
    with tempfile.TemporaryDirectory(prefix="claims-", dir=Path("/tmp").resolve()) as folder:
        fixture = ClaimWorld(Path(folder))
        try:
            yield fixture.values()
        finally:
            fixture.close()

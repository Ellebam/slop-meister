"""The login verdict belongs to the Codex executable the launcher actually runs."""

import pytest

from tests.integration.workstation.test_doctor import healthy, results
from tests.support.fakes import fake_binary


@pytest.mark.parametrize("path_client", [True, False])
def test_codex_login_uses_the_fixed_client_even_when_path_differs(tmp_path, path_client):
    home, bin_dir = healthy(tmp_path)
    fake_binary(home / ".local/bin", "codex", "exit 1" if path_client else "exit 0")
    if not path_client:
        (bin_dir / "codex").unlink()
    found = results(home, bin_dir)
    assert found["tool:codex"]["status"] == "ok"
    assert found["login:codex"]["status"] == ("problem" if path_client else "ok")

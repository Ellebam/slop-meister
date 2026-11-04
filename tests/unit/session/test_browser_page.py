"""Page configuration never overwrites a linked file."""

import pytest

from slopmeister.session import browser_runtime as runtime


@pytest.mark.parametrize("link", ["symlink", "hardlink"])
def test_page_config_cannot_overwrite_an_unrelated_file(tmp_path, link):
    import os

    target = tmp_path / "keep"
    target.write_text("untouched")
    config = tmp_path / "config.json"
    config.symlink_to(target) if link == "symlink" else os.link(target, config)
    with pytest.raises((OSError, ValueError)):
        runtime._configuration(config, {"console": {"level": "none"}})
    assert target.read_text() == "untouched"


def test_linked_page_tool_directory_preserves_its_target(root, tool):
    calls, _ = tool
    target = root.parent / "unrelated"
    target.mkdir()
    (target / "keep").write_text("unchanged")
    (root / "playwright").symlink_to(target)
    with pytest.raises(ValueError, match="STATE_REFUSED"):
        runtime.page(root, ["snapshot"])
    assert calls == [] and (target / "keep").read_text() == "unchanged"
    assert list(target.iterdir()) == [target / "keep"]

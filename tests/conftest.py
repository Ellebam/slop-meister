"""The layer is the directory. Every test gets the marker of the layer it sits in."""

from pathlib import Path

import pytest

LAYERS = ("unit", "integration", "native", "live")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    tests_root = Path(config.rootpath) / "tests"
    for item in items:
        layer = Path(item.path).relative_to(tests_root).parts[0]
        if layer not in LAYERS:
            raise pytest.UsageError(f"{item.path} is outside the four layers {LAYERS}")
        item.add_marker(getattr(pytest.mark, layer))
    live = [item for item in items if item.get_closest_marker("live")]
    if live and not any("tests/live" in arg for arg in config.args):
        # Live tests start paid sessions, so only a command naming tests/live collects them.
        config.hook.pytest_deselected(items=live)
        items[:] = [item for item in items if item not in live]

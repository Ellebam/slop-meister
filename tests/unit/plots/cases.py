"""Shared declaration inputs for plot unit tests."""

from copy import deepcopy
from pathlib import Path

VALID = {
    "plot": {"base": "code"},
    "target": {
        "tasks": "github",
        "repository": {"commit": "allow"},
    },
    "slots": {"ports": {"PG_PORT": 45432}},
}
PATH = Path("plots/example/plot.toml")


def change(key: str, value: object, *, remove: bool = False) -> dict:
    data = deepcopy(VALID)
    parts = key.split(".")
    parent = data
    for part in parts[:-1]:
        parent = parent[part]
    if remove:
        del parent[parts[-1]]
    else:
        parent[parts[-1]] = value
    return data

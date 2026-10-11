"""Git variables a harness injects, kept away from the Git and GitHub children started here.

A harness sets configuration and credential-prompt variables on every command it runs. They are
dropped, so they cannot change a child, while a variable that redirects the repository still
stops the caller.
"""

import os

INJECTED = ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS", "GIT_ASKPASS", "SSH_ASKPASS")
INJECTED_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
REDIRECTS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
)


def injected(name: str) -> bool:
    return name in INJECTED or name.startswith(INJECTED_PREFIXES)


def redirect() -> str | None:
    """The first variable present that points Git at another repository, index or object store."""
    return next((name for name in REDIRECTS if name in os.environ), None)


def child() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if not injected(name)}

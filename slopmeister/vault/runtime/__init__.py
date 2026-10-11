"""Self-contained vault commands installed outside a checkout."""

from collections.abc import Sequence


def main(argv: Sequence[str]) -> int:
    from .__main__ import main as command

    return command(argv)


__all__ = ["main"]

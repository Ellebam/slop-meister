#!/usr/bin/env python3
"""Thin entry for slopmeister.session.bloom, bound to the installed session snapshot."""

from pathlib import Path
import sys

SNAPSHOT = ""


def root() -> Path:
    if SNAPSHOT:
        return Path(SNAPSHOT)
    here = Path(__file__).resolve()
    return next(p for p in here.parents if (p / "slopmeister" / "session").is_dir())


sys.dont_write_bytecode = True
sys.path[:0] = [str(root())]
from slopmeister.session.bloom import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

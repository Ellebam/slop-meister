"""Thin entries, the delivered files that run one session program from the snapshot."""

import json
from pathlib import Path

# The installer bakes SNAPSHOT. Empty, the entry walks up from its own path to a checkout.
TEXT = '''#!/usr/bin/env python3
"""Thin entry for {module}, written by the slopmeister installer."""

from pathlib import Path
import sys

SNAPSHOT = {snapshot}


def root() -> Path:
    if SNAPSHOT:
        return Path(SNAPSHOT)
    here = Path(__file__).resolve()
    return next(p for p in here.parents if (p / "slopmeister" / "session").is_dir())


sys.dont_write_bytecode = True
sys.path[:0] = [str(root())]
from {module} import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
'''


def entry_text(module: str, snapshot: Path | None = None) -> str:
    """The entry file for a session program's `main(argv)`, bound to a snapshot when given."""
    return TEXT.format(module=module, snapshot=json.dumps(str(snapshot) if snapshot else ""))

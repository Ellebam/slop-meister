"""Issue locks serialize separate claim processes."""

import json
import subprocess
import sys

from slopmeister.claims import locks
from tests.support import trees


def test_lock_is_shared_and_released_without_releasing_claim(tmp_path):
    context = {"common": tmp_path}
    receipt = trees.write(tmp_path, "issue.json", '{"phase":"claimed"}')
    code = 'import fcntl,sys; f=open(sys.argv[1],"r+"); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)'
    with locks.locked(context, 7):
        attempt = subprocess.run(
            [sys.executable, "-c", code, str(locks.lock_path(context, 7))], capture_output=True
        )
        assert attempt.returncode != 0
    result = subprocess.run([sys.executable, "-c", code, str(locks.lock_path(context, 7))])
    assert result.returncode == 0
    assert json.loads(receipt.read_text())["phase"] == "claimed"

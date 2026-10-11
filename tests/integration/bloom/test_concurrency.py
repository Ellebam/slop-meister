"""A second process cannot enter publication while another store operation holds its lock."""

from pathlib import Path
import subprocess
import sys

import pytest

from slopmeister.session import bloom_storage as store

ROOT = Path(__file__).resolve().parents[3]


def test_publication_waits_for_another_process_store_lock(tmp_path):
    script = (
        "import sys;from pathlib import Path;"
        f"sys.path.insert(0, {str(ROOT)!r});"
        "from slopmeister.session.bloom_storage import publish;"
        "print('ready', flush=True);"
        f"print(publish(Path({str(tmp_path)!r}), b'complete page'), flush=True)"
    )
    worker = None
    try:
        with store.locked(tmp_path):
            worker = subprocess.Popen(
                [sys.executable, "-c", script], stdout=subprocess.PIPE, text=True
            )
            assert worker.stdout.readline().strip() == "ready"
            with pytest.raises(subprocess.TimeoutExpired):
                worker.wait(timeout=1)
            assert not list(tmp_path.glob("*.html"))
        output, _ = worker.communicate(timeout=5)
        assert worker.returncode == 0
        name = output.strip()
        assert store.PAGE.fullmatch(name)
        assert (tmp_path / name).read_bytes() == b"complete page"
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.wait(timeout=5)

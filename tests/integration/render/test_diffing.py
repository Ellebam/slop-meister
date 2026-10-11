"""Render checking compares bytes rather than file metadata."""

import os

from slopmeister.render import trees_differ
from tests.support.trees import write


def test_check_byte_exact_diffing(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    write(first, "f.md", "same size AA\n")
    write(second, "f.md", "same size ZZ\n")
    stamp = 1_000_000_000
    os.utime(first / "f.md", (stamp, stamp))
    os.utime(second / "f.md", (stamp, stamp))
    assert trees_differ(first, second)
    write(second, "f.md", "same size AA\n")
    assert not trees_differ(first, second)

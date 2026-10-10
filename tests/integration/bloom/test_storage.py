"""Immutable names, bounded storage and recovery of interrupted publication."""

from concurrent.futures import ThreadPoolExecutor
import io
import os
from pathlib import Path
import time

import pytest

from slopmeister.session import bloom_storage as store

DAY_SECONDS = 24 * 60 * 60


def planted(folder: Path, name: str, data: bytes, age: int = 0) -> Path:
    page = folder / name
    page.write_bytes(data)
    stamp = time.time() - age
    os.utime(page, (stamp, stamp))
    return page


def test_concurrent_same_topic_copies_never_replace_each_other(tmp_path):
    payloads = [b"<html>first same topic</html>", b"<html>second same topic</html>"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        names = list(executor.map(lambda data: store.publish(tmp_path, data), payloads))
    assert len(set(names)) == 2
    assert all(store.PAGE.fullmatch(name) for name in names)
    assert [(tmp_path / name).read_bytes() for name in names] == payloads
    assert not list(tmp_path.glob("*.part"))


def test_collision_preserves_the_previous_page(tmp_path, monkeypatch):
    token = "a" * 32
    monkeypatch.setattr(store.secrets, "token_hex", lambda _: token)
    assert store.publish(tmp_path, b"<html>first</html>") == token + ".html"
    with pytest.raises(FileExistsError):
        store.publish(tmp_path, b"<html>replacement</html>")
    assert (tmp_path / (token + ".html")).read_bytes() == b"<html>first</html>"
    assert not (tmp_path / ("." + token + ".part")).exists()


def test_cleanup_removes_old_page_and_retains_young_page(tmp_path):
    old = planted(tmp_path, "a" * 32 + ".html", b"old", 8 * DAY_SECONDS)
    young = planted(tmp_path, "b" * 32 + ".html", b"young", 6 * DAY_SECONDS)
    assert store.cleanup(tmp_path) == (1, len(b"young"))
    assert not old.exists()
    assert young.read_bytes() == b"young"


def test_cleanup_evicts_oldest_until_within_size_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_BYTES", 10)
    oldest = planted(tmp_path, "a" * 32 + ".html", b"1234567", 30)
    newest = planted(tmp_path, "b" * 32 + ".html", b"7654321", 10)
    assert store.cleanup(tmp_path) == (1, 7)
    assert not oldest.exists()
    assert newest.read_bytes() == b"7654321"


def test_default_capacity_evicts_a_page_when_total_exceeds_64_mib(tmp_path):
    first = planted(tmp_path, "a" * 32 + ".html", b"first", 30)
    second = planted(tmp_path, "b" * 32 + ".html", b"second", 10)
    for page in (first, second):
        with page.open("r+b") as stream:
            stream.truncate(40 * 1024 * 1024)
    assert store.cleanup(tmp_path) == (1, 40 * 1024 * 1024)
    assert not first.exists() and second.exists()


def test_publication_keeps_the_new_copy_even_after_clock_skew(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_BYTES", 10)
    future = planted(tmp_path, "a" * 32 + ".html", b"1234567", -100)
    name = store.publish(tmp_path, b"new page")
    assert not future.exists()
    assert (tmp_path / name).read_bytes() == b"new page"


def test_cleanup_recovers_partial_before_and_after_atomic_link(tmp_path):
    partial = planted(tmp_path, "." + "a" * 32 + ".part", b"incomplete")
    linked = planted(tmp_path, "." + "b" * 32 + ".part", b"complete")
    name = "b" * 32 + ".html"
    os.link(linked, tmp_path / name)
    assert store.cleanup(tmp_path) == (0, len(b"complete"))
    assert not partial.exists() and not linked.exists()
    assert (tmp_path / name).read_bytes() == b"complete"


def test_unexpected_entries_do_not_stop_safe_cleanup(tmp_path):
    old = planted(tmp_path, "a" * 32 + ".html", b"old", store.RETENTION_SECONDS + 5)
    foreign = planted(tmp_path, "foreign", b"preserve me")
    outside = planted(tmp_path.parent, tmp_path.name + "-outside", b"outside")
    link = tmp_path / ("b" * 32 + ".html")
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="cleaned managed pages; preserved 2 unsupported"):
        store.cleanup(tmp_path)
    assert not old.exists()
    assert foreign.read_bytes() == b"preserve me"
    assert link.is_symlink() and outside.read_bytes() == b"outside"


def test_unsafe_directory_and_lock_cannot_redirect_writes(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o750)
    link = tmp_path / "link"
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        store.publish(link, b"page")
    (outside / ".lock").symlink_to(tmp_path / "sentinel")
    with pytest.raises(OSError):
        store.publish(outside, b"page")
    assert not (tmp_path / "sentinel").exists()
    assert not list(outside.glob("*.html"))


def test_oversized_and_invalid_utf8_intake_is_rejected(monkeypatch):
    monkeypatch.setattr(store, "MAX_BYTES", 4)
    for data in (b"12345", b"", b"\xff"):
        with pytest.raises(ValueError, match="storage bound|UTF-8"):
            store.read_page(io.BytesIO(data))


def test_other_users_cannot_write_the_managed_directory_or_page(tmp_path):
    name = store.publish(tmp_path, b"private page")
    assert (tmp_path / name).stat().st_mode & 0o777 == 0o640
    unsafe = tmp_path / "shared"
    unsafe.mkdir()
    unsafe.chmod(0o777)
    with pytest.raises(ValueError, match="no other writers"):
        store.publish(unsafe, b"untrusted destination")
    assert list(unsafe.iterdir()) == []

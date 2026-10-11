"""Installer payload helper for integration spine tests."""

from slopmeister.install.payload import PayloadContext, payload
from slopmeister.paths import ROOT


def installer_payload(target: str) -> dict:
    files, _ = payload(PayloadContext(ROOT, target, "allow", False))
    return files

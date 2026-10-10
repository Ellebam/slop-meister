"""Render editable Slopmeister sources into deterministic tool trees."""

from slopmeister.render.build import build
from slopmeister.render.check import trees_differ

__all__ = ["build", "trees_differ"]

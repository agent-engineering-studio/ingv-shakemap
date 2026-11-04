"""The exceptions this package raises."""

from __future__ import annotations


class IngvError(Exception):
    """An INGV service failed, or answered something this package cannot read."""


class GridError(IngvError, ValueError):
    """A ``grid.xml`` that is not a readable ShakeMap grid."""


__all__ = ["GridError", "IngvError"]

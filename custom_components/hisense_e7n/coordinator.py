"""Compatibility alias. Runtime object is HisenseTvHub (TCL TclTvHub)."""

from __future__ import annotations

from .hub import HisenseTvHub as HisenseTvCoordinator

__all__ = ["HisenseTvCoordinator"]

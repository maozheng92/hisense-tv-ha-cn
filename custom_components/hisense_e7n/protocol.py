"""VIDAA MQTT protocol surface (TCL names this module protocol).

Implementation stays in ``tv_client`` so existing tests keep loading that file.
"""

from __future__ import annotations

from .tv_client import HisenseTvClient, TvState

__all__ = ["HisenseTvClient", "TvState"]

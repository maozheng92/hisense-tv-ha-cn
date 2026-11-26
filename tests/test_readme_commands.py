"""README documents every remote.send_command KEY_* and source-macro key."""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_README = (_REPO / "README.md").read_text(encoding="utf-8")
_KEYS = _REPO / "custom_components" / "hisense_e7n" / "keys.py"
_SOURCES = _REPO / "custom_components" / "hisense_e7n" / "custom_sources.py"


def test_readme_lists_remote_send_command() -> None:
    assert "`remote.send_command`" in _README
    assert "hisense_e7n.send_key" in _README
    assert "screenshot" in _README
    assert "smart_image" in _README
    assert "media_player.select_source" in _README


def test_readme_lists_every_key_constant() -> None:
    names = re.findall(
        r'^KEY_[A-Z_]+ = "(KEY_[A-Z_]+)"', _KEYS.read_text(encoding="utf-8"), re.M
    )
    assert names
    missing = [name for name in names if f"`{name}`" not in _README]
    assert missing == []


def test_readme_lists_source_macro_short_names() -> None:
    blob = _SOURCES.read_text(encoding="utf-8")
    block = blob.split("HISENSE_SOURCE_KEYS", 1)[1].split("}", 1)[0]
    shorts = re.findall(r'"([a-z_]+)"', block)
    assert "source" in shorts and "ok" in shorts
    missing = [name for name in shorts if f"`{name}`" not in _README]
    assert missing == []

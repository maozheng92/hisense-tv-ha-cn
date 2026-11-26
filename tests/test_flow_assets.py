"""Sanity checks for TCL-style options-flow copy (including Hisense extras)."""

from __future__ import annotations

import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_e7n"
_FORM_STEPS = (
    "connection",
    "power_on",
    "ir_details",
    "volume",
    "source_add",
    "source_edit",
    "source_form",
    "source_seq_pick",
    "source_seq_repeat",
    "source_delete",
    "source_reorder",
)
_INIT_MENU = ("connection", "power_on", "volume", "sources", "save")
_SOURCE_MENU = (
    "source_add",
    "source_edit",
    "source_delete",
    "source_reorder",
    "sources_done",
)


def _load(name: str) -> dict:
    return json.loads((_ROOT / name).read_text(encoding="utf-8"))


def test_zh_uses_button_entity_name() -> None:
    zh = _load("translations/zh-Hans.json")
    blob = json.dumps(zh, ensure_ascii=False)
    assert "按钮实体" in blob
    assert "Button 实体" not in blob
    assert "button 实体" not in blob
    kind = zh["options"]["step"]["source_seq_kind"]["menu_options"]
    assert kind["source_seq_buttons"] == "按钮实体"
    assert kind["source_seq_kind_back"] == "返回"
    assert zh["options"]["step"]["sources"]["menu_options"]["sources_done"] == "返回"
    assert "go_back" not in zh["options"]["step"]["init"].get("data", {})
    assert "go_back" not in zh["options"]["step"]["init"].get("menu_options", {})
    for step_id in _FORM_STEPS:
        assert zh["options"]["step"][step_id]["data"]["go_back"] == "返回上一界面"
    hidden = zh["options"]["step"]["source_add"]["data"]["hidden"]
    assert hidden == "从输入源列表中隐藏"
    assert zh["options"]["step"]["init"]["menu_options"]["volume"] == "音量按钮"
    assert zh["config"]["step"]["volume"]["data"]["音量加按钮"] == "音量加按钮"
    assert "entity" in zh
    assert "button" not in zh["entity"]


def test_strings_and_en_match_tcl_source_ux() -> None:
    for name in ("strings.json", "translations/en.json"):
        data = _load(name)
        step = data["options"]["step"]
        assert tuple(step["init"]["menu_options"]) == _INIT_MENU
        assert step["sources"]["menu_options"]["sources_done"] == "Back"
        assert tuple(step["sources"]["menu_options"]) == _SOURCE_MENU
        assert step["source_seq_kind"]["menu_options"]["source_seq_kind_back"] == "Back"
        assert step["source_seq_kind"]["menu_options"]["source_seq_buttons"] == "Button entities"
        assert step["source_add"]["data"]["hidden"] == "Hide from source list"
        assert step["source_add"]["data"]["name"] == "Name"
        assert step["source_reorder"]["data"]["source_order"] == "Order"
        for step_id in _FORM_STEPS:
            assert step[step_id]["data"]["go_back"] == "Go back"
        assert "button" not in data.get("entity", {})

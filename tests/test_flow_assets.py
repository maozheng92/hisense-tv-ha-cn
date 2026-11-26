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
        assert "go_back" not in zh["options"]["step"][step_id].get("data", {})
        assert "go_back" not in zh["options"]["step"][step_id].get("data_description", {})
        assert zh["options"]["step"][step_id]["submit"] == "提交"
    hidden = zh["options"]["step"]["source_add"]["data"]["hidden"]
    assert hidden == "从输入源列表中隐藏"
    assert zh["options"]["step"]["init"]["menu_options"]["volume"] == "音量按钮"
    assert zh["config"]["step"]["volume"]["data"]["音量加按钮"] == "音量加按钮"
    assert "entity" in zh
    assert "button" not in zh["entity"]
    assert "remote" not in zh["entity"]
    assert "go_back_choice" not in zh.get("selector", {})


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
            assert "go_back" not in step[step_id].get("data", {})
            assert "go_back" not in step[step_id].get("data_description", {})
            assert step[step_id]["submit"] == "Submit"
        assert "button" not in data.get("entity", {})
        assert "remote" not in data.get("entity", {})
        assert "go_back_choice" not in data.get("selector", {})


def test_footer_script_posts_go_back_and_hides_menu_rows() -> None:
    script = (_ROOT / "www" / "hisense_e7n_flow.js").read_text(encoding="utf-8")
    assert 'DOMAIN = "hisense_e7n"' in script
    assert 'sources: ["sources_done"]' in script
    assert "source_seq_kind_back" in script
    assert "go_back: true" in script
    assert "dialog-data-entry-flow" in script
    assert 'back: "返回"' in script
    assert "secondaryAction" in script
    assert "primaryAction" in script
    assert "space-between" in script
    assert "deepQuery(document, DIALOG_SEL)" in script
    flow_ui = (_ROOT / "flow_ui.py").read_text(encoding="utf-8")
    assert "es5=True" in flow_ui
    assert "add_extra_js_url" in flow_ui
    init_py = (_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "async_setup_flow_ui" in init_py
    assert "async def async_setup(" in init_py


def test_go_back_is_footer_not_schema_field() -> None:
    text = (_ROOT / "config_flow.py").read_text(encoding="utf-8")
    helper = text.split("def _with_back", 1)[1].split("def _show_form", 1)[0]
    assert "BooleanSelector" not in helper
    assert "_go_back_selector" not in text
    assert "button_toggle" not in text
    assert "hisense_e7n_flow.js" in helper
    assert "_SchemaWithBack(mapping)" in helper
    assert "description_placeholders" in text.split("def _show_form", 1)[1].split(
        "def _menu_placeholders", 1
    )[0]


def test_remote_entity_matches_tcl_unnamed_device() -> None:
    text = (_ROOT / "remote.py").read_text(encoding="utf-8")
    assert "_attr_name = None" in text
    assert '_attr_name = "Remote"' not in text
    assert "_attr_icon" not in text
    assert "_attr_translation_key" not in text
    assert "_attr_entity_picture" not in text
    assert "_attr_device_class" not in text
    assert "mdi:remote" not in text


def test_version_is_1_23_3() -> None:
    manifest = _load("manifest.json")
    assert manifest["version"] == "1.23.3"

"""Existing button entities must be hidden without being disabled."""

from __future__ import annotations


def test_should_hide_visible_buttons_only(proto_const) -> None:
    from pathlib import Path
    import importlib.util
    import sys

    pkg = "hisense_e7n_proto"
    path = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "hisense_e7n"
        / "button_visibility.py"
    )
    full = f"{pkg}.button_visibility"
    spec = importlib.util.spec_from_file_location(full, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg
    sys.modules[full] = module
    # const already loaded as proto_const under hisense_e7n_proto.const
    sys.modules[f"{pkg}.const"] = proto_const
    spec.loader.exec_module(module)

    should_hide = module.should_hide_button_registry_entry
    domain = proto_const.DOMAIN
    assert should_hide(domain="button", platform=domain, hidden_by=None) is True
    assert should_hide(domain="button", platform=domain, hidden_by="integration") is False
    assert should_hide(domain="button", platform=domain, hidden_by="user") is False
    assert should_hide(domain="remote", platform=domain, hidden_by=None) is False
    assert should_hide(domain="button", platform="other", hidden_by=None) is False


def test_button_module_writes_integration_hider() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "hisense_e7n"
        / "button.py"
    ).read_text(encoding="utf-8")
    assert "RegistryEntryHider.INTEGRATION" in source
    assert "async_hide_existing_buttons" in source
    assert "entity_registry_visible_default = False" in source
    assert "disabled_by" not in source

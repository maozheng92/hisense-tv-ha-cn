"""Older remoter button entities must be removed, not recreated."""

from __future__ import annotations


def test_should_remove_legacy_hisense_buttons_only(proto_const) -> None:
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
    sys.modules[f"{pkg}.const"] = proto_const
    spec.loader.exec_module(module)

    should_remove = module.should_remove_button_registry_entry
    domain = proto_const.DOMAIN
    assert should_remove(domain="button", platform=domain) is True
    assert should_remove(domain="remote", platform=domain) is False
    assert should_remove(domain="button", platform="other") is False
    assert should_remove(domain="select", platform=domain, unique_id="x_my_apps") is True
    assert should_remove(domain="select", platform=domain, unique_id="other") is False


def test_no_button_platform_and_legacy_cleanup() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "custom_components" / "hisense_e7n"
    init = (root / "__init__.py").read_text(encoding="utf-8")
    button = (root / "button.py").read_text(encoding="utf-8")
    assert "async_remove_legacy_button_entities" in init
    const = (root / "const.py").read_text(encoding="utf-8")
    assert 'PLATFORMS = ("media_player", "remote")' in const
    assert '"button"' not in const.split("PLATFORMS", 1)[1].split("\n", 1)[0]
    assert "async_setup_entry" not in button
    assert "ButtonEntity" not in button
    assert "class " not in button

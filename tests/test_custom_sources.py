"""Custom TV inputs are remoter key macros."""

from __future__ import annotations

import pytest


def test_parse_source_right_ok(proto_custom_sources) -> None:
    sources = proto_custom_sources.parse_custom_sources_text(
        "HDMI1: KEY_SOURCE, KEY_RIGHT, KEY_OK\n"
        "HDMI2: source, right, right, ok\n"
        "# comment\n"
    )
    assert sources == [
        {"name": "HDMI1", "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"]},
        {"name": "HDMI2", "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_RIGHT", "KEY_OK"]},
    ]


def test_parse_accepts_chinese_separators(proto_custom_sources) -> None:
    sources = proto_custom_sources.parse_custom_sources_text(
        "机顶盒：source、right、ok"
    )
    assert sources == [
        {"name": "机顶盒", "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"]},
    ]


def test_serialize_roundtrip(proto_custom_sources) -> None:
    text = "HDMI1: KEY_SOURCE, KEY_RIGHT, KEY_OK"
    sources = proto_custom_sources.parse_custom_sources_text(text)
    assert proto_custom_sources.serialize_custom_sources(sources) == text


def test_normalize_dict_and_list(proto_custom_sources) -> None:
    assert proto_custom_sources.normalize_custom_sources(
        {"AV": "source, down, ok"}
    ) == [{"name": "AV", "keys": ["KEY_SOURCE", "KEY_DOWN", "KEY_OK"]}]
    assert proto_custom_sources.normalize_custom_sources(
        [{"name": "USB", "keys": ["KEY_SOURCE", "KEY_OK"]}]
    ) == [{"name": "USB", "keys": ["KEY_SOURCE", "KEY_OK"]}]


def test_rejects_bad_lines(proto_custom_sources) -> None:
    with pytest.raises(ValueError):
        proto_custom_sources.parse_custom_sources_text("only-name")
    with pytest.raises(ValueError):
        proto_custom_sources.parse_custom_sources_text("A: KEY_OK\nA: KEY_HOME")


def test_slug_is_stable(proto_custom_sources) -> None:
    first = proto_custom_sources.custom_source_slug("HDMI1")
    second = proto_custom_sources.custom_source_slug("HDMI1")
    assert first == second
    assert "hdmi1" in first


def test_format_and_summarize_sequences(proto_custom_sources) -> None:
    assert (
        proto_custom_sources.format_key_sequence(
            ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"]
        )
        == "source → right → ok"
    )
    summary = proto_custom_sources.summarize_custom_sources(
        [
            {"name": "HDMI1", "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"]},
            {"name": "HDMI2", "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_RIGHT", "KEY_OK"]},
        ]
    )
    assert "1. HDMI1: source → right → ok" in summary
    assert "2. HDMI2: source → right → right → ok" in summary
    assert "KEY_SOURCE" in proto_custom_sources.SEQUENCE_BUTTON_KEYS
    assert "KEY_RIGHT" in proto_custom_sources.SEQUENCE_BUTTON_KEYS


def test_move_custom_source_reorders_list(proto_custom_sources) -> None:
    sources = [
        {"name": "HDMI1", "keys": ["KEY_SOURCE", "KEY_OK"]},
        {"name": "HDMI2", "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"]},
        {"name": "AV", "keys": ["KEY_SOURCE", "KEY_DOWN", "KEY_OK"]},
    ]
    down = proto_custom_sources.move_custom_source(
        sources, "HDMI1", direction="move_down"
    )
    assert [item["name"] for item in down] == ["HDMI2", "HDMI1", "AV"]
    up = proto_custom_sources.move_custom_source(down, "AV", direction="move_up")
    assert [item["name"] for item in up] == ["HDMI2", "AV", "HDMI1"]
    same = proto_custom_sources.move_custom_source(
        up, "HDMI2", direction="move_up"
    )
    assert [item["name"] for item in same] == ["HDMI2", "AV", "HDMI1"]
    jump = proto_custom_sources.move_custom_source(
        sources, "HDMI1", direction="move_down", steps=2
    )
    assert [item["name"] for item in jump] == ["HDMI2", "AV", "HDMI1"]
    clamped = proto_custom_sources.move_custom_source(
        sources, "AV", direction="move_up", steps=99
    )
    assert [item["name"] for item in clamped] == ["AV", "HDMI1", "HDMI2"]


def test_classify_source_action_keys_and_ha_buttons(proto_custom_sources) -> None:
    classify = proto_custom_sources.classify_source_action
    assert classify("source") == ("key", "KEY_SOURCE")
    assert classify("KEY_RIGHT") == ("key", "KEY_RIGHT")
    assert classify("ok") == ("key", "KEY_OK")
    assert classify("button.living_hdmi") == ("button", "button.living_hdmi")
    assert classify("switch.not_a_button") is None
    assert classify("key:source") == ("key", "KEY_SOURCE")
    assert classify("key:nope") is None
    payload = proto_custom_sources.source_payload(
        name="HDMI1",
        hidden=False,
        buttons=["source", "right", "right", "ok"],
        interval=0.1,
    )
    assert payload["keys"] == ["KEY_SOURCE", "KEY_RIGHT", "KEY_RIGHT", "KEY_OK"]
    assert payload["buttons"] == ["source", "right", "right", "ok"]
    collapsed = proto_custom_sources.collapse_source_actions(payload["buttons"])
    assert collapsed == [("source", 1), ("right", 2), ("ok", 1)]
    assert proto_custom_sources.expand_source_steps(collapsed) == [
        "source",
        "right",
        "right",
        "ok",
    ]


def test_hidden_sources_stay_callable_but_leave_source_list(proto_custom_sources) -> None:
    sources = proto_custom_sources.normalize_custom_sources(
        [
            {"name": "HDMI1", "keys": ["KEY_SOURCE", "KEY_OK"]},
            {
                "name": "HDMI2",
                "keys": ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"],
                "hidden": True,
                "interval": 0.2,
            },
        ]
    )
    assert proto_custom_sources.visible_source_names(sources) == ["HDMI1"]
    copied = proto_custom_sources.copy_sources(sources)
    assert copied[1]["hidden"] is True
    assert copied[1]["interval"] == 0.2
    found = proto_custom_sources.find_custom_source(sources, "hdmi2")
    assert found is not None and found["name"] == "HDMI2"
    assert proto_custom_sources.source_key_delay(found, 0.1) == 0.2
    assert proto_custom_sources.source_key_delay(sources[0], 0.1) == 0.1


def test_default_key_delay_is_snappier(proto_const) -> None:
    assert proto_const.DEFAULT_SOURCE_KEY_DELAY == 0.1
    assert 0.5 in proto_const.LEGACY_SOURCE_KEY_DELAYS
    assert 0.25 in proto_const.LEGACY_SOURCE_KEY_DELAYS


def test_run_key_sequence_pauses_between_keys(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._control_warmup = False
    opened: list[str] = []
    sent: list[str] = []
    waits: list[float] = []

    def fake_open(**kwargs) -> bool:
        opened.append("open")
        return True

    def fake_send(key: str) -> None:
        sent.append(key)

    def fake_pause(seconds: float) -> None:
        waits.append(seconds)

    client.open_source = fake_open  # type: ignore[method-assign]
    client.send_key = fake_send  # type: ignore[method-assign]
    client.run_key_sequence(
        ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"],
        delay=0.4,
        pause=fake_pause,
    )
    assert opened == ["open"]
    assert sent == ["KEY_RIGHT", "KEY_OK"]
    assert waits == [0.4, 0.4]


def test_key_source_uses_open_source(proto_client) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    opened: list[str] = []

    def fake_open(**kwargs) -> bool:
        opened.append("open")
        return True

    client.open_source = fake_open  # type: ignore[method-assign]
    client.send_key("KEY_SOURCE")
    client.send_key("source")
    assert opened == ["open", "open"]


def test_cold_start_source_sequence_waits_and_retries(proto_client, proto_const) -> None:
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    assert client._control_warmup is True
    ready_calls = 0
    open_kwargs: list[dict] = []
    sent: list[str] = []
    waits: list[float] = []

    def fake_wait(**kwargs) -> bool:
        nonlocal ready_calls
        ready_calls += 1
        return True

    def fake_open(**kwargs) -> bool:
        open_kwargs.append(kwargs)
        return True

    def fake_send(key: str) -> None:
        sent.append(key)

    def fake_pause(seconds: float) -> None:
        waits.append(seconds)

    client._wait_for_remoter = fake_wait  # type: ignore[method-assign]
    client.open_source = fake_open  # type: ignore[method-assign]
    client.send_key = fake_send  # type: ignore[method-assign]
    client.run_key_sequence(
        ["KEY_SOURCE", "KEY_RIGHT", "KEY_OK"],
        delay=0.4,
        pause=fake_pause,
    )
    assert ready_calls == 1
    assert open_kwargs[0]["retries"] == proto_const.SOURCE_OPEN_RETRIES
    assert sent == ["KEY_RIGHT", "KEY_OK"]
    assert waits[0] == proto_const.SOURCE_MENU_SETTLE
    assert waits[1:] == [0.4, 0.4]
    assert client._control_warmup is False


def test_open_source_retries_local_before_mqtt(proto_client) -> None:
    import sys

    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    attempts = {"voice": 0, "key": 0, "mqtt": 0}
    pauses: list[float] = []
    mod = sys.modules[client.__class__.__module__]

    def fake_voice(host, text, **kwargs):
        attempts["voice"] += 1
        return None

    def fake_key(host, key, **kwargs):
        attempts["key"] += 1
        if attempts["key"] < 3:
            return None
        return 200

    def fake_publish(*args, **kwargs):
        attempts["mqtt"] += 1

    orig_voice = mod.push_voice
    orig_key = mod.send_local_key
    mod.push_voice = fake_voice
    mod.send_local_key = fake_key
    client._publish_action = fake_publish  # type: ignore[method-assign]
    try:
        ok = client.open_source(retries=4, retry_delay=0.1, pause=pauses.append)
    finally:
        mod.push_voice = orig_voice
        mod.send_local_key = orig_key
    assert ok is True
    assert attempts["voice"] == 3
    assert attempts["key"] == 3
    assert attempts["mqtt"] == 0
    assert pauses == [0.1, 0.1]

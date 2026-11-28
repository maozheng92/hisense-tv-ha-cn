"""Installed-app list matches 爱家 我的应用, without Home Assistant."""

from __future__ import annotations

from conftest import load_proto


def test_installed_apps_skip_store_and_removed_rows() -> None:
    apps = load_proto("apps")
    parsed = apps.normalize_apps(
        {
            "app_list": [
                {
                    "appname": "云视听极光",
                    "appid": "com.ktcp.video",
                    "url": "tenvideo2",
                    "urlType": 37,
                    "storeType": 0,
                },
                {"name": "热门推荐", "url": "ad", "category": "recommend"},
                {"name": "已卸载", "url": "gone", "isuninstalled": 1},
            ]
        }
    )
    assert parsed == [
        {
            "name": "云视听极光",
            "url": "tenvideo2",
            "app_id": "com.ktcp.video",
            "url_type": 37,
            "store_type": 0,
        }
    ]


def test_local_package_keeps_size_and_title() -> None:
    apps = load_proto("apps")
    parsed = apps.normalize_apps(
        [
            {
                "name": "健身镜",
                "packageName": "com.hisense.fitness",
                "isLocalApp": 1,
                "appSize": 51.45 * 1024 * 1024,
            }
        ]
    )
    assert parsed[0]["package"] == "com.hisense.fitness"
    assert parsed[0]["url"] == "com.hisense.fitness"
    assert parsed[0]["url_type"] == 0
    assert parsed[0]["size"] == "51.45M"
    assert apps.format_app_title(parsed[0]) == "健身镜 (51.45M)"


def test_resolve_app_matches_package_name_and_substring() -> None:
    apps = load_proto("apps")
    parsed = apps.normalize_apps(
        [
            {
                "name": "云视听极光",
                "packageName": "com.ktcp.video",
                "url": "tenvideo2",
            },
            {
                "name": "健身镜",
                "packageName": "com.hisense.fitness",
                "isLocalApp": 1,
            },
        ]
    )
    assert apps.resolve_app(parsed, "com.ktcp.video")["name"] == "云视听极光"
    assert apps.resolve_app(parsed, "云视听极光")["package"] == "com.ktcp.video"
    assert apps.resolve_app(parsed, "tenvideo2")["name"] == "云视听极光"
    assert apps.resolve_app(parsed, "fitness")["package"] == "com.hisense.fitness"
    assert apps.resolve_app(parsed, "com") is None
    assert apps.app_media_id(parsed[0]) == "com.ktcp.video"


def test_default_launch_apps_are_local_packages() -> None:
    apps = load_proto("apps")
    catalog = apps.default_launch_apps()
    assert [item["name"] for item in catalog][:5] == [
        "海信爱家",
        "家庭私有云",
        "健身镜",
        "聚连会议",
        "天气",
    ]
    assert catalog[0]["package"] == "com.jamdeo.android.jamdeosmarthome"
    assert catalog[0]["url_type"] == 0
    assert "云视听极光" not in [item["name"] for item in catalog]
    assert apps.resolve_app(catalog, "com.android.wechathci")["name"] == "微信电视"
    assert apps.resolve_app(catalog, "com.jamdeo.tv.mediacenter")["name"] == "媒体中心"
    named = apps.attach_known_packages([{"name": "玩机宝典", "url": "玩机宝典"}])
    assert named[0]["package"] == "com.hisense.electronictutorial"
    assert named[0]["url_type"] == 0


def test_name_list_and_client_apply(proto_client) -> None:
    apps = load_proto("apps")
    # mqttAppNameList is the 爱家 cloud-column filter field, not VIDAA MQTT.
    assert [item["name"] for item in apps.normalize_apps({"mqttAppNameList": ["聚好看", "聚好看", ""]})] == [
        "聚好看"
    ]
    client = proto_client.HisenseTvClient("127.0.0.1", uuid="aa:bb:cc:dd:ee:ff")
    client._apply_apps([{"appName": "银河奇异果", "url": "iqiyi"}])
    client._apply_apps({"list": []})
    assert client.state.apps[0]["name"] == "银河奇异果"
    assert client.state.apps[0]["url"] == "iqiyi"


def test_my_apps_tab_skips_store_rows() -> None:
    apps = load_proto("apps")
    parsed = apps.normalize_apps(
        {
            "appTypeList": [
                {
                    "typeName": "我的应用",
                    "appList": [
                        {
                            "name": "云视听极光",
                            "packageName": "com.ktcp.video",
                            "isLocalApp": 1,
                        }
                    ],
                },
                {
                    "typeName": "热门",
                    "appList": [{"name": "广告", "url": "ad"}],
                },
            ]
        }
    )
    assert [item["name"] for item in parsed] == ["云视听极光"]
    assert parsed[0]["package"] == "com.ktcp.video"


def test_launch_payload_matches_vidaa_local_and_store() -> None:
    apps = load_proto("apps")
    local = apps.build_launch_payload(
        {
            "name": "云视听极光",
            "url": "com.ktcp.video",
            "app_id": "com.ktcp.video",
            "url_type": 0,
            "store_type": 0,
            "package": "com.ktcp.video",
        },
        is_local=True,
    )
    assert local["isLocalApp"] == 1
    assert local["urlType"] == 0
    assert local["url"] == "com.ktcp.video"
    assert local["has_detail_page"] == 0
    store = apps.build_launch_payload(name="Netflix", url="netflix", url_type=37)
    assert store == {
        "appIcon": "",
        "appId": "netflix",
        "has_detail_page": 0,
        "isLocalApp": 0,
        "name": "Netflix",
        "storeType": 0,
        "type": 0,
        "url": "netflix",
        "urlType": 37,
    }
    named = apps.normalize_apps(
        [{"name": "健身镜", "packageName": "com.hisense.fitness", "isLocalApp": 1}]
    )
    assert apps.app_choice_names(named) == ["健身镜"]
    assert apps.current_app_option(named, "com.hisense.fitness") == "健身镜"
    assert apps.current_app_option(named, "missing") is None


def test_cloud_column_tiles_and_jump_param() -> None:
    apps = load_proto("apps")
    parsed = apps.normalize_apps(
        {
            "columnName": "我的应用",
            "tiles": [
                {
                    "showName": "云视听极光",
                    "startupType": 4,
                    "jumpParam": {"packageName": "com.ktcp.video"},
                    "iconUrl": "https://example/icon.png",
                },
                {
                    "name": "广告",
                    "category": "recommend",
                    "url": "ad",
                },
            ],
        }
    )
    assert [item["name"] for item in parsed] == ["云视听极光"]
    assert parsed[0]["package"] == "com.ktcp.video"
    assert parsed[0]["url_type"] == 0
    assert parsed[0]["icon"] == "https://example/icon.png"

"""Constants for the Hisense E7N Pro integration."""

from __future__ import annotations

DOMAIN = "hisense_e7n"
DEFAULT_NAME = "Hisense E7N Pro"
DEFAULT_PORT = 36669
DEFAULT_AUTH_MODE = "auto"

CONF_AUTH_MODE = "auth_mode"
CONF_CLIENT_UUID = "client_uuid"
CONF_CLIENT_CERT = "client_cert"
CONF_CLIENT_KEY = "client_key"
CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_CONTROL_USERNAME = "control_username"
CONF_POWER_ON_BUTTON = "power_on_button"
CONF_POWER_ON_MODE = "power_on_mode"
CONF_POWER_ON_REMOTE = "power_on_remote"
CONF_POWER_ON_COMMAND = "power_on_command"
CONF_POWER_ON_DEVICE = "power_on_device"
CONF_VOLUME_UP_BUTTON = "volume_up_button"
CONF_VOLUME_DOWN_BUTTON = "volume_down_button"
# EntitySelector labels fall back to the schema key. Keep storage keys
# English; show Chinese on the form so HA does not print volume_up_button.
FORM_VOLUME_UP_BUTTON = "音量加按钮"
FORM_VOLUME_DOWN_BUTTON = "音量减按钮"
POWER_ON_MODE_BUTTON = "button"
POWER_ON_MODE_REMOTE = "remote"
POWER_ON_MODE_WOL = "wol"
DEFAULT_POWER_ON_COMMAND = "power"
CONF_USE_SSL = "use_ssl"
CONF_BLE_ADDRESS = "ble_address"
CONF_CUSTOM_SOURCES = "custom_sources"
CONF_CUSTOM_SOURCES_TEXT = "custom_sources_text"
CONF_SOURCE_KEY_DELAY = "source_key_delay"
CONF_SOURCE_ORDER = "source_order"
CONF_SOURCE_NAME = "name"
# Between-key gap in custom-source macros. Cold-start SOURCE wait/retry is separate.
DEFAULT_SOURCE_KEY_DELAY = 0.1
# Prior shipped defaults; migrate installs that never customized the gap.
LEGACY_SOURCE_KEY_DELAYS = (0.5, 0.25)
# After cold power-on, MQTT often comes up before the LAN remoter accepts
# 信号源. Retry the local open a few times instead of raising the global gap.
SOURCE_OPEN_RETRIES = 4
SOURCE_OPEN_RETRY_DELAY = 0.75
SOURCE_MENU_SETTLE = 0.75
# Wait for TCP 7778/7779 after power-on / MQTT reconnect before the first key.
REMOTER_READY_TIMEOUT = 8.0
REMOTER_READY_POLL = 0.4
# Probe the non-sticky remoter port quickly so a dead 7778 does not stall 7779.
REMOTER_PROBE_TIMEOUT = 0.35
# volumechange.volume_type from VIDAA (CaptainSolidus / RemoteNOW):
# 0 = TV speakers, 1 = HDMI ARC/eARC (CEC), 2 = mute flag (sehaas) or BT on some sets.
VOLUME_TYPE_TV = 0
VOLUME_TYPE_ARC = 1
VOLUME_TYPE_MUTE = 2
# TV-speaker KEY_VOLUME* pacing (not a substitute for ARC CEC volume).
VOLUME_KEY_PAUSE = 0.05
VOLUME_KEY_IDLE_WARMUP = 1.5
# eARC CEC: one LAN KEY_VOLUME per press (MQTT sendkey does not move volume).
# Dual MQTT+LAN (15:51) flooded CEC. 1.22.9 LAN retry jumped +2 — reverted.
VOLUME_CEC_GAP = 0.9
# When the current level is unknown, drive to 0 then climb (extra downs are no-ops).
VOLUME_UNKNOWN_FLOOR_STEPS = 100
# LAN remoter KEY (volume +/-) can drop MQTT 36669 for a moment. Do not flip
# media_player on→off→on until the broker stays down this long.
MQTT_DISCONNECT_GRACE = 3.0
# This E7N never publishes volumechange. Catch 爱家 / OSD via gettvstate
# + getvolume while ON. 3s is short enough for mute OSD, not a CEC flood.
VOLUME_POLL_SECONDS = 3.0
CONF_CUSTOM_SOURCE_NAME = "custom_source_name"
CONF_SOURCE_NAME_ACTION = "source_name_action"
CONF_SEQUENCE_BUTTON = "sequence_button"
CONF_SEQUENCE_ACTION = "sequence_action"
CONF_MANAGE_ACTION = "manage_action"
CONF_MANAGE_SOURCE = "manage_source"
CONF_MOVE_STEPS = "move_steps"
SEQUENCE_ACTION_ADD = "add"
SEQUENCE_ACTION_UNDO = "undo"
SEQUENCE_ACTION_CLEAR = "clear"
SEQUENCE_ACTION_DONE = "done"
SOURCE_NAME_ACTION_NEXT = "next"
SOURCE_NAME_ACTION_BACK = "back"
MANAGE_ACTION_ADD = "add"
MANAGE_ACTION_EDIT = "edit"
MANAGE_ACTION_REMOVE = "remove"
MANAGE_ACTION_MOVE_UP = "move_up"
MANAGE_ACTION_MOVE_DOWN = "move_down"
MANAGE_ACTION_FINISH = "finish"
DEFAULT_MOVE_STEPS = 1
MAX_MOVE_STEPS = 20

AUTH_MODE_AUTO = "auto"
AUTH_MODE_DYNAMIC = "dynamic"
AUTH_MODE_STATIC = "static"
AUTH_MODES = [AUTH_MODE_AUTO, AUTH_MODE_DYNAMIC, AUTH_MODE_STATIC]

# VIDAA / RemoteNOW broker on the TV (same KEY_* vocabulary as 海信爱家).
MQTT_KEEPALIVE = 30
MQTT_PROTOCOL_NAME = "VIDAA MQTT"
MQTT_CONNECT_TIMEOUT = 8.0
MQTT_CONNACK_WAIT = 8.0

# Internal connect results (not MQTT CONNACK codes).
RC_TCP_FAILED = 98
RC_TLS_FAILED = 99

STATIC_MQTT_USERNAME = "hisenseservice"
STATIC_MQTT_PASSWORD = "multimqttservice"
# Same client id sehaas/ha_hisense_tv publishes with. The TV authorizes
# remote keys for this name, not for an 爱家 dynamic client id.
REMOTE_CLIENT_ID = "HomeAssistant"

DATA_CLIENT = "client"
DATA_COORDINATOR = "coordinator"
# TCL has media_player + remote only. Remoter keys are not button entities.
PLATFORMS = ("media_player", "remote")
ATTR_HIDDEN = "hidden"

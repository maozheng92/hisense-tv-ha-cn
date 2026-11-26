# 海信爱家 / E7N Pro

仓库内 APK：`com.hisense.ms.fly2tv.apk`（海信爱家 7.0.8.12，Git LFS）。

## E7N Pro 怎么控

给 Home Assistant 用的按键通道是电视 **VIDAA 机内 MQTT（TCP 36669 / TLS）**，键值和爱家 App 的 `KEY_POWER`、`KEY_OK` 相同。不要填蓝牙 MAC，也不要走爱家云 token。

完整协议对照：[docs/tv-control-methods.md](docs/tv-control-methods.md)  
E7N Pro 结论与安装：[docs/e7n-pro-homeassistant.md](docs/e7n-pro-homeassistant.md)

## Home Assistant 集成

目录：`custom_components/hisense_e7n`

拷到 HA 的 `config/custom_components/` 后重启，在「添加集成」里搜 **Hisense E7N Pro**。选项页脚脚本在 `frontend/`，启动时自动安装到 `config/www/hisense_e7n/`（`/local/hisense_e7n/`）。集成目录里**没有** `www/`（避免 Windows 占用无法更新）。若旧版 `custom_components/hisense_e7n/www` 提示占用，先停止 Home Assistant 再删除该文件夹后更新。升级后请**硬刷新 HA 前端**（Ctrl+Shift+R）。配对时电视需已开机，填写 IP 即可，**不用蓝牙地址**。爱家遥控页上的键通过 `remote` 实体发送，**不会**建成 `button` 实体。连不上 36669 时，集成会自动用爱家客户端证书、降低 TLS 安全级别，并在必要时回退明文 MQTT。若电视屏幕出现 4 位数字，调用 `hisense_e7n.submit_code`。爱家无法唤醒关机的电视。每台电视在配置里单独选择开机方式：**按钮 / 开关 / 脚本**，或一只红外遥控（`remote.send_command`），或 Wi-Fi MAC 网络唤醒。播放器支持自定义输入源、媒体浏览器里的已安装应用，以及上一台 / 下一台。音量只有 +/-，没有滑块。VIDAA MQTT `volumechange` 会报静音，接到 `is_volume_muted`。

```text
custom_components/hisense_e7n/   # 本仓库
        ↓ 复制
<ha-config>/custom_components/hisense_e7n/
```

## `remote.send_command`

爱家遥控页上的键**不会**建成 `button` 实体。一律发到本集成的 `remote` 实体（Universal Remote Card 可用；实体属性 `commands` 是爱家遥控页那一组）。

```yaml
action: remote.send_command
target:
  entity_id: remote.hisense_e7n_pro
data:
  command: KEY_HOME
  # 可选：num_repeats、delay_secs（默认约 0.12 秒）
```

`command` 可以是单个字符串，或按输入源宏那样的**按键列表**（每项一发，中间隔 `delay_secs`）：

```yaml
action: remote.send_command
target:
  entity_id: remote.hisense_e7n_pro
data:
  command:
    - KEY_SOURCE
    - KEY_RIGHT
    - KEY_OK
  delay_secs: 0.1
```

线名（`KEY_HOME`）和别名（`home`、`ok`、`mute`）都可以。未收录的 `KEY_*` 会原样发到电视（HTTP 7778/7779，不行再 MQTT `sendkey`）。`hisense_e7n.send_key` 接受同一套名字。

### 爱家遥控页

实体 `commands` 属性按爱家 `control_page_tv` 顺序列出这些：

| 命令 | 别名 | 作用 |
|---|---|---|
| `KEY_POWER` | `power` `poweroff` `power_off` | 电源。电视**离线**时改走这台电视配置的开机方式（按钮 / 红外 / WOL），不瞎发 MQTT |
| `KEY_VOLUMEDOWN` | `voldown` `volume_down` `volumedown` | 音量 −。优先选项里的音量减按钮，否则本机 HTTP `KEY_VOLUME*`（eARC CEC） |
| `KEY_MUTE` | `mute` | 静音切换 |
| `KEY_VOLUMEUP` | `volup` `volume_up` `volumeup` | 音量 +。优先选项里的音量加按钮，否则本机 HTTP |
| `screenshot` | `capture` `capturescreen` `截屏` | 截当前画面，写入媒体浏览器 **Image upload**（同一台电视再截会换掉上一张） |
| `KEY_SOURCE` | `source` | 信号源。先本机语音「信号源」，不行再 HTTP `KEY_SOURCE`，再 MQTT |
| `smart_image` | `ai` | AI 识图。本机语音「识图」，不行再 `functionSmartImage` |
| `KEY_CONTROL_CENTER` | `settings` `control_center` `controlcenter` | 控制中心 / 设置 |
| `KEY_UP` | `up` | 上 |
| `KEY_LEFT` | `left` | 左 |
| `KEY_OK` | `ok` `enter` `select` | 确认 |
| `KEY_RIGHT` | `right` | 右 |
| `KEY_DOWN` | `down` | 下 |
| `KEY_RETURNS` | `back` `return` `returns` | 返回（导航。**不是**快退 `KEY_BACK`） |
| `KEY_HOME` | `home` | 主页 |
| `KEY_MENU` | `menu` | 菜单 |

### 其它 VIDAA / 爱家 `KEY_*`

| 命令 | 别名 | 作用 |
|---|---|---|
| `KEY_MULTITASK` | `multitask` | 多任务 / 最近任务 |
| `KEY_BRIGHTUP` | `brightup` | 亮度 + |
| `KEY_BRIGHTDOWN` | `brightdown` | 亮度 − |
| `KEY_JUBAO` | `jubao` | 爱家「聚宝」快捷 |
| `KEY_PLAY` | `play` | 播放 |
| `KEY_PAUSE` | `pause` | 暂停 |
| `KEY_STOP` | `stop` | 停止 |
| `KEY_FORWARDS` | `forward` `fastforward` | 快进 |
| `KEY_BACK` | `rewind` | 快退（媒体。导航返回用 `KEY_RETURNS`） |
| `KEY_CHANNELUP` | `chup` | 频道 +（`media_player` 上一台也走这个） |
| `KEY_CHANNELDOWN` | `chdown` | 频道 −（下一台同理） |
| `KEY_EXIT` | `exit` | 退出 |
| `KEY_NETFLIX` | `netflix` | Netflix 快捷键（固件支持时） |
| `KEY_YOUTUBE` | `youtube` | YouTube 快捷键（固件支持时） |

### 输入源宏

自定义输入源**名称**（例如 `HDMI 1`）**不是** `remote.send_command` 的命令。名称只给 `media_player.select_source`：集成按选项里保存的序列发键（可混用本集成按键和 HA `button.*`）。

用遥控复现同一宏：把序列里的 `KEY_*` 按顺序列在 `command` 里（见上面的 YAML）。选项「本集成按键」可选：

| 短名（选项 / 序列 JSON） | 发出的键 |
|---|---|
| `source` | `KEY_SOURCE`（语音「信号源」→ 本地键 → MQTT，与遥控页相同） |
| `up` `down` `left` `right` | `KEY_UP` / `KEY_DOWN` / `KEY_LEFT` / `KEY_RIGHT` |
| `ok` | `KEY_OK` |
| `back` | `KEY_RETURNS` |
| `home` | `KEY_HOME` |
| `menu` | `KEY_MENU` |
| `settings` | `KEY_CONTROL_CENTER` |
| `power` | `KEY_POWER` |
| `volume_up` `volume_down` | `KEY_VOLUMEUP` / `KEY_VOLUMEDOWN` |
| `mute` | `KEY_MUTE` |

序列里也可以写线名 `KEY_SOURCE`、`KEY_RIGHT`、`KEY_OK`。默认按键间隔 **0.1** 秒（每个输入源可覆盖）。开机后第一次切源会先等本机遥控口（7778/7779）就绪。

协议自测（不需要 Home Assistant）：

```bash
python3 -m pytest tests
```

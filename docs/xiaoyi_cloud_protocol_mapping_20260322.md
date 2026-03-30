# 小智原版云通信梳理与本地替换映射（2026-03-22）

## 1. 当前结论（基于你串口日志）
- 设备已恢复到原版可工作状态（Wi-Fi、激活、唤醒词链路正常）。
- 当前仍在连接官方云：
  - `https://api.tenclass.net/xiaozhi/ota/`
  - `mqtt.xiaozhi.me`
- “一直聆听中、不播报”在你当前改造分支里与 `host_local_only_mode` 有直接关系（会拦截服务器返回音频/tts流程）。

## 2. 启动阶段 HTTP 流程（OTA/激活）
代码位置：
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\ota.cc`
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\Kconfig.projbuild`

关键行为：
1. URL 来源：
- 优先 `NVS wifi.ota_url`
- 否则 `CONFIG_OTA_URL`（默认是 `https://api.tenclass.net/xiaozhi/ota/`）

2. 请求头：
- `Activation-Version`
- `Device-Id`（MAC）
- `Client-Id`（board uuid）
- `User-Agent`
- `Accept-Language`
- `Content-Type: application/json`
- 有序列号时会带 `Serial-Number`

3. 响应 JSON 关键字段（设备会写入 NVS）：
- `activation`（激活码/挑战/超时）
- `mqtt`（写入 namespace: `mqtt`）
- `websocket`（写入 namespace: `websocket`）
- `server_time`
- `firmware`

## 3. 协议选择逻辑（已加“可控替换入口”）
代码位置：
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\application.cc`

当前顺序：
1. 若 `NVS cloud.protocol` 被设置为 `mqtt`，强制 MQTT
2. 若 `NVS cloud.protocol` 被设置为 `websocket`，强制 WebSocket
3. 否则走原逻辑：优先 OTA 下发的 `mqtt`，再 `websocket`，最后 fallback MQTT

## 4. MQTT 协议要点
代码位置：
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\protocols\mqtt_protocol.cc`
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\protocols\protocol.cc`

NVS 读取键（namespace=`mqtt`）：
- `endpoint`
- `client_id`
- `username`
- `password`
- `keepalive`
- `publish_topic`

连接：
- `endpoint` 形如 `host:port`，无端口默认 8883
- 8883 走 TLS

文字控制面（JSON）：
- 设备发 `hello` 请求音频通道
- 设备发 `listen start/stop/detect`
- 设备发 `abort`
- 设备发 `goodbye`
- 设备发 `mcp`

`hello`（设备上行）核心结构：
- `type=hello`
- `version=3`
- `transport=udp`
- `audio_params: format=opus, sample_rate=16000, channels=1, frame_duration`

`hello`（服务端下行）设备期望字段：
- `type=hello`
- `transport=udp`
- `session_id`
- `audio_params.sample_rate/frame_duration`
- `udp.server`
- `udp.port`
- `udp.key`（hex）
- `udp.nonce`（hex）

音频数据面：
- MQTT 只走控制 JSON
- Opus 音频走 UDP，设备端按 AES-CTR 加解密

## 5. WebSocket 协议要点
代码位置：
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\protocols\websocket_protocol.cc`

NVS 读取键（namespace=`websocket`）：
- `url`
- `token`
- `version`

握手请求头：
- `Authorization`（token 自动补 `Bearer `）
- `Protocol-Version`
- `Device-Id`
- `Client-Id`

设备上行 `hello`：
- `type=hello`
- `transport=websocket`
- `audio_params` 同上（opus/16k/mono）

服务端返回 `hello`：
- `transport=websocket`
- `session_id`
- `audio_params.sample_rate/frame_duration`

二进制音频帧：
- version 2/3 有不同头格式（`BinaryProtocol2/3`）

## 6. 设备接收消息类型（通用）
代码位置：
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\application.cc`

支持下行 `type`：
- `tts`（start/stop/sentence_start）
- `stt`
- `llm`
- `mcp`
- `system`（如 reboot）
- `alert`

## 7. 本地 AI Agent 替换建议（最小改造）
推荐两条可落地路径：

1. WebSocket 最小闭环（实现快）
- 设备侧强制 `cloud.protocol=websocket`
- 本地服务先实现 `hello -> stt/tts` 基础消息
- 先返回固定文本+固定音频，验证端到端

2. MQTT+UDP 兼容层（和原版更像）
- 本地服务兼容 `hello/goodbye/listen/abort/mcp`
- 实现 UDP 音频参数下发（key/nonce/server/port）
- 复杂度高于 WS 方案

## 8. 新增串口控制命令（已实现）
代码位置：
- `D:\codex\xiaoyi_build\xiaozhi-esp32-main\main\application.cc`

状态/诊断：
- `XIAOYI_CMD:CLOUD_CONFIG`
- `XIAOYI_CMD:RELOAD_PROTOCOL`
- `XIAOYI_CMD:REBOOT`

协议选择：
- `XIAOYI_CMD:SET_PROTOCOL:MQTT`
- `XIAOYI_CMD:SET_PROTOCOL:WS`
- `XIAOYI_CMD:SET_PROTOCOL:AUTO`

OTA URL：
- `XIAOYI_CMD:SET_OTA_URL:http://<你的服务器>/xiaozhi/ota/`
- `XIAOYI_CMD:CLEAR_OTA_URL`

MQTT：
- `XIAOYI_CMD:SET_MQTT_ENDPOINT:<host:port>`
- `XIAOYI_CMD:SET_MQTT_PUB_TOPIC:<topic>`
- `XIAOYI_CMD:SET_MQTT_CLIENT_ID:<id>`
- `XIAOYI_CMD:SET_MQTT_USERNAME:<user>`
- `XIAOYI_CMD:SET_MQTT_PASSWORD:<password>`
- `XIAOYI_CMD:CLEAR_MQTT_CONFIG`

WebSocket：
- `XIAOYI_CMD:SET_WS_URL:ws://<host>:<port>/<path>` 或 `wss://...`
- `XIAOYI_CMD:SET_WS_TOKEN:<token>`
- `XIAOYI_CMD:SET_WS_VERSION:3`
- `XIAOYI_CMD:CLEAR_WS_CONFIG`

## 9. 不再连官方云的验收标准
串口里需要同时满足：
1. 不再出现 `api.tenclass.net` / `mqtt.xiaozhi.me`
2. `XIAOYI_CMD:CLOUD_CONFIG` 打印的是你本地地址
3. 唤醒后能看到本地服务返回 `stt/tts` 流程
4. 扬声器有播报且状态能从 listening -> speaking -> idle/listening 正常流转

## 10. 当前代码修复点（这次已改）
1. `host_local_only_mode_` 默认改为 `false`（避免默认吞云端回包）
2. 增加云端配置串口命令与协议热重载
3. 增加 `cloud.protocol` 强制协议选择入口，避免被 OTA 路径锁死

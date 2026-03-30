# 小医事件固件改造说明（COM5）

## 1. 这次已改内容

- 在 ESP32 固件增加统一事件输出：
  - `XIAOYI_EVT:WAKE:<唤醒词>`
  - `XIAOYI_EVT:STT:<识别文本>`
  - `XIAOYI_EVT:TTS:<播报句子>`
  - `XIAOYI_EVT:STATE:<状态>`
- 上位机与串口桥接均已支持优先解析 `XIAOYI_EVT`。
- 兼容旧日志格式（`Wake word detected`、`>>`、`<<`）。

## 2. 固件源码改动位置

- `D:\Desktop\xiaozhi\小智源码\xiaozhi-esp32-main_unzip\xiaozhi-esp32-main\main\application.cc`

## 3. 上位机改动位置

- `D:\Desktop\ai agent 护理精细化部署\scripts\xiaozhi_host_app.py`
- `D:\Desktop\ai agent 护理精细化部署\scripts\xiaozhi_serial_agent_bridge.py`

## 4. 刷写前注意（保护板子）

1. 先关闭所有占用串口的软件（串口助手、旧桥接脚本、旧上位机、烧录工具）。
2. 设备管理器确认端口是 `USB-Enhanced-SERIAL CH343 (COM5)`。
3. 仅在确认电源稳定时刷写。

## 5. 编译与烧录（需 ESP-IDF）

在 ESP-IDF 终端中执行：

```powershell
cd "D:\Desktop\xiaozhi\小智源码\xiaozhi-esp32-main_unzip\xiaozhi-esp32-main"
idf.py set-target esp32s3
idf.py build
idf.py -p COM5 flash monitor
```

如果你的板子不是 `esp32s3`，请把 `set-target` 改成实际芯片型号。

## 6. 验收标准

在串口监视器或上位机日志里看到以下任意行即通过：

- `XIAOYI_EVT:WAKE:...`
- `XIAOYI_EVT:STT:...`
- `XIAOYI_EVT:TTS:...`
- `XIAOYI_EVT:STATE:listening`

## 7. 常见问题

- 仍出现“小智云端聊天”内容：
  - 说明设备还在走官方云端协议。先确认是否已刷入新固件并重启。
- 显示 `PermissionError(13)`：
  - COM5 被其他程序占用，关闭后重试。
- API 网关不通：
  - 先启动后端：`D:\Desktop\ai agent 护理精细化部署\scripts\start_backend_core.ps1`。

# 小医改造：教程源码结论与落地步骤

本文档基于以下目录逐项核对：

- `D:\Desktop\《PCB版你好！小智》教程工具大全`
- `D:\Desktop\《PCB版你好！小智》教程工具大全\你好小智程序源代码（大神们可研究）\xiaozhi-esp32-main\xiaozhi-esp32-main`

## 1. 结论（为什么会一直出现“小智”）

教程包里的主源码是标准小智固件，不是小医改造固件：

- 唤醒词模型默认是 `NIHAOXIAOZHI`  
  见：`sdkconfig.defaults.esp32s3`
  - `CONFIG_USE_WAKENET=y`
  - `CONFIG_SR_WN_WN9_NIHAOXIAOZHI_TTS=y`
- 云端地址默认指向小智服务  
  见：`main/Kconfig.projbuild`
  - `CONFIG_WEBSOCKET_URL` 默认 `wss://api.tenclass.net/xiaozhi/v1/`
  - OTA 默认 `https://api.tenclass.net/xiaozhi/ota/`
- 教程主源码 `main/application.cc` 没有 `XIAOYI_CMD:*` 串口指令通道。

因此：

- 只刷教程原版固件时，设备仍会按“小智”链路工作；
- 你看到“小智”话术、唤醒词不匹配，是预期行为，不是你硬件接错。

## 2. 建议的稳定路线

### 路线A（推荐）
使用项目内小医改造固件 + 小医上位机：

1. 烧录固件：
   - `powershell -ExecutionPolicy Bypass -File D:\Desktop\ai agent 护理精细化部署\scripts\flash_xiaoyi_firmware.ps1 -ComPort COM5 -Baud 460800`
2. 启动后端与上位机：
   - `powershell -ExecutionPolicy Bypass -File D:\Desktop\ai agent 护理精细化部署\scripts\start_xiaoyi_full.ps1 -ComPort COM5 -Baud 115200 -ApiBase "http://127.0.0.1:8000" -DepartmentId dep-card-01 -UserId linmeili`

### 路线B（仅临时）
不刷固件，仅用上位机“持续监听+本地模式保活”接管（稳定性不如路线A）。

## 3. 当前上位机已做的防呆

- 自动清理会抢占串口的进程（bridge / idf monitor / miniterm）。
- 自动强制本地模式与持续监听。
- 串口协议探测：若没有 `serial_pong`，会提示“可能是原版固件，建议刷小医固件”。
- 对外文案统一显示“小医”。

## 4. 常见失败点

- `PermissionError(13, 拒绝访问)`：COM5 被其他程序占用。
- 有连接但无唤醒/转写事件：常见为原版固件或麦克风链路异常（接线、方向、供电）。
- 设备仍播报“小智”风格话术：说明未进入小医本地协议链路或仍是原版固件。

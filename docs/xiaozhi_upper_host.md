# 小智单片机上位机（AI Agent 工作流）说明

## 1. 为什么你会看到“串口有日志，但对话无响应”
- 你 `D:\Desktop\xiaozhi\小智源码\xiaozhi-esp32-main.zip` 里的文档明确了主通信协议是 **WebSocket / MCP**，不是纯串口问答。
- 串口通常会输出运行日志（如 `SystemInfo/free sram`），这些不是用户语音文本。
- 只有当串口输出了可解析的文本（如 `ASR: ...` 或 JSON 中的 `text/stt/transcript`）时，串口桥接才会触发 AI Agent。

## 2. 现在项目里提供的两种接入方式
### A. 串口桥接（已可用）
- 文件：`scripts/xiaozhi_serial_agent_bridge.py`
- 作用：串口文本 -> `/api/ai/chat` -> 回写摘要到串口
- 适合：设备已经能从串口吐出识别文本

### B. 单窗口上位机（本次新增）
- 文件：`scripts/xiaozhi_host_app.py`
- 启动器：`scripts/start_xiaozhi_host_app.ps1`
- 能力：
  - 串口连接/断开
  - 串口文本监听 + AI Agent 请求队列
  - 手动输入任务（不依赖串口语音也可直接触发）
  - 结果回写单片机
  - 会话历史查看与复用
  - 一键拉起后端核心服务

## 3. 推荐启动顺序（最稳）
1. 启动手机端与后端（可选）
   - `scripts/start_all_mobile.ps1`
2. 启动上位机（推荐）
   - `scripts/start_xiaozhi_host_app.ps1`
3. 在上位机里连接 `COM5`，点击“检查网关”，再开始对话

## 4. 一键桥接命令（不打开上位机）
- `scripts/start_xiaozhi_full.ps1 -ComPort COM5 -Baud 115200 -ApiBase http://127.0.0.1:8000 -DepartmentId dep-card-01 -UserId u_nurse_01`

## 5. 下一步（可做成真正“设备语音直控 AI Agent”）
- 让设备直接连本地 WebSocket/MCP 服务（而不是只看串口）
- 在本地协议层接管 STT/LLM/TTS 事件流并映射到你现有 `/api/ai/chat` 工作流
- 这一步需要在设备后台把服务器地址切到本机服务地址


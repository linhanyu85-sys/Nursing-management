# device-gateway (Xiaozhi local WebSocket compatibility service)

This service lets the ESP32 Xiaozhi device connect to your local backend instead of the official cloud.

It provides:
- OTA config endpoint: `/xiaozhi/ota/`
- WebSocket session endpoint: `/xiaozhi/v1/`
- Basic protocol compatibility: `hello/listen/abort/goodbye/mcp`
- Device API endpoints:
  - `POST /api/device/audio/upload`
  - `POST /api/device/query`
  - `GET /api/device/result/{session_id}`
  - `GET /api/device/audio/{session_id}`
  - `POST /api/device/heartbeat`

## Start

```powershell
cd "D:\Desktop\ai agent 护理精细化部署\services\device-gateway"
py -3.13 -m pip install -r requirements.txt
py -3.13 -m uvicorn app.main:app --host 0.0.0.0 --port 8013
```

## Check

```powershell
Invoke-RestMethod http://127.0.0.1:8013/health
Invoke-RestMethod http://127.0.0.1:8013/version
```

## Serial commands on device

Replace `<PC_IP>` with your LAN IP:

```text
XIAOYI_CMD:HOST_LOCAL_ONLY_ON
XIAOYI_CMD:SET_PROTOCOL:WS
XIAOYI_CMD:SET_OTA_URL:http://<PC_IP>:8013/xiaozhi/ota/
XIAOYI_CMD:SET_WS_URL:ws://<PC_IP>:8013/xiaozhi/v1/
XIAOYI_CMD:RELOAD_PROTOCOL
XIAOYI_CMD:CLOUD_CONFIG
XIAOYI_CMD:REBOOT
```

## Debug endpoints

```powershell
Invoke-RestMethod http://127.0.0.1:8013/api/device/sessions
Invoke-RestMethod -Method Post http://127.0.0.1:8013/api/device/mock/reply `
  -ContentType "application/json" `
  -Body '{"stt_text":"ok","tts_text":"bed 23 is stable, please continue observation.","once":true}'
```

## Notes

- `MOCK_MODE=true`: returns mock STT/TTS turn.
- `MOCK_MODE=false`: runs realtime pipeline through ASR -> Agent -> TTS services.

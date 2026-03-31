# 医护 AI 管理后台（Web）

路径固定为：

- `D:\Desktop\houduan guanli`

## 功能定位

这是“总后台管理库”：

1. 先选择账号（如 `linmeili`）
2. 再查看该账号下的患者、草稿、推荐、审计和设备绑定
3. 提供管理系统 ↔ app ↔ 单片机 三端联通监控与一键联调

## 已联通接口（走 api-gateway :8000）

- `GET /health`
- `GET /api/collab/accounts`
- `GET /api/wards/{department_id}/beds`
- `GET /api/document/inbox/{requested_by}`
- `GET /api/handover/inbox/{requested_by}`
- `GET /api/recommendation/inbox/{requested_by}`
- `GET /api/audit/history`
- `GET /api/workflow/history`
- `GET /api/device/binding`
- `POST /api/device/bind`
- `GET /api/device/sessions`
- `POST /api/device/query`
- `GET /api/device/result/{session_id}`
- `GET /api/device/audio/{session_id}`
- `POST /api/device/audio/upload`
- `POST /api/device/heartbeat`

## 主要改造点

- 账号优先视图（管理员先选账号）
- UUID 显示短码（悬停看全量）
- 表格布局重排，减少信息拥挤
- 患者显示优先用“姓名 + 床号”
- 三端联通面板 + 一键联调（创建设备 query 并轮询 result）

## 启动方式

1. 先启动后端（保证 `http://127.0.0.1:8000` 可访问）
2. 再打开此目录 `index.html` 或使用 `start_web.ps1`

## 文件

- `index.html`：页面骨架
- `assets/styles.css`：统一视觉样式
- `assets/app.js`：账号/数据/联通逻辑
- `start_web.ps1`：本地静态服务启动脚本

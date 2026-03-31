# AI护理精细化系统

一个面向临床护理场景的本地部署系统，主要用于床旁语音交互、医嘱执行跟踪、交班记录和护理文书辅助生成。当前版本在 Windows 本地运行，后端基于 Python FastAPI，移动端用 React Native + Expo 开发。

## 当前状态

**已可用：**
- 语音/文字混合输入，调用本地模型（MiniCPM3-4B）或百炼 API 进行意图识别和回答整理
- 患者上下文查询（诊断、医嘱、风险指标）
- 医嘱执行流程：查询 → 双人核对 → 执行记录 → 异常上报
- 交班摘要生成（基于患者当前状态自动生成草稿，需人工确认后提交）
- 护理文书草稿生成（支持模板导入，生成后需审核）
- 图片/PDF 附件上传后的多模态分析（实验性，准确率有限，需人工复核）

**开发中/待完善：**
- Admin 管理端目前只有目录骨架，审计日志检索和人工审核台尚未实现
- ASR/TTS 真服务接入（当前是 mock 或本地 pyttsx3 替代）
- 真实 HIS/LIS 数据对接（目前用模拟病例数据）
- 弱网环境下的稳定性优化

## 项目结构

```
apps/
  mobile/          # 护士移动端（React Native + Expo）
  admin-web/       # 管理后台（预留，未完成）

services/          # 后端服务（Python FastAPI）
  api-gateway/     # 统一入口，WebSocket 推送
  auth-service/    # 登录注册，账号持久化到本地 JSON
  patient-context-service/  # 患者数据、医嘱查询
  agent-orchestrator/       # Agent 编排核心（Planner + Memory + Tool Loop）
  handover-service/         # 交班记录 CRUD
  recommendation-service/   # 临床推荐（需 review_required 标记）
  document-service/         # 文书模板和草稿
  collaboration-service/    # 协作通知
  asr-service/     # 语音识别（当前 mock）
  tts-service/     # 语音合成（当前 mock）
  audit-service/   # 审计日志写入
  device-gateway/  # 小智设备兼容网关
  multimodal-med-service/   # 多模态分析（MedGemma，实验性）

infra/             # Docker Compose 配置
  postgres/        # 主数据库
  qdrant/          # 向量库（Agent Memory 用）
  nats/            # 消息队列
  minio/           # 对象存储（附件）

docs/              # 设计文档
scripts/           # 启动和运维脚本
UI/                # 设计稿 01-27
```

## 环境要求

- Windows 10/11 + PowerShell 5.1+
- Docker Desktop（用于 PostgreSQL、Qdrant、NATS）
- Python 3.10+（各服务独立 venv 运行）
- Node.js 18+（移动端）
- 本地模型运行建议 16GB+ 内存（MiniCPM3-4B Q4 约需 4-6GB）

**注意：** 项目路径建议放在纯英文目录，避免 Windows 中文路径导致的编码问题。

## 启动步骤

### 1. 基础配置
```powershell
cd "D:\Desktop\ai agent 护理精细化部署"
Copy-Item .env.example .env.local
# 按需修改 .env.local 中的配置，特别是 BAILIAN_API_KEY
```

### 2. 启动基础设施（Docker）
```powershell
.\bootstrap_local_stack.ps1
```
这会启动 PostgreSQL（5432）、Qdrant（6333）、NATS（4222）、MinIO（9000）、pgAdmin（5050）。

### 3. 启动后端服务
```powershell
.\scripts\start_backend_core.ps1
```
脚本会依次启动 13 个微服务，全部启动约需 30-60 秒。可以用 `check_health.ps1` 检查状态。

### 4. 启动本地模型（可选但推荐）
```powershell
# 首次下载模型（约 4.6GB）
.\scripts\download_cn_light_models.ps1 -Profile both

# 启动本地 LLM 服务
.\scripts\start_local_cn_llm.ps1 -Profile minicpm4b
```
如果不启动本地模型，会回退到百炼云端 API（需配置 API Key）。

### 5. 启动移动端
```powershell
cd apps\mobile
npm install
npm run start
```
默认会打开 Expo 开发者工具，可以用 Expo Go App 扫码在真机运行，或按 `w` 在浏览器预览。

## 常用脚本

| 脚本 | 说明 |
|------|------|
| `bootstrap_local_stack.ps1` | 启动/重启 Docker 基础设施 |
| `start_backend_core.ps1` | 启动所有后端服务 |
| `start_local_cn_llm.ps1` | 启动本地中文模型服务 |
| `download_cn_light_models.ps1` | 下载 MiniCPM3/Qwen 模型文件 |
| `check_health.ps1` | 检查各服务健康状态 |
| `seed_10_mock_cases.ps1` | 向数据库导入 10 个测试病例 |
| `import_his_cases_to_postgres.ps1` | 从 CSV 导入真实 HIS 病例数据 |
| `verify_bed_mapping.ps1` | 验证 1-40 床是否都有患者数据 |

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| API Gateway | 8000 | 统一入口，WebSocket 推送 |
| Patient Context | 8002 | 患者数据查询 |
| Agent Orchestrator | 8003 | Agent 编排核心 |
| Handover | 8004 | 交班记录 |
| Recommendation | 8005 | 临床推荐 |
| Document | 8006 | 文书草稿 |
| ASR | 8008 | 语音识别（mock） |
| TTS | 8009 | 语音合成（mock） |
| Multimodal Med | 8010 | 多模态分析 |
| Auth | 8012 | 认证服务 |
| Device Gateway | 8013 | 设备网关 |

## 一些注意事项

- **Mock 模式**：移动端默认开启 mock（`EXPO_PUBLIC_API_MOCK=true`），可以先看页面效果；关闭后才会走真实后端。
- **本地模型优先**：如果启动了本地 LLM 服务，Agent 会优先调用本地模型（MiniCPM3-4B），失败时回退到百炼 API。
- **人工确认**：推荐建议、交班草稿、文书生成都会标记 `review_required`，需要护士确认后才能生效，不会直接写入系统。
- **数据持久化**：患者数据、医嘱、交班记录、文书草稿都存 PostgreSQL；账号信息存 `auth-service/data/mock_users.json`。
- **模型许可**：MedGemma 使用需遵守 Google Health AI Developer Foundations terms，参赛前请确认合规。

## 许可证

项目代码：Apache-2.0

第三方组件：
- medplum：Apache-2.0
- FunASR：Apache-2.0
- CosyVoice：以官方发布页条款为准
- MedGemma：Health AI Developer Foundations terms

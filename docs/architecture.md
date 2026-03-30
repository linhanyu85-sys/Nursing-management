# AI护理精细化系统架构

## 1. 架构目标
- 本地开发和未来服务器部署同构。
- 微服务拆分，避免单体。
- 模型调用支持 mock 与真实双模式。
- 所有推荐/文书输出保留人工审核。
- 敏感与AI相关操作全部留痕。

## 2. 顶层分层
- 客户端层:
  - `apps/mobile`（React Native + Expo）
  - `apps/admin-web`（管理端预留）
- 网关层:
  - `services/api-gateway`
- 业务服务层:
  - `auth-service`
  - `patient-context-service`
  - `handover-service`
  - `recommendation-service`
  - `document-service`
  - `collaboration-service`
  - `audit-service`
- AI与模型层:
  - `agent-orchestrator`
  - `asr-service`（FunASR）
  - `tts-service`（CosyVoice）
  - `multimodal-med-service`（MedGemma）
  - 百炼（阿里云 DashScope 兼容接口）
- 数据与中间件层:
  - PostgreSQL（业务主库）
  - Qdrant（检索向量库）
  - NATS（事件总线）
  - MinIO（文件对象存储）
  - pgAdmin（本地运维）

## 3. 服务边界
- `api-gateway`
  - 统一入口与路由转发。
  - 对移动端暴露 `/api/*`。
- `patient-context-service`
  - 负责病区、床位、患者上下文聚合。
- `handover-service`
  - 交班生成、批量生成、审核。
- `recommendation-service`
  - 临床建议生成，统一结构化输出。
- `document-service`
  - 文书草稿生成、审核、提交。
- `agent-orchestrator`
  - 多Agent状态机，4条主工作流。
- `audit-service`
  - 审计日志写入与检索。

## 4. 关键调用路径
- 语音问询:
  - `mobile -> api-gateway -> asr-service -> agent-orchestrator -> patient-context-service -> recommendation-service -> audit-service`
- 交班:
  - `mobile/admin -> api-gateway -> handover-service -> patient-context-service -> audit-service`
- 推荐:
  - `mobile -> api-gateway -> recommendation-service -> patient-context-service -> agent-orchestrator(可选) -> audit-service`
- 文书:
  - `mobile -> api-gateway -> document-service -> patient-context-service -> audit-service`

## 5. 本地部署
- 基础设施容器由 `docker-compose.local.yml` 启动。
- 微服务默认本地端口运行（uvicorn）。
- `.env.local` 管理密钥与服务地址，`.env.example` 仅保留模板。

## 6. 安全与合规
- 所有AI结果包含:
  - `summary`
  - `findings`
  - `recommendations`
  - `confidence`
  - `review_required`
- 推荐/文书默认 `review_required=true`。
- 所有写操作与AI关键调用必须写审计日志。

## 7. 目录说明
- `apps/`: 客户端应用。
- `services/`: 微服务代码。
- `infra/`: 基础设施与初始化脚本。
- `docs/`: 架构与接口文档。
- `prompts/`: Agent与模型提示词模板。
- `scripts/`: 启动与开发脚本。

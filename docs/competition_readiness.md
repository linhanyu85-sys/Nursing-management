# Competition Readiness (国创赛交付版)

本文件用于比赛答辩与材料归档，证明本项目已具备“语音外设 + 临床 AI Agent 平台”的工程化与合规基础。

## 1) 系统定位（答辩口径）

- ESP32-S3 板子仅是语音外设入口（收音/上传/播报/状态）。
- 真实业务能力在后端微服务：患者上下文、推荐、交班、文书、协作、审计。
- 设备端不承载大模型推理，不存储临床主数据。

## 2) 当前已落地的关键能力

- 语音链路：设备网关支持 `wake/sleep` 指令与同音唤醒别名（小医/小依/小智）。
- 患者上下文：通过 `patient-context-service` 命中 PostgreSQL 实床位患者数据。
- 工作流：`agent-orchestrator` 统一入口，语音问询/推荐/交班/文书按意图分流。
- 结果落库：
  - 文书 -> `document_drafts`
  - 交班 -> `handover_records`
  - 推荐 -> `ai_recommendations`
  - 审计 -> `audit_logs`
- 账号绑定：设备默认绑定 `linmeili`（`u_linmeili`），并支持运行时改绑。

## 3) 合规材料

- 第三方声明：`THIRD_PARTY_NOTICES.md`
- 自动扫描脚本：`scripts/scan_competition_licenses.ps1`
- 扫描结果（自动生成）：
  - `docs/competition_open_source_inventory.md`
  - `data/compliance/license_scan.json`

## 4) 一键生成开源/模型风险清单

```powershell
cd "D:\Desktop\ai agent 护理精细化部署"
.\scripts\scan_competition_licenses.ps1
```

阻断模式（发现受限条款即失败）：

```powershell
.\scripts\scan_competition_licenses.ps1 -FailOnRestricted
```

## 5) 赛前一键闭环验收（推荐）

```powershell
.\scripts\verify_competition_e2e.ps1 `
  -ApiGatewayPort 8000 `
  -DeviceGatewayPort 8013 `
  -PatientContextPort 28002 `
  -Username "linmeili" `
  -RequestedBy "u_linmeili" `
  -BedCoverageMode "range" `
  -BedStart 1 `
  -BedEnd 40
```

自动验证项：
- 服务健康（api/device）
- 设备绑定账号（linmeili）
- 全床位映射（1..40）
- 患者问询/文书/交班/推荐四条链路
- `document_drafts / handover_records / ai_recommendations / audit_logs` 落库增量
- 输出报告：`docs/competition_preflight_report.md`

`BedCoverageMode` 说明：
- `range`：严格校验 `BedStart..BedEnd`（比赛封板推荐）
- `existing`：仅校验数据库中已存在床位（联调阶段推荐）

开源 Agent 内核（LangGraph）开关：

```powershell
# 查看当前内核状态
Invoke-RestMethod "http://127.0.0.1:8000/api/ai/runtime"

# 切换到 LangGraph（若不可用会自动回退 state_machine）
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/ai/runtime" -ContentType "application/json" -Body '{"engine":"langgraph"}'

# 切回稳定内核
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/ai/runtime" -ContentType "application/json" -Body '{"engine":"state_machine"}'
```

若 `bed_mapping_coverage` 失败（常见于仅导入了部分床位）：

```powershell
.\scripts\import_his_cases_to_postgres.ps1 `
  -SourcePath ".\data\his_import\your_full_1_40_cases.csv" `
  -Username "linmeili" `
  -DepartmentCode "dep-card-01" `
  -RequireFullBedRange `
  -BedStart 1 `
  -BedEnd 40 `
  -ClearDepartmentBeds
```

然后再次执行 `.\scripts\verify_competition_e2e.ps1`，直到报告全部 PASS。

或者直接执行一体化脚本（自动全量检查 + 导入 + range 验收）：

```powershell
.\scripts\sync_his_full_linmeili.ps1 `
  -Username "linmeili" `
  -DepartmentCode "dep-card-01" `
  -BedStart 1 `
  -BedEnd 40
```

若你有 HIS API，可在 `.env.local` 配置：
- `HIS_API_BASE_URL`
- `HIS_API_PATH_TEMPLATE=/api/his/users/{username}/beds`
- `HIS_API_TOKEN`

## 6) 比赛前必须确认

- 所有用于现场演示的模型均具备可用于本场景的许可（尤其是 `CUSTOM-TERMS` / `UNKNOWN` 项）。
- 不将受限条款模型/数据用于超出授权范围的商业化传播。
- 展示页明确标注“AI 建议仅辅助，最终由医护人员复核”。

## 7) 风险提示（重点）

- `MedGemma` 当前识别为 `CUSTOM-TERMS`（非标准开源许可证），参赛前需按条款再次确认使用边界。
- Python / Node 依赖默认按清单管理，建议在封板前导出完整 SPDX/SBOM 归档。

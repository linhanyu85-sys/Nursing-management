# API Design

Base URL:
- 本地网关: `http://localhost:8000`
- 前缀: `/api`

鉴权:
- 登录接口无需鉴权。
- 其余接口建议携带 `Authorization: Bearer <access_token>`（当前骨架可在mock模式放行）。

## 1. 认证
### POST /api/auth/login
请求:
```json
{
  "username": "nurse01",
  "password": "123456"
}
```
响应 200:
```json
{
  "access_token": "mock_access_nurse01",
  "refresh_token": "mock_refresh_nurse01",
  "expires_at": "2026-03-19T10:00:00Z",
  "user": {
    "id": "u_nurse_01",
    "full_name": "张护士",
    "role_code": "nurse"
  }
}
```
状态码:
- 200 登录成功
- 401 凭据错误

## 2. 病区与患者
### GET /api/wards/{department_id}/beds
响应 200:
```json
[
  {
    "id": "bed-12",
    "department_id": "dep-card-01",
    "bed_no": "12",
    "status": "occupied",
    "current_patient_id": "pat-001",
    "patient_name": "张晓明",
    "risk_tags": ["低血压风险"],
    "pending_tasks": ["复测血压"]
  }
]
```

### GET /api/patients/{patient_id}
### GET /api/patients/{patient_id}/context
响应 200:
```json
{
  "patient_id": "pat-001",
  "bed_no": "12",
  "diagnoses": ["慢性心衰急性加重"],
  "risk_tags": ["低血压风险", "液体管理风险"],
  "pending_tasks": ["复测血压", "记录尿量"]
}
```

状态码:
- 200 成功
- 404 患者或上下文不存在

## 3. 语音
### POST /api/asr/transcribe
请求:
```json
{
  "text_hint": "12床今天最需要注意什么"
}
```
响应:
```json
{
  "text": "12床今天最需要注意什么",
  "confidence": 0.94,
  "provider": "mock"
}
```

### POST /api/tts/speak
请求:
```json
{
  "text": "请先复测血压",
  "voice": "default"
}
```

## 4. 交班
### POST /api/handover/generate
请求:
```json
{
  "patient_id": "pat-001",
  "shift_type": "day"
}
```
响应:
```json
{
  "id": "handover_xxx",
  "patient_id": "pat-001",
  "summary": "患者本班次重点...",
  "next_shift_priorities": ["复测血压", "记录尿量"]
}
```

### POST /api/handover/batch-generate
### GET /api/handover/{patient_id}/latest
### POST /api/handover/{id}/review

## 5. 推荐
### POST /api/recommendation/run
请求:
```json
{
  "patient_id": "pat-001",
  "question": "当前应该如何安排优先级？",
  "attachments": []
}
```
响应:
```json
{
  "id": "rec_xxx",
  "summary": "当前存在低灌注风险，应先复测血压并上报医生。",
  "findings": ["收缩压偏低", "尿量减少"],
  "recommendations": [
    { "title": "立即复测血压", "priority": 1 },
    { "title": "记录尿量并通知医生", "priority": 1 }
  ],
  "confidence": 0.81,
  "review_required": true
}
```

## 6. 文书
### POST /api/document/draft
### GET /api/document/drafts/{patient_id}
### POST /api/document/{draft_id}/review
### POST /api/document/{draft_id}/submit

请求示例:
```json
{
  "patient_id": "pat-001",
  "document_type": "nursing_note",
  "spoken_text": "患者主诉胸闷减轻，继续监测。"
}
```

## 7. 多模态
### POST /api/multimodal/analyze
请求:
```json
{
  "patient_id": "pat-001",
  "input_refs": ["file_001.jpg", "file_002.pdf"],
  "question": "请总结当前病情重点"
}
```

## 8. 协作
### POST /api/collab/thread
### POST /api/collab/message
### GET /api/collab/thread/{id}
### POST /api/collab/escalate

## 9. 审计
### GET /api/audit/{resource_type}/{resource_id}
查询参数:
- `limit` 默认 50，最大 200

## 10. Agent编排
### POST /api/workflow/run
请求:
```json
{
  "workflow_type": "voice_inquiry",
  "patient_id": "pat-001",
  "user_input": "12床今天最需要注意什么"
}
```

响应结构:
```json
{
  "summary": "",
  "findings": [],
  "recommendations": [],
  "confidence": 0.0,
  "review_required": true
}
```

## 11. 错误码建议
| code | 说明 |
|---|---|
| `invalid_credentials` | 登录凭据错误 |
| `patient_not_found` | 未找到患者 |
| `patient_context_not_found` | 患者上下文缺失 |
| `bed_context_not_found` | 床位未绑定患者 |
| `handover_not_found` | 交班记录不存在 |
| `recommendation_not_found` | 推荐记录不存在 |
| `draft_not_found` | 文书草稿不存在 |
| `thread_not_found` | 协作会话不存在 |
| `upstream_error` | 上游服务异常 |

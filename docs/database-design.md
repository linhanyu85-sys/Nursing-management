# Database Design (PostgreSQL)

## 1. 设计原则
- 业务主数据在 PostgreSQL。
- 医疗结构尽量兼容 FHIR 思想（患者-就诊-观察-任务）。
- AI中间产物独立落表。
- 审计日志与模型调用日志独立落表。

## 2. 核心枚举建议
- `users.status`: `active | inactive | locked`
- `departments.ward_type`: `inpatient | icu | emergency | outpatient`
- `beds.status`: `occupied | empty | reserved | cleaning`
- `patients.current_status`: `admitted | discharged | transferred`
- `encounters.encounter_type`: `inpatient | outpatient | emergency`
- `encounters.status`: `active | completed | cancelled`
- `patient_diagnoses.diagnosis_type`: `primary | secondary | provisional`
- `patient_diagnoses.status`: `active | resolved`
- `observations.category`: `vital | lab | nursing | other`
- `observations.abnormal_flag`: `normal | high | low | critical`
- `care_tasks.source_type`: `manual | ai | handover | system`
- `care_tasks.status`: `pending | in_progress | completed | cancelled | overdue`
- `handover_records.shift_type`: `day | night`
- `handover_records.source_type`: `ai | manual | mixed`
- `ai_recommendations.scenario`: `handover | recommendation | triage | document | voice_inquiry`
- `ai_recommendations.status`: `draft | reviewed | accepted | rejected`
- `document_drafts.status`: `draft | reviewed | saved | submitted`
- `collaboration_threads.thread_type`: `consult | discussion | urgent_help`
- `collaboration_threads.status`: `open | closed | archived`
- `collaboration_messages.message_type`: `text | image | voice | system`
- `model_call_logs.model_type`: `llm | asr | tts | multimodal`
- `model_call_logs.provider`: `bailian | local | mock`

## 3. 表结构总览

### 3.1 roles
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| code | varchar(32) | UNIQUE, NOT NULL |
| name | varchar(64) | NOT NULL |
| description | text | NULL |
| created_at | timestamptz | NOT NULL |

### 3.2 departments
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| code | varchar(32) | UNIQUE, NOT NULL |
| name | varchar(128) | NOT NULL |
| ward_type | varchar(32) | CHECK |
| parent_id | uuid | FK -> departments.id |
| location | varchar(255) | NULL |
| created_at | timestamptz | NOT NULL |

### 3.3 users
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| username | varchar(64) | UNIQUE, NOT NULL |
| password_hash | varchar(255) | NOT NULL |
| full_name | varchar(64) | NOT NULL |
| phone | varchar(32) | NULL |
| email | varchar(128) | NULL |
| role_code | varchar(32) | FK -> roles.code |
| department_id | uuid | FK -> departments.id |
| title | varchar(64) | NULL |
| status | varchar(16) | CHECK |
| avatar_url | varchar(255) | NULL |
| last_login_at | timestamptz | NULL |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

索引:
- `idx_users_department_id (department_id)`
- `idx_users_role_code (role_code)`

### 3.4 patients
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| mrn | varchar(64) | UNIQUE, NOT NULL |
| inpatient_no | varchar(64) | NULL |
| full_name | varchar(64) | NOT NULL |
| gender | varchar(8) | NULL |
| birth_date | date | NULL |
| age | int | NULL |
| phone | varchar(32) | NULL |
| emergency_contact | varchar(128) | NULL |
| blood_type | varchar(8) | NULL |
| allergy_info | text | NULL |
| current_status | varchar(16) | CHECK |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

索引:
- `idx_patients_mrn (mrn)`
- `idx_patients_inpatient_no (inpatient_no)`

### 3.5 beds
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| department_id | uuid | FK -> departments.id |
| bed_no | varchar(16) | NOT NULL |
| room_no | varchar(16) | NULL |
| status | varchar(16) | CHECK |
| current_patient_id | uuid | FK -> patients.id |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

约束:
- UNIQUE `(department_id, bed_no)`

### 3.6 encounters
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_type | varchar(32) | CHECK |
| department_id | uuid | FK -> departments.id |
| attending_doctor_id | uuid | FK -> users.id |
| primary_nurse_id | uuid | FK -> users.id |
| admission_at | timestamptz | NULL |
| discharge_at | timestamptz | NULL |
| status | varchar(16) | CHECK |
| chief_complaint | text | NULL |
| admission_diagnosis | text | NULL |
| discharge_diagnosis | text | NULL |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

### 3.7 patient_diagnoses
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| encounter_id | uuid | FK -> encounters.id |
| diagnosis_code | varchar(64) | NULL |
| diagnosis_name | varchar(255) | NOT NULL |
| diagnosis_type | varchar(32) | CHECK |
| status | varchar(16) | CHECK |
| diagnosed_at | timestamptz | NULL |
| created_by | uuid | FK -> users.id |
| created_at | timestamptz | NOT NULL |

### 3.8 observations
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| category | varchar(32) | CHECK |
| code | varchar(64) | NULL |
| name | varchar(128) | NOT NULL |
| value_text | varchar(255) | NULL |
| value_num | numeric(18,4) | NULL |
| unit | varchar(32) | NULL |
| reference_range | varchar(64) | NULL |
| abnormal_flag | varchar(16) | CHECK |
| observed_at | timestamptz | NOT NULL |
| source | varchar(32) | CHECK |
| created_at | timestamptz | NOT NULL |

索引:
- `idx_observations_patient_id (patient_id)`
- `idx_observations_encounter_id (encounter_id)`
- `idx_observations_code_observed_at (code, observed_at desc)`

### 3.9 care_tasks
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| source_type | varchar(32) | CHECK |
| task_type | varchar(64) | NOT NULL |
| title | varchar(255) | NOT NULL |
| description | text | NULL |
| priority | int | CHECK (1/2/3) |
| status | varchar(16) | CHECK |
| assigned_to | uuid | FK -> users.id |
| created_by | uuid | FK -> users.id |
| due_at | timestamptz | NULL |
| completed_at | timestamptz | NULL |
| review_required | boolean | NOT NULL |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

索引:
- `idx_care_tasks_patient_id (patient_id)`
- `idx_care_tasks_assigned_to (assigned_to)`
- `idx_care_tasks_status_due_at (status, due_at)`

### 3.10 handover_records
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| shift_date | date | NOT NULL |
| shift_type | varchar(16) | CHECK |
| generated_by | uuid | FK -> users.id |
| source_type | varchar(16) | CHECK |
| summary | text | NOT NULL |
| new_changes | jsonb | NOT NULL |
| worsening_points | jsonb | NOT NULL |
| improved_points | jsonb | NOT NULL |
| pending_closures | jsonb | NOT NULL |
| next_shift_priorities | jsonb | NOT NULL |
| reviewed_by | uuid | FK -> users.id |
| reviewed_at | timestamptz | NULL |
| created_at | timestamptz | NOT NULL |

索引:
- `idx_handover_records_patient_shift (patient_id, shift_date, shift_type)`
- `idx_handover_records_shift_date (shift_date)`

### 3.11 ai_recommendations
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| scenario | varchar(64) | CHECK |
| input_summary | text | NULL |
| summary | text | NOT NULL |
| findings | jsonb | NOT NULL |
| recommendations | jsonb | NOT NULL |
| escalation_rules | jsonb | NOT NULL |
| confidence | numeric(5,4) | NOT NULL |
| review_required | boolean | NOT NULL |
| status | varchar(16) | CHECK |
| reviewed_by | uuid | FK -> users.id |
| reviewed_at | timestamptz | NULL |
| created_at | timestamptz | NOT NULL |

### 3.12 document_drafts
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| document_type | varchar(64) | CHECK |
| draft_text | text | NOT NULL |
| structured_fields | jsonb | NOT NULL |
| source_type | varchar(16) | CHECK |
| status | varchar(16) | CHECK |
| reviewed_by | uuid | FK -> users.id |
| reviewed_at | timestamptz | NULL |
| created_by | uuid | FK -> users.id |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

### 3.13 multimodal_analysis_records
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| input_type | varchar(32) | CHECK |
| input_refs | jsonb | NOT NULL |
| summary | text | NULL |
| findings | jsonb | NOT NULL |
| risk_points | jsonb | NOT NULL |
| suggested_focus | jsonb | NOT NULL |
| confidence | numeric(5,4) | NOT NULL |
| raw_output | jsonb | NULL |
| created_at | timestamptz | NOT NULL |

### 3.14 collaboration_threads
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| patient_id | uuid | FK -> patients.id |
| encounter_id | uuid | FK -> encounters.id |
| thread_type | varchar(32) | CHECK |
| title | varchar(255) | NOT NULL |
| created_by | uuid | FK -> users.id |
| status | varchar(16) | CHECK |
| created_at | timestamptz | NOT NULL |
| updated_at | timestamptz | NOT NULL |

### 3.15 collaboration_messages
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| thread_id | uuid | FK -> collaboration_threads.id |
| sender_id | uuid | FK -> users.id |
| message_type | varchar(32) | CHECK |
| content | text | NULL |
| attachment_refs | jsonb | NOT NULL |
| ai_generated | boolean | NOT NULL |
| created_at | timestamptz | NOT NULL |

### 3.16 audit_logs
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| user_id | uuid | FK -> users.id |
| action | varchar(128) | NOT NULL |
| resource_type | varchar(64) | NOT NULL |
| resource_id | uuid | NULL |
| request_id | varchar(64) | NULL |
| detail | jsonb | NOT NULL |
| ip_address | varchar(64) | NULL |
| device_info | varchar(255) | NULL |
| created_at | timestamptz | NOT NULL |

### 3.17 model_call_logs
| 字段 | 类型 | 约束 |
|---|---|---|
| id | uuid | PK |
| model_type | varchar(32) | CHECK |
| model_name | varchar(128) | NOT NULL |
| provider | varchar(32) | CHECK |
| request_payload | jsonb | NOT NULL |
| response_summary | text | NULL |
| latency_ms | int | NULL |
| success | boolean | NOT NULL |
| error_message | text | NULL |
| created_at | timestamptz | NOT NULL |

## 4. 典型查询场景
- 病区总览:
  - `beds + patients + care_tasks + observations(24h异常)`
- 患者上下文:
  - `patients + active encounters + diagnoses + observations + pending tasks`
- 交班生成:
  - 按患者读取 `risk_tags + pending_tasks + 最新观察`
- 推荐追踪:
  - `ai_recommendations` 按患者和状态过滤
- 文书闭环:
  - `document_drafts` 按患者和状态 `draft/reviewed/submitted`
- 协作沟通:
  - `collaboration_threads + collaboration_messages`
- 审计回溯:
  - `audit_logs` 按 `resource_type/resource_id/request_id`

## 5. 已实现脚本
- 初始化SQL文件:
  - `infra/postgres/init/001_backend_schema_init.sql`
  - 根目录镜像: `backend_schema_init.sql`

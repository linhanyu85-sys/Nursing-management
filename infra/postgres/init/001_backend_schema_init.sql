CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- =========================
-- Core dictionary tables
-- =========================
CREATE TABLE IF NOT EXISTS roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(64) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS departments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code VARCHAR(32) UNIQUE NOT NULL,
    name VARCHAR(128) NOT NULL,
    ward_type VARCHAR(32) NOT NULL CHECK (ward_type IN ('inpatient', 'icu', 'emergency', 'outpatient')),
    parent_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    location VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    full_name VARCHAR(64) NOT NULL,
    phone VARCHAR(32),
    email VARCHAR(128),
    role_code VARCHAR(32) NOT NULL REFERENCES roles(code),
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    title VARCHAR(64),
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'locked')),
    avatar_url VARCHAR(255),
    last_login_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_department_id ON users(department_id);
CREATE INDEX IF NOT EXISTS idx_users_role_code ON users(role_code);

-- =========================
-- Patient and encounter domain
-- =========================
CREATE TABLE IF NOT EXISTS patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mrn VARCHAR(64) UNIQUE NOT NULL,
    inpatient_no VARCHAR(64),
    full_name VARCHAR(64) NOT NULL,
    gender VARCHAR(8),
    birth_date DATE,
    age INTEGER,
    phone VARCHAR(32),
    emergency_contact VARCHAR(128),
    blood_type VARCHAR(8),
    allergy_info TEXT,
    current_status VARCHAR(16) NOT NULL DEFAULT 'admitted' CHECK (current_status IN ('admitted', 'discharged', 'transferred')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_patients_mrn ON patients(mrn);
CREATE INDEX IF NOT EXISTS idx_patients_inpatient_no ON patients(inpatient_no);

CREATE TABLE IF NOT EXISTS beds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    department_id UUID NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    bed_no VARCHAR(16) NOT NULL,
    room_no VARCHAR(16),
    status VARCHAR(16) NOT NULL DEFAULT 'empty' CHECK (status IN ('occupied', 'empty', 'reserved', 'cleaning')),
    current_patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(department_id, bed_no)
);

CREATE TABLE IF NOT EXISTS encounters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_type VARCHAR(32) NOT NULL CHECK (encounter_type IN ('inpatient', 'outpatient', 'emergency')),
    department_id UUID REFERENCES departments(id) ON DELETE SET NULL,
    attending_doctor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    primary_nurse_id UUID REFERENCES users(id) ON DELETE SET NULL,
    admission_at TIMESTAMPTZ,
    discharge_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'cancelled')),
    chief_complaint TEXT,
    admission_diagnosis TEXT,
    discharge_diagnosis TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS patient_diagnoses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    encounter_id UUID NOT NULL REFERENCES encounters(id) ON DELETE CASCADE,
    diagnosis_code VARCHAR(64),
    diagnosis_name VARCHAR(255) NOT NULL,
    diagnosis_type VARCHAR(32) NOT NULL CHECK (diagnosis_type IN ('primary', 'secondary', 'provisional')),
    status VARCHAR(16) NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'resolved')),
    diagnosed_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    category VARCHAR(32) NOT NULL CHECK (category IN ('vital', 'lab', 'nursing', 'other')),
    code VARCHAR(64),
    name VARCHAR(128) NOT NULL,
    value_text VARCHAR(255),
    value_num NUMERIC(18,4),
    unit VARCHAR(32),
    reference_range VARCHAR(64),
    abnormal_flag VARCHAR(16) CHECK (abnormal_flag IN ('normal', 'high', 'low', 'critical')),
    observed_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(32) NOT NULL DEFAULT 'manual' CHECK (source IN ('lis', 'manual', 'device', 'ai_extract')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_observations_patient_id ON observations(patient_id);
CREATE INDEX IF NOT EXISTS idx_observations_encounter_id ON observations(encounter_id);
CREATE INDEX IF NOT EXISTS idx_observations_code_observed_at ON observations(code, observed_at DESC);

-- =========================
-- Task / handover / recommendation / documents
-- =========================
CREATE TABLE IF NOT EXISTS care_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'manual' CHECK (source_type IN ('manual', 'ai', 'handover', 'system')),
    task_type VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT,
    priority INTEGER NOT NULL DEFAULT 2 CHECK (priority IN (1, 2, 3)),
    status VARCHAR(16) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled', 'overdue')),
    assigned_to UUID REFERENCES users(id) ON DELETE SET NULL,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    due_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    review_required BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_care_tasks_patient_id ON care_tasks(patient_id);
CREATE INDEX IF NOT EXISTS idx_care_tasks_assigned_to ON care_tasks(assigned_to);
CREATE INDEX IF NOT EXISTS idx_care_tasks_status_due_at ON care_tasks(status, due_at);

CREATE OR REPLACE VIEW tasks AS
SELECT * FROM care_tasks;

CREATE TABLE IF NOT EXISTS handover_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    shift_date DATE NOT NULL,
    shift_type VARCHAR(16) NOT NULL CHECK (shift_type IN ('day', 'night')),
    generated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    source_type VARCHAR(16) NOT NULL DEFAULT 'ai' CHECK (source_type IN ('ai', 'manual', 'mixed')),
    summary TEXT NOT NULL,
    new_changes JSONB NOT NULL DEFAULT '[]'::jsonb,
    worsening_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    improved_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    pending_closures JSONB NOT NULL DEFAULT '[]'::jsonb,
    next_shift_priorities JSONB NOT NULL DEFAULT '[]'::jsonb,
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_handover_records_patient_shift ON handover_records(patient_id, shift_date, shift_type);
CREATE INDEX IF NOT EXISTS idx_handover_records_shift_date ON handover_records(shift_date);

CREATE TABLE IF NOT EXISTS ai_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    scenario VARCHAR(64) NOT NULL CHECK (scenario IN ('handover', 'recommendation', 'triage', 'document', 'voice_inquiry')),
    input_summary TEXT,
    summary TEXT NOT NULL,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    recommendations JSONB NOT NULL DEFAULT '[]'::jsonb,
    escalation_rules JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    review_required BOOLEAN NOT NULL DEFAULT TRUE,
    status VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'accepted', 'rejected')),
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    document_type VARCHAR(64) NOT NULL CHECK (document_type IN ('nursing_note', 'progress_note', 'handover_note', 'admission_note')),
    draft_text TEXT NOT NULL,
    structured_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_type VARCHAR(16) NOT NULL DEFAULT 'ai' CHECK (source_type IN ('ai', 'manual', 'mixed')),
    status VARCHAR(16) NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'saved', 'submitted')),
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS multimodal_analysis_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    input_type VARCHAR(32) NOT NULL CHECK (input_type IN ('image', 'text', 'pdf', 'mixed')),
    input_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary TEXT,
    findings JSONB NOT NULL DEFAULT '[]'::jsonb,
    risk_points JSONB NOT NULL DEFAULT '[]'::jsonb,
    suggested_focus JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC(5,4) NOT NULL DEFAULT 0.0,
    raw_output JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================
-- Collaboration / audit / model logging
-- =========================
CREATE TABLE IF NOT EXISTS collaboration_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID REFERENCES patients(id) ON DELETE SET NULL,
    encounter_id UUID REFERENCES encounters(id) ON DELETE SET NULL,
    thread_type VARCHAR(32) NOT NULL CHECK (thread_type IN ('consult', 'discussion', 'urgent_help')),
    title VARCHAR(255) NOT NULL,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed', 'archived')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collaboration_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id UUID NOT NULL REFERENCES collaboration_threads(id) ON DELETE CASCADE,
    sender_id UUID REFERENCES users(id) ON DELETE SET NULL,
    message_type VARCHAR(32) NOT NULL DEFAULT 'text' CHECK (message_type IN ('text', 'image', 'voice', 'system')),
    content TEXT,
    attachment_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    ai_generated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(128) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id UUID,
    request_id VARCHAR(64),
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    ip_address VARCHAR(64),
    device_info VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS model_call_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type VARCHAR(32) NOT NULL CHECK (model_type IN ('llm', 'asr', 'tts', 'multimodal')),
    model_name VARCHAR(128) NOT NULL,
    provider VARCHAR(32) NOT NULL CHECK (provider IN ('bailian', 'local', 'mock')),
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    response_summary TEXT,
    latency_ms INTEGER,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =========================
-- Seed data for local bootstrap
-- =========================
INSERT INTO roles (code, name, description)
VALUES
('nurse', '护士', '临床护士'),
('senior_nurse', '高年资护士', '高年资护士'),
('charge_nurse', '护士长', '病区护士长'),
('resident_doctor', '住院医师', '住院医生'),
('attending_doctor', '主治医师', '主治医生'),
('consultant', '会诊专家', '多学科会诊专家'),
('admin', '管理员', '系统管理员'),
('auditor', '审计员', '审计人员')
ON CONFLICT (code) DO NOTHING;

INSERT INTO departments (code, name, ward_type, location)
VALUES
('CARD-01', '心内一病区', 'inpatient', 'A栋6层'),
('RESP-01', '呼吸内科病区', 'inpatient', 'A栋5层'),
('ICU-01', '综合ICU', 'icu', 'A栋3层')
ON CONFLICT (code) DO NOTHING;

INSERT INTO users (username, password_hash, full_name, role_code, department_id, title, status)
SELECT
    'nurse01',
    'mock_hash_replace_in_prod',
    '张护士',
    'nurse',
    d.id,
    '主管护师',
    'active'
FROM departments d
WHERE d.code = 'CARD-01'
ON CONFLICT (username) DO NOTHING;

INSERT INTO users (username, password_hash, full_name, role_code, department_id, title, status)
SELECT
    'doctor01',
    'mock_hash_replace_in_prod',
    '李医生',
    'attending_doctor',
    d.id,
    '主治医师',
    'active'
FROM departments d
WHERE d.code = 'CARD-01'
ON CONFLICT (username) DO NOTHING;

INSERT INTO patients (mrn, inpatient_no, full_name, gender, birth_date, age, blood_type, allergy_info, current_status)
VALUES
('MRN-0001', 'IP-2026-0001', '张晓明', '男', '1981-05-16', 45, 'A+', '青霉素过敏', 'admitted'),
('MRN-0002', 'IP-2026-0002', '王丽', '女', '1978-09-22', 48, 'B+', NULL, 'admitted')
ON CONFLICT (mrn) DO NOTHING;

INSERT INTO beds (department_id, bed_no, room_no, status, current_patient_id)
SELECT d.id, '12', '612', 'occupied', p.id
FROM departments d
JOIN patients p ON p.mrn = 'MRN-0001'
WHERE d.code = 'CARD-01'
ON CONFLICT (department_id, bed_no) DO NOTHING;

INSERT INTO beds (department_id, bed_no, room_no, status, current_patient_id)
SELECT d.id, '15', '615', 'occupied', p.id
FROM departments d
JOIN patients p ON p.mrn = 'MRN-0002'
WHERE d.code = 'CARD-01'
ON CONFLICT (department_id, bed_no) DO NOTHING;

INSERT INTO encounters (patient_id, encounter_type, department_id, status, admission_at, chief_complaint, admission_diagnosis)
SELECT p.id, 'inpatient', d.id, 'active', NOW() - INTERVAL '2 days', '胸闷、气促', '慢性心衰急性加重'
FROM patients p
JOIN departments d ON d.code = 'CARD-01'
WHERE p.mrn = 'MRN-0001'
AND NOT EXISTS (
    SELECT 1 FROM encounters e WHERE e.patient_id = p.id AND e.status = 'active'
);

INSERT INTO patient_diagnoses (encounter_id, diagnosis_code, diagnosis_name, diagnosis_type, status, diagnosed_at)
SELECT e.id, 'I50.901', '慢性心力衰竭急性加重', 'primary', 'active', NOW() - INTERVAL '2 days'
FROM encounters e
JOIN patients p ON p.id = e.patient_id
WHERE p.mrn = 'MRN-0001'
AND NOT EXISTS (
    SELECT 1 FROM patient_diagnoses d WHERE d.encounter_id = e.id AND d.diagnosis_code = 'I50.901'
);

INSERT INTO observations (patient_id, encounter_id, category, code, name, value_num, unit, abnormal_flag, observed_at, source)
SELECT p.id, e.id, 'vital', 'BP_SYS', '收缩压', 88, 'mmHg', 'low', NOW() - INTERVAL '1 hour', 'manual'
FROM patients p
JOIN encounters e ON e.patient_id = p.id AND e.status = 'active'
WHERE p.mrn = 'MRN-0001';

INSERT INTO observations (patient_id, encounter_id, category, code, name, value_num, unit, abnormal_flag, observed_at, source)
SELECT p.id, e.id, 'nursing', 'URINE_4H', '4小时尿量', 85, 'ml', 'low', NOW() - INTERVAL '30 minute', 'manual'
FROM patients p
JOIN encounters e ON e.patient_id = p.id AND e.status = 'active'
WHERE p.mrn = 'MRN-0001';

INSERT INTO care_tasks (patient_id, encounter_id, source_type, task_type, title, description, priority, status, due_at, review_required)
SELECT p.id, e.id, 'handover', 'vitals_recheck', '复测血压', '低血压风险，30分钟内复测并记录', 1, 'pending', NOW() + INTERVAL '30 minute', TRUE
FROM patients p
JOIN encounters e ON e.patient_id = p.id AND e.status = 'active'
WHERE p.mrn = 'MRN-0001';

-- Seed 10 mock cases for AI nursing demo (idempotent / FK-safe)

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

INSERT INTO departments (id, code, name, ward_type, location)
VALUES
  ('11111111-1111-1111-1111-111111111001'::uuid, 'dep-card-01', '心内护理单元A', 'inpatient', '住院楼6层')
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    ward_type = EXCLUDED.ward_type,
    location = EXCLUDED.location;

WITH seed_users(username, password_hash, full_name, role_code, title) AS (
  VALUES
    ('nurse01', 'mock_hash_123456', '张护士', 'nurse', '责任护士'),
    ('doctor01', 'mock_hash_123456', '李医生', 'attending_doctor', '主治医师')
)
INSERT INTO users (id, username, password_hash, full_name, role_code, department_id, title, status)
SELECT gen_random_uuid(), su.username, su.password_hash, su.full_name, su.role_code,
       '11111111-1111-1111-1111-111111111001'::uuid, su.title, 'active'
FROM seed_users su
ON CONFLICT (username) DO UPDATE
SET full_name = EXCLUDED.full_name,
    password_hash = EXCLUDED.password_hash,
    role_code = EXCLUDED.role_code,
    department_id = EXCLUDED.department_id,
    title = EXCLUDED.title,
    status = EXCLUDED.status,
    updated_at = NOW();

WITH seed_patients(id, mrn, inpatient_no, full_name, gender, age, blood_type, allergy_info) AS (
  VALUES
    ('33333333-3333-3333-3333-333333330001'::uuid, 'MRN-0001', 'IP-2026-0001', '张晓明', '男', 45, 'A+', '青霉素过敏'),
    ('33333333-3333-3333-3333-333333330002'::uuid, 'MRN-0002', 'IP-2026-0002', '王丽', '女', 48, 'B+', NULL),
    ('33333333-3333-3333-3333-333333330003'::uuid, 'MRN-0003', 'IP-2026-0003', '李建国', '男', 62, 'O+', '头孢过敏'),
    ('33333333-3333-3333-3333-333333330004'::uuid, 'MRN-0004', 'IP-2026-0004', '赵敏', '女', 36, 'AB+', NULL),
    ('33333333-3333-3333-3333-333333330005'::uuid, 'MRN-0005', 'IP-2026-0005', '陈伟', '男', 71, 'A-', '阿司匹林过敏'),
    ('33333333-3333-3333-3333-333333330006'::uuid, 'MRN-0006', 'IP-2026-0006', '周芳', '女', 54, 'O-', NULL),
    ('33333333-3333-3333-3333-333333330007'::uuid, 'MRN-0007', 'IP-2026-0007', '孙强', '男', 59, 'B-', NULL),
    ('33333333-3333-3333-3333-333333330008'::uuid, 'MRN-0008', 'IP-2026-0008', '何静', '女', 67, 'A+', '磺胺类过敏'),
    ('33333333-3333-3333-3333-333333330009'::uuid, 'MRN-0009', 'IP-2026-0009', '郭林', '男', 41, 'O+', NULL),
    ('33333333-3333-3333-3333-333333330010'::uuid, 'MRN-0010', 'IP-2026-0010', '刘娜', '女', 29, 'B+', NULL)
)
INSERT INTO patients (id, mrn, inpatient_no, full_name, gender, age, blood_type, allergy_info, current_status)
SELECT id, mrn, inpatient_no, full_name, gender, age, blood_type, allergy_info, 'admitted'
FROM seed_patients
ON CONFLICT (mrn) DO UPDATE
SET inpatient_no = EXCLUDED.inpatient_no,
    full_name = EXCLUDED.full_name,
    gender = EXCLUDED.gender,
    age = EXCLUDED.age,
    blood_type = EXCLUDED.blood_type,
    allergy_info = EXCLUDED.allergy_info,
    current_status = EXCLUDED.current_status,
    updated_at = NOW();

WITH seed_beds(id, bed_no, room_no, mrn) AS (
  VALUES
    ('44444444-4444-4444-4444-444444440001'::uuid, '12', '612', 'MRN-0001'),
    ('44444444-4444-4444-4444-444444440002'::uuid, '15', '615', 'MRN-0002'),
    ('44444444-4444-4444-4444-444444440003'::uuid, '16', '616', 'MRN-0003'),
    ('44444444-4444-4444-4444-444444440004'::uuid, '17', '617', 'MRN-0004'),
    ('44444444-4444-4444-4444-444444440005'::uuid, '18', '618', 'MRN-0005'),
    ('44444444-4444-4444-4444-444444440006'::uuid, '19', '619', 'MRN-0006'),
    ('44444444-4444-4444-4444-444444440007'::uuid, '20', '620', 'MRN-0007'),
    ('44444444-4444-4444-4444-444444440008'::uuid, '21', '621', 'MRN-0008'),
    ('44444444-4444-4444-4444-444444440009'::uuid, '22', '622', 'MRN-0009'),
    ('44444444-4444-4444-4444-444444440010'::uuid, '23', '623', 'MRN-0010')
)
INSERT INTO beds (id, department_id, bed_no, room_no, status, current_patient_id)
SELECT sb.id, '11111111-1111-1111-1111-111111111001'::uuid, sb.bed_no, sb.room_no, 'occupied', p.id
FROM seed_beds sb
JOIN patients p ON p.mrn = sb.mrn
ON CONFLICT (department_id, bed_no) DO UPDATE
SET room_no = EXCLUDED.room_no,
    status = EXCLUDED.status,
    current_patient_id = EXCLUDED.current_patient_id,
    updated_at = NOW();

WITH refs AS (
  SELECT
    (SELECT id FROM users WHERE username='doctor01' LIMIT 1) AS doctor_id,
    (SELECT id FROM users WHERE username='nurse01'  LIMIT 1) AS nurse_id
),
seed_encounters(id, mrn, chief_complaint, admission_diagnosis) AS (
  VALUES
    ('55555555-5555-5555-5555-555555550001'::uuid, 'MRN-0001', '胸闷、乏力', '慢性心衰急性加重'),
    ('55555555-5555-5555-5555-555555550002'::uuid, 'MRN-0002', '咳嗽气促', '肺部感染恢复期'),
    ('55555555-5555-5555-5555-555555550003'::uuid, 'MRN-0003', '下肢红肿疼痛', '2型糖尿病伴感染'),
    ('55555555-5555-5555-5555-555555550004'::uuid, 'MRN-0004', '术后疼痛', '术后恢复期'),
    ('55555555-5555-5555-5555-555555550005'::uuid, 'MRN-0005', '呼吸困难', '慢阻肺急性加重'),
    ('55555555-5555-5555-5555-555555550006'::uuid, 'MRN-0006', '头晕头痛', '高血压病3级'),
    ('55555555-5555-5555-5555-555555550007'::uuid, 'MRN-0007', '持续腹痛', '急性胰腺炎'),
    ('55555555-5555-5555-5555-555555550008'::uuid, 'MRN-0008', '少尿乏力', '慢性肾病'),
    ('55555555-5555-5555-5555-555555550009'::uuid, 'MRN-0009', '意识模糊', '脑出血术后'),
    ('55555555-5555-5555-5555-555555550010'::uuid, 'MRN-0010', '产后乏力', '产后出血恢复期')
)
INSERT INTO encounters (
  id, patient_id, encounter_type, department_id, attending_doctor_id, primary_nurse_id,
  admission_at, status, chief_complaint, admission_diagnosis
)
SELECT
  se.id,
  p.id,
  'inpatient',
  '11111111-1111-1111-1111-111111111001'::uuid,
  r.doctor_id,
  r.nurse_id,
  NOW() - INTERVAL '2 days',
  'active',
  se.chief_complaint,
  se.admission_diagnosis
FROM seed_encounters se
JOIN patients p ON p.mrn = se.mrn
CROSS JOIN refs r
ON CONFLICT (id) DO UPDATE
SET status = EXCLUDED.status,
    chief_complaint = EXCLUDED.chief_complaint,
    admission_diagnosis = EXCLUDED.admission_diagnosis,
    attending_doctor_id = EXCLUDED.attending_doctor_id,
    primary_nurse_id = EXCLUDED.primary_nurse_id,
    updated_at = NOW();

DELETE FROM patient_diagnoses
WHERE encounter_id IN (
  '55555555-5555-5555-5555-555555550001'::uuid,
  '55555555-5555-5555-5555-555555550002'::uuid,
  '55555555-5555-5555-5555-555555550003'::uuid,
  '55555555-5555-5555-5555-555555550004'::uuid,
  '55555555-5555-5555-5555-555555550005'::uuid,
  '55555555-5555-5555-5555-555555550006'::uuid,
  '55555555-5555-5555-5555-555555550007'::uuid,
  '55555555-5555-5555-5555-555555550008'::uuid,
  '55555555-5555-5555-5555-555555550009'::uuid,
  '55555555-5555-5555-5555-555555550010'::uuid
);

WITH doc AS (SELECT id FROM users WHERE username='doctor01' LIMIT 1)
INSERT INTO patient_diagnoses (encounter_id, diagnosis_code, diagnosis_name, diagnosis_type, status, diagnosed_at, created_by)
SELECT v.encounter_id, v.code, v.name, 'primary', 'active', NOW(), doc.id
FROM doc
CROSS JOIN (
  VALUES
    ('55555555-5555-5555-5555-555555550001'::uuid, 'I50.901', '慢性心衰急性加重'),
    ('55555555-5555-5555-5555-555555550002'::uuid, 'J18.901', '肺部感染恢复期'),
    ('55555555-5555-5555-5555-555555550003'::uuid, 'E11.900', '2型糖尿病伴感染'),
    ('55555555-5555-5555-5555-555555550004'::uuid, 'Z48.901', '术后恢复期'),
    ('55555555-5555-5555-5555-555555550005'::uuid, 'J44.101', '慢阻肺急性加重'),
    ('55555555-5555-5555-5555-555555550006'::uuid, 'I10.900', '高血压病3级'),
    ('55555555-5555-5555-5555-555555550007'::uuid, 'K85.900', '急性胰腺炎'),
    ('55555555-5555-5555-5555-555555550008'::uuid, 'N18.900', '慢性肾病'),
    ('55555555-5555-5555-5555-555555550009'::uuid, 'I61.900', '脑出血术后'),
    ('55555555-5555-5555-5555-555555550010'::uuid, 'O72.100', '产后出血恢复期')
) AS v(encounter_id, code, name);

DELETE FROM observations
WHERE patient_id IN (SELECT id FROM patients WHERE mrn LIKE 'MRN-00%')
  AND observed_at >= NOW() - INTERVAL '3 days';

WITH seed_obs(mrn, encounter_id, category, code, name, value_text, abnormal_flag, minutes_ago, source) AS (
  VALUES
    ('MRN-0001', '55555555-5555-5555-5555-555555550001'::uuid, 'vital',   'sbp',      '收缩压',      '88 mmHg',      'low',      10, 'manual'),
    ('MRN-0001', '55555555-5555-5555-5555-555555550001'::uuid, 'nursing', 'urine_4h', '4小时尿量',   '85 ml',        'low',       8, 'manual'),
    ('MRN-0002', '55555555-5555-5555-5555-555555550002'::uuid, 'vital',   'spo2',     'SpO2',        '93%',          'low',      12, 'device'),
    ('MRN-0003', '55555555-5555-5555-5555-555555550003'::uuid, 'lab',     'glu',      '随机血糖',    '16.2 mmol/L',  'high',     14, 'lis'),
    ('MRN-0004', '55555555-5555-5555-5555-555555550004'::uuid, 'nursing', 'pain',     '疼痛评分',    '7/10',         'high',     11, 'manual'),
    ('MRN-0005', '55555555-5555-5555-5555-555555550005'::uuid, 'vital',   'spo2',     'SpO2',        '89%',          'critical',  9, 'device'),
    ('MRN-0006', '55555555-5555-5555-5555-555555550006'::uuid, 'vital',   'sbp',      '收缩压',      '176 mmHg',     'high',     13, 'manual'),
    ('MRN-0007', '55555555-5555-5555-5555-555555550007'::uuid, 'nursing', 'pain',     '疼痛评分',    '8/10',         'high',      6, 'manual'),
    ('MRN-0008', '55555555-5555-5555-5555-555555550008'::uuid, 'lab',     'k',        '血钾',        '5.9 mmol/L',   'high',      7, 'lis'),
    ('MRN-0009', '55555555-5555-5555-5555-555555550009'::uuid, 'nursing', 'gcs',      'GCS',         '12 分',        'low',       5, 'manual'),
    ('MRN-0010', '55555555-5555-5555-5555-555555550010'::uuid, 'lab',     'hb',       '血红蛋白',    '88 g/L',       'low',      16, 'lis')
)
INSERT INTO observations (patient_id, encounter_id, category, code, name, value_text, abnormal_flag, observed_at, source)
SELECT p.id, so.encounter_id, so.category, so.code, so.name, so.value_text, so.abnormal_flag,
       NOW() - (so.minutes_ago::text || ' min')::interval, so.source
FROM seed_obs so
JOIN patients p ON p.mrn = so.mrn;

DELETE FROM care_tasks
WHERE patient_id IN (SELECT id FROM patients WHERE mrn LIKE 'MRN-00%')
  AND status IN ('pending', 'in_progress');

WITH refs AS (
  SELECT
    (SELECT id FROM users WHERE username='doctor01' LIMIT 1) AS doctor_id,
    (SELECT id FROM users WHERE username='nurse01'  LIMIT 1) AS nurse_id
),
seed_tasks(mrn, encounter_id, source_type, task_type, title, description, priority, due_minutes, created_by_role) AS (
  VALUES
    ('MRN-0001', '55555555-5555-5555-5555-555555550001'::uuid, 'ai',     'vitals_recheck', '立即复测血压',           '低血压趋势复核',             1,  30, 'doctor'),
    ('MRN-0002', '55555555-5555-5555-5555-555555550002'::uuid, 'ai',     'followup',       '连续监测血氧',           '每30分钟复测SpO2',          1,  60, 'doctor'),
    ('MRN-0003', '55555555-5555-5555-5555-555555550003'::uuid, 'ai',     'followup',       '复测血糖并记录',         '餐后2小时复测并记录趋势',     1, 120, 'doctor'),
    ('MRN-0004', '55555555-5555-5555-5555-555555550004'::uuid, 'manual', 'document',       '更新术后护理记录',       '补录疼痛评分与换药情况',       2, 240, 'nurse'),
    ('MRN-0005', '55555555-5555-5555-5555-555555550005'::uuid, 'ai',     'notify_doctor',  '低氧风险上报医生',       'SpO2持续偏低需评估氧疗升级',  1,  20, 'doctor'),
    ('MRN-0006', '55555555-5555-5555-5555-555555550006'::uuid, 'manual', 'followup',       '每小时血压监测',         '高血压病情波动，密切监测',     1,  60, 'doctor'),
    ('MRN-0007', '55555555-5555-5555-5555-555555550007'::uuid, 'manual', 'followup',       '评估腹痛与补液',         '重点评估腹痛变化和液体平衡',   1,  60, 'nurse'),
    ('MRN-0008', '55555555-5555-5555-5555-555555550008'::uuid, 'ai',     'vitals_recheck', '复测电解质并评估出入量', '高钾和少尿风险复核',           1,  45, 'doctor'),
    ('MRN-0009', '55555555-5555-5555-5555-555555550009'::uuid, 'manual', 'followup',       '神经评分与瞳孔监测',     '每30分钟执行一次',            1,  30, 'doctor'),
    ('MRN-0010', '55555555-5555-5555-5555-555555550010'::uuid, 'manual', 'followup',       '监测恶露与生命体征',     '警惕二次出血与感染',           1,  60, 'nurse')
)
INSERT INTO care_tasks (
  patient_id, encounter_id, source_type, task_type, title, description, priority, status,
  assigned_to, created_by, due_at, review_required
)
SELECT
  p.id,
  st.encounter_id,
  st.source_type,
  st.task_type,
  st.title,
  st.description,
  st.priority,
  'pending',
  r.nurse_id,
  CASE WHEN st.created_by_role = 'doctor' THEN r.doctor_id ELSE r.nurse_id END,
  NOW() + (st.due_minutes::text || ' min')::interval,
  true
FROM seed_tasks st
JOIN patients p ON p.mrn = st.mrn
CROSS JOIN refs r;

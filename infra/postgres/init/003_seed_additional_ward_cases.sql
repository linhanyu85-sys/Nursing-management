-- Additional ward cases (24-30 beds) for realistic bedside voice inquiry.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

WITH seed_patients(id, mrn, inpatient_no, full_name, gender, age, blood_type, allergy_info) AS (
  VALUES
    ('33333333-3333-3333-3333-333333330011'::uuid, 'MRN-0011', 'IP-2026-0011', '吴晨',   '男', 58, 'A+', NULL),
    ('33333333-3333-3333-3333-333333330012'::uuid, 'MRN-0012', 'IP-2026-0012', '郑雪',   '女', 66, 'O+', '头孢过敏'),
    ('33333333-3333-3333-3333-333333330013'::uuid, 'MRN-0013', 'IP-2026-0013', '冯凯',   '男', 72, 'B+', NULL),
    ('33333333-3333-3333-3333-333333330014'::uuid, 'MRN-0014', 'IP-2026-0014', '徐海燕', '女', 64, 'A-', '青霉素过敏'),
    ('33333333-3333-3333-3333-333333330015'::uuid, 'MRN-0015', 'IP-2026-0015', '韩磊',   '男', 53, 'AB+', NULL),
    ('33333333-3333-3333-3333-333333330016'::uuid, 'MRN-0016', 'IP-2026-0016', '罗静',   '女', 47, 'O-', NULL),
    ('33333333-3333-3333-3333-333333330017'::uuid, 'MRN-0017', 'IP-2026-0017', '邓宏',   '男', 75, 'B-', '阿司匹林过敏')
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
    ('44444444-4444-4444-4444-444444440011'::uuid, '24', '624', 'MRN-0011'),
    ('44444444-4444-4444-4444-444444440012'::uuid, '25', '625', 'MRN-0012'),
    ('44444444-4444-4444-4444-444444440013'::uuid, '26', '626', 'MRN-0013'),
    ('44444444-4444-4444-4444-444444440014'::uuid, '28', '628', 'MRN-0014'),
    ('44444444-4444-4444-4444-444444440015'::uuid, '29', '629', 'MRN-0015'),
    ('44444444-4444-4444-4444-444444440016'::uuid, '30', '630', 'MRN-0016'),
    ('44444444-4444-4444-4444-444444440017'::uuid, '31', '631', 'MRN-0017')
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
    (SELECT id FROM users WHERE username='nurse01' LIMIT 1) AS nurse_id
),
seed_encounters(id, mrn, chief_complaint, admission_diagnosis) AS (
  VALUES
    ('55555555-5555-5555-5555-555555550011'::uuid, 'MRN-0011', '胸闷伴夜间气促', '心功能不全失代偿期'),
    ('55555555-5555-5555-5555-555555550012'::uuid, 'MRN-0012', '发热伴咳痰', '肺部感染并低氧血症'),
    ('55555555-5555-5555-5555-555555550013'::uuid, 'MRN-0013', '反复黑便', '消化道出血恢复期'),
    ('55555555-5555-5555-5555-555555550014'::uuid, 'MRN-0014', '言语含糊伴肢体无力', '急性脑梗死恢复期'),
    ('55555555-5555-5555-5555-555555550015'::uuid, 'MRN-0015', '胸痛后复查', '冠心病介入术后'),
    ('55555555-5555-5555-5555-555555550016'::uuid, 'MRN-0016', '腹泻伴脱水', '感染性肠炎'),
    ('55555555-5555-5555-5555-555555550017'::uuid, 'MRN-0017', '意识模糊', '肝性脑病风险')
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
  NOW() - INTERVAL '1 day',
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
  '55555555-5555-5555-5555-555555550011'::uuid,
  '55555555-5555-5555-5555-555555550012'::uuid,
  '55555555-5555-5555-5555-555555550013'::uuid,
  '55555555-5555-5555-5555-555555550014'::uuid,
  '55555555-5555-5555-5555-555555550015'::uuid,
  '55555555-5555-5555-5555-555555550016'::uuid,
  '55555555-5555-5555-5555-555555550017'::uuid
);

WITH doc AS (SELECT id FROM users WHERE username='doctor01' LIMIT 1)
INSERT INTO patient_diagnoses (encounter_id, diagnosis_code, diagnosis_name, diagnosis_type, status, diagnosed_at, created_by)
SELECT v.encounter_id, v.code, v.name, 'primary', 'active', NOW(), doc.id
FROM doc
CROSS JOIN (
  VALUES
    ('55555555-5555-5555-5555-555555550011'::uuid, 'I50.901', '心功能不全失代偿期'),
    ('55555555-5555-5555-5555-555555550012'::uuid, 'J18.901', '肺部感染并低氧血症'),
    ('55555555-5555-5555-5555-555555550013'::uuid, 'K92.201', '消化道出血恢复期'),
    ('55555555-5555-5555-5555-555555550014'::uuid, 'I63.901', '急性脑梗死恢复期'),
    ('55555555-5555-5555-5555-555555550015'::uuid, 'I25.101', '冠心病介入术后'),
    ('55555555-5555-5555-5555-555555550016'::uuid, 'A09.901', '感染性肠炎'),
    ('55555555-5555-5555-5555-555555550017'::uuid, 'K72.901', '肝性脑病风险')
) AS v(encounter_id, code, name);

DELETE FROM observations
WHERE patient_id IN (
  '33333333-3333-3333-3333-333333330011'::uuid,
  '33333333-3333-3333-3333-333333330012'::uuid,
  '33333333-3333-3333-3333-333333330013'::uuid,
  '33333333-3333-3333-3333-333333330014'::uuid,
  '33333333-3333-3333-3333-333333330015'::uuid,
  '33333333-3333-3333-3333-333333330016'::uuid,
  '33333333-3333-3333-3333-333333330017'::uuid
)
AND observed_at >= NOW() - INTERVAL '3 days';

WITH seed_obs(mrn, encounter_id, category, code, name, value_text, abnormal_flag, minutes_ago, source) AS (
  VALUES
    ('MRN-0011', '55555555-5555-5555-5555-555555550011'::uuid, 'vital',   'sbp',    '收缩压',   '96 mmHg',       'low',      12, 'manual'),
    ('MRN-0011', '55555555-5555-5555-5555-555555550011'::uuid, 'nursing', 'urine',  '4小时尿量', '280 ml',        'normal',    9, 'manual'),
    ('MRN-0012', '55555555-5555-5555-5555-555555550012'::uuid, 'vital',   'spo2',   'SpO2',     '90%',           'low',      10, 'device'),
    ('MRN-0013', '55555555-5555-5555-5555-555555550013'::uuid, 'lab',     'hb',     '血红蛋白', '76 g/L',        'critical', 15, 'lis'),
    ('MRN-0014', '55555555-5555-5555-5555-555555550014'::uuid, 'nursing', 'nihss',  'NIHSS',    '8 分',          'high',      8, 'manual'),
    ('MRN-0014', '55555555-5555-5555-5555-555555550014'::uuid, 'vital',   'sbp',    '收缩压',   '168 mmHg',      'high',      7, 'manual'),
    ('MRN-0015', '55555555-5555-5555-5555-555555550015'::uuid, 'vital',   'hr',     '心率',     '112 次/分',      'high',     11, 'device'),
    ('MRN-0016', '55555555-5555-5555-5555-555555550016'::uuid, 'nursing', 'stool',  '腹泻次数', '6 次/班',        'high',      9, 'manual'),
    ('MRN-0017', '55555555-5555-5555-5555-555555550017'::uuid, 'lab',     'ammonia','血氨',     '98 umol/L',     'high',      5, 'lis')
)
INSERT INTO observations (patient_id, encounter_id, category, code, name, value_text, abnormal_flag, observed_at, source)
SELECT p.id, so.encounter_id, so.category, so.code, so.name, so.value_text, so.abnormal_flag,
       NOW() - (so.minutes_ago::text || ' min')::interval, so.source
FROM seed_obs so
JOIN patients p ON p.mrn = so.mrn;

DELETE FROM care_tasks
WHERE patient_id IN (
  '33333333-3333-3333-3333-333333330011'::uuid,
  '33333333-3333-3333-3333-333333330012'::uuid,
  '33333333-3333-3333-3333-333333330013'::uuid,
  '33333333-3333-3333-3333-333333330014'::uuid,
  '33333333-3333-3333-3333-333333330015'::uuid,
  '33333333-3333-3333-3333-333333330016'::uuid,
  '33333333-3333-3333-3333-333333330017'::uuid
)
AND status IN ('pending', 'in_progress');

WITH refs AS (
  SELECT
    (SELECT id FROM users WHERE username='doctor01' LIMIT 1) AS doctor_id,
    (SELECT id FROM users WHERE username='nurse01' LIMIT 1) AS nurse_id
),
seed_tasks(mrn, encounter_id, source_type, task_type, title, description, priority, due_minutes, created_by_role) AS (
  VALUES
    ('MRN-0011', '55555555-5555-5555-5555-555555550011'::uuid, 'ai',     'followup',      '复测血压并评估容量状态', '重点观察夜间气促及尿量变化',       1,  30, 'doctor'),
    ('MRN-0012', '55555555-5555-5555-5555-555555550012'::uuid, 'ai',     'notify_doctor', '低氧风险上报医生',       '若 SpO2 持续低于92% 立即升级氧疗', 1,  20, 'doctor'),
    ('MRN-0013', '55555555-5555-5555-5555-555555550013'::uuid, 'manual', 'followup',      '观察黑便与生命体征',     '警惕再次出血，必要时备血',         1,  25, 'nurse'),
    ('MRN-0014', '55555555-5555-5555-5555-555555550014'::uuid, 'ai',     'followup',      '卒中康复风险复核',       '重点观察血压、肢体肌力及吞咽情况', 1,  20, 'doctor'),
    ('MRN-0015', '55555555-5555-5555-5555-555555550015'::uuid, 'manual', 'document',      '补录术后心电监护记录',   '记录胸痛缓解情况及穿刺点观察',     2, 120, 'nurse'),
    ('MRN-0016', '55555555-5555-5555-5555-555555550016'::uuid, 'manual', 'followup',      '严密记录出入量',         '持续评估脱水与电解质紊乱风险',     1,  40, 'nurse'),
    ('MRN-0017', '55555555-5555-5555-5555-555555550017'::uuid, 'ai',     'notify_doctor', '肝性脑病风险上报',       '观察意识变化并准备保护措施',       1,  15, 'doctor')
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

param(
  [string]$SourcePath = "",
  [string]$Username = "linmeili",
  [string]$DepartmentCode = "",
  [int]$BedStart = 1,
  [int]$BedEnd = 40,
  [switch]$RequireFullBedRange,
  [switch]$ClearDepartmentBeds,
  [switch]$DryRun,
  [string]$ContainerName = "ai_nursing_postgres",
  [string]$Db = "ai_nursing",
  [string]$DbUser = "postgres"
)

$ErrorActionPreference = "Stop"

function SqlLiteral {
  param([object]$Value)
  if ($null -eq $Value) { return "NULL" }
  $text = [string]$Value
  if ([string]::IsNullOrWhiteSpace($text)) { return "NULL" }
  return "'" + $text.Replace("'", "''") + "'"
}

function Pick-FirstValue {
  param(
    [object]$Row,
    [string[]]$Keys
  )
  foreach ($key in $Keys) {
    if ($Row.PSObject.Properties.Name -contains $key) {
      $value = $Row.$key
      if ($null -ne $value) {
        $text = [string]$value
        if (-not [string]::IsNullOrWhiteSpace($text)) {
          return $text.Trim()
        }
      }
    }
  }
  return $null
}

function Normalize-BedNo {
  param([string]$RawBedNo)
  if ([string]::IsNullOrWhiteSpace($RawBedNo)) { return $null }
  $trimmed = $RawBedNo.Trim()
  if ($trimmed -match '(\d{1,4})') {
    return ([int]$Matches[1]).ToString()
  }
  $cleaned = ($trimmed -replace '[^0-9A-Za-z\-]', '')
  if ([string]::IsNullOrWhiteSpace($cleaned)) { return $null }
  return $cleaned
}

function Normalize-Age {
  param([string]$RawAge)
  if ([string]::IsNullOrWhiteSpace($RawAge)) { return $null }
  if ($RawAge -match '(\d{1,3})') {
    return [int]$Matches[1]
  }
  return $null
}

function Normalize-Date {
  param([string]$RawDate)
  if ([string]::IsNullOrWhiteSpace($RawDate)) { return $null }
  try {
    $dt = [datetime]$RawDate
    return $dt.ToString("yyyy-MM-dd")
  } catch {
    return $null
  }
}

function Ensure-SourcePath {
  param([string]$InputPath)
  if ($InputPath -and (Test-Path $InputPath)) {
    return (Resolve-Path $InputPath).Path
  }
  $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  $defaultDir = Join-Path $projectRoot "data\his_import"
  if (-not (Test-Path $defaultDir)) {
    throw "HIS source not found. Pass -SourcePath, or put csv/json/jsonl file under: $defaultDir"
  }
  $candidate = Get-ChildItem -Path $defaultDir -File -ErrorAction SilentlyContinue `
    | Where-Object { $_.Extension.ToLower() -in @(".csv", ".json", ".jsonl") } `
    | Sort-Object LastWriteTime -Descending `
    | Select-Object -First 1
  if (-not $candidate) {
    throw "HIS source not found. Pass -SourcePath, or put csv/json/jsonl file under: $defaultDir"
  }
  return $candidate.FullName
}

function Load-SourceRecords {
  param([string]$Path)
  $ext = [System.IO.Path]::GetExtension($Path).ToLower()
  switch ($ext) {
    ".csv" {
      return @(Import-Csv -Path $Path -Encoding UTF8)
    }
    ".json" {
      $raw = Get-Content -Raw -Path $Path -Encoding UTF8
      $jsonObj = ConvertFrom-Json -InputObject $raw -Depth 20
      if ($jsonObj -is [System.Array]) { return @($jsonObj) }
      foreach ($key in @("records", "rows", "data", "items")) {
        if ($jsonObj.PSObject.Properties.Name -contains $key) {
          $v = $jsonObj.$key
          if ($v -is [System.Array]) { return @($v) }
        }
      }
      return @($jsonObj)
    }
    ".jsonl" {
      $lines = Get-Content -Path $Path -Encoding UTF8
      $rows = @()
      foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $rows += (ConvertFrom-Json -InputObject $line -Depth 20)
      }
      return $rows
    }
    default {
      throw "Unsupported source format: $ext (supported: csv/json/jsonl)"
    }
  }
}

function Invoke-Psql {
  param([string]$Sql)
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) {
    throw "docker not found."
  }
  $exists = & $docker.Source ps --filter "name=$ContainerName" --format "{{.Names}}"
  if (-not ($exists -contains $ContainerName)) {
    throw "postgres container not running: $ContainerName"
  }
  $tmpSql = [System.IO.Path]::GetTempFileName()
  $containerSql = "/tmp/codex_import_" + [System.Guid]::NewGuid().ToString("N") + ".sql"
  try {
    [System.IO.File]::WriteAllText($tmpSql, $Sql, [System.Text.Encoding]::UTF8)
    & $docker.Source cp $tmpSql "${ContainerName}:$containerSql" | Out-Null
    if ($LASTEXITCODE -ne 0) {
      throw "docker cp sql failed."
    }
    return (& $docker.Source exec $ContainerName psql -v ON_ERROR_STOP=1 -U $DbUser -d $Db -P pager=off -A -F "|" -t -f $containerSql)
  } finally {
    try {
      & $docker.Source exec $ContainerName rm -f $containerSql | Out-Null
    } catch {}
    Remove-Item $tmpSql -Force -ErrorAction SilentlyContinue
  }
}

$resolvedSource = Ensure-SourcePath -InputPath $SourcePath
$sourceRecords = Load-SourceRecords -Path $resolvedSource
if (-not $sourceRecords -or $sourceRecords.Count -eq 0) {
  throw "No rows loaded from source: $resolvedSource"
}

$normalized = New-Object System.Collections.Generic.List[object]
$invalidRows = New-Object System.Collections.Generic.List[string]

$rowNo = 0
foreach ($row in $sourceRecords) {
  $rowNo += 1
  $bedNo = Normalize-BedNo (Pick-FirstValue -Row $row -Keys @("bed_no", "bedNo", "bed", "bed_id", "bedId", "bed_number", "ward_bed_no"))
  $roomNo = Pick-FirstValue -Row $row -Keys @("room_no", "roomNo", "room", "room_id", "roomId", "room_number")
  $mrn = Pick-FirstValue -Row $row -Keys @("mrn", "MRN", "patient_mrn", "medical_record_no", "medical_record_number")
  $inpatientNo = Pick-FirstValue -Row $row -Keys @("inpatient_no", "inpatientNo", "admission_no", "admissionNo", "visit_no", "hospitalization_no")
  $fullName = Pick-FirstValue -Row $row -Keys @("full_name", "fullName", "name", "patient_name", "patientName")
  $gender = Pick-FirstValue -Row $row -Keys @("gender", "sex")
  $age = Normalize-Age (Pick-FirstValue -Row $row -Keys @("age"))
  $birthDate = Normalize-Date (Pick-FirstValue -Row $row -Keys @("birth_date", "birthDate", "dob", "date_of_birth"))
  $chiefComplaint = Pick-FirstValue -Row $row -Keys @("chief_complaint", "chiefComplaint")
  $admissionDiagnosis = Pick-FirstValue -Row $row -Keys @("admission_diagnosis", "admissionDiagnosis", "diagnosis", "primary_diagnosis")

  if (-not $mrn -and $inpatientNo) {
    $mrn = "AUTO-" + $inpatientNo
  }
  if (-not $bedNo -or -not $fullName -or -not $mrn) {
    $invalidRows.Add("row=$rowNo missing required fields (bed_no/full_name/mrn|inpatient_no)") | Out-Null
    continue
  }

  $normalized.Add([PSCustomObject]@{
      bed_no = $bedNo
      room_no = $roomNo
      mrn = $mrn
      inpatient_no = $inpatientNo
      full_name = $fullName
      gender = $gender
      age = $age
      birth_date = $birthDate
      chief_complaint = $chiefComplaint
      admission_diagnosis = $admissionDiagnosis
    }) | Out-Null
}

if ($normalized.Count -eq 0) {
  throw "No valid rows after normalization."
}

$dupBed = $normalized | Group-Object bed_no | Where-Object { $_.Count -gt 1 }
if ($dupBed) {
  throw ("Duplicate bed_no found: " + (($dupBed | ForEach-Object { $_.Name }) -join ","))
}

$dupMrn = $normalized | Group-Object mrn | Where-Object { $_.Count -gt 1 }
if ($dupMrn) {
  throw ("Duplicate mrn found: " + (($dupMrn | ForEach-Object { $_.Name }) -join ","))
}

if ($RequireFullBedRange) {
  if ($BedStart -gt $BedEnd) {
    $tmp = $BedStart
    $BedStart = $BedEnd
    $BedEnd = $tmp
  }
  $present = @{}
  foreach ($item in $normalized) {
    $present[[int]$item.bed_no] = $true
  }
  $missing = New-Object System.Collections.Generic.List[string]
  for ($i = $BedStart; $i -le $BedEnd; $i++) {
    if (-not $present.ContainsKey($i)) {
      $missing.Add($i.ToString()) | Out-Null
    }
  }
  if ($missing.Count -gt 0) {
    throw ("Full bed range check failed, missing beds: " + ($missing -join ","))
  }
}

$userSql = @"
SELECT u.id::text, COALESCE(d.code, '')
FROM users u
LEFT JOIN departments d ON d.id = u.department_id
WHERE u.username = $(SqlLiteral $Username)
LIMIT 1;
"@
$userLine = @(Invoke-Psql -Sql $userSql) | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($userLine)) {
  throw "User not found: $Username"
}
$userParts = $userLine.Split("|")
$userId = $userParts[0]
$userDeptCode = if ($userParts.Length -gt 1) { $userParts[1] } else { "" }

$targetDepartmentCode = if ([string]::IsNullOrWhiteSpace($DepartmentCode)) { $userDeptCode } else { $DepartmentCode.Trim() }
if ([string]::IsNullOrWhiteSpace($targetDepartmentCode)) {
  throw "No department code resolved. Pass -DepartmentCode."
}

$depSql = @"
WITH inserted AS (
  INSERT INTO departments (code, name, ward_type, location)
  SELECT $(SqlLiteral $targetDepartmentCode), $(SqlLiteral ("Ward-" + $targetDepartmentCode)), 'inpatient', 'HIS import'
  WHERE NOT EXISTS (SELECT 1 FROM departments WHERE code = $(SqlLiteral $targetDepartmentCode))
  RETURNING id::text
)
SELECT COALESCE(
  (SELECT id::text FROM departments WHERE code = $(SqlLiteral $targetDepartmentCode) LIMIT 1),
  (SELECT id::text FROM inserted LIMIT 1)
);
"@
$targetDepartmentId = (@(Invoke-Psql -Sql $depSql) | Select-Object -First 1).Trim()
if ([string]::IsNullOrWhiteSpace($targetDepartmentId)) {
  throw "Failed to resolve department id for code: $targetDepartmentCode"
}

$bindSql = @"
UPDATE users
SET department_id = $(SqlLiteral $targetDepartmentId)::uuid,
    updated_at = NOW()
WHERE username = $(SqlLiteral $Username);
"@
[void](Invoke-Psql -Sql $bindSql)

$valueLines = New-Object System.Collections.Generic.List[string]
foreach ($r in $normalized) {
  $ageSql = if ($null -eq $r.age) { "NULL" } else { [int]$r.age }
  $valueLines.Add("(" + (SqlLiteral $r.bed_no) + "," +
    (SqlLiteral $r.room_no) + "," +
    (SqlLiteral $r.mrn) + "," +
    (SqlLiteral $r.inpatient_no) + "," +
    (SqlLiteral $r.full_name) + "," +
    (SqlLiteral $r.gender) + "," +
    "$ageSql," +
    (SqlLiteral $r.birth_date) + "," +
    (SqlLiteral $r.chief_complaint) + "," +
    (SqlLiteral $r.admission_diagnosis) + ")") | Out-Null
}

$clearBedsSql = ""
if ($ClearDepartmentBeds) {
  $clearBedsSql = @"
UPDATE beds
SET status = 'empty',
    current_patient_id = NULL,
    updated_at = NOW()
WHERE department_id = $(SqlLiteral $targetDepartmentId)::uuid
  AND bed_no NOT IN (SELECT bed_no FROM tmp_his_import);
"@
}

$importSql = @"
CREATE TEMP TABLE tmp_his_import (
  bed_no TEXT NOT NULL,
  room_no TEXT NULL,
  mrn TEXT NOT NULL,
  inpatient_no TEXT NULL,
  full_name TEXT NOT NULL,
  gender TEXT NULL,
  age INTEGER NULL,
  birth_date TEXT NULL,
  chief_complaint TEXT NULL,
  admission_diagnosis TEXT NULL
);

INSERT INTO tmp_his_import (
  bed_no, room_no, mrn, inpatient_no, full_name, gender, age, birth_date, chief_complaint, admission_diagnosis
)
VALUES
$($valueLines -join ",`n");

INSERT INTO patients (
  mrn, inpatient_no, full_name, gender, birth_date, age, current_status, updated_at
)
SELECT
  t.mrn,
  NULLIF(t.inpatient_no, ''),
  t.full_name,
  NULLIF(t.gender, ''),
  CASE WHEN NULLIF(t.birth_date, '') IS NULL THEN NULL ELSE NULLIF(t.birth_date, '')::date END,
  t.age,
  'admitted',
  NOW()
FROM tmp_his_import t
ON CONFLICT (mrn) DO UPDATE
SET inpatient_no = EXCLUDED.inpatient_no,
    full_name = EXCLUDED.full_name,
    gender = EXCLUDED.gender,
    birth_date = EXCLUDED.birth_date,
    age = EXCLUDED.age,
    current_status = 'admitted',
    updated_at = NOW();

WITH dep AS (SELECT $(SqlLiteral $targetDepartmentId)::uuid AS id)
INSERT INTO beds (department_id, bed_no, room_no, status, current_patient_id, updated_at)
SELECT dep.id, t.bed_no, NULLIF(t.room_no, ''), 'occupied', p.id, NOW()
FROM tmp_his_import t
JOIN patients p ON p.mrn = t.mrn
CROSS JOIN dep
ON CONFLICT (department_id, bed_no) DO UPDATE
SET room_no = EXCLUDED.room_no,
    status = 'occupied',
    current_patient_id = EXCLUDED.current_patient_id,
    updated_at = NOW();

$clearBedsSql

WITH dep AS (SELECT $(SqlLiteral $targetDepartmentId)::uuid AS id)
UPDATE encounters e
SET encounter_type = 'inpatient',
    department_id = dep.id,
    status = 'active',
    admission_at = COALESCE(e.admission_at, NOW()),
    chief_complaint = COALESCE(NULLIF(t.chief_complaint, ''), e.chief_complaint),
    admission_diagnosis = COALESCE(NULLIF(t.admission_diagnosis, ''), e.admission_diagnosis),
    updated_at = NOW()
FROM tmp_his_import t
JOIN patients p ON p.mrn = t.mrn
CROSS JOIN dep
WHERE e.patient_id = p.id
  AND e.status = 'active';

WITH dep AS (SELECT $(SqlLiteral $targetDepartmentId)::uuid AS id)
INSERT INTO encounters (
  patient_id, encounter_type, department_id, status, admission_at, chief_complaint, admission_diagnosis, updated_at
)
SELECT
  p.id,
  'inpatient',
  dep.id,
  'active',
  NOW(),
  NULLIF(t.chief_complaint, ''),
  NULLIF(t.admission_diagnosis, ''),
  NOW()
FROM tmp_his_import t
JOIN patients p ON p.mrn = t.mrn
CROSS JOIN dep
WHERE NOT EXISTS (
  SELECT 1
  FROM encounters e
  WHERE e.patient_id = p.id
    AND e.status = 'active'
);

DELETE FROM patient_diagnoses pd
USING encounters e, patients p, tmp_his_import t
WHERE pd.encounter_id = e.id
  AND e.patient_id = p.id
  AND p.mrn = t.mrn
  AND pd.diagnosis_type = 'primary';

INSERT INTO patient_diagnoses (
  encounter_id, diagnosis_name, diagnosis_type, status, diagnosed_at, created_by
)
SELECT
  e.id,
  NULLIF(t.admission_diagnosis, ''),
  'primary',
  'active',
  NOW(),
  $(SqlLiteral $userId)::uuid
FROM tmp_his_import t
JOIN patients p ON p.mrn = t.mrn
JOIN encounters e ON e.patient_id = p.id AND e.status = 'active'
WHERE NULLIF(t.admission_diagnosis, '') IS NOT NULL;

INSERT INTO audit_logs (user_id, action, resource_type, detail, device_info)
VALUES (
  $(SqlLiteral $userId)::uuid,
  'his_batch_import',
  'patients',
  jsonb_build_object(
    'source_path', $(SqlLiteral $resolvedSource),
    'department_code', $(SqlLiteral $targetDepartmentCode),
    'import_rows', (SELECT count(*) FROM tmp_his_import),
    'clear_department_beds', $(if ($ClearDepartmentBeds) { "true" } else { "false" })
  ),
  'scripts/import_his_cases_to_postgres.ps1'
);

SELECT
  (SELECT count(*) FROM tmp_his_import) AS import_rows,
  (SELECT count(*) FROM beds WHERE department_id = $(SqlLiteral $targetDepartmentId)::uuid AND status = 'occupied') AS occupied_beds,
  (SELECT count(DISTINCT p.id) FROM patients p JOIN beds b ON b.current_patient_id = p.id WHERE b.department_id = $(SqlLiteral $targetDepartmentId)::uuid) AS mapped_patients;
"@

Write-Host ("[his-import] source: {0}" -f $resolvedSource) -ForegroundColor Cyan
Write-Host ("[his-import] valid rows: {0}" -f $normalized.Count) -ForegroundColor Cyan
Write-Host ("[his-import] invalid rows: {0}" -f $invalidRows.Count) -ForegroundColor Yellow
Write-Host ("[his-import] user: {0} ({1})" -f $Username, $userId) -ForegroundColor Cyan
Write-Host ("[his-import] department: {0} ({1})" -f $targetDepartmentCode, $targetDepartmentId) -ForegroundColor Cyan

if ($DryRun) {
  Write-Host "[his-import] dry-run mode, SQL not executed." -ForegroundColor Yellow
  exit 0
}

$result = @(Invoke-Psql -Sql $importSql)
foreach ($line in $result) {
  if (-not [string]::IsNullOrWhiteSpace($line)) {
    Write-Host ("[his-import] result: {0}" -f $line) -ForegroundColor Green
  }
}
Write-Host "[his-import] completed." -ForegroundColor Green

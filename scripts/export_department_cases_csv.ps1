param(
  [string]$DepartmentCode = "dep-card-01",
  [string]$OutputPath = "",
  [string]$ContainerName = "ai_nursing_postgres",
  [string]$Db = "ai_nursing",
  [string]$DbUser = "postgres"
)

$ErrorActionPreference = "Stop"

if (-not $OutputPath) {
  $root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
  $OutputPath = Join-Path $root "data\his_import\${DepartmentCode}_current_cases.csv"
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) { throw "docker not found." }
$exists = & $docker.Source ps --filter "name=$ContainerName" --format "{{.Names}}"
if (-not ($exists -contains $ContainerName)) { throw "postgres container not running: $ContainerName" }

$sql = @"
COPY (
  SELECT
    b.bed_no,
    b.room_no,
    p.mrn,
    p.inpatient_no,
    p.full_name,
    p.gender,
    p.age,
    p.birth_date,
    e.chief_complaint,
    e.admission_diagnosis
  FROM beds b
  JOIN departments d ON d.id = b.department_id
  LEFT JOIN patients p ON p.id = b.current_patient_id
  LEFT JOIN encounters e ON e.patient_id = p.id AND e.status='active'
  WHERE d.code = '$($DepartmentCode.Replace("'","''"))'
  ORDER BY CASE WHEN b.bed_no ~ '^[0-9]+$' THEN b.bed_no::int ELSE 9999 END, b.bed_no
) TO STDOUT WITH CSV HEADER;
"@

$dir = Split-Path -Parent $OutputPath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

$result = $sql | & $docker.Source exec -i $ContainerName psql -v ON_ERROR_STOP=1 -U $DbUser -d $Db
if ($LASTEXITCODE -ne 0) {
  throw "psql export failed."
}
[System.IO.File]::WriteAllText($OutputPath, ($result -join "`r`n"), [System.Text.Encoding]::UTF8)
Write-Host ("[export] wrote: {0}" -f $OutputPath) -ForegroundColor Green

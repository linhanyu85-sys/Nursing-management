param(
  [string]$Username = "linmeili",
  [string]$FullName = "Lin Meili",
  [string]$RoleCode = "nurse",
  [string]$DepartmentCode = "dep-card-01",
  [string]$ContainerName = "ai_nursing_postgres",
  [string]$Db = "ai_nursing",
  [string]$DbUser = "postgres"
)

$ErrorActionPreference = "Stop"

function SqlEscape {
  param([string]$Text)
  $value = if ($null -eq $Text) { "" } else { [string]$Text }
  return ($value -replace "'", "''")
}

function NormalizeRoleCode {
  param([string]$Code)
  $rawValue = if ($null -eq $Code) { "" } else { [string]$Code }
  $raw = $rawValue.Trim().ToLower()
  switch ($raw) {
    "doctor" { return "attending_doctor" }
    "nurse" { return "nurse" }
    "senior_nurse" { return "senior_nurse" }
    "charge_nurse" { return "charge_nurse" }
    "attending_doctor" { return "attending_doctor" }
    "resident_doctor" { return "resident_doctor" }
    "admin" { return "admin" }
    default { return "nurse" }
  }
}

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
  Write-Host "[sync-user] docker not found, skip." -ForegroundColor Yellow
  exit 0
}

$exists = & $docker.Source ps --filter "name=$ContainerName" --format "{{.Names}}"
if (-not ($exists -contains $ContainerName)) {
  Write-Host ("[sync-user] container not running: {0}" -f $ContainerName) -ForegroundColor Yellow
  exit 0
}

$usernameEsc = SqlEscape -Text $Username
$fullNameEsc = SqlEscape -Text $FullName
$roleEsc = SqlEscape -Text (NormalizeRoleCode -Code $RoleCode)
$depEsc = SqlEscape -Text $DepartmentCode

$sql = @"
WITH dep_match AS (
  SELECT id FROM departments WHERE code = '$depEsc' LIMIT 1
),
dep_fallback AS (
  SELECT id FROM departments ORDER BY created_at LIMIT 1
),
dep_resolved AS (
  SELECT COALESCE((SELECT id FROM dep_match), (SELECT id FROM dep_fallback)) AS dep_id
)
INSERT INTO users (id, username, password_hash, full_name, role_code, department_id, title, status)
SELECT
  gen_random_uuid(),
  '$usernameEsc',
  'mock_hash_ww772305',
  '$fullNameEsc',
  '$roleEsc',
  dep_id,
  'Nurse',
  'active'
FROM dep_resolved
ON CONFLICT (username) DO UPDATE
SET full_name = EXCLUDED.full_name,
    role_code = EXCLUDED.role_code,
    department_id = EXCLUDED.department_id,
    status = 'active',
    updated_at = NOW();
"@

$bytes = [System.Text.Encoding]::UTF8.GetBytes($sql)
$tempSql = [System.IO.Path]::GetTempFileName()
[System.IO.File]::WriteAllBytes($tempSql, $bytes)

try {
  Get-Content -Raw $tempSql | & $docker.Source exec -i $ContainerName psql -v ON_ERROR_STOP=1 -U $DbUser -d $Db | Out-Null
  Write-Host ("[sync-user] upserted user: {0}" -f $Username) -ForegroundColor Green
} catch {
  Write-Host ("[sync-user] failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
  exit 1
} finally {
  Remove-Item $tempSql -Force -ErrorAction SilentlyContinue
}

param(
  [string]$DepartmentCode = "dep-card-01",
  [int]$BedStart = 1,
  [int]$BedEnd = 40,
  [ValidateSet("range", "existing")]
  [string]$CoverageMode = "range",
  [int]$PatientContextPort = 39002,
  [string]$ContainerName = "ai_nursing_postgres",
  [string]$Db = "ai_nursing",
  [string]$DbUser = "postgres"
)

$ErrorActionPreference = "Stop"

function Invoke-Psql {
  param([string]$Sql)
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) { throw "docker not found." }
  $exists = & $docker.Source ps --filter "name=$ContainerName" --format "{{.Names}}"
  if (-not ($exists -contains $ContainerName)) { throw "postgres container not running: $ContainerName" }
  return ($Sql | & $docker.Source exec -i $ContainerName psql -v ON_ERROR_STOP=1 -U $DbUser -d $Db -P pager=off -A -F "," -t)
}

if ($BedStart -gt $BedEnd) {
  $tmp = $BedStart
  $BedStart = $BedEnd
  $BedEnd = $tmp
}

$sql = @"
SELECT b.bed_no, COALESCE(p.mrn, ''), COALESCE(p.full_name, '')
FROM beds b
JOIN departments d ON d.id=b.department_id
LEFT JOIN patients p ON p.id=b.current_patient_id
WHERE d.code='$(($DepartmentCode).Replace("'", "''"))'
ORDER BY CASE WHEN b.bed_no ~ '^[0-9]+$' THEN b.bed_no::int ELSE 9999 END, b.bed_no;
"@
$rows = @(Invoke-Psql -Sql $sql)

$mapped = @{}
foreach ($line in $rows) {
  if ([string]::IsNullOrWhiteSpace($line)) { continue }
  $parts = $line.Split(",")
  $bedNo = $parts[0]
  $mrn = if ($parts.Length -gt 1) { $parts[1] } else { "" }
  if (-not [string]::IsNullOrWhiteSpace($bedNo)) {
    $mapped[$bedNo] = $mrn
  }
}

$missingInDb = New-Object System.Collections.Generic.List[string]
$missingInApi = New-Object System.Collections.Generic.List[string]

$targetBeds = New-Object System.Collections.Generic.List[string]
if ($CoverageMode -eq "existing") {
  foreach ($key in $mapped.Keys) {
    if (-not [string]::IsNullOrWhiteSpace([string]$key)) {
      $targetBeds.Add(([string]$key).Trim()) | Out-Null
    }
  }
  $targetBeds = $targetBeds | Sort-Object {
    if ($_ -match '^[0-9]+$') { [int]$_ } else { 9999 }
  }, {
    $_
  } | ForEach-Object { $_ }
} else {
  for ($i = $BedStart; $i -le $BedEnd; $i++) {
    $targetBeds.Add($i.ToString()) | Out-Null
  }
}

if (-not $targetBeds -or $targetBeds.Count -eq 0) {
  Write-Host ("[verify] department={0} coverage_mode={1} target_beds=0" -f $DepartmentCode, $CoverageMode) -ForegroundColor Yellow
  Write-Host "[verify] FAIL: no beds found for verification." -ForegroundColor Yellow
  exit 1
}

foreach ($bed in $targetBeds) {
  if (-not $mapped.ContainsKey($bed) -or [string]::IsNullOrWhiteSpace([string]$mapped[$bed])) {
    $missingInDb.Add($bed) | Out-Null
    continue
  }

  $url = "http://127.0.0.1:$PatientContextPort/beds/$bed/context?department_id=$DepartmentCode&requested_by=u_linmeili"
  try {
    $ctx = Invoke-RestMethod -Uri $url -TimeoutSec 3
    if (-not $ctx.patient_id -or -not $ctx.patient_name) {
      $missingInApi.Add($bed) | Out-Null
    }
  } catch {
    $missingInApi.Add($bed) | Out-Null
  }
}

if ($CoverageMode -eq "range") {
  Write-Host ("[verify] department={0} coverage_mode={1} bed_range={2}-{3}" -f $DepartmentCode, $CoverageMode, $BedStart, $BedEnd) -ForegroundColor Cyan
} else {
  Write-Host ("[verify] department={0} coverage_mode={1} target_beds={2}" -f $DepartmentCode, $CoverageMode, $targetBeds.Count) -ForegroundColor Cyan
}
Write-Host ("[verify] mapped_beds_in_db={0}" -f $mapped.Keys.Count) -ForegroundColor Cyan
Write-Host ("[verify] missing_in_db={0}" -f $missingInDb.Count) -ForegroundColor Yellow
if ($missingInDb.Count -gt 0) {
  Write-Host ("[verify] missing_in_db_list={0}" -f ($missingInDb -join ",")) -ForegroundColor Yellow
}
Write-Host ("[verify] missing_in_api={0}" -f $missingInApi.Count) -ForegroundColor Yellow
if ($missingInApi.Count -gt 0) {
  Write-Host ("[verify] missing_in_api_list={0}" -f ($missingInApi -join ",")) -ForegroundColor Yellow
}

if ($missingInDb.Count -gt 0 -or $missingInApi.Count -gt 0) {
  exit 1
}

Write-Host "[verify] PASS: all beds map to real patient context." -ForegroundColor Green

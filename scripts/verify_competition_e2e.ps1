param(
  [int]$ApiGatewayPort = 8000,
  [int]$DeviceGatewayPort = 8013,
  [int]$PatientContextPort = 28002,
  [string]$DepartmentCode = "dep-card-01",
  [string]$RequestedBy = "u_linmeili",
  [string]$Username = "linmeili",
  [int]$BedStart = 1,
  [int]$BedEnd = 40,
  [ValidateSet("range", "existing")]
  [string]$BedCoverageMode = "range",
  [int]$WorkflowTimeoutSec = 45,
  [string]$ContainerName = "ai_nursing_postgres",
  [string]$Db = "ai_nursing",
  [string]$DbUser = "postgres",
  [string]$OutMarkdown = "docs/competition_preflight_report.md",
  [switch]$SkipLicenseScan
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$script:failed = $false
$script:lowSignalMarkers = @(
  "`u672A`u8BC6`u522B`u5230`u6E05`u6670`u8BED`u97F3",
  "`u8BF7`u518D`u8BF4`u4E00`u904D"
)
$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
  param(
    [string]$Name,
    [bool]$Passed,
    [string]$Detail
  )
  if (-not $Passed) { $script:failed = $true }
  $checks.Add([PSCustomObject]@{
      name = $Name
      passed = $Passed
      detail = $Detail
    }) | Out-Null
  if ($Passed) {
    Write-Host ("[PASS] {0}: {1}" -f $Name, $Detail) -ForegroundColor Green
  } else {
    Write-Host ("[FAIL] {0}: {1}" -f $Name, $Detail) -ForegroundColor Red
  }
}

function Invoke-HealthCheck {
  param([string]$Url, [int]$TimeoutSec = 3)
  try {
    $resp = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
    $status = [string]($resp.status)
    if ($status -in @("ok", "ready")) {
      return [PSCustomObject]@{ ok = $true; detail = "status=$status" }
    }
    return [PSCustomObject]@{ ok = $false; detail = "unexpected_status=$status" }
  } catch {
    return [PSCustomObject]@{ ok = $false; detail = $_.Exception.Message }
  }
}

function Get-DockerCommand {
  $docker = Get-Command docker -ErrorAction SilentlyContinue
  if (-not $docker) {
    throw "docker not found."
  }
  return $docker.Source
}

function Invoke-PsqlScalar {
  param([string]$Sql)
  $dockerExe = Get-DockerCommand
  $exists = & $dockerExe ps --filter "name=$ContainerName" --format "{{.Names}}"
  if (-not ($exists -contains $ContainerName)) {
    throw "postgres container not running: $ContainerName"
  }
  $raw = $Sql | & $dockerExe exec -i $ContainerName psql -v ON_ERROR_STOP=1 -U $DbUser -d $Db -P pager=off -A -t
  if ($LASTEXITCODE -ne 0) {
    throw "psql query failed."
  }
  if ($null -eq $raw) { return "" }
  return ([string]($raw | Select-Object -First 1)).Trim()
}

function Get-TableCount {
  param([string]$TableName)
  $safe = ($TableName -replace "[^a-zA-Z0-9_]", "")
  if (-not $safe) { throw "invalid table name: $TableName" }
  $value = Invoke-PsqlScalar -Sql ("SELECT count(*)::text FROM {0};" -f $safe)
  if (-not $value) { return 0 }
  return [int]$value
}

function Get-SampleBedNo {
  $safeDepartment = ($DepartmentCode -replace "'", "''")
  $sql = @"
SELECT b.bed_no
FROM beds b
JOIN departments d ON d.id=b.department_id
WHERE d.code='$safeDepartment'
  AND b.current_patient_id IS NOT NULL
ORDER BY CASE WHEN b.bed_no ~ '^[0-9]+$' THEN b.bed_no::int ELSE 9999 END, b.bed_no
LIMIT 1;
"@
  $bed = Invoke-PsqlScalar -Sql $sql
  if (-not $bed) {
    return "12"
  }
  return $bed
}

function Wait-DeviceResult {
  param(
    [string]$SessionId,
    [int]$TimeoutSec
  )
  $resultUrl = "http://127.0.0.1:$DeviceGatewayPort/api/device/result/$SessionId"
  $deadline = (Get-Date).AddSeconds([Math]::Max($TimeoutSec, 8))
  while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 900
    try {
      $state = Invoke-RestMethod -Uri $resultUrl -TimeoutSec 4
      if ($state.status -in @("completed", "failed")) {
        return $state
      }
    } catch {
      continue
    }
  }
  return $null
}

function Invoke-DeviceWorkflow {
  param(
    [string]$Mode,
    [string]$Text,
    [string]$Label
  )
  $sid = "cmp-" + [Guid]::NewGuid().ToString("N").Substring(0, 14)
  $payload = @{
    device_id = "xiaozhi-device-local"
    session_id = $sid
    text = $Text
    mode = $Mode
    department_id = $DepartmentCode
    requested_by = $RequestedBy
  } | ConvertTo-Json -Depth 8

  $queryUrl = "http://127.0.0.1:$DeviceGatewayPort/api/device/query"
  try {
    $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($payload)
    $started = Invoke-RestMethod -Method Post -Uri $queryUrl -ContentType "application/json; charset=utf-8" -Body $bodyBytes -TimeoutSec 8
  } catch {
    Add-Check -Name ("workflow_{0}" -f $Label) -Passed $false -Detail ("query_error={0}" -f $_.Exception.Message)
    return $null
  }

  if ([string]($started.status) -ne "processing") {
    Add-Check -Name ("workflow_{0}" -f $Label) -Passed $false -Detail ("unexpected_query_status={0}" -f $started.status)
    return $null
  }

  $done = Wait-DeviceResult -SessionId $sid -TimeoutSec $WorkflowTimeoutSec
  if ($null -eq $done) {
    Add-Check -Name ("workflow_{0}" -f $Label) -Passed $false -Detail "timeout_waiting_result"
    return $null
  }

  $isCompleted = ([string]($done.status) -eq "completed")
  $summaryText = [string]($done.summary)
  $sttText = [string]($done.stt_text)
  $hasSummary = -not [string]::IsNullOrWhiteSpace($summaryText)
  $hasContext = (-not [string]::IsNullOrWhiteSpace([string]($done.resolved_bed_no))) -or (-not [string]::IsNullOrWhiteSpace([string]($done.resolved_patient_id)))
  $lowSignalHit = $false
  foreach ($marker in $script:lowSignalMarkers) {
    if (($summaryText -like "*$marker*") -or ($sttText -like "*$marker*")) {
      $lowSignalHit = $true
      break
    }
  }
  $detail = "status={0}; bed={1}; patient={2}; stt_len={3}; summary_len={4}; review_required={5}" -f `
    $done.status, `
    ([string]($done.resolved_bed_no)), `
    ([string]($done.resolved_patient_id)), `
    $sttText.Length, `
    $summaryText.Length, `
    ([string]($done.review_required))

  Add-Check -Name ("workflow_{0}" -f $Label) -Passed ($isCompleted -and $hasSummary -and $hasContext -and (-not $lowSignalHit)) -Detail $detail
  return $done
}

Write-Host "[step] competition preflight started..." -ForegroundColor Cyan

$licenseSummary = $null
if (-not $SkipLicenseScan) {
  $scanScript = Join-Path $projectRoot "scripts\scan_competition_licenses.ps1"
  if (Test-Path $scanScript) {
    try {
      & powershell -ExecutionPolicy Bypass -File $scanScript
      $scanJson = Join-Path $projectRoot "data\compliance\license_scan.json"
      if (Test-Path $scanJson) {
        $licenseSummary = (Get-Content -Raw -Path $scanJson -Encoding UTF8 | ConvertFrom-Json).summary
      }
      Add-Check -Name "license_scan" -Passed $true -Detail "scan_completed"
    } catch {
      Add-Check -Name "license_scan" -Passed $false -Detail $_.Exception.Message
    }
  } else {
    Add-Check -Name "license_scan" -Passed $false -Detail "scan_script_missing"
  }
} else {
  Add-Check -Name "license_scan" -Passed $true -Detail "skipped_by_param"
}

$apiHealth = Invoke-HealthCheck -Url ("http://127.0.0.1:{0}/health" -f $ApiGatewayPort)
Add-Check -Name "api_gateway_health" -Passed $apiHealth.ok -Detail $apiHealth.detail

$deviceHealth = Invoke-HealthCheck -Url ("http://127.0.0.1:{0}/health" -f $DeviceGatewayPort)
Add-Check -Name "device_gateway_health" -Passed $deviceHealth.ok -Detail $deviceHealth.detail

$bindingUrl = "http://127.0.0.1:$ApiGatewayPort/api/device/binding"
try {
  $binding = Invoke-RestMethod -Uri $bindingUrl -TimeoutSec 4
  $okUser = ([string]($binding.owner_username) -eq $Username)
  Add-Check -Name "device_owner_binding" -Passed $okUser -Detail ("owner_user_id={0}, owner_username={1}" -f $binding.owner_user_id, $binding.owner_username)
} catch {
  Add-Check -Name "device_owner_binding" -Passed $false -Detail $_.Exception.Message
}

$verifyScript = Join-Path $projectRoot "scripts\verify_bed_mapping.ps1"
if (-not (Test-Path $verifyScript)) {
  Add-Check -Name "bed_mapping_coverage" -Passed $false -Detail "verify_bed_mapping.ps1_missing"
} else {
  $verifyOutput = & powershell -ExecutionPolicy Bypass -File $verifyScript `
    -DepartmentCode $DepartmentCode `
    -BedStart $BedStart `
    -BedEnd $BedEnd `
    -CoverageMode $BedCoverageMode `
    -PatientContextPort $PatientContextPort `
    -ContainerName $ContainerName `
    -Db $Db `
    -DbUser $DbUser 2>&1
  $verifyExit = $LASTEXITCODE
  $verifyText = (($verifyOutput | Out-String).Trim() -replace "\r?\n", " | ")
  Add-Check -Name "bed_mapping_coverage" -Passed ($verifyExit -eq 0) -Detail $verifyText
}

$tables = @("document_drafts", "handover_records", "ai_recommendations", "audit_logs")
$before = @{}
$after = @{}
foreach ($table in $tables) {
  try {
    $before[$table] = Get-TableCount -TableName $table
  } catch {
    Add-Check -Name ("db_count_before_{0}" -f $table) -Passed $false -Detail $_.Exception.Message
    $before[$table] = -1
  }
}

$sampleBedNo = Get-SampleBedNo
Add-Check -Name "sample_bed_selected" -Passed $true -Detail ("bed_no={0}" -f $sampleBedNo)
$bedChar = [char]0x5E8A
$null = Invoke-DeviceWorkflow -Mode "patient_query" -Text ("check {0}{1} status" -f $sampleBedNo, $bedChar) -Label "patient_query"
$null = Invoke-DeviceWorkflow -Mode "document" -Text ("generate {0}{1} nursing draft" -f $sampleBedNo, $bedChar) -Label "document"
$null = Invoke-DeviceWorkflow -Mode "handover" -Text ("generate {0}{1} handover draft" -f $sampleBedNo, $bedChar) -Label "handover"
$null = Invoke-DeviceWorkflow -Mode "escalation" -Text ("{0}{1} blood pressure 92/58 and heart rate 112, triage recommendation" -f $sampleBedNo, $bedChar) -Label "recommendation"

foreach ($table in $tables) {
  try {
    $after[$table] = Get-TableCount -TableName $table
  } catch {
    Add-Check -Name ("db_count_after_{0}" -f $table) -Passed $false -Detail $_.Exception.Message
    $after[$table] = -1
  }
}

function Add-DeltaCheck {
  param(
    [string]$Name,
    [string]$Table,
    [int]$MinDelta = 1
  )
  $b = [int]($before[$Table])
  $a = [int]($after[$Table])
  if ($b -lt 0 -or $a -lt 0) {
    Add-Check -Name $Name -Passed $false -Detail ("before={0}, after={1}" -f $b, $a)
    return
  }
  $delta = $a - $b
  Add-Check -Name $Name -Passed ($delta -ge $MinDelta) -Detail ("before={0}, after={1}, delta={2}" -f $b, $a, $delta)
}

Add-DeltaCheck -Name "db_persist_document_drafts" -Table "document_drafts" -MinDelta 1
Add-DeltaCheck -Name "db_persist_handover_records" -Table "handover_records" -MinDelta 1
Add-DeltaCheck -Name "db_persist_ai_recommendations" -Table "ai_recommendations" -MinDelta 1
Add-DeltaCheck -Name "db_persist_audit_logs" -Table "audit_logs" -MinDelta 3

$outPath = Join-Path $projectRoot $OutMarkdown
$outDir = Split-Path -Parent $outPath
if (-not (Test-Path $outDir)) {
  New-Item -ItemType Directory -Path $outDir | Out-Null
}

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Competition Preflight Report") | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("Generated at: {0}" -f (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz"))) | Out-Null
$lines.Add("") | Out-Null
$lines.Add(("Target stack: api={0}, device={1}, patient_context={2}" -f $ApiGatewayPort, $DeviceGatewayPort, $PatientContextPort)) | Out-Null
$lines.Add(("Target owner: {0} ({1})" -f $Username, $RequestedBy)) | Out-Null
$lines.Add("") | Out-Null
if ($licenseSummary) {
  $lines.Add("## License Snapshot") | Out-Null
  $lines.Add("") | Out-Null
  $lines.Add(("- total: {0}" -f $licenseSummary.total)) | Out-Null
  $lines.Add(("- ok: {0}" -f $licenseSummary.ok)) | Out-Null
  $lines.Add(("- review_required: {0}" -f $licenseSummary.review_required)) | Out-Null
  $lines.Add(("- restricted: {0}" -f $licenseSummary.restricted)) | Out-Null
  $lines.Add("") | Out-Null
}
$lines.Add("## Check Results") | Out-Null
$lines.Add("") | Out-Null
$lines.Add("| Check | Result | Detail |") | Out-Null
$lines.Add("|---|---|---|") | Out-Null
foreach ($c in $checks) {
  $resultText = if ($c.passed) { "PASS" } else { "FAIL" }
  $detail = ([string]$c.detail).Replace("`r", " ").Replace("`n", " ").Trim()
  $detail = $detail.Replace("|", "/")
  $lines.Add(("| {0} | {1} | {2} |" -f $c.name, $resultText, $detail)) | Out-Null
}
$lines.Add("") | Out-Null
$lines.Add("## DB Counters") | Out-Null
$lines.Add("") | Out-Null
$lines.Add("| Table | Before | After | Delta |") | Out-Null
$lines.Add("|---|---:|---:|---:|") | Out-Null
foreach ($table in $tables) {
  $b = [int]($before[$table])
  $a = [int]($after[$table])
  $d = $a - $b
  $lines.Add(("| {0} | {1} | {2} | {3} |" -f $table, $b, $a, $d)) | Out-Null
}
$lines -join "`n" | Set-Content -Path $outPath -Encoding UTF8

Write-Host ("[report] wrote {0}" -f $OutMarkdown) -ForegroundColor Cyan
if ($script:failed) {
  Write-Host "[result] preflight FAILED. See report for details." -ForegroundColor Red
  exit 1
}

Write-Host "[result] preflight PASSED." -ForegroundColor Green
exit 0

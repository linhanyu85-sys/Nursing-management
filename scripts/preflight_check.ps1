param(
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$DepartmentId = "dep-card-01",
  [string]$ComPort = "COM5"
)

$ErrorActionPreference = "Stop"

function Test-Step {
  param(
    [string]$Name,
    [scriptblock]$Action
  )
  try {
    & $Action
    Write-Host "[PASS] $Name" -ForegroundColor Green
    return $true
  } catch {
    Write-Host "[FAIL] $Name => $($_.Exception.Message)" -ForegroundColor Red
    return $false
  }
}

$allPassed = $true

$allPassed = (Test-Step -Name "gateway health" -Action {
  $h = Invoke-RestMethod -Uri "$ApiBase/health" -TimeoutSec 8
  if ($h.status -ne "ok") { throw "health.status=$($h.status)" }
}) -and $allPassed

$allPassed = (Test-Step -Name "ward beds >= 10" -Action {
  $beds = Invoke-RestMethod -Uri "$ApiBase/api/wards/$DepartmentId/beds" -TimeoutSec 12
  if (-not $beds -or $beds.Count -lt 10) { throw "beds.count=$($beds.Count)" }
}) -and $allPassed

$allPassed = (Test-Step -Name "models list" -Action {
  $models = Invoke-RestMethod -Uri "$ApiBase/api/ai/models" -TimeoutSec 12
  if (-not $models.single_models -or $models.single_models.Count -lt 1) {
    throw "single_models empty"
  }
}) -and $allPassed

$allPassed = (Test-Step -Name "agent chat with bed 23" -Action {
  $payload = @{
    mode = "agent_cluster"
    cluster_profile = "nursing_default_cluster"
    department_id = $DepartmentId
    user_input = "23 bed current focus"
    requested_by = "u_nurse_01"
    attachments = @()
  } | ConvertTo-Json -Depth 8
  $r = Invoke-RestMethod -Uri "$ApiBase/api/ai/chat" -Method Post -ContentType "application/json" -Body $payload -TimeoutSec 30
  if (-not $r.summary) { throw "summary empty" }
}) -and $allPassed

$allPassed = (Test-Step -Name "register/login flow" -Action {
  $username = "pf_nurse_" + (Get-Random -Minimum 1000 -Maximum 9999)
  $reg = @{
    username = $username
    password = "123456"
    full_name = "preflight nurse"
    role_code = "nurse"
  } | ConvertTo-Json
  $null = Invoke-RestMethod -Uri "$ApiBase/api/auth/register" -Method Post -ContentType "application/json" -Body $reg -TimeoutSec 12
  $login = @{
    username = $username
    password = "123456"
  } | ConvertTo-Json
  $res = Invoke-RestMethod -Uri "$ApiBase/api/auth/login" -Method Post -ContentType "application/json" -Body $login -TimeoutSec 12
  if (-not $res.access_token) { throw "access_token empty" }
}) -and $allPassed

$allPassed = (Test-Step -Name "serial port open $ComPort" -Action {
  Add-Type -AssemblyName System
  $sp = New-Object System.IO.Ports.SerialPort($ComPort, 115200, [System.IO.Ports.Parity]::None, 8, [System.IO.Ports.StopBits]::One)
  $sp.ReadTimeout = 800
  $sp.Open()
  Start-Sleep -Milliseconds 200
  $sp.Close()
}) -and $allPassed

if ($allPassed) {
  Write-Host "=== PREFLIGHT OK ===" -ForegroundColor Green
  exit 0
}

Write-Host "=== PREFLIGHT FAILED ===" -ForegroundColor Red
exit 1

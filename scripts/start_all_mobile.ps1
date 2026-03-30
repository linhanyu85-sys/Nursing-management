param(
  [string]$MobileRoot = "",
  [string]$NodeRoot = "D:\软件\node",
  [string]$HostIp = "",
  [int]$Port = 8081
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path $NodeRoot)) {
  $candidateRoots = @(
    "D:\软件\node",
    "D:\software\node",
    "D:\node"
  )
  $matched = $candidateRoots | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($matched) {
    $NodeRoot = $matched
  }
}

if (-not (Test-Path $NodeRoot)) {
  $npx = Get-Command npx.cmd -ErrorAction SilentlyContinue
  if ($npx) {
    $NodeRoot = Split-Path -Parent $npx.Source
  }
}

if (-not (Test-Path $NodeRoot)) {
  throw "NodeRoot not found. Please pass -NodeRoot explicitly."
}

Write-Host "[1/6] Start docker infra..." -ForegroundColor Cyan
& (Join-Path $scriptRoot "bootstrap_local_stack.ps1")

Write-Host "[2/6] Start backend services..." -ForegroundColor Cyan
& (Join-Path $scriptRoot "start_backend_core.ps1")

Write-Host "[3/6] Wait for services..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host "[4/6] Health check..." -ForegroundColor Cyan
try {
  $health = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 8
  Write-Host ("Gateway: {0}" -f $health.Content) -ForegroundColor Green
} catch {
  Write-Host "[WARN] Gateway not ready yet, continue startup." -ForegroundColor Yellow
}

Write-Host "[5/6] Optional seed..." -ForegroundColor Cyan
$envLocal = Join-Path (Split-Path $scriptRoot -Parent) ".env.local"
$mockMode = $false
if (Test-Path $envLocal) {
  $line = Get-Content $envLocal | Where-Object { $_ -match "^MOCK_MODE=" } | Select-Object -First 1
  if ($line -match "^MOCK_MODE=true") {
    $mockMode = $true
  }
}

if ($mockMode) {
  Write-Host "[SKIP] MOCK_MODE=true, skip DB seed." -ForegroundColor Yellow
} else {
  try {
    & (Join-Path $scriptRoot "seed_10_mock_cases.ps1")
  } catch {
    Write-Host "[WARN] Seed failed, continue." -ForegroundColor Yellow
  }
}

Write-Host "[6/6] Start Expo Go..." -ForegroundColor Cyan
& (Join-Path $scriptRoot "start_mobile_expo.ps1") -MobileRoot $MobileRoot -NodeRoot $NodeRoot -HostIp $HostIp -Port $Port

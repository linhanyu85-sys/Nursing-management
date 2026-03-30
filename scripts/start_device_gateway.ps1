param(
  [int]$Port = 8013,
  [string]$ListenHost = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$svcPath = Join-Path $projectRoot "services\device-gateway"

if (-not (Test-Path $svcPath)) {
  throw "device-gateway not found: $svcPath"
}

Write-Host "[1/2] Install dependencies..." -ForegroundColor Cyan
& py -3.13 -m pip install --user -r (Join-Path $svcPath "requirements.txt") | Out-Null

Write-Host "[2/3] Release port lock (if any)..." -ForegroundColor Cyan
$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
  $processIds = $existing | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($procId in $processIds) {
    try {
      Stop-Process -Id $procId -Force -ErrorAction Stop
      Write-Host "Stopped existing process on port $Port (PID=$procId)." -ForegroundColor Yellow
    } catch {
      Write-Host "Warning: unable to stop process on port $Port (PID=$procId)." -ForegroundColor Yellow
    }
  }
  Start-Sleep -Milliseconds 600
}

Write-Host "[3/3] Start device-gateway..." -ForegroundColor Cyan
Write-Host ("URL: http://{0}:{1}" -f $ListenHost, $Port) -ForegroundColor Green
Set-Location $svcPath
& py -3.13 -m uvicorn app.main:app --host $ListenHost --port $Port

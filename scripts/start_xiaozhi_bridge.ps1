param(
  [string]$ComPort = "COM5",
  [int]$Baud = 115200,
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$DepartmentId = "dep-card-01",
  [string]$UserId = "linmeili",
  [bool]$WriteBack = $true
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$bridge = Join-Path $scriptRoot "xiaozhi_serial_agent_bridge.py"

if (-not (Test-Path $bridge)) {
  throw "Bridge script not found: $bridge"
}

$py = "py -3.13"

Write-Host "[1/4] Ensure Python deps..." -ForegroundColor Cyan
& py -3.13 -m pip install --user pyserial requests | Out-Null

Write-Host "[2/4] Check API gateway..." -ForegroundColor Cyan
$gatewayOk = $false
try {
  $health = Invoke-WebRequest -Uri "$ApiBase/health" -UseBasicParsing -TimeoutSec 6
  Write-Host ("Gateway: {0}" -f $health.Content) -ForegroundColor Green
  $gatewayOk = $true
} catch {
  Write-Host "[WARN] API gateway is not reachable. Try start backend core..." -ForegroundColor Yellow
  $startBackend = Join-Path $scriptRoot "start_backend_core.ps1"
  if (Test-Path $startBackend) {
    try {
      powershell -ExecutionPolicy Bypass -File $startBackend | Out-Null
      for ($i = 0; $i -lt 25; $i++) {
        Start-Sleep -Seconds 1
        try {
          $health = Invoke-WebRequest -Uri "$ApiBase/health" -UseBasicParsing -TimeoutSec 3
          Write-Host ("Gateway: {0}" -f $health.Content) -ForegroundColor Green
          $gatewayOk = $true
          break
        } catch {
          # wait
        }
      }
    } catch {
      Write-Host "[WARN] Backend auto-start failed, bridge will still run." -ForegroundColor Yellow
    }
  }
}

if (-not $gatewayOk) {
  Write-Host "[WARN] Gateway still unavailable. Bridge will run but AI requests may fail." -ForegroundColor Yellow
}

Write-Host "[3/4] List serial ports..." -ForegroundColor Cyan
Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name,Status | Format-Table -AutoSize

Write-Host "[4/4] Start bridge on $ComPort ..." -ForegroundColor Cyan
$args = @(
  "-3.13", $bridge,
  "--port", $ComPort,
  "--baud", "$Baud",
  "--api-base", $ApiBase,
  "--department-id", $DepartmentId,
  "--user-id", $UserId
)
if ($WriteBack) {
  $args += "--write-back"
}

& py @args

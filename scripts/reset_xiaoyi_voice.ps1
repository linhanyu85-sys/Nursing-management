param(
  [string]$ComPort = "COM7",
  [int]$Baud = 115200,
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$DepartmentId = "dep-card-01",
  [string]$UserId = "linmeili",
  [int]$GatewayPort = 8013,
  [switch]$NoConsole
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $scriptRoot "start_xiaoyi_full.ps1"

if (-not (Test-Path $launcher)) {
  throw "launcher not found: $launcher"
}

Write-Host "[1/5] Stop stale host/bridge processes..." -ForegroundColor Cyan
Get-CimInstance Win32_Process `
  | Where-Object {
      ($_.CommandLine -like "*xiaozhi_host_app.py*" -or
       $_.CommandLine -like "*start_xiaozhi_host_app.ps1*" -or
       $_.CommandLine -like "*xiaozhi_serial_agent_bridge.py*" -or
       $_.CommandLine -like "*start_xiaozhi_bridge.ps1*") -and
      ($_.ProcessId -ne $PID)
    } `
  | ForEach-Object {
      try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        Write-Host ("  stopped pid={0}" -f $_.ProcessId) -ForegroundColor Yellow
      } catch {}
    }

Write-Host "[2/5] Quick serial lock check..." -ForegroundColor Cyan
$serialProbe = @"
import serial
try:
    s=serial.Serial(r"$ComPort",$Baud,timeout=0.2)
    print("SERIAL_OK")
    s.close()
except Exception as e:
    print("SERIAL_FAIL",e)
"@
$probeOut = $serialProbe | py -3.13 -
if ($probeOut -match "SERIAL_FAIL") {
  Write-Host ("[error] {0}" -f ($probeOut -join " ")) -ForegroundColor Red
  Write-Host "[hint] Close SSCOM / serial monitor / any process using COM7, then run again." -ForegroundColor Yellow
  exit 2
}
Write-Host "  serial check ok." -ForegroundColor Green

Write-Host "[3/5] Start full local stack (skip local llm)..." -ForegroundColor Cyan
$args = @(
  "-ExecutionPolicy","Bypass",
  "-File",$launcher,
  "-ComPort",$ComPort,
  "-Baud","$Baud",
  "-ApiBase",$ApiBase,
  "-DepartmentId",$DepartmentId,
  "-UserId",$UserId,
  "-GatewayPort","$GatewayPort",
  "-SkipLocalLlm"
)
if ($NoConsole) { $args += "-NoConsole" }
& powershell @args

Write-Host "[4/5] Verify health..." -ForegroundColor Cyan
$healthOk = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 1
  try {
    $h1 = Invoke-RestMethod -TimeoutSec 2 ("http://127.0.0.1:{0}/health" -f 8000)
    $h2 = Invoke-RestMethod -TimeoutSec 2 ("http://127.0.0.1:{0}/health" -f $GatewayPort)
    if ($h1.status -eq "ok" -and $h2.status -eq "ok") {
      $healthOk = $true
      break
    }
  } catch {}
}
if (-not $healthOk) {
  Write-Host "[warn] backend health not ready in time. check logs/*.err.log" -ForegroundColor Yellow
}

Write-Host "[5/5] Wait device websocket session..." -ForegroundColor Cyan
$sessionOk = $false
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Seconds 1
  try {
    $s = Invoke-RestMethod -TimeoutSec 2 ("http://127.0.0.1:{0}/api/device/sessions" -f $GatewayPort)
    $cnt = [int]($s.count)
    Write-Host ("  [{0}] sessions={1}" -f $i, $cnt)
    if ($cnt -gt 0) {
      $sessionOk = $true
      break
    }
  } catch {
    Write-Host ("  [{0}] err={1}" -f $i, $_.Exception.Message)
  }
}

if ($sessionOk) {
  Write-Host "[ok] device session online. now say wake word + question." -ForegroundColor Green
  exit 0
}

Write-Host "[warn] no websocket session yet." -ForegroundColor Yellow
Write-Host "[hint] 1) Same Wi-Fi for board and PC; 2) disable hotspot AP isolation; 3) use port 8013 (avoid mixed 19013)." -ForegroundColor Yellow
exit 1

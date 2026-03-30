param(
  [switch]$NoConsole,
  [switch]$SkipBackend,
  [int]$GatewayPort = 8013
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$app = Join-Path $scriptRoot "xiaozhi_host_app.py"

if (-not (Test-Path $app)) {
  throw "Host app not found: $app"
}

Write-Host "[1/3] Ensure Python deps..." -ForegroundColor Cyan
& py -3.13 -m pip install --user pyserial requests | Out-Null

if (-not $SkipBackend) {
  $backendScript = Join-Path $scriptRoot "start_backend_core.ps1"
  if (Test-Path $backendScript) {
    Write-Host "[2/3] Start backend core..." -ForegroundColor Cyan
    & powershell -ExecutionPolicy Bypass -File $backendScript | Out-Null
    Write-Host ("[2.5/3] Wait device-gateway ready ({0})..." -f $GatewayPort) -ForegroundColor Cyan
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
      Start-Sleep -Milliseconds 1000
      try {
        $h = Invoke-RestMethod ("http://127.0.0.1:{0}/health" -f $GatewayPort) -TimeoutSec 2
        $o = $null
        foreach ($candidate in @("/xiaozhi/ota/", "/xiaozhi/", "/xiaoz/")) {
          try {
            $o = Invoke-RestMethod ("http://127.0.0.1:{0}{1}" -f $GatewayPort, $candidate) -TimeoutSec 2
            if ($o -and $o.firmware -ne $null) {
              break
            }
          } catch {}
        }
        if ($h.status -eq "ok" -and $o -and $o.firmware -ne $null) {
          $ready = $true
          break
        }
      } catch {
        # keep waiting
      }
    }
    if ($ready) {
      Write-Host "device-gateway ready." -ForegroundColor Green
    } else {
      Write-Host "Warning: device-gateway readiness timeout, continue startup." -ForegroundColor Yellow
    }
  } else {
    Write-Host "[WARN] start_backend_core.ps1 not found, skip backend start." -ForegroundColor Yellow
  }
} else {
  Write-Host "[2/3] Skip backend start (by parameter)." -ForegroundColor Yellow
}

Write-Host "[3/3] Start Xiaoyi host app..." -ForegroundColor Cyan
# avoid stale process occupying COM port
Get-CimInstance Win32_Process `
  | Where-Object { $_.CommandLine -like "*xiaozhi_host_app.py*" -and $_.ProcessId -ne $PID } `
  | ForEach-Object {
      try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }

# also stop known serial competitors (bridge / idf monitor / pyserial miniterm)
Get-CimInstance Win32_Process `
  | Where-Object {
      $_.ProcessId -ne $PID -and (
        $_.CommandLine -like "*xiaozhi_serial_agent_bridge.py*" -or
        $_.CommandLine -like "*start_xiaozhi_bridge.ps1*" -or
        $_.CommandLine -like "*idf.py*monitor*" -or
        $_.CommandLine -like "*pyserial*miniterm*" -or
        $_.CommandLine -like "*esptool.py*monitor*"
      )
    } `
  | ForEach-Object {
      try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        Write-Host ("Stopped COM competitor PID={0}" -f $_.ProcessId) -ForegroundColor Yellow
      } catch {}
    }

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$env:XIAOYI_AUTO_CONNECT = "1"
$env:XIAOYI_GATEWAY_PORT = "$GatewayPort"
$env:XIAOYI_STRICT_GATEWAY_PORT = "1"

if ($NoConsole) {
  Start-Process -FilePath "py" -ArgumentList @("-3.13", $app) -WorkingDirectory $scriptRoot -WindowStyle Hidden | Out-Null
  Write-Host "Host app started in background." -ForegroundColor Green
  exit 0
}

& py -3.13 $app

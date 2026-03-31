$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Push-Location $ProjectRoot
try {
  $envFile = Join-Path $ProjectRoot ".env.local"
  if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
      $line = $_.Trim()
      if (-not $line -or $line.StartsWith("#")) {
        return
      }
      $parts = $line.Split("=", 2)
      if ($parts.Count -eq 2) {
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($key) {
          [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
      }
    }
    Write-Host "Loaded env from .env.local" -ForegroundColor Green
  } else {
    Write-Host "Warning: .env.local not found, services will use defaults." -ForegroundColor Yellow
  }

  $logsDir = Join-Path $ProjectRoot "logs"
  if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
  }

  $services = @(
    @{ path = "services/audit-service"; port = 8007 },
    @{ path = "services/auth-service"; port = 8012 },
    @{ path = "services/patient-context-service"; port = 8002 },
    @{ path = "services/agent-orchestrator"; port = 8003 },
    @{ path = "services/handover-service"; port = 8004 },
    @{ path = "services/recommendation-service"; port = 8005 },
    @{ path = "services/document-service"; port = 8006 },
    @{ path = "services/asr-service"; port = 8008 },
    @{ path = "services/tts-service"; port = 8009 },
    @{ path = "services/multimodal-med-service"; port = 8010 },
    @{ path = "services/collaboration-service"; port = 8011 },
    @{ path = "services/device-gateway"; port = 8013 },
    @{ path = "services/api-gateway"; port = 8000 }
  )

  foreach ($svc in $services) {
    $svcPath = Join-Path $ProjectRoot $svc.path
    $port = [int]$svc.port
    $outLog = Join-Path $logsDir ("svc_{0}.out.log" -f $port)
    $errLog = Join-Path $logsDir ("svc_{0}.err.log" -f $port)

    $existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    if ($existing) {
      foreach ($conn in $existing) {
        try {
          Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop
          Write-Host "Stopped existing process on port $port (PID=$($conn.OwningProcess))." -ForegroundColor Yellow
        } catch {
          Write-Host "Warning: unable to stop process on port $port (PID=$($conn.OwningProcess)); trying taskkill..." -ForegroundColor Yellow
          try {
            taskkill /PID $($conn.OwningProcess) /F | Out-Null
            Write-Host "taskkill sent for PID=$($conn.OwningProcess)." -ForegroundColor Yellow
          } catch {
            Write-Host "Warning: taskkill also failed for PID=$($conn.OwningProcess)." -ForegroundColor Yellow
          }
        }
      }
      Start-Sleep -Milliseconds 600

      $stillListening = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
      if ($stillListening) {
        $alivePids = ($stillListening | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
        Write-Host "Warning: port $port still occupied by PID(s): $alivePids. Skip relaunch and keep existing listener." -ForegroundColor Yellow
        continue
      }
    }

    if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
    if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

    Write-Host "Starting $($svc.path) on port $port ..."
    Start-Process py `
      -WorkingDirectory $svcPath `
      -ArgumentList @("-3.13", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$port") `
      -WindowStyle Hidden `
      -RedirectStandardOutput $outLog `
      -RedirectStandardError $errLog | Out-Null
  }

  Write-Host "All backend services start commands were sent. Logs: $logsDir" -ForegroundColor Green
} finally {
  Pop-Location
}

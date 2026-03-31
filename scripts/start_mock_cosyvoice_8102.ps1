$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$app = Join-Path $scriptRoot "mock_cosyvoice_8102.py"

if (-not (Test-Path $app)) {
  throw "Not found: $app"
}

$existing = Get-NetTCPConnection -State Listen -LocalPort 8102 -ErrorAction SilentlyContinue
if ($existing) {
  foreach ($conn in $existing) {
    try { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction Stop } catch {}
  }
  Start-Sleep -Milliseconds 500
}

Write-Host "Starting mock cosyvoice on :8102 ..." -ForegroundColor Cyan
Start-Process py `
  -WorkingDirectory $scriptRoot `
  -ArgumentList @("-3.13", "-m", "uvicorn", "mock_cosyvoice_8102:app", "--host", "0.0.0.0", "--port", "8102") `
  -WindowStyle Hidden | Out-Null

Start-Sleep -Seconds 1
Invoke-RestMethod http://127.0.0.1:8102/health

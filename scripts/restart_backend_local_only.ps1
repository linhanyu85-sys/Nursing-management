param(
  [switch]$SkipLocalLlm
)

$ErrorActionPreference = "Continue"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "[1/4] Kill backend ports..." -ForegroundColor Cyan
$ports = 8000,8002,8003,8004,8005,8006,8007,8008,8009,8010,8011,8012
foreach ($p in $ports) {
  $conns = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    cmd /c "taskkill /PID $($c.OwningProcess) /F" | Out-Null
  }
}
Start-Sleep -Milliseconds 800

if (-not $SkipLocalLlm) {
  Write-Host "[2/4] Start local CN LLM on 9100..." -ForegroundColor Cyan
  & powershell -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "start_local_cn_llm.ps1") -Profile minicpm4b -Port 9100 -StartupTimeoutSec 240
} else {
  Write-Host "[2/4] Skip local LLM startup." -ForegroundColor Yellow
}

Write-Host "[3/4] Start backend services..." -ForegroundColor Cyan
& powershell -ExecutionPolicy Bypass -File (Join-Path $scriptRoot "start_backend_core.ps1")

Write-Host "[4/4] Verify local-only + mock mode..." -ForegroundColor Cyan
foreach ($url in @("http://127.0.0.1:8003/version","http://127.0.0.1:8005/version","http://127.0.0.1:8006/version")) {
  try {
    $v = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 6
    Write-Host ("[OK] {0} => mock_mode={1}, local_only_mode={2}" -f $url, $v.mock_mode, $v.local_only_mode) -ForegroundColor Green
  } catch {
    Write-Host ("[FAIL] {0} => {1}" -f $url, $_.Exception.Message) -ForegroundColor Yellow
  }
}

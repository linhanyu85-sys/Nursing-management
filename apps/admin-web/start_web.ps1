param(
  [int]$Port = 8099
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "[admin-web] root: $root" -ForegroundColor Cyan

$started = $false
$serverProcess = $null
$python = "C:\Users\58258\.codegeex\mamba\envs\codegeex-agent\python.exe"

function Wait-UrlReady {
  param(
    [string]$Url,
    [int]$Retries = 10
  )
  for ($i = 0; $i -lt $Retries; $i++) {
    Start-Sleep -Milliseconds 350
    try {
      $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
      return $true
    } catch {
      continue
    }
  }
  return $false
}

if (Test-Path $python) {
  try {
    $serverProcess = Start-Process -FilePath $python -ArgumentList "-m http.server $Port" -WorkingDirectory $root -PassThru
    if (Wait-UrlReady -Url "http://127.0.0.1:$Port/index.html") {
      $started = $true
      Write-Host "[admin-web] started on http://127.0.0.1:$Port" -ForegroundColor Green
    } elseif ($serverProcess) {
      Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }
  } catch {
    Write-Host "[admin-web] python start failed: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

if ($started) {
  Start-Process "http://127.0.0.1:$Port/index.html"
  exit 0
}

Write-Host "[admin-web] fallback: open local index.html directly." -ForegroundColor Yellow
Start-Process (Join-Path $root "index.html")

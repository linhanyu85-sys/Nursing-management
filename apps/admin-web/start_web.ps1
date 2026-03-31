param(
  [int]$Port = 8099
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host "[web] root: $root" -ForegroundColor Cyan

$started = $false
$serverProcess = $null

function Wait-UrlReady {
  param(
    [string]$Url,
    [int]$Retries = 8
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

if (-not $started) {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) {
    try {
      $serverProcess = Start-Process -FilePath $py.Source -ArgumentList "-m http.server $Port" -WorkingDirectory $root -PassThru
      if (Wait-UrlReady -Url "http://127.0.0.1:$Port/index.html") {
        $started = $true
        Write-Host "[web] started by py on http://127.0.0.1:$Port" -ForegroundColor Green
      } else {
        if ($serverProcess) { Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue }
      }
    } catch {
      Write-Host "[web] py start failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  }
}

if (-not $started) {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) {
    try {
      $serverProcess = Start-Process -FilePath $python.Source -ArgumentList "-m http.server $Port" -WorkingDirectory $root -PassThru
      if (Wait-UrlReady -Url "http://127.0.0.1:$Port/index.html") {
        $started = $true
        Write-Host "[web] started by python on http://127.0.0.1:$Port" -ForegroundColor Green
      } else {
        if ($serverProcess) { Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue }
      }
    } catch {
      Write-Host "[web] python start failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  }
}

if (-not $started) {
  $fallbackPython = "C:\Users\58258\AppData\Local\Programs\Python\Python313\python.exe"
  if (Test-Path $fallbackPython) {
    try {
      $serverProcess = Start-Process -FilePath $fallbackPython -ArgumentList "-m http.server $Port" -WorkingDirectory $root -PassThru
      if (Wait-UrlReady -Url "http://127.0.0.1:$Port/index.html") {
        $started = $true
        Write-Host "[web] started by Python313 fallback on http://127.0.0.1:$Port" -ForegroundColor Green
      } else {
        if ($serverProcess) { Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue }
      }
    } catch {
      Write-Host "[web] fallback python start failed: $($_.Exception.Message)" -ForegroundColor Yellow
    }
  }
}

if ($started) {
  Start-Process "http://127.0.0.1:$Port/index.html"
  exit 0
}

Write-Host "[web] fallback: open local index.html directly." -ForegroundColor Yellow
Start-Process (Join-Path $root "index.html")

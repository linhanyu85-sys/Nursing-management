$ErrorActionPreference = "Continue"

$targets = @(
  "http://localhost:8000/health",
  "http://localhost:8012/health",
  "http://localhost:8002/health",
  "http://localhost:8003/health",
  "http://localhost:8004/health",
  "http://localhost:8005/health",
  "http://localhost:8006/health",
  "http://localhost:8007/health",
  "http://localhost:8008/health",
  "http://localhost:8009/health",
  "http://localhost:8010/health",
  "http://localhost:8011/health",
  "http://localhost:8013/health"
)

foreach ($url in $targets) {
  try {
    $resp = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 3
    Write-Host "[OK] $url => $($resp.status) / $($resp.service)"
  } catch {
    Write-Host "[FAIL] $url => $($_.Exception.Message)"
  }
}

param(
  [string]$RulePrefix = "AINursingLocalDev",
  [int[]]$TcpPorts = @(8000, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009, 8010, 8011, 8012, 8081, 8082, 19000, 19001),
  [int[]]$UdpPorts = @(19000, 19001)
)

$ErrorActionPreference = "Stop"

function Ensure-Rule {
  param(
    [string]$Name,
    [string]$Protocol,
    [int]$Port
  )

  $exists = Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue
  if ($exists) {
    return
  }

  New-NetFirewallRule `
    -DisplayName $Name `
    -Direction Inbound `
    -Action Allow `
    -Protocol $Protocol `
    -LocalPort $Port `
    -Profile Private `
    -Enabled True | Out-Null
}

try {
  foreach ($port in $TcpPorts) {
    Ensure-Rule -Name "$RulePrefix-TCP-$port" -Protocol TCP -Port $port
  }
  foreach ($port in $UdpPorts) {
    Ensure-Rule -Name "$RulePrefix-UDP-$port" -Protocol UDP -Port $port
  }
  Write-Host "[OK] Firewall inbound rules are ready (Private profile)." -ForegroundColor Green
} catch {
  Write-Host "[WARN] Failed to create firewall rules: $($_.Exception.Message)" -ForegroundColor Yellow
  Write-Host "[WARN] Run this script as Administrator if phone cannot connect." -ForegroundColor Yellow
}


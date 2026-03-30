param(
  [int]$GatewayPort = 29113,
  [string]$OwnerUserId = "u_linmeili",
  [string]$OwnerUsername = "linmeili"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logs = Join-Path $root "logs"
if (-not (Test-Path $logs)) {
  New-Item -ItemType Directory -Path $logs | Out-Null
}

if ($GatewayPort -lt 1000) {
  throw "GatewayPort too small: $GatewayPort"
}

# Port layout (same as existing 19xxx/29xxx scripts):
#  - patient-context: base + 2
#  - orchestrator:    base + 3
#  - asr:             base + 8
#  - device-gateway:  base + 13
$base = $GatewayPort - 13
$patientPort = $base + 2
$orchPort = $base + 3
$asrPort = $base + 8
$devPort = $base + 13

function Stop-PortOwner {
  param([int]$Port)
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if (-not $listeners) { return }
  $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($ownerId in $ownerIds) {
    if ($ownerId -and $ownerId -gt 0) {
      try {
        Stop-Process -Id $ownerId -Force -ErrorAction Stop
        Write-Host ("stopped existing process on :{0} (pid={1})" -f $Port, $ownerId) -ForegroundColor Yellow
      } catch {
        Write-Host ("warn: failed to stop pid={0} on :{1}: {2}" -f $ownerId, $Port, $_.Exception.Message) -ForegroundColor Yellow
      }
    }
  }
  Start-Sleep -Milliseconds 180
}

function Ensure-FirewallPort {
  param([int]$Port)
  if ($Port -le 0) { return }
  $ruleName = "xiaoyi-test-stack-$Port"
  try {
    $existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null | Out-String
    if ($existing -and ($existing -match $ruleName)) { return }
  } catch {}
  try {
    netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$Port | Out-Null
    Write-Host ("opened firewall TCP:{0}" -f $Port) -ForegroundColor DarkGray
  } catch {
    Write-Host ("warn: failed open firewall TCP:{0}: {1}" -f $Port, $_.Exception.Message) -ForegroundColor Yellow
  }
}

function Start-One {
  param(
    [string]$Name,
    [string]$WorkDir,
    [int]$Port,
    [hashtable]$EnvMap
  )

  foreach ($kv in $EnvMap.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($kv.Key, [string]$kv.Value, "Process")
  }

  $outLog = Join-Path $logs ($Name + ".out.log")
  $errLog = Join-Path $logs ($Name + ".err.log")
  if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
  if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

  Stop-PortOwner -Port $Port
  Ensure-FirewallPort -Port $Port

  Start-Process py `
    -WorkingDirectory $WorkDir `
    -ArgumentList @("-3.13", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog | Out-Null

  Write-Host ("started {0} on :{1}" -f $Name, $Port) -ForegroundColor Green
}

Write-Host ("[custom-stack] base={0} patient={1} orch={2} asr={3} dev={4}" -f $base, $patientPort, $orchPort, $asrPort, $devPort) -ForegroundColor Cyan

Start-One -Name ("pc{0}" -f $patientPort) -WorkDir (Join-Path $root "services\patient-context-service") -Port $patientPort -EnvMap @{}
Start-One -Name ("orch{0}" -f $orchPort) -WorkDir (Join-Path $root "services\agent-orchestrator") -Port $orchPort -EnvMap @{
  "PATIENT_CONTEXT_SERVICE_URL" = ("http://127.0.0.1:{0}" -f $patientPort)
}
Start-One -Name ("asr{0}" -f $asrPort) -WorkDir (Join-Path $root "services\asr-service") -Port $asrPort -EnvMap @{}
Start-One -Name ("dev{0}" -f $devPort) -WorkDir (Join-Path $root "services\device-gateway") -Port $devPort -EnvMap @{
  "AGENT_ORCHESTRATOR_SERVICE_URL" = ("http://127.0.0.1:{0}" -f $orchPort)
  "ASR_SERVICE_URL" = ("http://127.0.0.1:{0}" -f $asrPort)
  "TTS_SERVICE_URL" = "http://127.0.0.1:8009"
  "API_GATEWAY_URL" = "http://127.0.0.1:8000"
  "DEVICE_OWNER_USER_ID" = $OwnerUserId
  "DEVICE_OWNER_USERNAME" = $OwnerUsername
}

Write-Host ("gateway_port={0}" -f $devPort) -ForegroundColor Cyan
Write-Host ("logs: {0}" -f $logs) -ForegroundColor Cyan

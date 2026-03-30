$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logs = Join-Path $root "logs"
if (-not (Test-Path $logs)) {
  New-Item -ItemType Directory -Path $logs | Out-Null
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

function Assert-PortFree {
  param([int]$Port)
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if ($listeners) {
    $pids = ($listeners | Select-Object -ExpandProperty OwningProcess -Unique) -join ","
    throw ("port :{0} already occupied by PID(s): {1}. Please close those processes or choose another stack." -f $Port, $pids)
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

  Assert-PortFree -Port $Port
  Ensure-FirewallPort -Port $Port

  Start-Process py `
    -WorkingDirectory $WorkDir `
    -ArgumentList @("-3.13", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog | Out-Null

  Write-Host ("started {0} on :{1}" -f $Name, $Port) -ForegroundColor Green
}

Start-One -Name "pc29102" -WorkDir (Join-Path $root "services\patient-context-service") -Port 29102 -EnvMap @{}
Start-One -Name "orch29103" -WorkDir (Join-Path $root "services\agent-orchestrator") -Port 29103 -EnvMap @{
  "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:29102"
}
Start-One -Name "asr29108" -WorkDir (Join-Path $root "services\asr-service") -Port 29108 -EnvMap @{}
Start-One -Name "dev29113" -WorkDir (Join-Path $root "services\device-gateway") -Port 29113 -EnvMap @{
  "AGENT_ORCHESTRATOR_SERVICE_URL" = "http://127.0.0.1:29103"
  "ASR_SERVICE_URL" = "http://127.0.0.1:29108"
  "TTS_SERVICE_URL" = "http://127.0.0.1:8009"
  "API_GATEWAY_URL" = "http://127.0.0.1:8000"
  "DEVICE_OWNER_USER_ID" = "u_linmeili"
  "DEVICE_OWNER_USERNAME" = "linmeili"
}

Write-Host ("gateway_port=29113") -ForegroundColor Cyan
Write-Host ("logs: {0}" -f $logs) -ForegroundColor Cyan

param(
  [int]$OrchPort = 38003,
  [int]$AsrPort = 38008,
  [int]$GatewayPort = 8013,
  [int]$PatientContextPort = 28002,
  [int]$RecommendationPort = 28005,
  [int]$DocumentPort = 28006,
  [int]$HandoverPort = 38004,
  [int]$TtsPort = 28009,
  [ValidateSet("state_machine", "langgraph")]
  [string]$AgentRuntimeEngine = "state_machine",
  [string]$OwnerUserId = "u_linmeili",
  [string]$OwnerUsername = "linmeili"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$logs = Join-Path $root "logs"
if (-not (Test-Path $logs)) {
  New-Item -ItemType Directory -Path $logs | Out-Null
}

function Load-EnvFile {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) { return }
    [Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), "Process")
  }
}

function Stop-PortOwner {
  param([int]$Port)
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if (-not $listeners) { return }
  $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($ownerId in $ownerIds) {
    try {
      Stop-Process -Id $ownerId -Force -ErrorAction Stop
      Write-Host ("stopped process on :{0} (pid={1})" -f $Port, $ownerId) -ForegroundColor Yellow
    } catch {
      Write-Host ("warn: cannot stop pid={0} on :{1}: {2}" -f $ownerId, $Port, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
  Start-Sleep -Milliseconds 300
}

function Start-Service {
  param(
    [string]$Name,
    [string]$WorkDir,
    [int]$Port,
    [hashtable]$EnvMap
  )

  Stop-PortOwner -Port $Port

  foreach ($kv in $EnvMap.GetEnumerator()) {
    [Environment]::SetEnvironmentVariable($kv.Key, [string]$kv.Value, "Process")
  }

  $outLog = Join-Path $logs ($Name + ".out.log")
  $errLog = Join-Path $logs ($Name + ".err.log")
  if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
  if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

  Start-Process py `
    -WorkingDirectory $WorkDir `
    -ArgumentList @("-3.13", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog | Out-Null

  Write-Host ("started {0} on :{1}" -f $Name, $Port) -ForegroundColor Green
}

function Wait-Ready {
  param([string]$Url, [int]$Retry = 25)
  for ($i = 0; $i -lt $Retry; $i++) {
    Start-Sleep -Milliseconds 800
    try {
      $res = Invoke-RestMethod $Url -TimeoutSec 2
      if ($res -and $res.status -in @("ok", "ready")) {
        return $true
      }
    } catch {}
  }
  return $false
}

Load-EnvFile -Path (Join-Path $root ".env.local")

Start-Service -Name "patch-handover$HandoverPort" -WorkDir (Join-Path $root "services\handover-service") -Port $HandoverPort -EnvMap @{
  "MOCK_MODE" = "false"
  "HANDOVER_USE_POSTGRES" = "true"
  "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:$PatientContextPort"
  "AUDIT_SERVICE_URL" = "http://127.0.0.1:8007"
}

Start-Service -Name "patch-orch$OrchPort" -WorkDir (Join-Path $root "services\agent-orchestrator") -Port $OrchPort -EnvMap @{
  "MOCK_MODE" = "false"
  "LOCAL_ONLY_MODE" = "false"
  "AGENT_RUNTIME_ENGINE" = "$AgentRuntimeEngine"
  "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:$PatientContextPort"
  "RECOMMENDATION_SERVICE_URL" = "http://127.0.0.1:$RecommendationPort"
  "DOCUMENT_SERVICE_URL" = "http://127.0.0.1:$DocumentPort"
  "HANDOVER_SERVICE_URL" = "http://127.0.0.1:$HandoverPort"
  "COLLABORATION_SERVICE_URL" = "http://127.0.0.1:8011"
  "AUDIT_SERVICE_URL" = "http://127.0.0.1:8007"
}

Start-Service -Name "patch-asr$AsrPort" -WorkDir (Join-Path $root "services\asr-service") -Port $AsrPort -EnvMap @{
  "MOCK_MODE" = "false"
  "ASR_PROVIDER_PRIORITY" = "local_first"
  "LOCAL_ASR_MODEL_SIZE" = "large-v3"
  "LOCAL_ASR_BEAM_SIZE" = "2"
}

Start-Service -Name "patch-dev$GatewayPort" -WorkDir (Join-Path $root "services\device-gateway") -Port $GatewayPort -EnvMap @{
  "MOCK_MODE" = "false"
  "SERVICE_PORT" = "$GatewayPort"
  "ASR_SERVICE_URL" = "http://127.0.0.1:$AsrPort"
  "AGENT_ORCHESTRATOR_SERVICE_URL" = "http://127.0.0.1:$OrchPort"
  "TTS_SERVICE_URL" = "http://127.0.0.1:$TtsPort"
  "API_GATEWAY_URL" = "http://127.0.0.1:8000"
  "DEVICE_OWNER_USER_ID" = "$OwnerUserId"
  "DEVICE_OWNER_USERNAME" = "$OwnerUsername"
  "DEVICE_LISTEN_SILENCE_TIMEOUT_SEC" = "1"
  "DEVICE_LISTEN_MAX_DURATION_SEC" = "7"
  "DEVICE_CAPTURE_WAIT_MS" = "220"
  "DEVICE_MIN_AUDIO_BYTES" = "480"
  "DEVICE_STT_SAMPLE_RATE" = "16000"
  "DEVICE_TTS_SAMPLE_RATE" = "16000"
  "DEVICE_TTS_FRAME_DURATION_MS" = "40"
  "DEVICE_TTS_PACKET_PACE_MS" = "38"
  "DEVICE_TTS_MAX_CHARS" = "100"
}

$okHandover = Wait-Ready -Url "http://127.0.0.1:$HandoverPort/health"
$okOrch = Wait-Ready -Url "http://127.0.0.1:$OrchPort/health"
$okAsr = Wait-Ready -Url "http://127.0.0.1:$AsrPort/health"
$okDev = Wait-Ready -Url "http://127.0.0.1:$GatewayPort/health"

Write-Host ("ready handover={0} orch={1} asr={2} dev={3}" -f $okHandover, $okOrch, $okAsr, $okDev) -ForegroundColor Cyan
Write-Host ("gateway ws: ws://127.0.0.1:{0}/xiaozhi/v1/" -f $GatewayPort) -ForegroundColor Cyan
Write-Host ("gateway ota: http://127.0.0.1:{0}/xiaozhi/ota/" -f $GatewayPort) -ForegroundColor Cyan

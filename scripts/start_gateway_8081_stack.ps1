param(
  [switch]$SkipInstall,
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
    $key = $parts[0].Trim()
    $val = $parts[1].Trim()
    if ($key) {
      [Environment]::SetEnvironmentVariable($key, $val, "Process")
    }
  }
}

function Stop-PortOwner {
  param([int]$Port)
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if (-not $listeners) { return }
  $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($ownerId in $ownerIds) {
    if (-not $ownerId -or $ownerId -le 0) { continue }
    try {
      Stop-Process -Id $ownerId -Force -ErrorAction Stop
      Write-Host ("stopped existing process on :{0} (pid={1})" -f $Port, $ownerId) -ForegroundColor Yellow
    } catch {
      Write-Host ("warn: failed to stop pid={0} on :{1}: {2}" -f $ownerId, $Port, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
  Start-Sleep -Milliseconds 300
}

function Ensure-FirewallPort {
  param([int]$Port)
  if ($Port -le 0) { return }
  $ruleName = "xiaoyi-gateway-$Port"
  try {
    $existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null | Out-String
    if ($existing -and ($existing -match $ruleName)) { return }
  } catch {}
  try {
    netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$Port | Out-Null
  } catch {
    Write-Host ("warn: failed open firewall TCP:{0}: {1}" -f $Port, $_.Exception.Message) -ForegroundColor Yellow
  }
}

function Install-ServiceDeps {
  param([string]$WorkDir)
  $req = Join-Path $WorkDir "requirements.txt"
  if (-not (Test-Path $req)) { return }
  & py -3.13 -m pip install --user -r $req | Out-Null
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

  if (-not $SkipInstall) {
    Install-ServiceDeps -WorkDir $WorkDir
  }

  $outLog = Join-Path $logs ($Name + ".out.log")
  $errLog = Join-Path $logs ($Name + ".err.log")
  if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
  if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

  Stop-PortOwner -Port $Port
  if ($Port -in @(8081, 808, 8013)) {
    Ensure-FirewallPort -Port $Port
  }

  Start-Process py `
    -WorkingDirectory $WorkDir `
    -ArgumentList @("-3.13", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "$Port") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog | Out-Null

  Write-Host ("started {0} on :{1}" -f $Name, $Port) -ForegroundColor Green
}

function Wait-Ready {
  param([string]$Name, [string]$Url, [int]$Retry = 30)
  for ($i = 0; $i -lt $Retry; $i++) {
    Start-Sleep -Milliseconds 1000
    try {
      $res = Invoke-RestMethod $Url -TimeoutSec 2
      if ($res -and $res.status -in @("ok", "ready")) {
        Write-Host ("ready {0}: {1}" -f $Name, $Url) -ForegroundColor Green
        return $true
      }
    } catch {}
  }
  Write-Host ("warn: readiness timeout for {0}: {1}" -f $Name, $Url) -ForegroundColor Yellow
  return $false
}

Load-EnvFile -Path (Join-Path $root ".env.local")

# Replace legacy gateway instance on 8013 if it exists.
Stop-PortOwner -Port 8013

$handoverPort = 18004
$recPort = 18005
$docPort = 18006
$asrModelSize = if ($env:ASR_MODEL_SIZE) { $env:ASR_MODEL_SIZE } else { "large-v3" }
$asrBeamSize = if ($env:ASR_BEAM_SIZE) { $env:ASR_BEAM_SIZE } else { "2" }

# patient-context
Start-One -Name "pc18002" `
  -WorkDir (Join-Path $root "services\patient-context-service") `
  -Port 18002 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "DOCUMENT_SERVICE_URL" = "http://127.0.0.1:$docPort"
    "INCLUDE_VIRTUAL_EMPTY_BEDS" = "false"
    "DB_ERROR_FALLBACK_TO_MOCK" = "false"
  }

# handover
Start-One -Name "handover$handoverPort" `
  -WorkDir (Join-Path $root "services\handover-service") `
  -Port $handoverPort `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "HANDOVER_USE_POSTGRES" = "true"
    "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:18002"
    "AUDIT_SERVICE_URL" = "http://127.0.0.1:8007"
  }

# recommendation
Start-One -Name "rec$recPort" `
  -WorkDir (Join-Path $root "services\recommendation-service") `
  -Port $recPort `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "LOCAL_ONLY_MODE" = "false"
    "LOCAL_LLM_TIMEOUT_SEC" = "12"
    "RECOMMENDATION_USE_POSTGRES" = "true"
    "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:18002"
    "MULTIMODAL_SERVICE_URL" = "http://127.0.0.1:8010"
    "AUDIT_SERVICE_URL" = "http://127.0.0.1:8007"
  }

# document
Start-One -Name "doc$docPort" `
  -WorkDir (Join-Path $root "services\document-service") `
  -Port $docPort `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:18002"
    "AUDIT_SERVICE_URL" = "http://127.0.0.1:8007"
  }

# asr
Start-One -Name "asr18008" `
  -WorkDir (Join-Path $root "services\asr-service") `
  -Port 18008 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "ASR_PROVIDER_PRIORITY" = "local_first"
    "FUNASR_TIMEOUT_SEC" = "4"
    "LOCAL_ASR_MODEL_SIZE" = "$asrModelSize"
    "LOCAL_ASR_BEAM_SIZE" = "$asrBeamSize"
    "LOCAL_ASR_WARMUP_ON_STARTUP" = "true"
  }

# tts
Start-One -Name "tts18009" `
  -WorkDir (Join-Path $root "services\tts-service") `
  -Port 18009 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "COSYVOICE_BASE_URL" = "http://127.0.0.1:8102"
  }

# orchestrator
Start-One -Name "orch18003" `
  -WorkDir (Join-Path $root "services\agent-orchestrator") `
  -Port 18003 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "LOCAL_ONLY_MODE" = "false"
    "PATIENT_CONTEXT_SERVICE_URL" = "http://127.0.0.1:18002"
    "RECOMMENDATION_SERVICE_URL" = "http://127.0.0.1:$recPort"
    "DOCUMENT_SERVICE_URL" = "http://127.0.0.1:$docPort"
    "HANDOVER_SERVICE_URL" = "http://127.0.0.1:$handoverPort"
    "COLLABORATION_SERVICE_URL" = "http://127.0.0.1:8011"
    "AUDIT_SERVICE_URL" = "http://127.0.0.1:8007"
  }

# device-gateway on fixed 8081
Start-One -Name "dev8081" `
  -WorkDir (Join-Path $root "services\device-gateway") `
  -Port 8081 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "SERVICE_PORT" = "8081"
    "ASR_SERVICE_URL" = "http://127.0.0.1:18008"
    "AGENT_ORCHESTRATOR_SERVICE_URL" = "http://127.0.0.1:18003"
    "TTS_SERVICE_URL" = "http://127.0.0.1:18009"
    "API_GATEWAY_URL" = "http://127.0.0.1:8000"
    "DEVICE_LISTEN_SILENCE_TIMEOUT_SEC" = "1"
    "DEVICE_LISTEN_MAX_DURATION_SEC" = "7"
    "DEVICE_CAPTURE_WAIT_MS" = "220"
    "DEVICE_RESPONSE_DELAY_MS" = "0"
    "DEVICE_MIN_AUDIO_BYTES" = "480"
    "DEVICE_STT_SAMPLE_RATE" = "16000"
    "DEVICE_TTS_SAMPLE_RATE" = "16000"
    "DEVICE_TTS_FRAME_DURATION_MS" = "40"
    "DEVICE_TTS_PACKET_PACE_MS" = "38"
    "DEVICE_TTS_SENTENCE_GAP_MS" = "0"
    "DEVICE_TTS_MAX_CHARS" = "100"
    "DEVICE_OWNER_USER_ID" = "$OwnerUserId"
    "DEVICE_OWNER_USERNAME" = "$OwnerUsername"
  }

# compatibility gateway alias on :808 for firmwares that truncate WS URL
Start-One -Name "dev808" `
  -WorkDir (Join-Path $root "services\device-gateway") `
  -Port 808 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "SERVICE_PORT" = "808"
    "ASR_SERVICE_URL" = "http://127.0.0.1:18008"
    "AGENT_ORCHESTRATOR_SERVICE_URL" = "http://127.0.0.1:18003"
    "TTS_SERVICE_URL" = "http://127.0.0.1:18009"
    "API_GATEWAY_URL" = "http://127.0.0.1:8000"
    "DEVICE_LISTEN_SILENCE_TIMEOUT_SEC" = "1"
    "DEVICE_LISTEN_MAX_DURATION_SEC" = "7"
    "DEVICE_CAPTURE_WAIT_MS" = "220"
    "DEVICE_RESPONSE_DELAY_MS" = "0"
    "DEVICE_MIN_AUDIO_BYTES" = "480"
    "DEVICE_STT_SAMPLE_RATE" = "16000"
    "DEVICE_TTS_SAMPLE_RATE" = "16000"
    "DEVICE_TTS_FRAME_DURATION_MS" = "40"
    "DEVICE_TTS_PACKET_PACE_MS" = "38"
    "DEVICE_TTS_SENTENCE_GAP_MS" = "0"
    "DEVICE_TTS_MAX_CHARS" = "100"
    "DEVICE_OWNER_USER_ID" = "$OwnerUserId"
    "DEVICE_OWNER_USERNAME" = "$OwnerUsername"
  }

# compatibility gateway alias on :8013 for firmwares pinned to old default endpoint
Start-One -Name "dev8013" `
  -WorkDir (Join-Path $root "services\device-gateway") `
  -Port 8013 `
  -EnvMap @{
    "MOCK_MODE" = "false"
    "SERVICE_PORT" = "8013"
    "ASR_SERVICE_URL" = "http://127.0.0.1:18008"
    "AGENT_ORCHESTRATOR_SERVICE_URL" = "http://127.0.0.1:18003"
    "TTS_SERVICE_URL" = "http://127.0.0.1:18009"
    "API_GATEWAY_URL" = "http://127.0.0.1:8000"
    "DEVICE_LISTEN_SILENCE_TIMEOUT_SEC" = "1"
    "DEVICE_LISTEN_MAX_DURATION_SEC" = "7"
    "DEVICE_CAPTURE_WAIT_MS" = "220"
    "DEVICE_RESPONSE_DELAY_MS" = "0"
    "DEVICE_MIN_AUDIO_BYTES" = "480"
    "DEVICE_STT_SAMPLE_RATE" = "16000"
    "DEVICE_TTS_SAMPLE_RATE" = "16000"
    "DEVICE_TTS_FRAME_DURATION_MS" = "40"
    "DEVICE_TTS_PACKET_PACE_MS" = "38"
    "DEVICE_TTS_SENTENCE_GAP_MS" = "0"
    "DEVICE_TTS_MAX_CHARS" = "100"
    "DEVICE_OWNER_USER_ID" = "$OwnerUserId"
    "DEVICE_OWNER_USERNAME" = "$OwnerUsername"
  }

Wait-Ready -Name "pc18002" -Url "http://127.0.0.1:18002/health" | Out-Null
Wait-Ready -Name "handover$handoverPort" -Url "http://127.0.0.1:$handoverPort/health" | Out-Null
Wait-Ready -Name "rec$recPort" -Url "http://127.0.0.1:$recPort/health" | Out-Null
Wait-Ready -Name "doc$docPort" -Url "http://127.0.0.1:$docPort/health" | Out-Null
Wait-Ready -Name "asr18008" -Url "http://127.0.0.1:18008/health" | Out-Null
Wait-Ready -Name "tts18009" -Url "http://127.0.0.1:18009/health" | Out-Null
Wait-Ready -Name "orch18003" -Url "http://127.0.0.1:18003/health" | Out-Null
Wait-Ready -Name "dev8081" -Url "http://127.0.0.1:8081/health" | Out-Null
Wait-Ready -Name "dev808" -Url "http://127.0.0.1:808/health" | Out-Null
Wait-Ready -Name "dev8013" -Url "http://127.0.0.1:8013/health" | Out-Null

try {
  $ver = Invoke-RestMethod "http://127.0.0.1:8081/version" -TimeoutSec 3
  Write-Host ("gateway version on 8081: {0}" -f ($ver.version | Out-String).Trim()) -ForegroundColor Cyan
} catch {}
try {
  $ver808 = Invoke-RestMethod "http://127.0.0.1:808/version" -TimeoutSec 3
  Write-Host ("gateway alias version on 808: {0}" -f ($ver808.version | Out-String).Trim()) -ForegroundColor Cyan
} catch {}
try {
  $ver8013 = Invoke-RestMethod "http://127.0.0.1:8013/version" -TimeoutSec 3
  Write-Host ("gateway alias version on 8013: {0}" -f ($ver8013.version | Out-String).Trim()) -ForegroundColor Cyan
} catch {}

Write-Host ("logs: {0}" -f $logs) -ForegroundColor Cyan

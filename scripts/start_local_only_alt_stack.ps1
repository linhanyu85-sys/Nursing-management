param(
  [int]$GatewayPort = 18000,
  [int]$OrchestratorPort = 18003
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")

# stop same alt ports if occupied
foreach ($p in @($GatewayPort, $OrchestratorPort)) {
  $conns = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  foreach ($c in $conns) {
    try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction Stop } catch {}
  }
}

# agent-orchestrator (local only)
$orchDir = Join-Path $projectRoot "services\agent-orchestrator"
[Environment]::SetEnvironmentVariable("APP_ENV", "local", "Process")
[Environment]::SetEnvironmentVariable("APP_VERSION", "0.1.0", "Process")
[Environment]::SetEnvironmentVariable("MOCK_MODE", "false", "Process")
[Environment]::SetEnvironmentVariable("LLM_FORCE_ENABLE", "true", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_ONLY_MODE", "true", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_LLM_ENABLED", "true", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_LLM_BASE_URL", "http://127.0.0.1:9100/v1", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_LLM_API_KEY", "", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_LLM_MODEL_PRIMARY", "minicpm3-4b-q4_k_m", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_LLM_MODEL_FALLBACK", "qwen2.5-3b-instruct-q4_k_m", "Process")
[Environment]::SetEnvironmentVariable("LOCAL_LLM_TIMEOUT_SEC", "18", "Process")
[Environment]::SetEnvironmentVariable("PATIENT_CONTEXT_SERVICE_URL", "http://127.0.0.1:8002", "Process")
[Environment]::SetEnvironmentVariable("RECOMMENDATION_SERVICE_URL", "http://127.0.0.1:8005", "Process")
[Environment]::SetEnvironmentVariable("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8006", "Process")
[Environment]::SetEnvironmentVariable("AUDIT_SERVICE_URL", "http://127.0.0.1:8007", "Process")
Start-Process py -WorkingDirectory $orchDir -ArgumentList @("-3.13","-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$OrchestratorPort") -WindowStyle Hidden | Out-Null

# api-gateway (route ai to alt orchestrator)
$gwDir = Join-Path $projectRoot "services\api-gateway"
[Environment]::SetEnvironmentVariable("APP_ENV", "local", "Process")
[Environment]::SetEnvironmentVariable("APP_VERSION", "0.1.0", "Process")
[Environment]::SetEnvironmentVariable("MOCK_MODE", "false", "Process")
[Environment]::SetEnvironmentVariable("CORS_ORIGINS", "*", "Process")
[Environment]::SetEnvironmentVariable("AUTH_SERVICE_URL", "http://127.0.0.1:8012", "Process")
[Environment]::SetEnvironmentVariable("PATIENT_CONTEXT_SERVICE_URL", "http://127.0.0.1:8002", "Process")
[Environment]::SetEnvironmentVariable("AGENT_ORCHESTRATOR_SERVICE_URL", "http://127.0.0.1:$OrchestratorPort", "Process")
[Environment]::SetEnvironmentVariable("HANDOVER_SERVICE_URL", "http://127.0.0.1:8004", "Process")
[Environment]::SetEnvironmentVariable("RECOMMENDATION_SERVICE_URL", "http://127.0.0.1:8005", "Process")
[Environment]::SetEnvironmentVariable("DOCUMENT_SERVICE_URL", "http://127.0.0.1:8006", "Process")
[Environment]::SetEnvironmentVariable("AUDIT_SERVICE_URL", "http://127.0.0.1:8007", "Process")
[Environment]::SetEnvironmentVariable("ASR_SERVICE_URL", "http://127.0.0.1:8008", "Process")
[Environment]::SetEnvironmentVariable("TTS_SERVICE_URL", "http://127.0.0.1:8009", "Process")
[Environment]::SetEnvironmentVariable("MULTIMODAL_SERVICE_URL", "http://127.0.0.1:8010", "Process")
[Environment]::SetEnvironmentVariable("COLLABORATION_SERVICE_URL", "http://127.0.0.1:8011", "Process")
Start-Process py -WorkingDirectory $gwDir -ArgumentList @("-3.13","-m","uvicorn","app.main:app","--host","127.0.0.1","--port","$GatewayPort") -WindowStyle Hidden | Out-Null

Start-Sleep -Seconds 2
Write-Host "[OK] local-only alt stack started: gateway=http://127.0.0.1:$GatewayPort, orchestrator=http://127.0.0.1:$OrchestratorPort" -ForegroundColor Green

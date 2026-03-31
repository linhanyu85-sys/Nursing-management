param(
  [ValidateSet("qwen3_8b", "deepseek_r1_qwen_7b", "both")]
  [string]$Profile = "both",
  [string]$ProjectRoot = "",
  [string]$AssetsRoot = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

if (-not $AssetsRoot) {
  $AssetsRoot = Join-Path $ProjectRoot "ai model\local_cn"
}

function Ensure-Directory([string]$Path) {
  if (-not (Test-Path $Path)) {
    New-Item -Path $Path -ItemType Directory | Out-Null
  }
}

function Download-File([string]$Url, [string]$TargetPath) {
  $targetDir = Split-Path -Parent $TargetPath
  Ensure-Directory $targetDir

  Write-Host "Downloading: $Url" -ForegroundColor Cyan
  Write-Host "Target: $TargetPath" -ForegroundColor Cyan

  & curl.exe -L --fail --retry 3 --retry-delay 4 -C - -o $TargetPath $Url
  if ($LASTEXITCODE -ne 0) {
    throw "Download failed: $Url"
  }
}

$modelsRoot = Join-Path $AssetsRoot "models"
Ensure-Directory $modelsRoot

$profiles = @()
if ($Profile -eq "qwen3_8b" -or $Profile -eq "both") {
  $profiles += @{
    profile = "qwen3_8b"
    alias = "qwen3-8b"
    repo = "Qwen/Qwen3-8B-GGUF"
    note = "Official Qwen GGUF model"
    url = "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/qwen3-8b-q4_k_m.gguf"
    target = Join-Path $modelsRoot "qwen3-8b-q4_k_m.gguf"
  }
}
if ($Profile -eq "deepseek_r1_qwen_7b" -or $Profile -eq "both") {
  $profiles += @{
    profile = "deepseek_r1_qwen_7b"
    alias = "deepseek-r1-distill-qwen-7b"
    repo = "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF"
    note = "Third-party GGUF quantization for local llama.cpp deployment"
    url = "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf"
    target = Join-Path $modelsRoot "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf"
  }
}

foreach ($item in $profiles) {
  Download-File -Url $item.url -TargetPath $item.target
  Write-Host "[OK] $($item.profile) downloaded." -ForegroundColor Green
}

$manifestPath = Join-Path $modelsRoot "agent_open_models_manifest.json"
$manifest = @{
  updated_at = (Get-Date).ToString("s")
  root = $modelsRoot
  profiles = $profiles
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding utf8

Write-Host ""
Write-Host "Done. Suggested next steps:" -ForegroundColor Green
Write-Host "  1) .\\scripts\\download_llama_runtime.ps1 -Runtime cpu"
Write-Host "  2) .\\scripts\\start_local_cn_llm.ps1 -Profile custom -ModelPath `"$($profiles[0].target)`" -ModelAlias `"$($profiles[0].alias)`""
Write-Host "  3) Set LOCAL_LLM_MODEL_PLANNER / LOCAL_LLM_MODEL_REASONING in .env.local"

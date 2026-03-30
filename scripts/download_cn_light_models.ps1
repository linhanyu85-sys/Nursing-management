param(
  [ValidateSet("minicpm4b", "qwen3b", "both")]
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

function Download-File([string]$Url, [string]$TargetPath, [string]$Sha256) {
  $targetDir = Split-Path -Parent $TargetPath
  Ensure-Directory $targetDir

  Write-Host "Downloading: $Url" -ForegroundColor Cyan
  Write-Host "Target: $TargetPath" -ForegroundColor Cyan

  & curl.exe -k -L --fail --retry 3 --retry-delay 4 -C - -o $TargetPath $Url
  if ($LASTEXITCODE -ne 0) {
    throw "Download failed: $Url"
  }

  if ($Sha256) {
    $actual = (Get-FileHash -Path $TargetPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Sha256.ToLowerInvariant()) {
      throw "SHA256 mismatch for $TargetPath. expected=$Sha256 actual=$actual"
    }
  }
}

$modelsRoot = Join-Path $AssetsRoot "models"
Ensure-Directory $modelsRoot

$profiles = @()
if ($Profile -eq "minicpm4b" -or $Profile -eq "both") {
  $profiles += @{
    profile = "minicpm4b"
    alias = "minicpm3-4b-q4_k_m"
    url = "https://www.modelscope.cn/models/OpenBMB/MiniCPM3-4B-GGUF/resolve/master/minicpm3-4b-q4_k_m.gguf"
    sha256 = "64913247e927414ecf47fd3e9ea8e3f0c9acae293f583dfa7e24b8872e20fa4c"
    target = Join-Path $modelsRoot "minicpm3-4b-q4_k_m.gguf"
  }
}
if ($Profile -eq "qwen3b" -or $Profile -eq "both") {
  $profiles += @{
    profile = "qwen3b"
    alias = "qwen2.5-3b-instruct-q4_k_m"
    url = "https://www.modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/master/qwen2.5-3b-instruct-q4_k_m.gguf"
    sha256 = "626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"
    target = Join-Path $modelsRoot "qwen2.5-3b-instruct-q4_k_m.gguf"
  }
}

foreach ($item in $profiles) {
  Download-File -Url $item.url -TargetPath $item.target -Sha256 $item.sha256
  Write-Host "[OK] $($item.profile) downloaded." -ForegroundColor Green
}

$manifestPath = Join-Path $modelsRoot "local_models_manifest.json"
$manifest = @{
  updated_at = (Get-Date).ToString("s")
  root = $modelsRoot
  profiles = $profiles
}
$manifest | ConvertTo-Json -Depth 6 | Set-Content -Path $manifestPath -Encoding utf8

Write-Host ""
Write-Host "Done. Next step:" -ForegroundColor Green
Write-Host "  .\scripts\download_llama_runtime.ps1"
Write-Host "  .\scripts\start_local_cn_llm.ps1 -Profile minicpm4b"

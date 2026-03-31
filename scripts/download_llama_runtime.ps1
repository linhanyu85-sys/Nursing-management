param(
  [ValidateSet("cpu", "cuda")]
  [string]$Runtime = "cpu",
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

$toolsRoot = Join-Path $AssetsRoot "tools"
$runtimeRoot = Join-Path $toolsRoot "llama.cpp"
$zipRoot = Join-Path $toolsRoot "packages"

Ensure-Directory $runtimeRoot
Ensure-Directory $zipRoot

$releaseJson = & curl.exe -k -sL "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
if (-not $releaseJson) {
  throw "Failed to fetch llama.cpp release metadata."
}
$release = $releaseJson | ConvertFrom-Json

$assetPattern = if ($Runtime -eq "cuda") { "*win-cuda-12.4-x64.zip" } else { "*win-cpu-x64.zip" }
$asset = $release.assets | Where-Object { $_.name -like $assetPattern } | Select-Object -First 1
if (-not $asset) {
  throw "Cannot find release asset for pattern: $assetPattern"
}

$zipPath = Join-Path $zipRoot $asset.name
Write-Host "Downloading llama.cpp runtime: $($asset.name)" -ForegroundColor Cyan
& curl.exe -k -L --fail --retry 3 --retry-delay 4 -C - -o $zipPath $asset.browser_download_url
if ($LASTEXITCODE -ne 0) {
  throw "Runtime download failed: $($asset.browser_download_url)"
}

Write-Host "Extracting runtime to: $runtimeRoot" -ForegroundColor Cyan
Expand-Archive -Path $zipPath -DestinationPath $runtimeRoot -Force

$server = Get-ChildItem -Path $runtimeRoot -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) {
  throw "llama-server.exe not found after extraction."
}

Write-Host "[OK] llama-server ready: $($server.FullName)" -ForegroundColor Green

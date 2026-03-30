param(
  [ValidateSet("minicpm4b", "qwen3b", "custom")]
  [string]$Profile = "minicpm4b",
  [switch]$UseGpu,
  [int]$Port = 9100,
  [int]$ContextSize = 2048,
  [int]$StartupTimeoutSec = 240,
  [string]$ProjectRoot = "",
  [string]$AssetsRoot = "",
  [string]$ModelPath = "",
  [string]$ModelAlias = ""
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

function Ensure-Directory([string]$Path) {
  if (-not (Test-Path $Path)) {
    New-Item -Path $Path -ItemType Directory | Out-Null
  }
}

function Resolve-AssetsRoot([string]$ProjectRoot, [string]$RequestedAssetsRoot) {
  $sourceRoot = $RequestedAssetsRoot
  if ([string]::IsNullOrWhiteSpace($sourceRoot)) {
    $sourceRoot = Join-Path $ProjectRoot "ai model\local_cn"
  }

  if (-not (Test-Path $sourceRoot)) {
    throw "AssetsRoot not found: $sourceRoot"
  }

  if ($sourceRoot -notmatch '[^\x00-\x7F]') {
    return (Resolve-Path $sourceRoot).Path
  }

  $aliasRoot = "D:\codex\tmp\ai_nursing_local_cn"
  Ensure-Directory (Split-Path $aliasRoot -Parent)
  if (Test-Path $aliasRoot) {
    Remove-Item $aliasRoot -Force -Recurse -ErrorAction SilentlyContinue
  }
  New-Item -ItemType Junction -Path $aliasRoot -Target $sourceRoot | Out-Null
  return $aliasRoot
}

$AssetsRoot = Resolve-AssetsRoot -ProjectRoot $ProjectRoot -RequestedAssetsRoot $AssetsRoot

$modelMap = @{
  minicpm4b = @{
    alias = "minicpm3-4b-q4_k_m"
    file = "minicpm3-4b-q4_k_m.gguf"
  }
  qwen3b = @{
    alias = "qwen2.5-3b-instruct-q4_k_m"
    file = "qwen2.5-3b-instruct-q4_k_m.gguf"
  }
}

$modelsRoot = Join-Path $AssetsRoot "models"
$runtimeRoot = Join-Path $AssetsRoot "tools\llama.cpp"
$logsRoot = Join-Path $ProjectRoot "logs"
Ensure-Directory $logsRoot

if ($Profile -eq "custom") {
  if (-not $ModelPath) {
    throw "Custom profile requires -ModelPath pointing to a GGUF model file."
  }
  $resolvedModel = Resolve-Path -LiteralPath $ModelPath -ErrorAction Stop
  $modelPath = $resolvedModel.Path
  if (-not $ModelAlias) {
    $ModelAlias = [System.IO.Path]::GetFileNameWithoutExtension($modelPath)
  }
  $profileCfg = @{
    alias = $ModelAlias
    file = [System.IO.Path]::GetFileName($modelPath)
  }
} else {
  $profileCfg = $modelMap[$Profile]
  $modelPath = Join-Path $modelsRoot $profileCfg.file
}

if (-not (Test-Path $modelPath)) {
  throw "Model file not found: $modelPath. Run .\scripts\download_cn_light_models.ps1 first or use -Profile custom -ModelPath <your.gguf>."
}

$server = Get-ChildItem -Path $runtimeRoot -Recurse -Filter "llama-server.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $server) {
  throw "llama-server.exe not found. Run .\scripts\download_llama_runtime.ps1 first."
}

$existing = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($existing) {
  foreach ($conn in $existing) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Milliseconds 600
}

$outLog = Join-Path $logsRoot "local_llm_${Port}.out.log"
$errLog = Join-Path $logsRoot "local_llm_${Port}.err.log"
if (Test-Path $outLog) { Remove-Item $outLog -Force -ErrorAction SilentlyContinue }
if (Test-Path $errLog) { Remove-Item $errLog -Force -ErrorAction SilentlyContinue }

$ngl = "0"
if ($UseGpu.IsPresent) {
  $ngl = "99"
}

$threads = [Math]::Max(4, [int]([Environment]::ProcessorCount / 2))
$args = @(
  "--host", "0.0.0.0",
  "--port", "$Port",
  "-m", "$modelPath",
  "--alias", "$($profileCfg.alias)",
  "-c", "$ContextSize",
  "-ngl", "$ngl",
  "--temp", "0.2",
  "--threads", "$threads"
)

function Quote-Arg([string]$arg) {
  if ($arg -match '[\s"`]') {
    $escaped = $arg -replace '"', '\"'
    return '"' + $escaped + '"'
  }
  return $arg
}

$argLine = ($args | ForEach-Object { Quote-Arg $_ }) -join " "

Write-Host "Starting local CN model server..." -ForegroundColor Cyan
Write-Host "  model : $modelPath"
Write-Host "  alias : $($profileCfg.alias)"
Write-Host "  port  : $Port"
Write-Host "  ctx   : $ContextSize"

# PowerShell 在部分 Windows 环境里会同时暴露 Path 和 PATH，导致 Start-Process 直接失败。
Remove-Item Env:PATH -ErrorAction SilentlyContinue
Start-Process -FilePath $server.FullName -ArgumentList $argLine -RedirectStandardOutput $outLog -RedirectStandardError $errLog | Out-Null
Start-Sleep -Milliseconds 500

$ready = $false
for ($i = 0; $i -lt [Math]::Max(10, $StartupTimeoutSec); $i++) {
  $listening = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if ($listening) {
    try {
      $resp = Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2
      if ($resp -ne $null) {
        $ready = $true
        break
      }
    } catch {
      # Port is up but HTTP not ready yet; continue polling.
    }
  }
  Start-Sleep -Seconds 1
}

if (-not $ready) {
  throw "Local CN LLM server failed to become ready in $StartupTimeoutSec sec. Check: $errLog"
}

Write-Host "[OK] Local CN LLM server is running at http://127.0.0.1:$Port/v1" -ForegroundColor Green

param(
  [string]$NodeRoot = "",
  [string]$HostIp = "",
  [int]$Port = 8094,
  [switch]$WithLocalModel
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")

Write-Host "=== AI Nursing Quick Start ===" -ForegroundColor Cyan
Write-Host ("Project root: {0}" -f $projectRoot) -ForegroundColor DarkGray

if ([string]::IsNullOrWhiteSpace($NodeRoot)) {
  foreach ($candidate in @("D:\软件\node", "D:\software\node", "D:\node")) {
    if (Test-Path $candidate) {
      $NodeRoot = $candidate
      break
    }
  }
}

if ([string]::IsNullOrWhiteSpace($NodeRoot)) {
  $npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
  if ($npmCmd) {
    $NodeRoot = Split-Path -Parent $npmCmd.Source
  }
}

if ([string]::IsNullOrWhiteSpace($NodeRoot) -or -not (Test-Path $NodeRoot)) {
  throw "Node.js folder not found. Pass -NodeRoot, for example D:\软件\node"
}

Write-Host ("Node root: {0}" -f $NodeRoot) -ForegroundColor Green

& (Join-Path $scriptRoot "bootstrap_local_stack.ps1")
& (Join-Path $scriptRoot "start_backend_core.ps1")

if ($WithLocalModel) {
  & (Join-Path $scriptRoot "start_local_cn_llm.ps1")
} else {
  Write-Host "Skip local model startup; current run will use configured remote or fallback capability." -ForegroundColor Yellow
}

& (Join-Path $scriptRoot "start_mobile_expo.ps1") -NodeRoot $NodeRoot -HostIp $HostIp -Port $Port

Write-Host ""
Write-Host "After startup, check:" -ForegroundColor Cyan
Write-Host "1. Backend health: http://127.0.0.1:8000/health" -ForegroundColor Green
Write-Host ("2. Expo Web: http://127.0.0.1:{0}" -f $Port) -ForegroundColor Green

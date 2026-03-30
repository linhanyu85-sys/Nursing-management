$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $scriptRoot "start_mobile_expo.ps1"

if (-not (Test-Path $target)) {
  throw "未找到脚本: $target"
}

powershell -ExecutionPolicy Bypass -File $target @args


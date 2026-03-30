param(
  [string]$MobileRoot = "",
  [string]$NodeRoot = "D:\software\node",
  [string]$HostIp = "",
  [int]$Port = 8081
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$target = Join-Path $scriptRoot "start_mobile_expo.ps1"

if (-not (Test-Path $target)) {
  throw "未找到脚本: $target"
}

powershell -ExecutionPolicy Bypass -File $target -MobileRoot $MobileRoot -NodeRoot $NodeRoot -HostIp $HostIp -Port $Port

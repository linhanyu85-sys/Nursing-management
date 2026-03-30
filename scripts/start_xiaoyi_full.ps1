param(
  [string]$ComPort = "COM7",
  [int]$Baud = 115200,
  [string]$HostIp = "",
  # Default to isolated stack to avoid multi-board port conflicts.
  [int]$GatewayPort = 29113,
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$DepartmentId = "dep-card-01",
  [string]$UserId = "linmeili",
  [switch]$SkipLocalLlm,
  [switch]$NoConsole
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$legacy = Join-Path $scriptRoot "start_xiaozhi_full.ps1"

if (-not (Test-Path $legacy)) { throw "Launcher not found: $legacy" }

$argsList = @(
  "-ComPort", $ComPort,
  "-Baud", "$Baud",
  "-GatewayPort", "$GatewayPort",
  "-ApiBase", $ApiBase,
  "-DepartmentId", $DepartmentId,
  "-UserId", $UserId
)
if ($HostIp -and $HostIp.Trim()) {
  $argsList += @("-HostIp", $HostIp.Trim())
}
if ($NoConsole) { $argsList += "-NoConsole" }
if ($SkipLocalLlm) { $argsList += "-SkipLocalLlm" }

& powershell -ExecutionPolicy Bypass -File $legacy @argsList

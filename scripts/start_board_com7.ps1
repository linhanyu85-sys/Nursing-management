param(
  [string]$ComPort = "COM7",
  [int]$Baud = 115200,
  [int]$GatewayPort = 8013,
  [int]$GatewayBasePort = 39000,
  [string]$UserId = "linmeili",
  [string]$DepartmentId = "dep-card-01",
  [ValidateSet("minicpm4b", "qwen3b")]
  [string]$LocalLlmProfile = "minicpm4b",
  [switch]$SkipLocalLlm,
  [switch]$NoConsole,
  [switch]$UseLegacyHostApp
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcher = Join-Path $scriptRoot "start_xiaozhi_full.ps1"

if (-not (Test-Path $launcher)) {
  throw "Launcher not found: $launcher"
}

$argsList = @(
  "-ComPort", $ComPort,
  "-Baud", "$Baud",
  "-GatewayPort", "$GatewayPort",
  "-GatewayBasePort", "$GatewayBasePort",
  "-UserId", $UserId,
  "-DepartmentId", $DepartmentId,
  "-LocalLlmProfile", $LocalLlmProfile
)

if ($SkipLocalLlm) { $argsList += "-SkipLocalLlm" }
if ($NoConsole) { $argsList += "-NoConsole" }
if ($UseLegacyHostApp) { $argsList += "-UseLegacyHostApp" }

Write-Host "[board] starting COM7 device stack..." -ForegroundColor Cyan
Write-Host ("[board] port={0} gateway={1} user={2} dep={3}" -f $ComPort, $GatewayPort, $UserId, $DepartmentId) -ForegroundColor DarkGray
Write-Host "[board] wake word: xiao yi xiao yi" -ForegroundColor DarkGray

& powershell -NoProfile -ExecutionPolicy Bypass -File $launcher @argsList

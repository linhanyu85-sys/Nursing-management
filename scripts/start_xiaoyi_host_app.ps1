param(
  [switch]$NoConsole,
  [switch]$SkipBackend,
  [int]$GatewayPort = 29113
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$legacy = Join-Path $scriptRoot "start_xiaozhi_host_app.ps1"

if (-not (Test-Path $legacy)) { throw "Launcher not found: $legacy" }

$argsList = @()
if ($NoConsole) { $argsList += "-NoConsole" }
if ($SkipBackend) { $argsList += "-SkipBackend" }
$argsList += @("-GatewayPort", "$GatewayPort")

& powershell -ExecutionPolicy Bypass -File $legacy @argsList

param(
  [string]$ComPort = "COM7",
  [int]$Baud = 460800,
  [ValidateSet("default","left","right")]
  [string]$MicVariant = "default"
)

$ErrorActionPreference = "Stop"
$projRoot = Split-Path -Parent $PSScriptRoot
$fw = Join-Path $projRoot "firmware\xiaoyi_esp32s3_20260322"

$boot = Join-Path $fw "bootloader.bin"
$pt = Join-Path $fw "partition-table.bin"
$ota = Join-Path $fw "ota_data_initial.bin"
$appDefault = Join-Path $fw "xiaoyi_app.bin"
$appLeft = Join-Path $fw "xiaoyi_app_left.bin"
$appRight = Join-Path $fw "xiaoyi_app_right.bin"
$assets = Join-Path $fw "generated_assets.bin"

switch ($MicVariant) {
  "left" { $app = if (Test-Path $appLeft) { $appLeft } else { $appDefault } }
  "right" { $app = if (Test-Path $appRight) { $appRight } else { $appDefault } }
  default { $app = $appDefault }
}

foreach ($ff in @($boot, $pt, $ota, $app, $assets)) {
  if (-not (Test-Path $ff)) {
    throw "Missing firmware file: $ff"
  }
}

Write-Host "[1/3] Ensure esptool..." -ForegroundColor Cyan
& py -3.13 -m pip install --user esptool | Out-Null

Write-Host "[2/3] Release COM lock..." -ForegroundColor Cyan
Get-CimInstance Win32_Process `
  | Where-Object { $_.CommandLine -like "*xiaozhi_host_app.py*" -or $_.CommandLine -like "*xiaozhi_serial_agent_bridge.py*" } `
  | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }

Write-Host ("[3/3] Flashing to {0} ... (MIC variant: {1})" -f $ComPort, $MicVariant) -ForegroundColor Cyan
& py -3.13 -m esptool `
  --chip esp32s3 `
  --port $ComPort `
  -b $Baud `
  --before default_reset `
  --after hard_reset `
  write_flash `
  --flash_mode dio `
  --flash_size 16MB `
  --flash_freq 80m `
  0x0 $boot `
  0x8000 $pt `
  0xd000 $ota `
  0x20000 $app `
  0x800000 $assets

Write-Host "Flash done." -ForegroundColor Green

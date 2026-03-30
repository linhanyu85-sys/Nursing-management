param(
    [string]$ApiUrl = "http://47.84.99.189:18000",
    [string]$AsrUrl = "http://47.84.99.189:18013",
    [string]$OutputDir = "..\build",
    [string]$NodeRoot = ""
)

$ErrorActionPreference = "Stop"

if ($NodeRoot) {
    if (-not (Test-Path $NodeRoot)) {
        Write-Error "NodeRoot does not exist: $NodeRoot"
        exit 1
    }
    $env:Path = "$NodeRoot;$env:APPDATA\npm;$env:Path"
}

Write-Host "=== AI Nursing APK Build Script ===" -ForegroundColor Cyan
Write-Host ""

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js not found. Please install Node.js 18 or later first."
    exit 1
}

$nodeVersionText = (& node -v).Trim()
$nodeMajor = [int]($nodeVersionText.TrimStart("v").Split(".")[0])
if ($nodeMajor -ge 25) {
    Write-Host "Warning: detected $nodeVersionText. Expo SDK 53 is more stable with Node 20 LTS." -ForegroundColor Yellow
}

$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Error "npm.cmd not found. Please reinstall Node.js so npm is available."
    exit 1
}

$mobileDir = Join-Path $PSScriptRoot "..\apps\mobile"
if (-not (Test-Path $mobileDir)) {
    Write-Error "Mobile app directory not found: $mobileDir"
    exit 1
}

Set-Location $mobileDir

Write-Host "[1/5] Checking EAS CLI..." -ForegroundColor Yellow
$easCmd = Get-Command eas.cmd -ErrorAction SilentlyContinue
$npxCmd = Get-Command npx.cmd -ErrorAction SilentlyContinue
if (-not $easCmd -and -not $npxCmd) {
    Write-Error "Neither eas nor npx.cmd was found. Please install Node.js and eas-cli first."
    exit 1
}

Write-Host "[2/5] Writing mobile environment variables..." -ForegroundColor Yellow
$envContent = @"
EXPO_PUBLIC_API_BASE_URL=$ApiUrl
EXPO_PUBLIC_API_MOCK=false
EXPO_PUBLIC_ASR_BASE_URL=$AsrUrl
"@

$envContent | Out-File -FilePath ".env" -Encoding UTF8 -Force
Write-Host "API URL: $ApiUrl" -ForegroundColor Green
Write-Host "ASR URL: $AsrUrl" -ForegroundColor Green

Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
& npm.cmd install

Write-Host "[4/5] Checking Expo config..." -ForegroundColor Yellow
$appJson = Get-Content "app.json" -Raw | ConvertFrom-Json
Write-Host "App name: $($appJson.expo.name)" -ForegroundColor Green
Write-Host "Android package: $($appJson.expo.android.package)" -ForegroundColor Green
Write-Host "Version: $($appJson.expo.version)" -ForegroundColor Green

if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

Write-Host "[5/5] Starting APK build..." -ForegroundColor Yellow
Write-Host ""
Write-Host "Before the first build, run: eas.cmd login" -ForegroundColor Yellow
Write-Host "If EAS is not configured yet, run: eas.cmd build:configure" -ForegroundColor Yellow
Write-Host ""

$buildArgs = @(
    "build",
    "--platform", "android",
    "--profile", "preview",
    "--non-interactive",
    "--no-wait"
)

if ($easCmd) {
    $buildOutput = & $easCmd.Source @buildArgs 2>&1 | Tee-Object -Variable buildLog
} else {
    $buildOutput = & npx.cmd eas-cli @buildArgs 2>&1 | Tee-Object -Variable buildLog
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== APK build succeeded ===" -ForegroundColor Green
    Write-Host "Download the APK from the build link shown above." -ForegroundColor Green
} else {
    $buildLogText = ($buildLog | Out-String)
    Write-Host ""
    Write-Host "=== APK build failed ===" -ForegroundColor Red
    if ($buildLogText -match "storage\.googleapis\.com" -or $buildLogText -match "ECONNRESET") {
        Write-Host "Upload to Expo storage failed. This is usually a network or proxy problem between your machine and storage.googleapis.com." -ForegroundColor Yellow
        Write-Host "Try again on a different network, a mobile hotspot, or with a working VPN/proxy, then rerun this script." -ForegroundColor Yellow
    } else {
        Write-Host "Please confirm the following first:" -ForegroundColor Yellow
        Write-Host "1. eas.cmd login has completed" -ForegroundColor Yellow
        Write-Host "2. eas.cmd build:configure has completed" -ForegroundColor Yellow
        Write-Host "3. apps/mobile/eas.json exists and is correct" -ForegroundColor Yellow
    }
}

Set-Location $PSScriptRoot

# APK打包脚本
# 用法: .\scripts\build_apk.ps1 -ApiUrl "http://47.84.99.189:8000"

param(
    [string]$ApiUrl = "http://47.84.99.189:8000",
    [string]$OutputDir = "..\build"
)

$ErrorActionPreference = "Stop"

Write-Host "=== AI护理系统 APK 打包脚本 ===" -ForegroundColor Cyan
Write-Host ""

# 检查Node.js
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js 未安装，请先安装 Node.js 18+"
    exit 1
}

# 进入移动端目录
$mobileDir = Join-Path $PSScriptRoot "..\apps\mobile"
if (-not (Test-Path $mobileDir)) {
    Write-Error "移动端目录不存在: $mobileDir"
    exit 1
}

Set-Location $mobileDir

# 检查并安装eas-cli
Write-Host "[1/5] 检查 EAS CLI..." -ForegroundColor Yellow
$npxCmd = Get-Command npx -ErrorAction SilentlyContinue
if (-not $npxCmd) {
    Write-Error "npx 命令不可用"
    exit 1
}

# 创建环境配置文件
Write-Host "[2/5] 配置环境变量..." -ForegroundColor Yellow
$envContent = @"
EXPO_PUBLIC_API_BASE_URL=$ApiUrl
EXPO_PUBLIC_API_MOCK=false
"@

$envContent | Out-File -FilePath ".env" -Encoding UTF8 -Force
Write-Host "API地址: $ApiUrl" -ForegroundColor Green

# 安装依赖
Write-Host "[3/5] 安装依赖..." -ForegroundColor Yellow
npm install

# 检查expo配置
Write-Host "[4/5] 检查 Expo 配置..." -ForegroundColor Yellow
$appJson = Get-Content "app.json" | ConvertFrom-Json
Write-Host "应用名称: $($appJson.expo.name)" -ForegroundColor Green
Write-Host "包名: $($appJson.expo.android.package)" -ForegroundColor Green
Write-Host "版本: $($appJson.expo.version)" -ForegroundColor Green

# 预构建检查
Write-Host "[5/5] 开始构建 APK..." -ForegroundColor Yellow
Write-Host ""
Write-Host "注意：首次构建需要登录 Expo 账号" -ForegroundColor Yellow
Write-Host "请按提示操作..." -ForegroundColor Yellow
Write-Host ""

# 执行构建
npx eas build --platform android --profile preview --non-interactive

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "=== APK 构建成功 ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "下载地址会显示在上方的输出中"
    Write-Host "或者访问: https://expo.dev/accounts/[你的账号]/projects/ai-nursing-mobile/builds"
} else {
    Write-Host ""
    Write-Host "=== APK 构建失败 ===" -ForegroundColor Red
    Write-Host ""
    Write-Host "可能的解决方案："
    Write-Host "1. 运行 'npx eas login' 登录 Expo 账号"
    Write-Host "2. 运行 'npx eas build:configure' 初始化配置"
    Write-Host "3. 检查 eas.json 配置是否正确"
}

Set-Location $PSScriptRoot

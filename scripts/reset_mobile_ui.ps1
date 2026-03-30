param(
  [string]$MobileRoot = "",
  [string]$NodeRoot = "D:\软件\node",
  [string]$HostIp = "",
  [int]$Port = 8090
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path

function Resolve-MobileWorkspace {
  param(
    [string]$RequestedPath,
    [string]$ProjectRoot
  )

  $sourceRoot = $RequestedPath
  if ([string]::IsNullOrWhiteSpace($sourceRoot)) {
    $sourceRoot = Join-Path $ProjectRoot "apps\mobile"
  }

  if (-not (Test-Path $sourceRoot)) {
    Write-Host "[ERROR] 项目目录不存在: $sourceRoot" -ForegroundColor Red
    exit 1
  }

  if ($sourceRoot -notmatch "[^\x00-\x7F]") {
    return (Resolve-Path $sourceRoot).Path
  }

  $aliasRoot = "D:\codex\tmp\mobile_ascii_alias"
  $aliasParent = Split-Path $aliasRoot -Parent
  if (-not (Test-Path $aliasParent)) {
    New-Item -ItemType Directory -Path $aliasParent | Out-Null
  }
  if (Test-Path $aliasRoot) {
    Remove-Item $aliasRoot -Force -Recurse -ErrorAction SilentlyContinue
  }
  New-Item -ItemType Junction -Path $aliasRoot -Target $sourceRoot | Out-Null
  return $aliasRoot
}

$MobileRoot = Resolve-MobileWorkspace -RequestedPath $MobileRoot -ProjectRoot $projectRoot

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $candidate = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "169.254.*" -and
      $_.IPAddress -ne "127.0.0.1" -and
      $_.IPAddress -notlike "172.26.*" -and
      $_.InterfaceAlias -notlike "*Loopback*" -and
      $_.PrefixOrigin -ne "WellKnown"
    } |
    Sort-Object InterfaceMetric |
    Select-Object -First 1 -ExpandProperty IPAddress

  if (-not $candidate) {
    Write-Host "[ERROR] 无法自动检测局域网 IP，请手动传入 -HostIp。" -ForegroundColor Red
    exit 1
  }
  $HostIp = $candidate
}

Write-Host "[1/6] 使用项目目录: $MobileRoot" -ForegroundColor Cyan
Write-Host "[2/6] 使用局域网 IP: $HostIp" -ForegroundColor Cyan
Write-Host "[3/6] 使用端口: $Port" -ForegroundColor Cyan

Write-Host "[4/6] 关闭可访问的 Expo/Metro 进程..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -like "*expo*start*" -or
    $_.CommandLine -like "*expo\\bin\\cli*" -or
    $_.CommandLine -like "*@expo\\ngrok*" -or
    $_.CommandLine -like "*metro*"
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

$ports = @($Port, 19000, 19001)
foreach ($p in $ports) {
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  if ($listeners) {
    $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($pid in $pids) {
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
  }
}

Write-Host "[5/6] 清理缓存并启动 Expo Go (LAN)..." -ForegroundColor Cyan
$targets = @(
  (Join-Path $MobileRoot ".expo"),
  (Join-Path $MobileRoot ".expo-shared"),
  (Join-Path $MobileRoot "node_modules\\.cache\\metro")
)
foreach ($t in $targets) {
  if (Test-Path $t) {
    Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue
  }
}

$env:Path = "$NodeRoot;$env:Path"
$env:REACT_NATIVE_PACKAGER_HOSTNAME = $HostIp
$npxCmd = Join-Path $NodeRoot "npx.cmd"
if (-not (Test-Path $npxCmd)) {
  Write-Host "[ERROR] 未找到 npx: $npxCmd" -ForegroundColor Red
  exit 1
}

Set-Location $MobileRoot
$openUrl = "exp://${HostIp}:$Port"
try {
  Set-Clipboard -Value $openUrl
  Write-Host "已复制到剪贴板: $openUrl" -ForegroundColor Green
} catch {
  Write-Host "手动输入 URL: $openUrl" -ForegroundColor Yellow
}

Write-Host "命令: $npxCmd expo start -c --host lan --port $Port" -ForegroundColor DarkGray
& $npxCmd expo start -c --host lan --port $Port

Write-Host "[6/6] Expo 进程已退出。" -ForegroundColor Cyan


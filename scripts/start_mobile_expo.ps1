param(
  [string]$MobileRoot = "",
  [string]$NodeRoot = "D:\软件\node",
  [string]$HostIp = "",
  [int]$Port = 8081
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
    throw "MobileRoot 不存在: $sourceRoot"
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

$npxCmd = Join-Path $NodeRoot "npx.cmd"
if (-not (Test-Path $npxCmd)) {
  throw "未找到 npx.cmd: $npxCmd"
}

function Get-IpFromEnvFile {
  param([string]$EnvPath)
  if (-not (Test-Path $EnvPath)) {
    return $null
  }
  $line = Get-Content $EnvPath | Where-Object { $_ -like "*EXPO_PUBLIC_API_BASE_URL=*" } | Select-Object -First 1
  if (-not $line) {
    return $null
  }

  $clean = $line.Trim()
  $clean = $clean.Trim([char]0xFEFF)
  $url = ($clean -replace "^EXPO_PUBLIC_API_BASE_URL=", "").Trim()
  if (-not $url) {
    return $null
  }

  try {
    $uri = [System.Uri]$url
    $parsedHost = $uri.Host
    if ($parsedHost -match "^\d{1,3}(\.\d{1,3}){3}$") {
      return $parsedHost
    }
  } catch {
    return $null
  }

  return $null
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $preferredIp = Get-IpFromEnvFile -EnvPath (Join-Path $MobileRoot ".env")
  if ($preferredIp) {
    $exists = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -eq $preferredIp } |
      Select-Object -First 1
    if ($exists) {
      $HostIp = $preferredIp
    }
  }
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  $HostIp = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object {
      $_.IPAddress -notlike "169.254.*" -and
      $_.IPAddress -ne "127.0.0.1" -and
      $_.InterfaceAlias -notlike "*Loopback*" -and
      $_.PrefixOrigin -ne "WellKnown"
    } |
    Sort-Object InterfaceMetric |
    Select-Object -First 1 -ExpandProperty IPAddress
}

if ([string]::IsNullOrWhiteSpace($HostIp)) {
  throw "无法检测可用局域网 IP，请手动传入 -HostIp。"
}

$firewallScript = Join-Path $scriptRoot "ensure_dev_firewall.ps1"
if (Test-Path $firewallScript) {
  try {
    & $firewallScript | Out-Null
  } catch {
    Write-Host "[WARN] 防火墙规则写入失败，可能需要管理员权限。" -ForegroundColor Yellow
  }
}

$envFile = Join-Path $MobileRoot ".env"
if (Test-Path $envFile) {
  $lines = Get-Content $envFile
  $apiLine = "EXPO_PUBLIC_API_BASE_URL=http://${HostIp}:8000"
  $proxyLine = "EXPO_PACKAGER_PROXY_URL=http://${HostIp}:$Port"
  $mockLine = "EXPO_PUBLIC_API_MOCK=false"
  $hasApi = $false
  $hasProxy = $false
  $hasMock = $false
  $nextLines = foreach ($line in $lines) {
    if ($line -match "^EXPO_PUBLIC_API_BASE_URL=") {
      $hasApi = $true
      $apiLine
    } elseif ($line -match "^EXPO_PACKAGER_PROXY_URL=") {
      $hasProxy = $true
      $proxyLine
    } elseif ($line -match "^EXPO_PUBLIC_API_MOCK=") {
      $hasMock = $true
      $mockLine
    } else {
      $line
    }
  }
  if (-not $hasApi) {
    $nextLines += $apiLine
  }
  if (-not $hasProxy) {
    $nextLines += $proxyLine
  }
  if (-not $hasMock) {
    $nextLines += $mockLine
  }
  Set-Content -Path $envFile -Value $nextLines -Encoding UTF8
}

Write-Host "[ENV] EXPO_PUBLIC_API_BASE_URL=http://${HostIp}:8000" -ForegroundColor DarkGray
Write-Host "[ENV] EXPO_PACKAGER_PROXY_URL=http://${HostIp}:$Port" -ForegroundColor DarkGray

if (Test-Path (Join-Path $MobileRoot "app.json")) {
  try {
    $appJsonPath = Join-Path $MobileRoot "app.json"
    $raw = Get-Content $appJsonPath -Raw -Encoding UTF8
    $updated = $raw -replace '"apiBaseUrl"\s*:\s*"[^"]*"', ('"apiBaseUrl": "http://{0}:8000"' -f $HostIp)
    if ($updated -ne $raw) {
      Set-Content -Path $appJsonPath -Value $updated -Encoding UTF8
    }
  } catch {
    Write-Host "[WARN] app.json 的 apiBaseUrl 自动更新失败，可忽略。" -ForegroundColor Yellow
  }
}

if (Test-Path (Join-Path $MobileRoot ".env")) {
  Write-Host "[ENV] .env 已自动更新为当前局域网 IP。" -ForegroundColor Green
}

if (Test-Path (Join-Path $MobileRoot "node_modules")) {
  # keep existing dependencies
} else {
  Write-Host "[INIT] 未检测到 node_modules，开始安装依赖..." -ForegroundColor Cyan
  $oldPathInstall = $env:Path
  $env:Path = "$NodeRoot;$env:Path"
  Push-Location $MobileRoot
  try {
    & (Join-Path $NodeRoot "npm.cmd") install --legacy-peer-deps
  } finally {
    Pop-Location
    $env:Path = $oldPathInstall
  }
}

$out = Join-Path $MobileRoot ".expo_start.out.log"
$err = Join-Path $MobileRoot ".expo_start.err.log"
if (Test-Path $out) { Remove-Item $out -Force -ErrorAction SilentlyContinue }
if (Test-Path $err) { Remove-Item $err -Force -ErrorAction SilentlyContinue }

Write-Host "[1/5] 停止旧 Expo/Metro 进程..." -ForegroundColor Cyan
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
  Where-Object {
    $_.CommandLine -like "*expo*start*" -or
    $_.CommandLine -like "*@expo\\cli*" -or
    $_.CommandLine -like "*metro*"
  } |
  ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  }

foreach ($p in @($Port, 19000, 19001, 19002)) {
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue
  if ($listeners) {
    $pids = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $pids) {
      Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
  }
}
Start-Sleep -Milliseconds 800

Write-Host "[2/5] 清理 Metro 缓存..." -ForegroundColor Cyan
foreach ($cachePath in @(
  (Join-Path $MobileRoot ".expo"),
  (Join-Path $MobileRoot ".expo-shared"),
  (Join-Path $MobileRoot "node_modules\\.cache\\metro")
)) {
  if (Test-Path $cachePath) {
    Remove-Item $cachePath -Recurse -Force -ErrorAction SilentlyContinue
  }
}

Write-Host "[3/5] 启动 Expo Go (LAN)..." -ForegroundColor Cyan
$oldPath = $env:Path
$oldHost = $env:REACT_NATIVE_PACKAGER_HOSTNAME
$oldProxyUrl = $env:EXPO_PACKAGER_PROXY_URL
$oldDevListen = $env:EXPO_DEVTOOLS_LISTEN_ADDRESS
$oldExpoHome = $env:EXPO_HOME
$oldTemp = $env:TEMP
$oldTmp = $env:TMP

$env:Path = "$NodeRoot;$env:Path"
$env:REACT_NATIVE_PACKAGER_HOSTNAME = $HostIp
$env:EXPO_PACKAGER_PROXY_URL = "http://${HostIp}:${Port}"
$env:EXPO_DEVTOOLS_LISTEN_ADDRESS = "0.0.0.0"
$expoHome = "D:\codex\.expo-home"
$tempRoot = "D:\codex\tmp"
if (-not (Test-Path $expoHome)) { New-Item -ItemType Directory -Path $expoHome | Out-Null }
if (-not (Test-Path $tempRoot)) { New-Item -ItemType Directory -Path $tempRoot | Out-Null }
$env:EXPO_HOME = $expoHome
$env:TEMP = $tempRoot
$env:TMP = $tempRoot

Start-Process -FilePath $npxCmd `
  -WorkingDirectory $MobileRoot `
  -ArgumentList @("expo", "start", "-c", "--host", "lan", "--port", "$Port") `
  -RedirectStandardOutput $out `
  -RedirectStandardError $err `
  -WindowStyle Minimized | Out-Null

$env:Path = $oldPath
if ($null -ne $oldHost) {
  $env:REACT_NATIVE_PACKAGER_HOSTNAME = $oldHost
} else {
  Remove-Item Env:\REACT_NATIVE_PACKAGER_HOSTNAME -ErrorAction SilentlyContinue
}
if ($null -ne $oldProxyUrl) {
  $env:EXPO_PACKAGER_PROXY_URL = $oldProxyUrl
} else {
  Remove-Item Env:\EXPO_PACKAGER_PROXY_URL -ErrorAction SilentlyContinue
}
if ($null -ne $oldDevListen) {
  $env:EXPO_DEVTOOLS_LISTEN_ADDRESS = $oldDevListen
} else {
  Remove-Item Env:\EXPO_DEVTOOLS_LISTEN_ADDRESS -ErrorAction SilentlyContinue
}
if ($null -ne $oldExpoHome) {
  $env:EXPO_HOME = $oldExpoHome
} else {
  Remove-Item Env:\EXPO_HOME -ErrorAction SilentlyContinue
}
if ($null -ne $oldTemp) {
  $env:TEMP = $oldTemp
} else {
  Remove-Item Env:\TEMP -ErrorAction SilentlyContinue
}
if ($null -ne $oldTmp) {
  $env:TMP = $oldTmp
} else {
  Remove-Item Env:\TMP -ErrorAction SilentlyContinue
}

Write-Host "[4/5] 等待端口监听..." -ForegroundColor Cyan
$ok = $false
for ($i = 0; $i -lt 45; $i++) {
  Start-Sleep -Seconds 1
  $listen = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if ($listen) {
    $ok = $true
    break
  }
}

if (-not $ok) {
  Write-Host "[FAIL] Expo 未监听端口 $Port，请查看日志：" -ForegroundColor Red
  Write-Host "OUT: $out"
  Write-Host "ERR: $err"
  if (Test-Path $err) {
    Write-Host "--- ERR Tail ---" -ForegroundColor DarkYellow
    Get-Content $err -Tail 80
  }
  exit 1
}

$openUrl = "exp://${HostIp}:$Port"
try {
  Set-Clipboard -Value $openUrl
} catch {
  # ignore
}

Write-Host "[5/5] Expo 已启动（后台）" -ForegroundColor Green
Write-Host "Expo Go 手动输入: $openUrl" -ForegroundColor Green
Write-Host "调试 JSON 地址: http://${HostIp}:$Port" -ForegroundColor Gray
Write-Host "输出日志: $out" -ForegroundColor Gray
Write-Host "错误日志: $err" -ForegroundColor Gray

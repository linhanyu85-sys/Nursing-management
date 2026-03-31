param(
  [string]$ComPort = "COM7",
  [int]$Baud = 115200,
  [string]$HostIp = "",
  [int]$GatewayPort = 8013,
  [int]$GatewayBasePort = 39000,
  [string]$ApiBase = "http://127.0.0.1:8000",
  [string]$DepartmentId = "dep-card-01",
  [string]$UserId = "linmeili",
  [ValidateSet("minicpm4b", "qwen3b")]
  [string]$LocalLlmProfile = "minicpm4b",
  [int]$LocalLlmPort = 9100,
  [switch]$SkipLocalLlm,
  [switch]$NoConsole,
  [switch]$UseLegacyHostApp
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$cfgDir = Join-Path $projectRoot "data"
$cfgPathLegacy = Join-Path $cfgDir "xiaozhi_host_config.json"
$cfgPathXiaoyi = Join-Path $cfgDir "xiaoyi_host_config.json"

if (-not (Test-Path $cfgDir)) {
  New-Item -ItemType Directory -Path $cfgDir | Out-Null
}

function Resolve-LanIPv4 {
  if ($HostIp -and $HostIp.Trim()) {
    return $HostIp.Trim()
  }

  $candidates = @()

  try {
    $active = Get-NetIPConfiguration -ErrorAction SilentlyContinue `
      | Where-Object {
          $_.IPv4Address -and $_.IPv4DefaultGateway -and
          $_.InterfaceAlias -notmatch "Loopback|vEthernet|VMware|Virtual|Hyper-V|Docker|Tailscale"
        } `
      | Sort-Object InterfaceMetric `
      | Select-Object -First 1
    if ($active -and $active.IPv4Address -and $active.IPv4Address.IPAddress) {
      $candidates += $active.IPv4Address.IPAddress
    }
  } catch {}

  try {
    $wlan = Get-NetIPConfiguration -InterfaceAlias "WLAN" -ErrorAction SilentlyContinue `
      | Where-Object { $_.IPv4Address -and $_.IPv4DefaultGateway } `
      | Select-Object -First 1
    if ($wlan -and $wlan.IPv4Address -and $wlan.IPv4Address.IPAddress) {
      $candidates += $wlan.IPv4Address.IPAddress
    }
  } catch {}

  try { $candidates += Get-NetIPAddress -AddressFamily IPv4 -InterfaceAlias "WLAN" -ErrorAction SilentlyContinue } catch {}
  try { $candidates += Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue } catch {}

  $filtered = $candidates `
    | ForEach-Object {
        if ($_ -is [string]) {
          $_
        } elseif ($_.IPAddress) {
          $_.IPAddress
        } else {
          $null
        }
      } `
    | Where-Object { $_ -and $_ -notlike "127.*" -and $_ -notlike "169.254.*" } `
    | Select-Object -Unique

  # Prefer board hotspot segment first.
  $ip = $filtered | Where-Object { $_ -like "192.168.128.*" } | Select-Object -First 1
  if (-not $ip) { $ip = $filtered | Where-Object { $_ -like "192.168.*" } | Select-Object -First 1 }
  if (-not $ip) { $ip = $filtered | Where-Object { $_ -like "10.*" } | Select-Object -First 1 }
  if (-not $ip) { $ip = $filtered | Where-Object { $_ -like "172.*" } | Select-Object -First 1 }
  if (-not $ip) { $ip = $filtered | Select-Object -First 1 }
  if (-not $ip) { $ip = "127.0.0.1" }
  return $ip
}

function Resolve-WorkingComPort {
  param(
    [string]$PreferredPort,
    [int]$PortBaud = 115200
  )
  $candidates = @()
  if ($PreferredPort -and $PreferredPort.Trim()) {
    $candidates += $PreferredPort.Trim().ToUpper()
  }
  try {
    $ports = Get-CimInstance Win32_SerialPort -ErrorAction SilentlyContinue | Select-Object -ExpandProperty DeviceID
    if ($ports) { $candidates += $ports }
  } catch {}
  $candidates = $candidates | Where-Object { $_ } | ForEach-Object { $_.ToString().Trim().ToUpper() } | Select-Object -Unique
  if (-not $candidates -or $candidates.Count -eq 0) {
    return $PreferredPort
  }
  try { & py -3.13 -m pip install --user pyserial | Out-Null } catch {}
  foreach ($portName in $candidates) {
    $probe = @"
import serial, time
port = r"$portName"
baud = int($PortBaud)
try:
    s = serial.Serial(port=port, baudrate=baud, timeout=0.3, write_timeout=0.8)
    try:
        s.write(b"XIAOYI_CMD:PING\\r\\n")
        s.flush()
        t0 = time.time()
        got = False
        while time.time() - t0 < 1.0:
            line = s.readline()
            if not line:
                continue
            txt = line.decode("utf-8", errors="ignore").lower()
            if "serial_pong" in txt or "xiaoyi_evt:state:serial_pong" in txt:
                got = True
                break
        print("PONG" if got else "OPEN")
    finally:
        s.close()
except Exception:
    print("FAIL")
"@
    $result = ($probe | & py -3.13 - 2>$null | Select-Object -First 1)
    if ($result -eq "PONG" -or $result -eq "OPEN") {
      return $portName
    }
  }
  return $PreferredPort
}

function Wait-BackendReady {
  param(
    [int]$TimeoutSec = 45,
    [int]$Port = 8081
  )
  $ok = $false
  for ($i = 0; $i -lt $TimeoutSec; $i++) {
    Start-Sleep -Milliseconds 1000
    try {
      $h = Invoke-RestMethod ("http://127.0.0.1:{0}/health" -f $Port) -TimeoutSec 2
      $o = $null
      foreach ($candidate in @("/xiaozhi/ota/", "/xiaozhi/", "/xiaoz/")) {
        try {
          $o = Invoke-RestMethod ("http://127.0.0.1:{0}{1}" -f $Port, $candidate) -TimeoutSec 2
          if ($o -and $o.firmware -ne $null -and $o.websocket -ne $null) {
            break
          }
        } catch {}
      }
      if ($h.status -eq "ok" -and $o -and $o.firmware -ne $null -and $o.websocket -ne $null) {
        $ok = $true
        break
      }
    } catch {}
  }
  return $ok
}

function Get-GatewayVersion {
  param([int]$Port)
  try {
    $v = Invoke-RestMethod ("http://127.0.0.1:{0}/version" -f $Port) -TimeoutSec 2
    if ($v -and $v.version) { return [string]$v.version }
  } catch {}
  return ""
}

function Wait-DeviceSessionOnline {
  param(
    [int]$Port = 808,
    [int]$TimeoutSec = 35
  )
  $url = "http://127.0.0.1:$Port/api/device/sessions"
  for ($i = 0; $i -lt $TimeoutSec; $i++) {
    Start-Sleep -Milliseconds 1000
    try {
      $resp = Invoke-RestMethod -Uri $url -TimeoutSec 2
      $count = 0
      if ($resp -and $resp.count -ne $null) {
        $count = [int]$resp.count
      }
      if ($count -gt 0) {
        $first = $null
        if ($resp.sessions -and $resp.sessions.Count -gt 0) {
          $first = $resp.sessions[0]
        }
        if ($first) {
          Write-Host ("[online] device session connected: id={0} client={1}" -f $first.connection_id, $first.client) -ForegroundColor Green
        } else {
          Write-Host ("[online] device session connected: count={0}" -f $count) -ForegroundColor Green
        }
        return $true
      }
    } catch {}
  }
  Write-Host "[warn] device session still offline (count=0)." -ForegroundColor Yellow
  return $false
}

function Bind-DeviceOwner {
  param(
    [int]$Port = 808,
    [string]$Username = "linmeili"
  )
  $clean = [string]$Username
  $clean = $clean.Trim()
  if (-not $clean) { $clean = "linmeili" }
  $ownerId = if ($clean.StartsWith("u_")) { $clean } else { "u_$clean" }
  $ownerName = if ($clean.StartsWith("u_")) { $clean.Substring(2) } else { $clean }
  $url = "http://127.0.0.1:$Port/api/device/bind"
  $payload = @{
    user_id = $ownerId
    username = $ownerName
  } | ConvertTo-Json
  try {
    $resp = Invoke-RestMethod -Method Post -Uri $url -ContentType "application/json" -Body $payload -TimeoutSec 4
    Write-Host ("[bind] device owner => {0} ({1})" -f $ownerName, $ownerId) -ForegroundColor Green
    return $resp
  } catch {
    Write-Host ("[bind_warn] failed bind owner on :{0}: {1}" -f $Port, $_.Exception.Message) -ForegroundColor Yellow
    return $null
  }
}

function Ensure-GatewayFirewall {
  param([int]$Port)
  if ($Port -le 0) { return }
  $ruleName = "xiaoyi-device-gateway-$Port"
  try {
    $existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null | Out-String
    if ($existing -and ($existing -match $ruleName)) {
      Write-Host ("[firewall] rule exists: {0}" -f $ruleName) -ForegroundColor DarkGray
      return
    }
  } catch {}
  try {
    netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=$Port | Out-Null
    Write-Host ("[firewall] opened TCP:{0}" -f $Port) -ForegroundColor Green
  } catch {
    Write-Host ("[firewall_warn] failed to open TCP:{0}: {1}" -f $Port, $_.Exception.Message) -ForegroundColor Yellow
  }
}

function Stop-PortOwner {
  param([int]$Port)
  if ($Port -le 0) { return }
  $listeners = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
  if (-not $listeners) { return }
  $ownerIds = $listeners | Select-Object -ExpandProperty OwningProcess -Unique
  foreach ($ownerId in $ownerIds) {
    if (-not $ownerId -or $ownerId -le 0) { continue }
    try {
      Stop-Process -Id $ownerId -Force -ErrorAction Stop
      Write-Host ("[cleanup] stopped process on :{0} (pid={1})" -f $Port, $ownerId) -ForegroundColor Yellow
    } catch {
      Write-Host ("[cleanup_warn] cannot stop pid={0} on :{1}: {2}" -f $ownerId, $Port, $_.Exception.Message) -ForegroundColor Yellow
    }
  }
  Start-Sleep -Milliseconds 250
}

function Push-DeviceLocalMode {
  param(
    [string]$Port,
    [int]$PortBaud,
    [string]$LanIp,
    [int]$PortGateway = 8081
  )

  # Use canonical endpoints to avoid OTA/version-check mismatch.
  $otaUrl = "http://$($LanIp):$($PortGateway)/xiaozhi/ota/"
  $wsPort = if ($PortGateway -eq 8081) { 808 } else { $PortGateway }
  $wsUrl = "ws://$($LanIp):$($wsPort)/xiaozhi/v1/"
  $wsUrlCompat = "ws://$($LanIp):$($wsPort)/xiaozhi/v1"

  try {
    & py -3.13 -m pip install --user pyserial | Out-Null
    $py = @"
import serial, time

port = r"$Port"
ota = r"$otaUrl"
ws = r"$wsUrl"
ws_compat = r"$wsUrlCompat"
bauds = [int($PortBaud), 115200]
cmds = [
    "XIAOYI_CMD:PING",
    "XIAOYI_CMD:HOST_LOCAL_ONLY_ON",
    "XIAOYI_CMD:SET_PROTOCOL:WS",
    f"XIAOYI_CMD:SET_OTA_URL:{ota}",
    f"XIAOYI_CMD:SET_WS_URL:{ws}",
    f"XIAOYI_CMD:SET_WS_URL:{ws}",
    f"XIAOYI_CMD:SET_WS_URL:{ws_compat}",
    "XIAOYI_CMD:RELOAD_PROTOCOL",
    "XIAOYI_CMD:CLOUD_CONFIG",
    "XIAOYI_CMD:REBOOT",
]

last_err = None
for b in bauds:
    try:
        s = serial.Serial()
        s.port = port
        s.baudrate = b
        s.timeout = 0.45
        s.write_timeout = 1.2
        s.rtscts = False
        s.dsrdtr = False
        try:
            s.dtr = False
            s.rts = False
        except Exception:
            pass
        s.open()
        try:
            time.sleep(0.25)
            for c in cmds:
                s.write((c + "\\r\\n").encode("utf-8", errors="ignore"))
                s.flush()
                time.sleep(0.34)
            time.sleep(2.2)
            s.write(("XIAOYI_CMD:START_LISTENING\\r\\n").encode("utf-8", errors="ignore"))
            s.flush()
            time.sleep(0.5)
            s.write(("XIAOYI_CMD:PING\\r\\n").encode("utf-8", errors="ignore"))
            s.flush()
            t0 = time.time()
            while time.time() - t0 < 2.2:
                line = s.readline()
                if line:
                    try:
                        txt = line.decode("utf-8", errors="ignore").strip()
                    except Exception:
                        txt = str(line)
                    if txt:
                        print(f"SERIAL_EVT {txt}")
            print(f"LOCAL_MODE_OK baud={b}")
            raise SystemExit(0)
        finally:
            s.close()
    except SystemExit:
        raise
    except Exception as e:
        last_err = e
        continue

raise RuntimeError(f"serial_push_failed: {last_err}")
"@
    $py | & py -3.13 -
    Write-Host "[local-mode] Commands pushed via serial." -ForegroundColor Green
    Write-Host "[local-mode] OTA: $otaUrl" -ForegroundColor Green
    Write-Host "[local-mode] WS : $wsUrl" -ForegroundColor Green
    Write-Host "[local-mode] WS2: $wsUrlCompat" -ForegroundColor Green
  } catch {
    Write-Host ("[local-mode] Serial push skipped: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
  }
}

Write-Host "[1/5] Prepare host config..." -ForegroundColor Cyan
$resolvedComPort = Resolve-WorkingComPort -PreferredPort $ComPort -PortBaud $Baud
if ($resolvedComPort -and ($resolvedComPort.Trim().ToUpper() -ne $ComPort.Trim().ToUpper())) {
  Write-Host ("[serial] requested {0}, switched to active device port {1}" -f $ComPort, $resolvedComPort) -ForegroundColor Yellow
}
$ComPort = $resolvedComPort
$wakeWord = ([string][char]0x5C0F) + ([string][char]0x533B) + ([string][char]0x5C0F) + ([string][char]0x533B)
$sleepWord = ([string][char]0x4F11) + ([string][char]0x7720)
$cfg = @{
  port = $ComPort
  baud = "$Baud"
  api = $ApiBase
  dep = $DepartmentId
  user = $UserId
  wake = $wakeWord
  sleep = $sleepWord
  write = $true
  raw = $false
  tts = $true
  concise = $true
  device_tts = $true
}
$cfgJson = $cfg | ConvertTo-Json -Depth 4
$cfgJson | Set-Content -Path $cfgPathLegacy -Encoding UTF8
$cfgJson | Set-Content -Path $cfgPathXiaoyi -Encoding UTF8
Write-Host ("Config written: {0}" -f $cfgPathXiaoyi) -ForegroundColor Green

if (-not $SkipLocalLlm) {
  Write-Host "[2/5] Start local CN LLM..." -ForegroundColor Cyan
  $localLlmScript = Join-Path $scriptRoot "start_local_cn_llm.ps1"
  if (-not (Test-Path $localLlmScript)) {
    Write-Host "[warn] Local LLM launcher not found, continue without local LLM." -ForegroundColor Yellow
  } else {
    try {
      & powershell -NoProfile -ExecutionPolicy Bypass -File $localLlmScript -Profile $LocalLlmProfile -Port $LocalLlmPort -StartupTimeoutSec 180
    } catch {
      Write-Host ("[warn] Local LLM startup failed, continue without local LLM: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    }
  }
} else {
  Write-Host "[2/5] Skip local CN LLM startup (by parameter)." -ForegroundColor Yellow
}

Write-Host "[3/5] Start backend core..." -ForegroundColor Cyan
if ($GatewayPort -ne 8013) {
  Stop-PortOwner -Port 8013
}
$isolated8081 = Join-Path $scriptRoot "start_gateway_8081_stack.ps1"
$isolated808 = Join-Path $scriptRoot "start_gateway_808_isolated.ps1"
if (($GatewayPort -eq 808 -or $GatewayPort -eq 8013) -and (Test-Path $isolated808)) {
  Write-Host ("[backend] launching isolated gateway stack on :{0} (BasePort={1}) ..." -f $GatewayPort, $GatewayBasePort) -ForegroundColor DarkGray
  & powershell -NoProfile -ExecutionPolicy Bypass -File $isolated808 -SkipInstall -GatewayPort $GatewayPort -BasePort $GatewayBasePort -OwnerUserId ("u_{0}" -f $UserId) -OwnerUsername $UserId
} elseif ($GatewayPort -eq 8081 -and (Test-Path $isolated8081)) {
  Write-Host "[backend] launching isolated gateway stack on :8081 ..." -ForegroundColor DarkGray
  & powershell -NoProfile -ExecutionPolicy Bypass -File $isolated8081 -SkipInstall -OwnerUserId ("u_{0}" -f $UserId) -OwnerUsername $UserId
} else {
  $backendScript = Join-Path $scriptRoot "start_backend_core.ps1"
  if (-not (Test-Path $backendScript)) {
    throw "Backend launcher not found: $backendScript"
  }
  Write-Host "[backend] launching core stack... (this usually takes 10~30s)" -ForegroundColor DarkGray
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  & powershell -NoProfile -ExecutionPolicy Bypass -File $backendScript
  $backendExitCode = $LASTEXITCODE
  $sw.Stop()
  if ($backendExitCode -ne 0) {
    Write-Host ("[warn] backend launcher exit code: {0} (elapsed {1:n1}s)" -f $backendExitCode, $sw.Elapsed.TotalSeconds) -ForegroundColor Yellow
  } else {
    Write-Host ("[backend] launcher completed in {0:n1}s" -f $sw.Elapsed.TotalSeconds) -ForegroundColor Green
  }

  if ($GatewayPort -ne 8081 -and $GatewayPort -ne 8013) {
    $testStackScript = $null
    $testArgs = @()
    if ($GatewayPort -eq 19013) {
      $testStackScript = Join-Path $scriptRoot "start_test_stack_19xxx.ps1"
    } elseif ($GatewayPort -eq 29113) {
      $testStackScript = Join-Path $scriptRoot "start_test_stack_29xxx.ps1"
    } else {
      $testStackScript = Join-Path $scriptRoot "start_test_stack_custom.ps1"
      $testArgs += @("-GatewayPort", "$GatewayPort", "-OwnerUserId", ("u_{0}" -f $UserId), "-OwnerUsername", $UserId)
    }

    if (Test-Path $testStackScript) {
      Write-Host ("[backend] GatewayPort={0}, starting isolated stack via {1} ..." -f $GatewayPort, (Split-Path $testStackScript -Leaf)) -ForegroundColor Cyan
      & powershell -NoProfile -ExecutionPolicy Bypass -File $testStackScript @testArgs
    } else {
      Write-Host ("[warn] isolated stack launcher not found: {0}" -f $testStackScript) -ForegroundColor Yellow
    }
  }
}

Write-Host "[4/5] Wait device-gateway ready..." -ForegroundColor Cyan
$ready = Wait-BackendReady -TimeoutSec 45 -Port $GatewayPort
if (-not $ready) {
  Write-Host ("[warn] device-gateway:{0} readiness timeout, continue anyway." -f $GatewayPort) -ForegroundColor Yellow
}

$syncScript = Join-Path $scriptRoot "sync_linmeili_to_postgres.ps1"
if (Test-Path $syncScript) {
  $syncUser = [string]$UserId
  if ($syncUser.StartsWith("u_")) {
    $syncUser = $syncUser.Substring(2)
  }
  try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $syncScript -Username $syncUser -RoleCode "nurse" | Out-Null
  } catch {
    Write-Host ("[sync-user-warn] {0}" -f $_.Exception.Message) -ForegroundColor Yellow
  }
}
Bind-DeviceOwner -Port $GatewayPort -Username $UserId | Out-Null

$lanIp = Resolve-LanIPv4
Write-Host ("LAN IP: {0}" -f $lanIp) -ForegroundColor Cyan
$env:XIAOYI_DEVICE_HOST = $lanIp
$env:XIAOYI_GATEWAY_PORT = [string]$GatewayPort
$env:XIAOYI_STRICT_GATEWAY_PORT = "1"
Ensure-GatewayFirewall -Port $GatewayPort
Push-DeviceLocalMode -Port $ComPort -PortBaud $Baud -LanIp $lanIp -PortGateway $GatewayPort

if ($UseLegacyHostApp) {
  Write-Host "[5/5] Start legacy Xiaoyi host app..." -ForegroundColor Cyan
  $launcher = Join-Path $scriptRoot "start_xiaozhi_host_app.ps1"
  if (-not (Test-Path $launcher)) {
    throw "Launcher not found: $launcher"
  }
  if ($NoConsole) {
    & powershell -ExecutionPolicy Bypass -File $launcher -SkipBackend -NoConsole -GatewayPort $GatewayPort
  } else {
    & powershell -ExecutionPolicy Bypass -File $launcher -SkipBackend -GatewayPort $GatewayPort
  }
} else {
  Write-Host "[5/5] Skip legacy host app (default). Device will talk directly to device-gateway." -ForegroundColor Green
}

Write-Host "[verify] waiting device websocket online..." -ForegroundColor Cyan
$online = Wait-DeviceSessionOnline -Port $GatewayPort -TimeoutSec 35
if (-not $online) {
  Write-Host "[verify] session offline, retry local-mode push + reboot once..." -ForegroundColor Yellow
  Push-DeviceLocalMode -Port $ComPort -PortBaud $Baud -LanIp $lanIp -PortGateway $GatewayPort
  Start-Sleep -Seconds 4
  $online = Wait-DeviceSessionOnline -Port $GatewayPort -TimeoutSec 45
}
if (-not $online) {
  Write-Host "[next] Please press board RST once, wait 5-10s, then check: http://127.0.0.1:$GatewayPort/api/device/sessions" -ForegroundColor Yellow
}
Write-Host "[next] 唤醒词请说：小医小医（同音如小依小依也可）。示例：帮我看一下12床的情况。" -ForegroundColor Cyan

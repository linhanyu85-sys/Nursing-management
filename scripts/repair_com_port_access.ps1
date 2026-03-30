param(
  [string]$ComPort = "COM7",
  [int]$Baud = 115200
)

$ErrorActionPreference = "SilentlyContinue"
Write-Host "[1/5] 检查串口列表..." -ForegroundColor Cyan
try {
  Get-PnpDevice -Class Ports | Select-Object Status, FriendlyName, InstanceId | Format-Table -AutoSize
} catch {}

Write-Host "`n[2/5] 结束常见 COM 占用进程..." -ForegroundColor Cyan
$patterns = @(
  "*xiaozhi_host_app.py*",
  "*xiaozhi_serial_agent_bridge.py*",
  "*idf.py*monitor*",
  "*pyserial*miniterm*",
  "*esptool.py*monitor*",
  "*putty*",
  "*teraterm*",
  "*SecureCRT*",
  "*MobaXterm*",
  "*arduino*serial*"
)
Get-CimInstance Win32_Process | ForEach-Object {
  $line = [string]$_.CommandLine
  if (-not $line) { return }
  foreach ($pt in $patterns) {
    if ($line -like $pt) {
      try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        Write-Host ("  已结束: PID {0} => {1}" -f $_.ProcessId, $line) -ForegroundColor Yellow
      } catch {}
      break
    }
  }
}

Write-Host "`n[3/5] 测试串口是否可打开: $ComPort ..." -ForegroundColor Cyan
$py = @"
import sys
try:
    import serial
except Exception as e:
    print('NO_PYSERIAL', repr(e))
    sys.exit(2)

port = r'$ComPort'
baud = int($Baud)
try:
    s = serial.Serial()
    s.port = port
    s.baudrate = baud
    s.timeout = 0.5
    s.write_timeout = 1.0
    s.rtscts = False
    s.dsrdtr = False
    try:
        s.dtr = False
        s.rts = False
    except Exception:
        pass
    s.open()
    s.write(b'XIAOYI_CMD:PING\\r\\n')
    s.flush()
    print('OPEN_OK')
    s.close()
except Exception as e:
    print('OPEN_FAIL', repr(e))
    sys.exit(1)
"@
$pyExe = "C:\Users\58258\AppData\Local\Programs\Python\Python313\python.exe"
if (Test-Path $pyExe) {
  $py | & $pyExe -
} else {
  $py | & py -3.13 -
}
$code = $LASTEXITCODE

Write-Host "`n[4/5] 结果建议..." -ForegroundColor Cyan
if ($code -eq 0) {
  Write-Host "  串口已可用。现在可以执行本地模式推送或刷机。" -ForegroundColor Green
} else {
  Write-Host "  仍然被占用或拒绝访问，请按顺序操作：" -ForegroundColor Red
  Write-Host ("  A. 拔掉 {0} 对应 USB，等待 5 秒再插回" -f $ComPort) -ForegroundColor Red
  Write-Host "  B. 关闭串口监视工具后重试（IDF Monitor/串口助手等）" -ForegroundColor Red
  Write-Host "  C. 以管理员身份运行本脚本再试" -ForegroundColor Red
  Write-Host ("  D. 临时改用 115200: .\\scripts\\repair_com_port_access.ps1 -ComPort {0} -Baud 115200" -f $ComPort) -ForegroundColor Red
  $probeAlt = @"
import serial, time
import serial.tools.list_ports
for p in serial.tools.list_ports.comports():
    name = p.device.upper()
    if name == r"$ComPort".upper():
        continue
    try:
        s = serial.Serial(name, int($Baud), timeout=0.25, write_timeout=0.8)
        try:
            s.write(b"XIAOYI_CMD:PING\\r\\n")
            s.flush()
            ok = False
            t0 = time.time()
            while time.time() - t0 < 0.8:
                line = s.readline()
                if line and b"serial_pong" in line.lower():
                    ok = True
                    break
            if ok:
                print("ALT_PONG", name)
                break
            print("ALT_OPEN", name)
            break
        finally:
            s.close()
    except Exception:
        pass
"@
  $altOut = $null
  if (Test-Path $pyExe) {
    $altOut = ($probeAlt | & $pyExe - 2>$null | Select-Object -First 1)
  } else {
    $altOut = ($probeAlt | & py -3.13 - 2>$null | Select-Object -First 1)
  }
  if ($altOut -and $altOut -match '^ALT_(PONG|OPEN)\s+(\S+)$') {
    $altPort = $Matches[2]
    Write-Host ("  E. 检测到可用备选串口：{0}（建议先改用它）" -f $altPort) -ForegroundColor Yellow
    Write-Host ("     示例：.\\scripts\\start_xiaozhi_full.ps1 -ComPort {0}" -f $altPort) -ForegroundColor Yellow
  }
}

Write-Host "`n[5/5] 完成。" -ForegroundColor Cyan

param(
  [Parameter(Mandatory = $true)]
  [string]$ServerHost,

  [Parameter(Mandatory = $true)]
  [string]$Password,

  [string]$ServerUser = "root",
  [string]$BundlePath = "D:\codex\tmp\ai-nursing-server-bundle.zip",
  [string]$EnvFile = "D:\codex\tmp\ai-nursing-server.env",
  [string]$RemoteDir = "/opt/ai-nursing"
)

$ErrorActionPreference = "Stop"

Import-Module Posh-SSH

if (-not (Test-Path $BundlePath)) {
  throw "Bundle not found: $BundlePath"
}

if (-not (Test-Path $EnvFile)) {
  throw "Env file not found: $EnvFile"
}

$secure = ConvertTo-SecureString $Password -AsPlainText -Force
$credential = [System.Management.Automation.PSCredential]::new($ServerUser, $secure)

$ssh = $null
$sftp = $null

try {
  $ssh = New-SSHSession -ComputerName $ServerHost -Credential $credential -AcceptKey
  $sftp = New-SFTPSession -ComputerName $ServerHost -Credential $credential -AcceptKey

  Invoke-SSHCommand -SessionId $ssh.SessionId -Command "mkdir -p '$RemoteDir' && mkdir -p /root/deploy_tmp && rm -f /root/deploy_tmp/ai-nursing-server-bundle.zip /root/deploy_tmp/ai-nursing-server.env" | Out-Null

  Set-SFTPItem -SessionId $sftp.SessionId -Path $BundlePath -Destination "/root/deploy_tmp"
  Set-SFTPItem -SessionId $sftp.SessionId -Path $EnvFile -Destination "/root/deploy_tmp"

  $remoteCommand = @"
python3 -m zipfile -e /root/deploy_tmp/ai-nursing-server-bundle.zip '$RemoteDir'
mv /root/deploy_tmp/ai-nursing-server.env '$RemoteDir/.env.server'
chmod +x '$RemoteDir/scripts/deploy_backend_ubuntu.sh'
bash '$RemoteDir/scripts/deploy_backend_ubuntu.sh'
"@

  $result = Invoke-SSHCommand -SessionId $ssh.SessionId -Command $remoteCommand -TimeOut 3600
  $result.Output
  if ($result.ExitStatus -ne 0) {
    throw "Remote deploy failed with exit status $($result.ExitStatus)."
  }
} finally {
  if ($sftp) {
    Remove-SFTPSession -SFTPSession $sftp | Out-Null
  }
  if ($ssh) {
    Remove-SSHSession -SSHSession $ssh | Out-Null
  }
}
